import streamlit as st
import base64
import os
import re
import textwrap
import html

# 페이지 설정
st.set_page_config(
    page_title="MUMU - Read Diary",
    page_icon="img/main/web_icon.png",
    layout="centered"
)

# 프로젝트 루트(= pages 상위) 기준 diary_DB
BASE_DIR  = os.path.dirname(os.path.dirname(__file__))
DIARY_DIR = os.path.join(BASE_DIR, "diary_DB")
os.makedirs(DIARY_DIR, exist_ok=True)

# 이미지 디렉토리 (diary.py와 동일)
IMG_DIR = "img/diary"

def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# 이미지 로드
bg_base64        = image_to_base64(os.path.join(IMG_DIR, "background.png"))
btn_back_base64  = image_to_base64(os.path.join(IMG_DIR, "btn_back.png"))
animals_base64   = image_to_base64(os.path.join(IMG_DIR, "animals.png"))

# --- 파일 선택: 반드시 쿼리로 넘어온 파일만 표시 ---
# 새 API 우선 사용, 불가 시 experimental로 폴백
try:
    qp = st.query_params           # Streamlit 1.29+
    query_file = qp.get("file")
    if isinstance(query_file, list):
        query_file = query_file[0]
except Exception:
    params = st.experimental_get_query_params()  # 폴백
    lst = params.get("file", [None])
    query_file = lst[0] if isinstance(lst, list) else lst

selected_path = None
if query_file:
    candidate = os.path.join(DIARY_DIR, os.path.basename(query_file))
    if os.path.exists(candidate):
        selected_path = candidate

def split_title_and_body(text: str):
    """
    제목 규칙:
      1) 마지막 3줄 내 '제목: ...' 있으면 그 줄을 제목으로, 본문에서 제외
      2) 없으면 마지막 비어있지 않은 줄을 제목으로, 본문에서 제외
    """
    if not text.strip():
        return ("", "")
    lines = [ln.rstrip() for ln in text.splitlines()]
    nonempty_idx = [i for i, ln in enumerate(lines) if ln.strip()]

    title = ""
    title_idx = None
    for i in reversed(nonempty_idx[-3:]):
        m = re.search(r"제목\s*[:：]\s*(.+)\s*$", lines[i])
        if m:
            title = m.group(1).strip()
            title_idx = i
            break
    if title_idx is None and nonempty_idx:
        title_idx = nonempty_idx[-1]
        title = lines[title_idx].strip()

    body_lines = [ln for idx, ln in enumerate(lines) if idx != title_idx]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    body = "\n".join(body_lines)
    return (title, body)

# 스타일
st.markdown(f"""
<style>
html, body, [data-testid="stAppViewContainer"], .stApp, .block-container {{
  background-color: #ffffff !important;
}}
[data-testid="stSidebar"], [data-testid="stToolbar"] {{ display: none !important; }}

.main-box {{
  background-image: url("data:image/png;base64,{bg_base64}");
  background-size: 100% auto; background-position: center top; background-repeat: no-repeat;
  width: 85vw; max-width: 320px; aspect-ratio: 318 / 693; margin: 0 auto; position: relative;
  
    
            border-radius: 28px; border: 1.5px solid #e0a96d; 
            box-shadow: 0 10px 24px rgba(0,0,0,.08), 0 2px 6px rgba(0,0,0,.06); 
            overflow: hidden;
  
}}
.btn-back {{ width: 9%; position: absolute; top: 6.8%; left: 6%; }}

.content-wrap {{
  position: absolute; left: 0; right: 0; top: 26%; bottom: 16%;
  padding: 0 10px; overflow-y: auto;
}}
.title-chip {{
  display: inline-block; max-width: 92%;
  background: #f0f0f0; border: 1px solid #ddd; border-radius: 999px;
  padding: 6px 12px; margin: 0 0 8px 8px;
  font-weight: 700; font-size: 13px; color: #000;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.diary-box {{
  background: #ffffff; border: 1px solid #d9d9d9; border-radius: 12px;
  padding: 12px 14px; margin: 0 8px; box-shadow: 0 1px 3px rgba(0,0,0,.06);
  color: #000; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
}}
.animals {{ width: 40%; position: absolute; bottom: 4%; left: 50%; transform: translateX(-50%); }}
</style>
""", unsafe_allow_html=True)

# 렌더
if not selected_path:
    st.markdown(textwrap.dedent(f"""
    <div class="main-box">
      <a href="/diary" target="_self">
        <img src="data:image/png;base64,{btn_back_base64}" class="btn-back"/>
      </a>
      <div class="content-wrap">
        <div class="diary-box">열람할 일기를 찾을 수 없습니다.<br/>다이어리 목록에서 항목을 선택해 주세요.</div>  
    """), unsafe_allow_html=True)
else:
    try:
        with open(selected_path, "r", encoding="utf-8") as f:
            raw = f.read()
        title_text, body_text = split_title_and_body(raw)
    except Exception as e:
        title_text, body_text = "", f"파일을 여는 중 오류가 발생했습니다: {e}"

    safe_title = html.escape(title_text) if title_text else "제목 없음"
    safe_body  = html.escape(body_text)  if body_text  else "내용이 없습니다."

    html_block = f"""
<div class="main-box">
  <a href="/diary" target="_self">
    <img src="data:image/png;base64,{btn_back_base64}" class="btn-back"/>
  </a>
  <div class="content-wrap">
    <div class="title-chip">{safe_title}</div>
    <div class="diary-box">{safe_body}</div>
"""
    st.markdown(textwrap.dedent(html_block), unsafe_allow_html=True)
