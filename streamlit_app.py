import streamlit as st
import sqlite3
import hashlib
import sys
import io
import docx
import pandas as pd # CSV出力のために追加

# 必要なライブラリのインポートを試行
try:
    import google.generativeai as genai
except ImportError:
    st.error(
        "必要なライブラリが見つかりません。以下のコマンドでインストールしてください："
    )
    st.code("pip install google-generativeai python-docx pandas")
    st.info(
        "ターミナルでこのコマンドを実行し、アプリを再起動してください。"
    )
    st.stop()

# --- データベース設定 ---

# データベース接続を管理する関数
def get_db_connection():
    conn = sqlite3.connect('chat_app.db')
    conn.row_factory = sqlite3.Row
    return conn

# データベースの初期化（テーブル作成）
def init_db():
    conn = get_db_connection()
    # ユーザーテーブル
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    # チャット履歴テーブル
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

# パスワードをハッシュ化する関数
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ユーザーをデータベースに追加する関数
def add_user(username, password):
    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO users (username, password_hash) VALUES (?, ?)',
            (username, hash_password(password))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError: # ユーザー名が既に存在する場合
        return False
    finally:
        conn.close()

# ユーザーを認証する関数
def verify_user(username, password):
    conn = get_db_connection()
    user = conn.execute(
        'SELECT * FROM users WHERE username = ?', (username,)
    ).fetchone()
    conn.close()
    if user and user['password_hash'] == hash_password(password):
        return user
    return None

# チャット履歴をデータベースに追加する関数
def add_message_to_db(user_id, role, content):
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)',
        (user_id, role, content)
    )
    conn.commit()
    conn.close()

# 特定のユーザーのチャット履歴を取得する関数
def get_messages_from_db(user_id):
    conn = get_db_connection()
    messages_cursor = conn.execute(
        'SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY timestamp ASC',
        (user_id,)
    )
    messages = [{"role": row["role"], "content": row["content"]} for row in messages_cursor]
    conn.close()
    return messages

# --- メインアプリケーション ---

def main():
    # データベースの初期化を一度だけ実行
    init_db()

    # セッション状態の初期化
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['username'] = ""
        st.session_state['user_id'] = None

    # --- ログイン/新規登録UI (サイドバー) ---
    st.sidebar.title("ユーザー認証")
    if st.session_state['logged_in']:
        st.sidebar.success(f"{st.session_state['username']} としてログイン中")
        if st.sidebar.button("ログアウト"):
            # セッション状態をリセットして再実行
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    else:
        choice = st.sidebar.selectbox("メニュー", ["ログイン", "新規登録"])

        if choice == "ログイン":
            with st.sidebar.form("login_form"):
                username = st.text_input("ユーザー名")
                password = st.text_input("パスワード", type="password")
                submitted = st.form_submit_button("ログイン")
                if submitted:
                    user = verify_user(username, password)
                    if user:
                        st.session_state['logged_in'] = True
                        st.session_state['username'] = user['username']
                        st.session_state['user_id'] = user['id']
                        st.rerun()
                    else:
                        st.sidebar.error("ユーザー名またはパスワードが間違っています。")

        elif choice == "新規登録":
            with st.sidebar.form("signup_form"):
                new_username = st.text_input("ユーザー名")
                new_password = st.text_input("パスワード", type="password")
                submitted = st.form_submit_button("登録")
                if submitted:
                    if add_user(new_username, new_password):
                        st.sidebar.success("登録が完了しました。ログインしてください。")
                    else:
                        st.sidebar.error("このユーザー名は既に使用されています。")

    # --- ログインしている場合のみチャットアプリを表示 ---
    if st.session_state['logged_in']:
        # StreamlitのUI設定
        st.title("💬 チャットボットと学びを振り返ろう！")
        st.write(
            "記入済みの学習日記フォーマットをDOCS形式でアップロードすると、その内容に関する対話ができます！"
        )

        # secretsからAPIキーを読み込む
        try:
            gemini_api_key = st.secrets["google_api_key"]
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel('gemini-2.5-flash-preview-05-20')
        except Exception as e:
            st.error(f"APIキーの設定でエラーが発生しました: {e}")
            st.info(
                "プロジェクトの`.streamlit/secrets.toml`ファイルにGoogle APIキーが正しく設定されているか確認してください。"
            )
            st.stop()
        
        # === ドキュメントアップローダーの追加 ===
        uploaded_file = st.file_uploader(
            "ドキュメントをアップロードしてください",
            type=['txt', 'docx']
        )

        # === セッション状態変数の作成 ===
        if "messages" not in st.session_state:
            # データベースから履歴を読み込む
            st.session_state.messages = get_messages_from_db(st.session_state['user_id'])
        if "document_content" not in st.session_state:
            st.session_state.document_content = None

        # アップロードされたファイルを処理する
        if uploaded_file is not None:
            # ファイルを一度だけ読み込む
            if st.session_state.document_content is None:
                try:
                    if uploaded_file.type == 'text/plain':
                        document_content = uploaded_file.getvalue().decode('utf-8')
                    elif uploaded_file.type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
                        document = docx.Document(uploaded_file)
                        paragraphs = [p.text for p in document.paragraphs]
                        document_content = "\n".join(paragraphs)
                    
                    st.session_state.document_content = document_content
                    st.success("ドキュメントが正常にアップロードされました。")
                    # ここではチャット履歴をリセットしない
                    st.info("これで、ドキュメントの内容について質問できます。")
                    
                    initial_prompt = f"これからあなたの学習をサポートします。今日の学習日記を拝見しました。\n\nドキュメント:\n{document_content}\n\nまずは、この日の学習で一番印象に残っていることについて教えていただけますか？"
                    
                    with st.spinner("思考中です..."):
                        response = model.generate_content(initial_prompt)
                    
                    assistant_message = response.text
                    st.session_state.messages.append({"role": "assistant", "content": assistant_message})
                    add_message_to_db(st.session_state['user_id'], "assistant", assistant_message) # DBに保存
                    
                    st.rerun()

                except Exception as e:
                    st.error(f"ファイルの読み込み中にエラーが発生しました: {e}")

        # === チャットUIの表示 ===
        # 既存のチャットメッセージの表示
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # ユーザー入力のチャットフィールド
        if prompt := st.chat_input("ドキュメントについて質問してください"):
            # ユーザーのプロンプトを保存・表示・DBに保存
            st.session_state.messages.append({"role": "user", "content": prompt})
            add_message_to_db(st.session_state['user_id'], "user", prompt)
            with st.chat_message("user"):
                st.markdown(prompt)

            try:
                # Gemini APIに渡すためにメッセージ形式を変換
                history = []
                document_context = f"""
# Please paste the text defining the chatbot's role here.
# ここにチャットボットの役割を定義するテキストを貼り付けてください。
（...元のプロンプトと同じ内容なので省略...）
\nドキュメント:\n{st.session_state.get('document_content', 'ドキュメントはまだアップロードされていません。')}"""

                history.append({'role': 'user', 'parts': [document_context]})
                
                # DBから取得した履歴全体をコンテキストとして使用
                for msg in st.session_state.messages:
                    role = "user" if msg["role"] == "user" else "model"
                    history.append({'role': role, 'parts': [msg["content"]]})
                
                # Gemini APIを使用して応答を生成
                response_stream = model.generate_content(history, stream=True)

                # 応答をストリーミング表示し、セッションとDBに保存
                full_response = ""
                with st.chat_message("assistant"):
                    message_placeholder = st.empty()
                    for chunk in response_stream:
                        if chunk.parts:
                            text_part = chunk.parts[0].text
                            full_response += text_part
                            message_placeholder.markdown(full_response + "▌")
                    message_placeholder.markdown(full_response)
                
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                add_message_to_db(st.session_state['user_id'], "assistant", full_response) # DBに保存

            except Exception as e:
                st.error("エラーが発生しました。詳細はコンソールを確認してください。")
                print(f"エラーの詳細: {e}", file=sys.stderr)
                error_message = "申し訳ありません、応答の生成中にエラーが発生しました。"
                st.session_state.messages.append({"role": "assistant", "content": error_message})
                add_message_to_db(st.session_state['user_id'], "assistant", error_message) # DBに保存
        
        # === 各種ダウンロードボタンの追加 ===
        st.sidebar.header("エクスポート")

        # 1. Wordファイル出力
        doc = docx.Document()
        doc.add_heading(f'{st.session_state["username"]}さんの振り返り', 0)
        for message in st.session_state.messages:
            role_jp = "ユーザー" if message["role"] == "user" else "チャットボット"
            doc.add_paragraph(f"{role_jp}: {message['content']}")
        doc_io = io.BytesIO()
        doc.save(doc_io)
        doc_io.seek(0)
        st.sidebar.download_button(
            label="振り返りをWord形式でダウンロード",
            data=doc_io,
            file_name=f"{st.session_state['username']}_振り返り.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

        # 2. CSVファイル出力
        if st.session_state.messages:
            df = pd.DataFrame(st.session_state.messages)
            csv = df.to_csv(index=False).encode('utf-8')
            st.sidebar.download_button(
                label="対話履歴をCSV形式でダウンロード",
                data=csv,
                file_name=f"{st.session_state['username']}_対話履歴.csv",
                mime="text/csv",
            )
    else:
        st.info("チャットボットを利用するには、サイドバーからログインまたは新規登録をしてください。")

if __name__ == '__main__':
    main()
