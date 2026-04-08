import os
import json
import base64
from io import BytesIO

import streamlit as st
from PIL import Image
from openai import OpenAI

st.set_page_config(
    page_title="SNS要注意サイン診断",
    page_icon="⚠️",
    layout="centered"
)

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    st.error("OPENAI_API_KEY が設定されていません。Streamlit Cloud の Secrets を確認してください。")
    st.stop()

client = OpenAI(api_key=api_key)


# ----------------------------
# UI
# ----------------------------
st.title("⚠️SNS要注意サイン診断⚠️")
st.write("メッセージ内容や画像をAIが読み取り、危険度と注意ポイントを診断します。")

st.markdown("### ここにメッセージを貼る")
text = st.text_area(
    label="メッセージ入力",
    label_visibility="collapsed",
    height=220,
    placeholder="例：『すぐLINEに来て』『投資で必ず儲かる』『誰にも言わないで』など"
)

st.markdown("### 画像をアップしてください")
uploaded_file = st.file_uploader(
    "画像を選択",
    type=["png", "jpg", "jpeg"],
    key="image_uploader"
)

image_bytes = None
if uploaded_file is not None:
    image_bytes = uploaded_file.read()
    try:
        preview_img = Image.open(BytesIO(image_bytes))
        st.image(preview_img, caption="アップロード画像", use_container_width=True)
    except Exception:
        st.warning("画像のプレビューに失敗しました。別の画像を試してください。")


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


def ai_check_risk(user_text: str, image_data: bytes | None = None) -> dict:
    prompt = build_prompt(user_text)

    content = [
        {"type": "input_text", "text": prompt}
    ]

    if image_data:
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{image_base64}"
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
    if not text.strip() and image_bytes is None:
        st.warning("メッセージまたは画像を入力してください。")
    else:
        with st.spinner("診断中です..."):
            try:
                result = ai_check_risk(text, image_bytes)
                render_result(result)
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")


st.markdown("---")
st.caption("※この診断は参考情報です。緊急性がある場合は警察・公的窓口に相談してください。")
