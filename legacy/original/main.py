# main.py
import streamlit as st
import base64
import os
import mumu  # 모델 및 기능 전부 로딩됨

# 페이지 설정
st.set_page_config(
    page_title="Me & U Mellow Unit",
    page_icon="img/main/web_icon.png", 
    layout="centered"
)

# 이미지 디렉토리
IMG_DIR = "img/main"

# base64 인코딩 함수
def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# 경로 지정
bg_img_path = os.path.join(IMG_DIR, "main_bg.png")
logo_path = os.path.join(IMG_DIR, "maintitle.png")
mascot_path = os.path.join(IMG_DIR, "mascot.png")
subtitle_path = os.path.join(IMG_DIR, "subtitle.png")
btn_chat_path = os.path.join(IMG_DIR, "btn_chat.png")
btn_story_path = os.path.join(IMG_DIR, "btn_story.png")

# base64 인코딩
bg_base64 = image_to_base64(bg_img_path)
logo_base64 = image_to_base64(logo_path)
mascot_base64 = image_to_base64(mascot_path)
subtitle_base64 = image_to_base64(subtitle_path)
btn_chat_base64 = image_to_base64(btn_chat_path)
btn_story_base64 = image_to_base64(btn_story_path)

# 스타일 적용
st.markdown(f"""
    <style>
    html, body, [data-testid="stAppViewContainer"], .stApp, .block-container {{
        background-color: #ffffff !important;
    }}

    [data-testid="stSidebar"], [data-testid="stToolbar"], .st-emotion-cache-z5fcl4 {{
        display: none !important;
    }}

    .main-box {{
        background-image: url("data:image/png;base64,{bg_base64}");
        background-size: 100% auto;
        background-position: center top;
        background-repeat: no-repeat;
        
            border-radius: 28px; border: 1.5px solid #e0a96d; 
            box-shadow: 0 10px 24px rgba(0,0,0,.08), 0 2px 6px rgba(0,0,0,.06); 
            overflow: hidden;  background: #fffaf3;

        width: 85vw;
        max-width: 320px;
        aspect-ratio: 318 / 693;
        margin: 0 auto;

        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-start;
        padding-top: 8%;
        gap: 4%;
    }}

    .logo     {{ width: 60%; }}
    .mascot   {{ width: 48%; }}
    .subtitle {{ width: 80%; }}

    a {{
        width: 100%;
        display: block;
        text-align: center;
    }}

    .btn {{
        width: 85%;
        cursor: pointer;
        display: block;
        margin: 0 auto;
    }}
    </style>
""", unsafe_allow_html=True)

# 본문 구성
st.markdown(f"""
<div class="main-box">
    <img src="data:image/png;base64,{logo_base64}" class="logo"/>
    <img src="data:image/png;base64,{mascot_base64}" class="mascot"/>
    <img src="data:image/png;base64,{subtitle_base64}" class="subtitle"/>
    <a href="chat" target="_self">
        <img src="data:image/png;base64,{btn_chat_base64}" class="btn"/>
    </a>
    <a href="diary" target="_self">
        <img src="data:image/png;base64,{btn_story_base64}" class="btn"/>
    </a>
</div>
""", unsafe_allow_html=True)
