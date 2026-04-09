import os
import json
import base64
import streamlit as st
from datetime import date
from openai import OpenAI
from PIL import Image, UnidentifiedImageError

# =========================
# 基本設定
# =========================
st.set_page_config(page_title="SNS要注意サイン診断", page_icon="⚠️")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

# 日付リセット
today = str(date.today())
if st.session_state.usage_date != today:
    st.session_state.usage_date = today
    st.session_state.free_count = 0

# =========================
# JSON安全処理
# =========================
def safe_json_parse(text):
    try:
        return json.loads(text)
    except:
        return {"risk": "不明", "flags": [], "advice": text}

# =========================
# テキスト診断
# =========================
def ai_check_risk_text(text):
    prompt = f"""
あなたはSNS安全アドバイザーです。
以下のメッセージを分析しJSONで返してください。

{{
"risk":"低/中/高",
"flags":["注意点"],
"advice":"助言"
}}

{text}
"""

    res = client.responses.create(
        model="gpt-4o-mini",
        input=prompt
    )

    return safe_json_parse(res.output_text)

# =========================
# 画像診断
# =========================
def ai_check_risk_image(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    base64_image = base64.b64encode(file_bytes).decode()

    res = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "この画像の危険性をJSONで分析して"},
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{base64_image}"}
                ]
            }
        ]
    )

    return safe_json_parse(res.output_text)

# =========================
# UI
# =========================
st.title("⚠️ SNS要注意サイン診断")

# 状態表示
if st.session_state.premium:
    st.success("💎 有料版")
else:
    remaining = FREE_DAILY_LIMIT - st.session_state.free_count
    st.info(f"無料版：残り {remaining} 回")

# =========================
# ログイン
# =========================
password = st.text_input(
    "有料版パスワード",
    type="password",
    key="premium_pass"
)

if st.button("ログイン"):
    if password == "1234":  # 仮
        st.session_state.premium = True
        st.success("ログイン成功")
    else:
        st.error("パスワード違う")

# =========================
# 入力
# =========================
text = st.text_area("メッセージ入力", key="main_text")

uploaded_file = None
if st.session_state.premium:
    uploaded_file = st.file_uploader("画像アップロード", type=["png","jpg","jpeg"], key="main_img")
else:
    st.write("🔒画像診断は有料版のみ")

# 画像表示
if uploaded_file:
    try:
        img = Image.open(uploaded_file)
        st.image(img)
    except UnidentifiedImageError:
        st.error("画像読めません")

# =========================
# 診断
# =========================
if st.button("診断する"):
    if not text and not uploaded_file:
        st.warning("入力してください")
        st.stop()

    if not st.session_state.premium:
        if st.session_state.free_count >= FREE_DAILY_LIMIT:
            st.error("無料回数終了")
            st.stop()
        st.session_state.free_count += 1

    with st.spinner("診断中..."):
        try:
            if uploaded_file:
                result = ai_check_risk_image(uploaded_file)
            else:
                result = ai_check_risk_text(text)

            st.write("### 診断結果")
            st.write(result)

        except Exception as e:
            st.error("エラー発生")
            if DEBUG_MODE:
                st.write(e)
