import os
import io
import csv
import json
import base64
import requests
import streamlit as st
from datetime import date
from openai import OpenAI
from PIL import Image, UnidentifiedImageError


# =========================
# 基本設定
# =========================
st.set_page_config(
    page_title="SNS要注意サイン診断",
    page_icon="⚠️",
    layout="centered"
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
PASSWORD_SHEET_CSV_URL = os.getenv("PASSWORD_SHEET_CSV_URL")

FREE_DAILY_LIMIT = 3
DEBUG_MODE = False

# =========================
# セッション初期化
# =========================
if "premium" not in st.session_state:
    st.session_state.premium = False

if "usage_date" not in st.session_state:
    st.session_state.usage_date = str(date.today())

if "free_count" not in st.session_state:
    st.session_state.free_count = 0

if "premium_password" not in st.session_state:
    st.session_state.premium_password = ""

# 日付が変わったら無料回数リセット
today_str = str(date.today())
if st.session_state.usage_date != today_str:
    st.session_state.usage_date = today_str
    st.session_state.free_count = 0


# =========================
# 共通関数
# =========================
def safe_json_parse(text: str) -> dict:
    """
    AI応答からJSONをできるだけ安全に取り出す
    """
    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    # 余分な文章が混ざった場合に JSON 部分だけ抽出
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and start < end:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    return {
        "risk": "判断保留",
        "flags": ["AIの応答をJSONとして処理できませんでした"],
        "advice": "入力内容を少し短くするか、もう一度お試しください。",
        "category": "判断保留"
    }


def show_result(result: dict):
    risk = result.get("risk", "判断保留")
    flags = result.get("flags", [])
    advice = result.get("advice", "")
    category = result.get("category", "判断保留")

    st.subheader("診断結果")

    if risk == "高":
        st.error(f"危険度：{risk}")
    elif risk == "中":
        st.warning(f"危険度：{risk}")
    else:
        st.success(f"危険度：{risk}")

    st.write(f"**分類:** {category}")

    st.write("**注意ポイント**")
    if isinstance(flags, list) and flags:
        for f in flags:
            st.write(f"- {f}")
    else:
        st.write("- 特記事項なし")

    st.write("**アドバイス**")
    st.write(advice)


def get_active_passwords_from_sheet(csv_url: str):
    """
    公開CSV化したGoogleスプレッドシートから有効なパスワード一覧を取得
    想定列: month, password, active, expires
    active が TRUE / true / 1 / yes の行のみ有効
    """
    if not csv_url:
        raise ValueError("PASSWORD_SHEET_CSV_URL が未設定です")

    response = requests.get(csv_url, timeout=10)
    response.raise_for_status()

    decoded = response.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(decoded))

    active_rows = []
    for row in reader:
        active_value = str(row.get("active", "")).strip().lower()
        is_active = active_value in ["true", "1", "yes", "y", "on"]

        password = str(row.get("password", "")).strip()
        month = str(row.get("month", "")).strip()
        expires = str(row.get("expires", "")).strip()

        if is_active and password:
            active_rows.append({
                "month": month,
                "password": password,
                "expires": expires
            })

    return active_rows


def validate_premium_password(input_password: str):
    """
    入力パスワードが有効か判定
    """
    active_rows = get_active_passwords_from_sheet(PASSWORD_SHEET_CSV_URL)
    for row in active_rows:
        if input_password.strip() == row["password"]:
            return True, row
    return False, None


def ai_check_risk_text(text: str, premium: bool = False):
    if premium:
        instruction = """
より詳しく分析してください。
危険の断定ではなく、文章に含まれる注意サインを慎重に抽出し、
実用的な対処法も少し具体的に示してください。
"""
    else:
        instruction = """
簡潔に分析してください。
危険の断定ではなく、文章に含まれる注意サインだけを短く整理してください。
"""

    prompt = f"""
あなたはSNS安全アドバイザーです。
次のメッセージを読み、人物を断定評価せず、
文章内に見られる注意サインだけを分析してください。

{instruction}

出力は必ずJSONのみで返してください。
形式:
{{
  "risk": "低" または "中" または "高",
  "flags": ["注意ポイント1", "注意ポイント2"],
  "advice": "短い助言",
  "category": "詐欺" または "ストーカー" または "操作的言動" または "要注意" または "判断保留"
}}

分析対象:
{text}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "あなたは慎重で実用的なSNS安全アドバイザーです。必ずJSONのみで返答してください。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3
    )

    content = response.choices[0].message.content or ""
    return safe_json_parse(content)


def ai_check_risk_image(uploaded_file, premium: bool = True):
    file_bytes = uploaded_file.read()
    mime_type = uploaded_file.type or "image/jpeg"
    base64_image = base64.b64encode(file_bytes).decode("utf-8")

    prompt = """
あなたはSNS安全アドバイザーです。
画像に含まれるDM・チャット内容を分析し、
危険の断定はせず、注意サインのみを抽出してください。

出力は必ずJSONのみで返してください。
{
  "risk": "低" または "中" または "高",
  "flags": ["注意ポイント1", "注意ポイント2"],
  "advice": "短い助言",
  "category": "詐欺" または "ストーカー" または "操作的言動" または "要注意" または "判断保留"
}
"""

    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{base64_image}"
                    }
                ]
            }
        ]
    )

    raw = response.output_text
    return safe_json_parse(raw)

# =========================
# UI
# =========================
# =========================
# UI
# =========================
st.title("⚠️ SNS要注意サイン診断")
st.write("DMやメッセージをAIが読み取り、危険度と注意ポイントを整理します。")

if st.session_state.premium:
    st.info("💎 有料版：テキスト無制限 / 画像診断対応")
else:
    remaining = max(FREE_DAILY_LIMIT - st.session_state.free_count, 0)
    st.info(f"🔓 無料版：1日{FREE_DAILY_LIMIT}回まで / 残り {remaining} 回")

with st.expander("🔐 有料版ログイン"):
    st.write("note購入後に案内された最新パスワードを入力してください。")
    password = st.text_input("有料版パスワード", type="password")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("ログイン", use_container_width=True):
            if not password.strip():
                st.warning("パスワードを入力してください")
            else:
                try:
                    ok, matched_row = validate_premium_password(password)
                    if ok:
                        st.session_state.premium = True
                        st.session_state.premium_password = password
                        month_label = matched_row.get("month", "")
                        expires_label = matched_row.get("expires", "")
                        st.success(f"有料版が有効化されました（{month_label} / {expires_label}まで）")
                    else:
                        st.error("パスワードが違うか、現在は無効です")
                except Exception as e:
                    st.error(f"パスワード確認に失敗しました: {e}")

    with col2:
        if st.button("ログアウト", use_container_width=True):
            st.session_state.premium = False
            st.session_state.premium_password = ""
            st.success("ログアウトしました")

st.markdown("### ここにメッセージを貼る")
text = st.text_area(
    "メッセージ入力",
    height=220,
    placeholder="例：『すぐLINEに来て』『投資で必ず儲かる』『誰にも言わないで』など"
)

st.markdown("### 画像をアップしてください")

if st.session_state.premium:
    uploaded_file = st.file_uploader(
        "画像を選択",
        type=["png", "jpg", "jpeg", "webp"],
        help="PNG / JPG / JPEG / WEBP の画像を選べます"
    )
else:
    uploaded_file = None
    st.write("🔒 画像診断は有料版で利用できます")

image_bytes = None
image_mime_type = None
image_ready = False

if uploaded_file is not None:
    try:
        image_bytes = uploaded_file.getvalue()
        image_mime_type = uploaded_file.type or "image/jpeg"
        preview_img = Image.open(uploaded_file)
        st.image(preview_img, caption="アップロード画像", use_container_width=True)
        image_ready = True
    except UnidentifiedImageError:
        st.error("画像形式を読み取れませんでした。PNG/JPGの画像を試してください。")
        image_bytes = None
        image_mime_type = None

if st.button("🔍 診断する", use_container_width=True):
    if not text.strip() and not image_ready:
        st.warning("メッセージまたは画像を入力してください。")
    else:
        if not st.session_state.premium:
            if st.session_state.free_count >= FREE_DAILY_LIMIT:
                st.warning("無料版の利用回数に達しました。有料版をご利用ください。")
                st.stop()
            st.session_state.free_count += 1

        with st.spinner("診断中です..."):
            try:
                if image_ready:
                    result = ai_check_risk(text, image_bytes, image_mime_type)
                    render_result(result)
                else:
                    result = ai_check_risk_text(text, premium=st.session_state.premium)
                    show_result(result)
            except Exception as e:
                st.error("診断中にエラーが発生しました。時間をおいて再度お試しください。")
                if DEBUG_MODE:
                    st.exception(e)

        if not st.session_state.premium:
            remaining = max(FREE_DAILY_LIMIT - st.session_state.free_count, 0)
            st.caption(f"無料版の残り回数: {remaining} 回")

st.markdown("---")
st.write("### 無料版と有料版の違い")

st.write("**無料版**")
st.write("- テキスト診断")
st.write(f"- 1日{FREE_DAILY_LIMIT}回まで")
st.write("- シンプル分析")

st.write("**有料版**")
st.write("- テキスト診断 無制限")
st.write("- 画像診断対応")
st.write("- より詳細な分析")
st.write("- 実用的な安全アドバイス")

# =========================
# 有料版ログイン
# =========================
with st.expander("🔐 有料版ログイン"):
    st.write("note購入後に案内された最新パスワードを入力してください。")

    password = st.text_input("有料版パスワード", type="password")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("ログイン", use_container_width=True):
            if not password.strip():
                st.warning("パスワードを入力してください")
            else:
                try:
                    ok, matched_row = validate_premium_password(password)
                    if ok:
                        st.session_state.premium = True
                        st.session_state.premium_password = password
                        month_label = matched_row.get("month", "")
                        expires_label = matched_row.get("expires", "")
                        st.success(f"有料版が有効化されました（{month_label} / {expires_label}まで）")
                    else:
                        st.error("パスワードが違うか、現在は無効です")
                except Exception as e:
                    st.error(f"パスワード確認に失敗しました: {e}")

    with col2:
        if st.button("ログアウト", use_container_width=True):
            st.session_state.premium = False
            st.session_state.premium_password = ""
            st.success("ログアウトしました")

    if st.session_state.premium:
        st.success("現在、有料版が有効です")


# =========================
# テキスト診断
# =========================
st.subheader("📝 テキスト診断")
text = st.text_area("ここにメッセージを貼ってください", height=220)

if st.button("テキストを診断する"):
    if not text.strip():
        st.warning("診断するメッセージを入力してください")
    else:
        if not st.session_state.premium:
            if st.session_state.free_count >= FREE_DAILY_LIMIT:
                st.warning("無料版の利用回数に達しました。有料版をご利用ください。")
                st.stop()
            st.session_state.free_count += 1

        with st.spinner("診断中..."):
            result = ai_check_risk_text(text, premium=st.session_state.premium)

        show_result(result)

        if not st.session_state.premium:
            remaining = max(FREE_DAILY_LIMIT - st.session_state.free_count, 0)
            st.caption(f"無料版の残り回数: {remaining} 回")


# =========================
# 画像診断（有料版のみ）
# =========================
st.subheader("🖼️ 画像診断")

if st.session_state.premium:
    uploaded_file = st.file_uploader(
        "スクリーンショットや画像をアップロード",
        type=["png", "jpg", "jpeg", "webp"]
    )

    if uploaded_file is not None:
        try:
            image = Image.open(uploaded_file)
            st.image(image, caption="アップロード画像", use_container_width=True)

        except UnidentifiedImageError:
            st.error("画像ファイルが読み取れません。PNG/JPG形式を試してください。")

        if st.button("画像を診断する"):
            with st.spinner("画像を診断中..."):
                result = ai_check_risk_image(uploaded_file, premium=True)
            show_result(result)
else:
    st.write("🔒 画像診断は有料版で利用できます")


# =========================
# 下部説明
# =========================
st.markdown("---")
st.write("### 無料版と有料版の違い")

st.write("**無料版**")
st.write("- テキスト診断")
st.write(f"- 1日{FREE_DAILY_LIMIT}回まで")
st.write("- シンプル分析")

st.write("**有料版**")
st.write("- テキスト診断 無制限")
st.write("- 画像診断対応")
st.write("- より詳細な分析")
st.write("- 実用的な安全アドバイス")




# ----------------------------
# Functions
# ----------------------------
def build_prompt(user_text: str) -> str:
    return f"""
あなたはSNS安全アドバイザーです。
人物を断定評価せず、文章や画像内に見られる注意サインのみを分析してください。
出力は必ずJSONのみで返してください。説明文は不要です。

出力形式:
{{
  "risk":"低"または"中"または"高",
  "flags":["注意ポイント1","注意ポイント2"],
  "advice":"短い助言",
  "category":"詐欺" または "性的リスク" または "操作的言動" または "ストーカー傾向" または "その他"
}}

判定ルール:
- 金銭要求、投資勧誘、副業勧誘、認証コード要求、外部アプリ誘導、秘密の強要、脅し、罪悪感を使った操作は危険度を上げる
- 性的な話題そのものを自動で危険認定しない
- ただし、以下は危険度を上げる
  - 急な性的要求
  - 裸の写真や動画の要求
  - 断っても続く性的な要求
  - 会う前の露骨な性的発言
  - 秘密を求める性的会話
  - 脅しや拡散を示唆する性的要求
  - 年齢不明または未成年の可能性がある相手への性的接触
- ストーカー的な特徴
  - 過剰な連絡
  - 返信の強要
  - 位置情報や行動把握の要求
  - 嫉妬や束縛
  - 無視しても連絡を続ける
- 強い注意サインが複数ある場合は「高」
- 注意サインが一つなら「中」の候補
- 特に強い注意サインがなければ「低」
- 人物断定は禁止
- 「注意が必要な表現がある」などの表現にする

出力ルール:
- flags は短く分かりやすく
- advice はユーザーがすぐ使える一文
- category は最も近いものを1つだけ選ぶ

ユーザーが入力したメッセージ:
{user_text if user_text.strip() else "（入力なし）"}
""".strip()


def safe_json_parse(raw_text: str) -> dict:
    raw_text = raw_text.strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(raw_text[start:end + 1])
        raise


def ai_check_risk(user_text: str, image_data: bytes | None = None, mime_type: str | None = None) -> dict:
    prompt = build_prompt(user_text)

    content = [
        {"type": "input_text", "text": prompt}
    ]

    if image_data:
        safe_mime = mime_type if mime_type in ["image/png", "image/jpeg", "image/jpg"] else "image/jpeg"
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{safe_mime};base64,{image_base64}"
            }
        )

    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {
                "role": "user",
                "content": content
            }
        ]
    )

    raw = response.output_text

    if DEBUG_MODE:
        st.write("モデル出力:", raw)

    data = safe_json_parse(raw)

    if "risk" not in data:
        data["risk"] = "低"
    if "flags" not in data or not isinstance(data["flags"], list):
        data["flags"] = []
    if "advice" not in data:
        data["advice"] = "違和感がある場合は慎重に対応してください。"
    if "category" not in data:
        data["category"] = "その他"

    return data


def suggest_safe_action(category: str, risk: str) -> list[str]:
    actions = []

    if risk == "高":
        actions.append("【最優先】今すぐ返信をやめてください")
        actions.append("メッセージや画像をスクリーンショットで保存してください")
        actions.append("URLや添付ファイルは開かないでください")
        actions.append("ブロックや通報を検討してください")

    elif risk == "中":
        actions.append("個人情報は送らないでください")
        actions.append("相手の意図を慎重に確認してください")
        actions.append("違和感があればやり取りを止めてください")

    else:
        actions.append("大きな危険サインは少ないですが、個人情報の共有は慎重にしてください")

    if category == "詐欺":
        actions.append("お金・認証コード・ログイン情報は絶対に渡さないでください")
    elif category == "性的リスク":
        actions.append("性的な要求や画像要求には応じないでください")
    elif category == "ストーカー傾向":
        actions.append("しつこい連絡には無理に対応せず、記録を残してください")
        actions.append("位置情報や予定は伝えないでください")
    elif category == "操作的言動":
        actions.append("罪悪感を利用した誘導には乗らず、いったん距離を置いてください")

    return actions


def render_result(result: dict):
    risk = result.get("risk", "低")
    category = result.get("category", "その他")
    flags = result.get("flags", [])
    advice = result.get("advice", "違和感がある場合は慎重に対応してください。")

    st.subheader("診断結果")

    if risk == "低":
        st.success("🟢 危険度：低")
    elif risk == "中":
        st.warning("🟡 危険度：中")
    else:
        st.error("🔴 危険度：高")

    st.write(f"**カテゴリ**：{category}")

    st.subheader("注意ポイント")
    if flags:
        for f in flags:
            st.write(f"・{f}")
    else:
        st.write("特に強い注意サインは見つかりませんでした。")

    st.subheader("アドバイス")
    st.info(advice)

    st.subheader("🛡 安全な対応")
    for action in suggest_safe_action(category, risk):
        st.write(f"・{action}")

    st.markdown("---")
    st.link_button(
        "👉 消費者庁の注意喚起を見る",
        "https://www.caa.go.jp/policies/policy/consumer_policy/caution/"
    )


# ----------------------------
# Action
# ----------------------------
if st.button("🔍 診断する", key="diagnose_button", use_container_width=True):
    if not text.strip() and not image_ready:
        st.warning("メッセージまたは画像を入力してください。")
    else:
        with st.spinner("診断中です..."):
            try:
                result = ai_check_risk(text, image_bytes if image_ready else None, image_mime_type)
                render_result(result)
            except Exception as e:
                st.error("診断中にエラーが発生しました。時間をおいて再度お試しください。")
                st.caption("画像がうまく通らない場合は、スクリーンショット画像に変えて再度お試しください。")
                if DEBUG_MODE:
                    st.exception(e)

st.markdown("---")
st.caption("※この診断は参考情報です。緊急性がある場合は警察・公的窓口に相談してください。")
