import os
import json
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
APP_PASSWORD = os.getenv("APP_PASSWORD")  # 有料版パスワードを環境変数で設定

# =========================
# セッション初期化
# =========================
if "premium" not in st.session_state:
    st.session_state.premium = False

if "usage_date" not in st.session_state:
    st.session_state.usage_date = str(date.today())

if "free_count" not in st.session_state:
    st.session_state.free_count = 0

# 日付が変わったら無料回数リセット
today_str = str(date.today())
if st.session_state.usage_date != today_str:
    st.session_state.usage_date = today_str
    st.session_state.free_count = 0

# =========================
# 関数
# =========================
def ai_check_risk_text(text: str):
    prompt = f"""
あなたはSNS安全アドバイザーです。
次のメッセージを読み、人物を断定評価せず、
文章内の注意サインだけを分析してください。

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
            {"role": "system", "content": "あなたは慎重で実用的なSNS安全アドバイザーです。必ずJSONのみで返答してください。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    content = response.choices[0].message.content.strip()

    try:
        return json.loads(content)
    except Exception:
        return {
            "risk": "判断保留",
            "flags": ["AIの応答整形に失敗しました"],
            "advice": "もう一度入力内容を少し短くして試してください。",
            "category": "判断保留"
        }


def ai_check_risk_image(uploaded_file):
    # ここは現段階では簡易表示
    # 将来的に vision対応モデルで画像解析に差し替え可能
    return {
        "risk": "要実装",
        "flags": ["有料版の画像診断エリアです"],
        "advice": "ここに画像解析機能を追加できます。",
        "category": "画像診断"
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
    if flags:
        for f in flags:
            st.write(f"- {f}")
    else:
        st.write("- 特記事項なし")

    st.write("**アドバイス**")
    st.write(advice)


# =========================
# ヘッダー
# =========================
st.title("⚠️ SNS要注意サイン診断")
st.write("メッセージ内容をAIが読み取り、危険度と注意ポイントを判定します。")

# =========================
# 有料版ログイン
# =========================
with st.expander("🔐 有料版ログイン"):
    password = st.text_input("パスワードを入力", type="password")

    if st.button("ログイン"):
        if not APP_PASSWORD:
            st.error("APP_PASSWORD が設定されていません")
        elif password == APP_PASSWORD:
            st.session_state.premium = True
            st.success("有料版が有効化されました")
        else:
            st.error("パスワードが違います")

    if st.session_state.premium:
        st.success("現在、有料版が有効です")

# =========================
# プラン表示
# =========================
if st.session_state.premium:
    st.info("💎 有料版：無制限 / 画像診断対応")
else:
    remaining = 3 - st.session_state.free_count
    st.info(f"🔓 無料版：1日3回まで / 残り {max(remaining, 0)} 回")

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
            if st.session_state.free_count >= 3:
                st.warning("無料版は1日3回までです。有料版をご利用ください。")
                st.stop()
            st.session_state.free_count += 1

        with st.spinner("診断中..."):
            result = ai_check_risk_text(text)

        show_result(result)

        if not st.session_state.premium:
            remaining = 3 - st.session_state.free_count
            st.caption(f"無料版の残り回数: {max(remaining, 0)} 回")

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
            with st.spinner("画像を確認中..."):
                result = ai_check_risk_image(uploaded_file)
            show_result(result)
else:
    st.write("🔒 画像診断は有料版で利用できます")

# =========================
# フッター
# =========================
st.markdown("---")
st.write("### 無料版と有料版の違い")
st.write("**無料版**")
st.write("- テキスト診断")
st.write("- 1日3回まで")
st.write("- シンプル分析")

st.write("**有料版**")
st.write("- テキスト診断 無制限")
st.write("- 画像診断対応")
st.write("- 詳細分析")
st.write("- 安全アドバイス強化")
