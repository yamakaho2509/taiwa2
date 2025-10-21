import streamlit as st
import sqlite3
import hashlib
import sys
import io
import docx
import pandas as pd

# --- データベース設定 ---

def get_db_connection():
    """データベース接続を取得する"""
    conn = sqlite3.connect('chat_app.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """データベースを初期化し、テーブルと管理者アカウントを作成する"""
    conn = get_db_connection()
    # ユーザーテーブルに is_admin 列を追加
    try:
        conn.execute('ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE')
    except sqlite3.OperationalError:
        # 列が既に存在する場合は何もしない
        pass

    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT FALSE
        )
    ''')
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

    # ★★★ ここで管理者アカウント情報を変更 ★★★
    admin_username = 'adminkaho1020'
    admin_password = 'adminkaho1020pw'
    
    # 管理者アカウントが存在しない場合のみ作成
    admin_user = conn.execute('SELECT * FROM users WHERE username = ?', (admin_username,)).fetchone()
    if not admin_user:
        conn.execute(
            'INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)',
            (admin_username, hash_password(admin_password), True)
        )
    conn.commit()
    conn.close()

def hash_password(password):
    """パスワードをハッシュ化する"""
    return hashlib.sha256(password.encode()).hexdigest()

def add_user(username, password):
    """一般ユーザーをデータベースに追加する"""
    conn = get_db_connection()
    try:
        # ★★★ 管理者名での一般登録を禁止 ★★★
        if username.lower() == 'adminkaho1020':
            return False
        conn.execute(
            'INSERT INTO users (username, password_hash) VALUES (?, ?)',
            (username, hash_password(password))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def verify_user(username, password):
    """ユーザーを認証する"""
    conn = get_db_connection()
    user = conn.execute(
        'SELECT * FROM users WHERE username = ?', (username,)
    ).fetchone()
    conn.close()
    if user and user['password_hash'] == hash_password(password):
        return user
    return None

def get_all_users():
    """管理者以外の全ユーザーを取得する"""
    conn = get_db_connection()
    users = conn.execute('SELECT id, username FROM users WHERE is_admin = FALSE ORDER BY username').fetchall()
    conn.close()
    return users

def add_message_to_db(user_id, role, content):
    """チャット履歴をデータベースに追加する"""
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)',
        (user_id, role, content)
    )
    conn.commit()
    conn.close()

def get_messages_from_db(user_id):
    """特定のユーザーのチャット履歴を取得する"""
    conn = get_db_connection()
    messages_cursor = conn.execute(
        'SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY timestamp ASC',
        (user_id,)
    )
    messages = [{"role": row["role"], "content": row["content"]} for row in messages_cursor]
    conn.close()
    return messages

# --- 管理者パネル ---
def admin_panel():
    st.sidebar.title("管理者パネル")
    st.sidebar.write("---")
    
    # なりすまし中の場合、管理者ビューに戻るボタンを表示
    if st.session_state.get('impersonating', False):
        if st.sidebar.button("管理者ビューに戻る"):
            # 管理者自身のセッション情報に戻す
            st.session_state['user_id'] = st.session_state['admin_id']
            st.session_state['username'] = st.session_state['admin_username']
            st.session_state['is_admin'] = True
            st.session_state['impersonating'] = False
            # 閲覧中のチャット履歴をクリア
            if 'viewing_messages' in st.session_state:
                del st.session_state['viewing_messages']
            st.rerun()
        st.sidebar.write("---")

    st.sidebar.subheader("ユーザー一覧")
    users = get_all_users()
    if not users:
        st.sidebar.info("まだ一般ユーザーは登録されていません。")
        return

    for user in users:
        with st.sidebar.expander(f"ユーザー: {user['username']}"):
            # 1. 履歴閲覧機能
            if st.button("履歴を閲覧", key=f"view_{user['id']}"):
                messages = get_messages_from_db(user['id'])
                st.session_state['viewing_messages'] = messages
                st.session_state['viewing_username'] = user['username']
                # なりすまし状態は解除
                if 'impersonating' in st.session_state:
                    st.session_state['impersonating'] = False

            # 2. なりすましログイン機能
            if st.button("このユーザーとしてログイン", key=f"login_as_{user['id']}"):
                st.session_state['impersonating'] = True
                # 現在の管理者情報を保存
                st.session_state['admin_id'] = st.session_state['user_id']
                st.session_state['admin_username'] = st.session_state['username']
                # なりすまし対象のユーザー情報に切り替え
                st.session_state['user_id'] = user['id']
                st.session_state['username'] = user['username']
                st.session_state['is_admin'] = False # 一時的に管理者権限をオフ
                # セッションのメッセージ履歴を対象ユーザーのものに切り替え
                st.session_state.messages = get_messages_from_db(user['id'])
                # 閲覧モードは解除
                if 'viewing_messages' in st.session_state:
                    del st.session_state['viewing_messages']
                st.rerun()


# --- メインアプリケーション ---
def main():
    init_db()

    # セッション状態の初期化
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.user_id = None
        st.session_state.is_admin = False

    # --- ログイン/新規登録UI (サイドバー) ---
    if not st.session_state.logged_in:
        st.sidebar.title("ユーザー認証")
        choice = st.sidebar.selectbox("メニュー", ["ログイン", "新規登録"])

        if choice == "ログイン":
            with st.sidebar.form("login_form"):
                username = st.text_input("ユーザー名")
                password = st.text_input("パスワード", type="password")
                submitted = st.form_submit_button("ログイン")
                if submitted:
                    user = verify_user(username, password)
                    if user:
                        st.session_state.logged_in = True
                        st.session_state.username = user['username']
                        st.session_state.user_id = user['id']
                        st.session_state.is_admin = user['is_admin']
                        st.rerun()
                    else:
                        st.sidebar.error("ユーザー名またはパスワードが間違っています。")

        elif choice == "新規登録":
            with st.sidebar.form("signup_form"):
                new_username = st.text_input("ユーザー名")
                # ★★★ 管理者名での一般登録を禁止 ★★★
                if new_username.lower() == 'adminkaho1020':
                    st.warning("このユーザー名は使用できません。")
                new_password = st.text_input("パスワード", type="password")
                submitted = st.form_submit_button("登録")
                if submitted and new_username.lower() != 'adminkaho1020':
                    if add_user(new_username, new_password):
                        st.sidebar.success("登録が完了しました。ログインしてください。")
                    else:
                        st.sidebar.error("このユーザー名は既に使用されています。")
    else: # ログイン後の処理
        st.sidebar.success(f"{st.session_state.username} としてログイン中")
        if st.sidebar.button("ログアウト"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # --- ログインしている場合のみアプリ本体を表示 ---
    if st.session_state.logged_in:
        # 管理者の場合、管理者パネルを表示
        if st.session_state.is_admin and not st.session_state.get('impersonating', False):
            admin_panel()
            st.title("管理者ダッシュボード")
            st.info("サイドバーからユーザーを選択し、操作を行ってください。")

            # 履歴閲覧モードの場合、チャット履歴を表示
            if 'viewing_messages' in st.session_state:
                st.header(f"ユーザー「{st.session_state['viewing_username']}」の学習履歴")
                messages_to_display = st.session_state['viewing_messages']
                if not messages_to_display:
                    st.write("このユーザーのチャット履歴はまだありません。")
                else:
                    for message in messages_to_display:
                        with st.chat_message(message["role"]):
                            st.markdown(message["content"])
        
        # 一般ユーザーまたはなりすまし中の管理者の場合、チャットUIを表示
        else:
            # なりすまし中の管理者向けの表示
            if st.session_state.get('impersonating', False):
                st.info(f"現在、管理者として「{st.session_state.username}」でログインしています。")
                if st.sidebar.button("管理者ビューに戻る"):
                    st.session_state.user_id = st.session_state.admin_id
                    st.session_state.username = st.session_state.admin_username
                    st.session_state.is_admin = True
                    st.session_state.impersonating = False
                    if 'viewing_messages' in st.session_state:
                        del st.session_state['viewing_messages']
                    st.rerun()
            
            # --- ここから元のチャットアプリのロジック ---
            st.title("💬 チャットボットと学びを振り返ろう！")
            st.write("記入済みの学習日記フォーマットをDOCS形式でアップロードすると、その内容に関する対話ができます！")

            try:
                gemini_api_key = st.secrets["google_api_key"]
                genai.configure(api_key=gemini_api_key)
                model = genai.GenerativeModel('gemini-2.5-flash-preview-05-20')
            except Exception as e:
                st.error(f"APIキーの設定でエラーが発生しました: {e}")
                st.stop()
            
            uploaded_file = st.file_uploader("ドキュメントをアップロードしてください", type=['txt', 'docx'])

            if "messages" not in st.session_state:
                st.session_state.messages = get_messages_from_db(st.session_state.user_id)
            if "document_content" not in st.session_state:
                st.session_state.document_content = None

            if uploaded_file is not None and st.session_state.document_content is None:
                # （ファイルアップロード処理は元のコードと同じため省略）
                 try:
                    if uploaded_file.type == 'text/plain':
                        document_content = uploaded_file.getvalue().decode('utf-8')
                    elif uploaded_file.type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
                        document = docx.Document(uploaded_file)
                        paragraphs = [p.text for p in document.paragraphs]
                        document_content = "\n".join(paragraphs)
                    
                    st.session_state.document_content = document_content
                    st.success("ドキュメントが正常にアップロードされました。")
                    st.info("これで、ドキュメントの内容について質問できます。")
                    
                    initial_prompt = f"これからあなたの学習をサポートします。今日の学習日記を拝見しました。\n\nドキュメント:\n{document_content}\n\nまずは、この日の学習で一番印象に残っていることについて教えていただけますか？"
                    
                    with st.spinner("思考中です..."):
                        response = model.generate_content(initial_prompt)
                    
                    assistant_message = response.text
                    st.session_state.messages.append({"role": "assistant", "content": assistant_message})
                    add_message_to_db(st.session_state['user_id'], "assistant", assistant_message)
                    st.rerun()
                 except Exception as e:
                    st.error(f"ファイルの読み込み中にエラーが発生しました: {e}")


            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            if prompt := st.chat_input("ドキュメントについて質問してください"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                add_message_to_db(st.session_state.user_id, "user", prompt)
                with st.chat_message("user"):
                    st.markdown(prompt)

                try:
                    history = []
                    document_context = f"""
# ここにチャットボットの役割を定義するテキストを貼り付けてください。
（...元のプロンプトと同じ内容なので省略...）
\nドキュメント:\n{st.session_state.get('document_content', 'ドキュメントはまだアップロードされていません。')}"""

                    history.append({'role': 'user', 'parts': [document_context]})
                    
                    for msg in st.session_state.messages:
                        role = "user" if msg["role"] == "user" else "model"
                        history.append({'role': role, 'parts': [msg["content"]]})
                    
                    response_stream = model.generate_content(history, stream=True)

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
                    add_message_to_db(st.session_state.user_id, "assistant", full_response)

                except Exception as e:
                    st.error("エラーが発生しました。詳細はコンソールを確認してください。")
                    print(f"エラーの詳細: {e}", file=sys.stderr)
                    error_message = "申し訳ありません、応答の生成中にエラーが発生しました。"
                    st.session_state.messages.append({"role": "assistant", "content": error_message})
                    add_message_to_db(st.session_state.user_id, "assistant", error_message)
            
            # エクスポート機能
            st.sidebar.header("エクスポート")
            # （エクスポート機能は元のコードと同じため省略）
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
