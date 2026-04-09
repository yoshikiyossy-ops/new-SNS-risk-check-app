import os
import io
import csv
import json
import base64
import requests
import streamlit as st
from datetime import date
from openai import OpenAI

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
    """
    有料版用の画像診断
    画像の中の文面・雰囲気・誘導表現などを分析
    """
    file_bytes = uploaded_file.read()
    mime_type = uploaded_file.type or "image/png"
    base64_image = base64.b64encode(file_bytes).decode("utf-8")

    if premium:
        instruction = """
画像内のメッセージ文面や誘導表現、圧の強さ、金銭誘導、外部誘導などの注意サインを丁寧に分析してください。
人物の断定は避けてください。
"""
    else:
        instruction = "簡潔に分析してください。"

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "あなたは慎重で実用的なSNS安全アドバイザーです。必ずJSONのみで返答してください。"
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"""
あなたはSNS安全アドバイザーです。
画像に含まれるDM・チャット・メッセージ内容を分析し、
危険の断定はせず、注意サインのみを抽出してください。

{instruction}

出力は必ずJSONのみで返してください。
形式:
{{
  "risk": "低" または "中" または "高",
  "flags": ["注意ポイント1", "注意ポイント2"],
  "advice": "短い助言",
  "category": "詐欺" または "ストーカー" または "操作的言動" または "要注意" または "判断保留"
}}
"""
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        temperature=0.2
    )

    content = response.choices[0].message.content or ""
    return safe_json_parse(content)


# =========================
# UI
# =========================
st.title("⚠️ SNS要注意サイン診断")
st.write("DMやメッセージをAIが読み取り、危険度と注意ポイントを整理します。")

# プラン状態表示
if st.session_state.premium:
    st.info("💎 有料版：テキスト無制限 / 画像診断対応")
else:
    remaining = max(FREE_DAILY_LIMIT - st.session_state.free_count, 0)
    st.info(f"🔓 無料版：1日{FREE_DAILY_LIMIT}回まで / 残り {remaining} 回")

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
        st.image(uploaded_file, caption="アップロード画像", use_container_width=True)

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
