import streamlit as st
import base64
import os
import re
import textwrap

# ── 기본 설정 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MUMU - Diary",
    page_icon="img/main/web_icon.png",
    layout="centered"
)

# 프로젝트 루트(= pages 상위) 기준으로 diary_DB 찾기
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DIARY_DIR = os.path.join(BASE_DIR, "diary_DB")
os.makedirs(DIARY_DIR, exist_ok=True)

# 이미지 디렉토리
IMG_DIR = "img/diary"

def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# 에셋 경로
bg_img_path     = os.path.join(IMG_DIR, "background.png")
btn_back_path   = os.path.join(IMG_DIR, "btn_back.png")
btn_diary_path  = os.path.join(IMG_DIR, "btn_diary.png")

# base64
bg_base64        = image_to_base64(bg_img_path)
btn_back_base64  = image_to_base64(btn_back_path)
btn_diary_base64 = image_to_base64(btn_diary_path)

# ── 요약 파일 로드 & 타이틀 추출 ───────────────────────────────────────────
def list_diaries():
    files = []
    for name in os.listdir(DIARY_DIR):
        if name.startswith("diary_") and name.endswith(".txt"):
            path = os.path.join(DIARY_DIR, name)
            try:
                mtime = os.path.getmtime(path)
            except Exception:
                mtime = 0
            files.append((name, path, mtime))
    files.sort(key=lambda x: x[2], reverse=True)  # 최신순
    return files

def extract_title_from_summary(text: str) -> str:
    if not text:
        return ""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    for line in reversed(lines[-3:]):
        m = re.search(r"제목\s*[:：]\s*(.+)", line)
        if m:
            return m.group(1).strip()
    last_line = lines[-1]
    return last_line[:40] + ("…" if len(last_line) > 40 else "")

def load_diary_cards():
    cards = []
    for fname, fpath, _ in list_diaries():
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = ""
        title = extract_title_from_summary(content) or fname
        href = f"read_diary?file={fname}"
        cards.append((href, title))
    return cards

cards = load_diary_cards()  # [(href, title), ...]

# ── 스타일 ────────────────────────────────────────────────────────────────
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
            overflow: hidden;

    width: 85vw;
    max-width: 320px;
    aspect-ratio: 318 / 693;
    margin: 0 auto;
    position: relative;
}}

.btn-back {{
    width: 9%;
    position: absolute;
    top: 6.8%;
    left: 6%;
}}

/* 다이어리 리스트 영역 */
.list-wrap {{
    position: absolute;
    left: 0; right: 0;
    top: 28%;
    bottom: 16%;
    overflow-y: auto;
    padding: 0 .5rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
}}

/* 버튼(이미지 + 센터 텍스트) */
.diary-btn {{
    position: relative;
    width: 80%;
    display: block;
    text-decoration: none;
}}
.diary-btn img {{
    width: 100%;
    height: auto;
    display: block;
}}
.diary-btn .title {{
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    margin: 0; padding: 0 .6rem; width: 85%;
    text-align: center;
    font-size: 14px; font-weight: 700; color: #000;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}

/* 비어있는 상태 안내 */
.empty-msg {{
    width: 80%;
    text-align: center;
    color: #555;
    font-size: 14px;
    background: #fff;
    border: 1px dashed #d9d9d9;
    border-radius: 12px;
    padding: 14px 10px;
    margin-top: 6px;
}}
</style>
""", unsafe_allow_html=True)

# ── HTML 구성 (들여쓰기 제거) ─────────────────────────────────────────────
if cards:
    cards_html = "".join([
        f'''<a href="{href}" target="_self" class="diary-btn">
<img src="data:image/png;base64,{btn_diary_base64}" alt="diary button"/>
<div class="title">{title}</div>
</a>'''
        for href, title in cards
    ])
else:
    cards_html = '<div class="empty-msg">나랑 대화하면 내가 일기를 쓸거야!</div>'

raw_html = f"""
<div class="main-box">
<a href="/" target="_self">
<img src="data:image/png;base64,{btn_back_base64}" class="btn-back"/>
</a>
<div class="list-wrap">
{cards_html}
</div>
</div>
"""

st.markdown(textwrap.dedent(raw_html), unsafe_allow_html=True)
