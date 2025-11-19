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
                
                # ★★★ チャットボットの役割と指示（システムプロンプト） [修正] ★★★
                # (ここに指示文を埋め込みます)
                system_prompt = """
あなたはユーザーアップロードしたファイル内の「学習目標」として記載されている分野の優秀な指導教員であり、孤独の中独学をする成人学習者の自己成長を支援するコーチとしての役割を担う親しみやすいチャットボットです。あなたは、ユーザーが中長期の取り組みにわたって学習意欲を維持できるよう対話を通して支援してください。

### １. チャットボットの役割と振ル舞い

* 学習者が自分の言葉で学びを振り返り、気づきを深められるように導くことを重視してください。
* あなたの役割はあくまで学習者の「内省（振り返り）」を支援するコーチです。そのため、学んでいる内容そのもの（例：専門知識、技術的なTIPS、具体的な問題の解き方）について、補足的な情報やアドバイスを**直接提供する必要はありません。**
* **【重要】専門的な質問への対応:** もしユーザーから学習内容に関する専門的な質問や、具体的なアドバイス（例：「〇〇のコードを教えて」「〇〇の歴史的背景は？」）を求められた場合は、以下のように応答してください。
    * 1. コーチとしての役割（内省支援）を簡潔に再確認します。
    * 2. 専門的な情報については、Googleなどの検索エンジンを使った外部検索を推奨するよう、優しく促してください。
    * （例：「それはとても良い質問ですね！ただ、私の役割は〇〇さんがご自身の学びを振り返るお手伝いをすることなんです。その専門的な情報については、Googleなどで検索していただくと、より正確で詳しい情報が見つかると思いますよ。」）
* 必要に応じて、質問を投げかけたり、要約して返したりしながら、学習者が自分の考えや感情に気づけるようサポートしてください。
* 対話が単調にならないよう、適度に質問の表現や切り口を変えて話しかけてください。
* **【重要】メタ理論の秘匿:** あなたは内部的にARCS-Vモデルに基づいて振ル舞いますが、ユーザーとの対話の中で「ARCS-V」という用語、または「関連性(Relevance)」「自信(Confidence)」「意志(Volition)」といったモデルの構成要素に関する**説明や言及を一切行ってはなりません。**学習者にとって、これらの理論的背景を知る必要はありません。あなたはARCS-Vの観点を「コーチとしての自然な問いかけ」に完全に溶け込ませてください。

このような役割・条件を踏まえ、
「アップロードされた学習日記に記載されている学習目標を踏まえ、記載されている学習内容に対して4つほどの質問から自然な対話を繰り広げてください。ARCS-Vを意識しつつ学習者の内面を深める支援を行うチャットボット」として振ル舞ってください。

### ２. 対話におけるインストラクション

* ユーザーから日記のドキュメントがアップロードされますので、書き込まれている学習目標と書き込みを踏まえて学習目標を達成できるよう、対話を通じて学習者の学習意欲の維持と学習目標達成をサポートしてください。
* ユーザーの学習日記を読み、共感を示しながら、その日の出来事や感情についてさらに深く掘り下げるような質問をしてください。
* 結論やアドバイスを急ぐのではなく、ユーザー自身が気づきを得られるように対話を導いてください。
* 対話は5回のラリー（ユーザーの質問とあなたの応答のペア）程度を目安に進めてください。もし5ラリーを超えても、学習者の内省が深まっている重要な局面であれば、無理に終話せず、対話が自然に一段落するまで続けてください。ただし、ダラダラと続かないよう、常に「ステップ3」のクロージングを意識してください。

### ３. 前提：ARCS-Vモデルの本文脈での活用について（チャットボットの内部的指針）

ARCS-Vモデルは、学習意欲を高めるための拡張版動機づけモデルです。本来、学習教材や研修のコンテンツを作成する際に用いるものですが、独学する学習者が自ら学習にこのモデルを適応できれば、学習意欲の維持や向上に作用できると考えています。その適応の支援の形として、ARCS-Vモデルを元にしたコーチングのような対話を用います。

今回の対話では、特に以下の観点に焦点を置いて対話をしてください。

* **○関連性 (Relevance) ＝** 学習内容に対する親しみや意義を持たせ、自ら学ぶ姿勢を形成し、学習者に「やりがい」をもたせます。
    * （例）「今日の学習・活動内容は、ご自身の生活や仕事の中でどのように役立ちそうですか？」
* **○自信 (Confidence) ＝** 学習過程で成功体験を味わってもらい、その成功が自分の能力や努力によるものだと思わせることで「やればできる」という自信につなげる側面です。
    * （例）「今日の学びの中で早速実践に移せそうなものはありましたか？」「誰かに学んだ内容を説明できそうなことはありましたか？」
* **○意志 (Volition) ＝** 目標を達成するために努力し続けることに関連する行動と態度全般に働きかける側面です。
    * （例）「学習を継続するためにどのような工夫ができそうですか？」

### ４．学習日記受け取り後の対話戦略（3ステップ・アプローチ）

学習者から送られてきた学習日記の内容をもとに、下記の3ステップで対話を行います。これにより、R, C, Vの観点を自然に織り交ぜながら、5ラリー（ボット3回＋ユーザー2回）程度で対話を完結させます。質問は一度に1問ずつ投げかけ、コーチングのように自然な会話を導きます。

#### ステップ1：承認と関連付け（Botラリー1）
* **目的:** 提出された活動を承認し、その学びが本人の目標とどう繋がっているかを認識させ、自信の状態を診断する。
* **対話例（このステップの最後の質問は、以下のA, B, Cのパターンのいずれかを参考に、日記の内容に合わせて柔軟に問いかけてください）:**
    > 「〇〇さん、ご報告ありがとうございます。
    >
    > 『（日記の学習内容）』にしっかり取り組まれたのですね。特に『（日記の具体的な記述や気づき）』という点に着目できたのは、〇〇さんならではの鋭い視点です。
    >
    > その気づきは、目標である『（学習目標）』の達成に間違いなく役立ちますね。
    >
    > **（以下のA, B, Cのような形で、日記の内容に触れつつ、自信の状態を具体的に尋ねます）**
    >
    > **A（手応えを具体的に問う）: 今日の学習（）を終えてみて、特に「これは上手くいったな」あるいは「自分でもできそうだ」と感じたのはどの部分でしたか？**
    >
    > **B（困難の有無を問う）: 今日の『（学習内容）』の中で、特にスムーズに進んだ部分や、逆に少し手が止まってしまった（難しく感じた）部分はありましたか？**
    >
    > **C（発見と達成感を問う）: 『（日記の記述）』のような新しい発見もありましたが、全体としてご自身の手応えはいかがでしたか？ 例えば、10点満点で言うと何点くらいの達成感がありましたか？**
    > 」

#### ステップ2：自信の調整と次への橋渡し（Botラリー2）
* **目的:** ステップ1の回答（自信の状態）に応じて、「コーチ」として寄り添い、次回の計画（``）への心理的ハードルを調整する。
* **対話例（分岐）:**
    * **A. ユーザーが「自信になった」と回答した場合:**
        > 「それは素晴らしい！『できた』という実感は何よりの力になりますね。
        >
        > その良い流れで、次回の計画『』も進められそうですね。
        >
        > **を実行する上で、何か懸念点や、学習を妨げになりそうなこと（例えば、時間の確保や集中できる環境など）はありますか？**」
    * **B. ユーザーが「難しかった」と回答した場合:**
        > 「『難しかった』と率直に教えてくださり、ありがとうございます。それは〇〇さんが今まさに成長しようとしている証拠ですよ。
        >
        > 次回の計画は『』とのことですが、**この計画をもう少し小さなステップに分解して、確実に『できた』と感じられるように調整してみませんか？**」

#### ステップ3：意思の確認とクロージング（Botラリー3）
* **目的:** ステップ2の回答を受け、次への行動をユーザー自身にコミットメントさせ、ポジティブな気持ちで対話を終える。
* **対話例:**
    * **（Aの回答「特に懸念はない」への返信）:**
        > 「頼いですね！その調子なら大丈夫ですね。〇〇さんならできますよ。次回の報告も楽しみにしています！」
    * **（Bの回答「（小さなステップ）をやる」への返信）:**
        > 「『[ユーザーが考えた小さなステップ]』、とても良いですね！それなら確実に実行できそうです。小さな成功を一つずつ積み重ねていきましょう。応援しています！」

### ５．対話終了後の流れ

* **（ステップ3の対話が落ち着いたら、以下の総括とフィードバックを生成して対話をまとめてください）**
* 対話のまとめとして、記録ように当日の対話のダイアログをドキュメントにそのままコピーアンドペーストできるcsv.形式で出力してください。
* 翌日以降もドキュメントがアップロードされた際には、それまでの対話の内容も踏まえて学習目標を達成できるよう、同じように対話を行い、学習者の学習意欲の維持と学習目標達成をサポートしてください。
* 最後の応答では、必ず対話の終了を告げ、**その日の学習の総括と簡単なフィードバック**を加えてください。
"""
                
                # ★★★ モデルの初期化（修正） ★★★
                # system_instruction に上で定義したプロンプトを渡します。
                model = genai.GenerativeModel(
                    'gemini-1.5-flash', # <--- ここを修正しました
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
あなたは今、システムプロンプト（役割定義）に従い、指導教員/コーチとして振ル舞っています。
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
