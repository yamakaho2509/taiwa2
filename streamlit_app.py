import streamlit as st
# import sqlite3 # sqlite3 は不要になったため削除
from supabase import create_client, Client
import hashlib
import sys
import io
import docx
import pandas as pd
import google.generativeai as genai
import os # os をインポート

# --- Supabase データベース設定 ---

@st.cache_resource # Streamlit のリソースとして Supabase クライアントをキャッシュ
def init_supabase_client():
    """Supabaseクライアントを初期化して返す"""
    try:
        supabase_url = st.secrets["SUPABASE_URL"]
        supabase_key = st.secrets["SUPABASE_KEY"]
        return create_client(supabase_url, supabase_key)
    except KeyError:
        st.error("Supabase の URL または Key が Streamlit Secrets に設定されていません。")
        st.stop()

# main() の中で supabase クライアントを初期化
# supabase = init_supabase_client()

# --- データベース スキーマ (Supabase UI で手動設定) ---
#
# init_db() 関数は不要になりました。
# Supabase のダッシュボードで以下のテーブルを手動で作成してください。
#
# 1. テーブル: users
#    - id: bigint (Primary Key, Identity)
#    - username: text (Unique)
#    - password_hash: text
#    - is_admin: boolean (Default: false)
#
# 2. テーブル: chat_history
#    - id: bigint (Primary Key, Identity)
#    - user_id: bigint (Foreign Key -> users.id)
#    - role: text
#    - content: text
#    - timestamp: timestampz (Default: now())
#
# 3. 管理者アカウント (手動で users テーブルに追加)
#    - username: 'adminkaho1020'
#    - password_hash: 'adminkaho1020pw' を hash_password() でハッシュ化した値
#    - is_admin: true
#
# --- 

def hash_password(password):
    """パスワードをハッシュ化する (変更なし)"""
    return hashlib.sha256(password.encode()).hexdigest()

def add_user(supabase: Client, username, password):
    """一般ユーザーを Supabase に追加する"""
    if username.lower() == 'adminkaho1020':
        return False
    try:
        supabase.table('users').insert({
            'username': username,
            'password_hash': hash_password(password),
            'is_admin': False
        }).execute()
        return True
    #except APIError as e:
        # ユーザー名が既に存在する場合 (Unique constraint violation)
        #st.error(f"登録エラー: {e.message}")
        #return False
    except Exception as e:
        st.error(f"不明なエラーが発生しました: {e}")
        return False

def verify_user(supabase: Client, username, password):
    """ユーザーを認証する"""
    try:
        response = supabase.table('users').select('*').eq('username', username).execute()
        if response.data:
            user = response.data[0]
            if user['password_hash'] == hash_password(password):
                # Supabase の辞書を返す
                return user
        return None
    except Exception as e:
        st.error(f"認証エラー: {e}")
        return None

def get_all_users(supabase: Client):
    """管理者以外の全ユーザーを取得する"""
    try:
        response = supabase.table('users').select('id, username').eq('is_admin', False).order('username').execute()
        return response.data # 既に辞書のリスト
    except Exception as e:
        st.error(f"ユーザー取得エラー: {e}")
        return []

def add_message_to_db(supabase: Client, user_id, role, content):
    """チャット履歴を Supabase に追加する"""
    try:
        supabase.table('chat_history').insert({
            'user_id': user_id,
            'role': role,
            'content': content
        }).execute()
    except Exception as e:
        st.error(f"メッセージ保存エラー: {e}")

def get_messages_from_db(supabase: Client, user_id):
    """特定のユーザーのチャット履歴を取得する"""
    try:
        response = supabase.table('chat_history').select('role, content').eq('user_id', user_id).order('timestamp', desc=False).execute()
        # response.data は [{"role": "user", "content": "..."}, ...] の形式
        return response.data
    except Exception as e:
        st.error(f"履歴取得エラー: {e}")
        return []

# --- 管理者パネル ---
def admin_panel(supabase: Client): # supabase を引数として受け取る
    st.sidebar.title("管理者パネル")
    st.sidebar.write("---")
    
    if st.session_state.get('impersonating', False):
        if st.sidebar.button("管理者ビューに戻る"):
            st.session_state['user_id'] = st.session_state['admin_id']
            st.session_state['username'] = st.session_state['admin_username']
            st.session_state['is_admin'] = True
            st.session_state['impersonating'] = False
            if 'viewing_messages' in st.session_state:
                del st.session_state['viewing_messages']
            st.rerun()
        st.sidebar.write("---")

    st.sidebar.subheader("ユーザー一覧")
    users = get_all_users(supabase) # supabase を渡す
    if not users:
        st.sidebar.info("まだ一般ユーザーは登録されていません。")
        return

    for user in users:
        with st.sidebar.expander(f"ユーザー: {user['username']}"):
            if st.button("履歴を閲覧", key=f"view_{user['id']}"):
                messages = get_messages_from_db(supabase, user['id']) # supabase を渡す
                st.session_state['viewing_messages'] = messages
                st.session_state['viewing_username'] = user['username']
                if 'impersonating' in st.session_state:
                    st.session_state['impersonating'] = False

            if st.button("このユーザーとしてログイン", key=f"login_as_{user['id']}"):
                st.session_state['impersonating'] = True
                st.session_state['admin_id'] = st.session_state['user_id']
                st.session_state['admin_username'] = st.session_state['username']
                st.session_state['user_id'] = user['id']
                st.session_state['username'] = user['username']
                st.session_state['is_admin'] = False
                st.session_state.messages = get_messages_from_db(supabase, user['id']) # supabase を渡す
                if 'viewing_messages' in st.session_state:
                    del st.session_state['viewing_messages']
                st.rerun()


# --- メインアプリケーション ---
def main():
    # init_db() # データベースの初期化は不要
    
    # Supabase クライアントを初期化
    supabase = init_supabase_client()

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
                    user = verify_user(supabase, username, password) # supabase を渡す
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
                if new_username.lower() == 'adminkaho1020':
                    st.warning("このユーザー名は使用できません。")
                new_password = st.text_input("パスワード", type="password")
                submitted = st.form_submit_button("登録")
                if submitted and new_username.lower() != 'adminkaho1020':
                    if add_user(supabase, new_username, new_password): # supabase を渡す
                        st.sidebar.success("登録が完了しました。ログインしてください。")
                    else:
                        st.sidebar.error("このユーザー名は既に使用されているか、登録に失敗しました。")
    else: # ログイン後の処理
        st.sidebar.success(f"{st.session_state.username} としてログイン中")
        if st.sidebar.button("ログアウト"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # --- ログインしている場合のみアプリ本体を表示 ---
    if st.session_state.logged_in:
        # 管理者の場合
        if st.session_state.is_admin and not st.session_state.get('impersonating', False):
            admin_panel(supabase) # supabase を渡す
            st.title("管理者ダッシュボード")
            st.info("サイドバーからユーザーを選択し、操作を行ってください。")

            if 'viewing_messages' in st.session_state:
                st.header(f"ユーザー「{st.session_state['viewing_username']}」の学習履歴")
                messages_to_display = st.session_state['viewing_messages']
                if not messages_to_display:
                    st.write("このユーザーのチャット履歴はまだありません。")
                else:
                    for message in messages_to_display:
                        with st.chat_message(message["role"]):
                            st.markdown(message["content"])
        
        # 一般ユーザーまたはなりすまし中の管理者の場合
        else:
            if st.session_state.get('impersonating', False):
                st.info(f"現在、管理者として「{st.session_state.username}」でログインしています。")
                # admin_panel 内で既に戻るボタンがあるので、ここでは不要かもしれません
                # ただし、ロジックの一貫性のため残しておきます
                if st.sidebar.button("管理者ビューに戻る"):
                    st.session_state.user_id = st.session_state.admin_id
                    st.session_state.username = st.session_state.admin_username
                    st.session_state.is_admin = True
                    st.session_state.impersonating = False
                    if 'viewing_messages' in st.session_state:
                        del st.session_state['viewing_messages']
                    st.rerun()
            
            # --- チャットアプリ本体 ---
            st.title("💬 チャットボットと学びを振り返ろう！")
            st.write("記入済みの学習日記フォーマットをDOCS形式でアップロードすると、その内容に関する対話ができます！")

            try:
                gemini_api_key = st.secrets["google_api_key"]
                genai.configure(api_key=gemini_api_key)
                
                # ★★★ チャットボットの役割と指示（システムプロンプト） ★★★
                # (ここに指示文を埋め込みます)
                system_prompt = """
あなたはユーザーアップロードしたファイル内の「学習目標」として記載されている分野の優秀な指導教員であり、孤独の中独学をする成人学習者の自己成長を支援するコーチとしての役割を担う親しみやすいチャットボットです。

### 最重要ルール：対話のペース配分（ターン制）
**あなたは対話履歴の長さ（往復回数）を確認し、現在どのフェーズにいるかを厳密に守らなければなりません。**
AIとしての「すぐに解決策を提示したい」という欲求を抑え、以下のルールに従って対話を長引かせ、内省を深めてください。

* **フェーズ1（開始〜3往復目まで）：徹底的な内省（Step 1 & 2）**
    * **禁止事項:** この期間に「次回の計画」や「まとめ」の話をしてはいけません。
    * **義務:** ユーザーの回答に対し、「なぜそう感じたのですか？」「具体的にはどの部分ですか？」「以前と比べてどうですか？」と**深掘りの質問**を投げかけ続けてください。
    * このフェーズでは、絶対にステップ3（行動計画・クロージング）に移行しないでください。

* **フェーズ2（4往復目〜6往復目）：視点の転換と自信の醸成（Step 2後半）**
    * 内省が深まったところで、徐々に自信（Confidence）に繋がるフィードバックを行います。過去の対話履歴との比較もここで行います。

* **フェーズ3（7往復目以降）：行動への橋渡し（Step 3）**
    * ここで初めて、次回の具体的なアクションプランの話に移行し、クロージングに向かいます。

---

### １. チャットボットの役割

* 学習者が自分の言葉で学びを振り返り、気づきを深められるように導くコーチ。
* 直接的なアドバイスや専門知識の提供はせず、問いかけによってユーザー自身の答えを引き出す。
* ARCS-V（関連性、自信、意志）の理論を裏側に持ちつつ、表面上は親しみやすいコーチとして振る舞う。

### ２. 対話の進行プロセス（Step by Step）

#### ステップ1：承認と詳細な深掘り（フェーズ1：序盤）
まず、提出された活動を承認します。そして、以下の質問パターンを使って、**最低2回以上**ラリーを続けてください。
* **A（手応え）:** 「特に上手くいったと感じた瞬間はどこですか？なぜそう感じましたか？」
* **B（困難）:** 「逆に、少し詰まった部分はありましたか？その時、どう感じましたか？」
* **C（発見）:** 「新しい発見はありましたか？それはご自身の目標にどう繋がりそうですか？」

**【重要】ユーザーが答えたら、すぐに「わかりました、次は…」と進まず、「なるほど、それは深いですね。具体的には…？」とさらに質問を重ねてください。**

#### ステップ2：自信の調整と過去比較（フェーズ2：中盤）
ステップ1での内省を踏まえ、自信を高めるフェーズです。
* ここで**「６．過去の対話履歴の活用」**を積極的に行ってください。「以前は〇〇で悩んでいましたが、今回は克服できていますね！」と成長を強調します。
* 成功体験をユーザー自身の能力（努力）に帰属させるような声かけを行ってください。

#### ステップ3：意思の確認とクロージング（フェーズ3：終盤）
**対話が十分に（目安として合計7往復以上）行われた後でのみ**、このステップに入ります。
* 次回の学習に向けた具体的な行動計画（Volition）をユーザーに宣言させます。
* 「次回も楽しみにしています！」とポジティブに終了します。

### ３. 専門的な質問への対応（変更なし）
* 専門的な質問が来た場合は、役割（内省支援）を伝え、Google検索などを促してください。

### ６．過去の対話履歴の活用（成長フィードバック）
* **実行条件:** 過去のアップロードが2回以上、対話履歴が十分ある場合。
* **頻度:** フェーズ2（中盤）で必ず1回は過去との比較を入れてください。
"""
                
                # ★★★ モデルの初期化（修正） ★★★
                # system_instruction に上で定義したプロンプトを渡します。
                model = genai.GenerativeModel(
                    'gemini-2.5-flash',
                    system_instruction=system_prompt
                )

            except Exception as e:
                st.error(f"APIキーの設定でエラーが発生しました: {e}")
                st.stop()
            
            uploaded_file = st.file_uploader("ドキュメントをアップロードしてください", type=['txt', 'docx'])

            if "messages" not in st.session_state:
                st.session_state.messages = get_messages_from_db(supabase, st.session_state.user_id) # supabase を渡す
            if "document_content" not in st.session_state:
                st.session_state.document_content = None

            if uploaded_file is not None and st.session_state.document_content is None:
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
                    
                    # ★★★ 初回プロンプトの修正 ★★★
                    # システムプロンプトに従い、ステップ1の対話を開始するよう指示します。
                    initial_prompt = f"""
あなたは今、システムプロンプト（役割定義）に従い、指導教員/コーチとして振る舞っています。
学習者（ユーザー）が、以下の学習日記（ドキュメント）をアップロードしました。
このドキュメントの内容（〜）を解釈し、システムプロンプトの「ステップ1の対話例」（A, B, Cのパターンがあります）を参考に、学習日記の内容に最も適した形で、最初の応答（Botラリー1）を生成してください。
ワンパターンな質問ではなく、日記の内容に具体的に言及し、回答しやすい具体的な問いかけを心がけてください。

---
学習日記（ドキュメント）:
{document_content}
---

あなたの最初の応答を開始してください：
"""
                    
                    with st.spinner("思考中です..."):
                        # model.generate_content はシステムプロンプトを自動的に使用します
                        response = model.generate_content(initial_prompt)
                    
                    assistant_message = response.text
                    st.session_state.messages.append({"role": "assistant", "content": assistant_message})
                    add_message_to_db(supabase, st.session_state['user_id'], "assistant", assistant_message) # supabase を渡す
                    st.rerun()
                 except Exception as e:
                    st.error(f"ファイルの読み込み中にエラーが発生しました: {e}")


            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            if prompt := st.chat_input("ドキュメントについて質問してください"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                add_message_to_db(supabase, st.session_state.user_id, "user", prompt) # supabase を渡す
                with st.chat_message("user"):
                    st.markdown(prompt)

                try:
                    # ★★★ 履歴構築の修正 ★★★
                    history = []
                    
                    # system_prompt は model 初期化時に渡しているので、ここでは不要です。
                    
                    # ユーザーのドキュメント（日記）を、毎回履歴の「最初」に
                    # 「参考情報」として含めます。
                    document_context = f"参考：ユーザーの学習日記（ドキュメント）:\n{st.session_state.get('document_content', 'ドキュメントなし')}"
                    history.append({'role': 'user', 'parts': [document_context]})
                    history.append({'role': 'model', 'parts': ["（承知しました。学習日記を再度参照します。）"]})

                    # 実際のチャット履歴を（ドキュメントの後に）追加
                    for msg in st.session_state.messages:
                        role = "user" if msg["role"] == "user" else "model"
                        history.append({'role': role, 'parts': [msg["content"]]})
                    
                    # history の最後はユーザーのプロンプトのはずなので、Geminiに渡す
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
                    add_message_to_db(supabase, st.session_state.user_id, "assistant", full_response) # supabase を渡す

                except Exception as e:
                    st.error("エラーが発生しました。詳細はコンソールを確認してください。")
                    print(f"エラーの詳細: {e}", file=sys.stderr)
                    error_message = "申し訳ありません、応答の生成中にエラーが発生しました。"
                    st.session_state.messages.append({"role": "assistant", "content": error_message})
                    add_message_to_db(supabase, st.session_state.user_id, "assistant", error_message) # supabase を渡す
            
            # --- エクスポート機能 (変更なし) ---
            st.sidebar.header("エクスポート")
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
