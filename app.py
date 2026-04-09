import os
import json
import base64
from datetime import date

import streamlit as st
from openai import OpenAI
from PIL import Image, UnidentifiedImageError

# ----------------------------
# 基本設定
# ----------------------------
st.set_page_config(page_title="SNS要注意サイン診断", page_icon="⚠️")

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.error("OPENAI_API_KEY が設定されていません")
    st.stop()

client = OpenAI(api_key=api_key)

FREE_DAILY_LIMIT = 3
PREMIUM_PASSWORD = "1234"  # 仮

# ----------------------------
# セッション初期化
# ----------------------------
if "premium" not in st.session_state:
    st.session_state.premium = False

if "usage_date" not in st.session_state:
    st.session_state.usage_date = str(date.today())

if "free_count" not in st.session_state:
    st.session_state.free_count = 0

today = str(date.today())
if st.session_state.usage_date != today:
    st.session_state.usage_date = today
    st.session_state.free_count = 0

# ----------------------------
# 共通関数
# ----------------------------
def extract_text_from_response(response) -> str:
    """
    OpenAIレスポンスから文字列を安全に取り出す
    """
    # まずは使えるなら output_text
    text = getattr(response, "output_text", None)
    if text:
        return text

    # ダメなら output 配列を順番に探す
    try:
        for item in response.output:
            content_list = getattr(item, "content", None)
            if not content_list:
                continue
            for content in content_list:
                ctext = getattr(content, "text", None)
                if ctext:
                    return ctext
    except Exception:
        pass

    return ""


def safe_json_parse(text: str) -> dict:
    """
    JSONで返らなかったときも落ちないようにする
    """
    try:
        return json.loads(text)
    except Exception:
        return {
            "risk": "不明",
            "flags": [],
            "advice": text[:200] if text else "結果を取得できませんでした"
        }


def build_prompt(user_text: str) -> str:
    return f"""
あなたはSNS安全アドバイザーです。
相手を断定せず、文章や画像に含まれる注意サインだけを分析してください。
必ずJSONのみで返してください。

形式:
{{
  "risk": "低" または "中" または "高",
  "flags": ["注意ポイント1", "注意ポイント2"],
  "advice": "短い助言"
}}

分析対象:
{user_text}
""".strip()


def ai_check_risk_text(user_text: str) -> dict:
    prompt = build_prompt(user_text)

    response = client.responses.create(
        model="gpt-4o-mini",
        input=prompt
    )

    text = extract_text_from_response(response)
    return safe_json_parse(text)


def ai_check_risk_image(uploaded_file) -> dict:
    file_bytes = uploaded_file.getvalue()
    mime_type = uploaded_file.type or "image/jpeg"
    base64_image = base64.b64encode(file_bytes).decode("utf-8")

    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": """
あなたはSNS安全アドバイザーです。
画像に写っている文面・表示内容・不自然さを見て、
危険性をJSONのみで返してください。

形式:
{
  "risk": "低" または "中" または "高",
  "flags": ["注意ポイント1", "注意ポイント2"],
  "advice": "短い助言"
}
""".strip()
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{mime_type};base64,{base64_image}"
                    }
                ]
            }
        ]
    )

    text = extract_text_from_response(response)
    return safe_json_parse(text)

# ----------------------------
# UI
# ----------------------------
st.title("⚠️ SNS要注意サイン診断")

if st.session_state.premium:
    st.success("💎 有料版")
else:
    remaining = max(0, FREE_DAILY_LIMIT - st.session_state.free_count)
    st.info(f"無料版：残り {remaining} 回")

with st.expander("有料版ログイン"):
    password = st.text_input(
        "有料版パスワード",
        type="password",
        key="premium_pass_input"
    )
    if st.button("ログイン", key="login_button"):
        if password == PREMIUM_PASSWORD:
            st.session_state.premium = True
            st.success("ログイン成功")
        else:
            st.error("パスワードが違います")

text_input = st.text_area(
    "メッセージ入力",
    height=220,
    key="main_text_input"
)

uploaded_file = None
if st.session_state.premium:
    uploaded_file = st.file_uploader(
        "画像アップロード",
        type=["png", "jpg", "jpeg", "webp"],
        key="main_image_uploader"
    )
else:
    st.write("🔒 画像診断は有料版のみ")

if uploaded_file is not None:
    try:
        img = Image.open(uploaded_file)
        st.image(img, caption="アップロード画像", use_container_width=True)
    except UnidentifiedImageError:
        st.error("画像を読み込めませんでした")
        uploaded_file = None
    except Exception as e:
        st.error(f"画像表示エラー: {e}")
        uploaded_file = None

if st.button("診断する", key="run_check_button"):
    if not text_input and uploaded_file is None:
        st.warning("テキストか画像を入力してください")
        st.stop()

    if not st.session_state.premium:
        if st.session_state.free_count >= FREE_DAILY_LIMIT:
            st.error("無料回数が上限です")
            st.stop()
        st.session_state.free_count += 1

    with st.spinner("診断中..."):
        try:
            if uploaded_file is not None:
                result = ai_check_risk_image(uploaded_file)
            else:
                result = ai_check_risk_text(text_input)

            st.subheader("診断結果")

            risk = result.get("risk", "不明")
            flags = result.get("flags", [])
            advice = result.get("advice", "")

            st.write(f"**危険度:** {risk}")

            st.write("**注意ポイント:**")
            if flags:
                for flag in flags:
                    st.write(f"- {flag}")
            else:
                st.write("- なし")

            st.write("**助言:**")
            st.write(advice)

            with st.expander("JSON表示"):
                st.json(result)

        except Exception as e:
            st.error("診断中にエラーが発生しました")
            st.code(str(e))
