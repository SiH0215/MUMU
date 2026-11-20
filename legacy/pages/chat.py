import os
import re
import base64
import whisper
import pyaudio
import numpy as np
import pygame
import requests
import tempfile
import streamlit as st
from dotenv import load_dotenv
from ibm_watson_machine_learning.foundation_models import Model
from ibm_watson_machine_learning.metanames import GenTextParamsMetaNames as GenParams

# ───── 환경설정 ─────
load_dotenv()
WATSONX_API   = os.environ['API_KEY']
PROJECT_ID    = os.environ['PROJECT_ID']
IBM_URL       = os.environ['IBM_CLOUD_URL']
SUPERTONE_API = os.environ['SUPERTONE_API']
VOICE_ID      = os.environ['VOICE_ID']

# 프로젝트 루트(= pages 상위) 절대경로
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

# 페이지 아이콘(없으면 None)
ICON_PATH = os.path.join(BASE_DIR, "img", "main", "web_icon.png")
PAGE_ICON = ICON_PATH if os.path.exists(ICON_PATH) else None

# ───── 모델 ─────
model = Model(
    model_id="meta-llama/llama-4-maverick-17b-128e-instruct-fp8",
    params={GenParams.MAX_NEW_TOKENS: 900, "stop_sequences": ["<|eot|>"]},
    credentials={"apikey": WATSONX_API, "url": IBM_URL},
    project_id=PROJECT_ID
)

with open(os.path.join(BASE_DIR, "SYSTEMPROMPT.txt"), "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()
with open(os.path.join(BASE_DIR, "DIARYPROMPT.txt"), "r", encoding="utf-8") as f:
    DIARY_PROMPT = f.read()

# ───── 프롬프트 토큰 ─────
BOS = "<|begin_of_text|>"; EOT = "<|eot|>"
USER_TAG = "<|header_start|>user<|header_end|>"
SYS_TAG = "<|header_start|>system<|header_end|>"
ASSISTANT_TAG = "<|header_start|>assistant<|header_end|>"

# ───── 오디오 설정 ─────
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024
RECORD_SECONDS = 5

END_PHRASES = ["종료", "잘가", "그만", "나중에 봐", "다음에 더 얘기하자"]

# ───── 유틸 ─────
def image_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def find_asset(*relative_candidates):
    here = os.path.dirname(__file__)              # pages/chat
    root = os.path.dirname(os.path.dirname(here)) # 프로젝트 루트
    for rel in relative_candidates:
        p1 = os.path.join(here, *rel)
        if os.path.exists(p1): return p1
        p2 = os.path.join(root, *rel)
        if os.path.exists(p2): return p2
    return os.path.join(here, *relative_candidates[0])

# 말머리 제거
ROLE_PREFIX_RE = re.compile(
    r'^(무무\s*>>\s*|유저\s*>>\s*|assistant\s*:?\s*|bot\s*:?\s*|system\s*:?\s*)+',
    re.IGNORECASE
)
def sanitize_role_prefixes(text: str) -> str:
    return ROLE_PREFIX_RE.sub('', text or '').strip()

def record_audio(status_ph=None):
    if status_ph is None:
        status_ph = st.session_state.get("stt_status_ph")
    if status_ph is None:
        status_ph = st.empty()

    status_ph.info("(녹음중)")
    audio = pyaudio.PyAudio()
    stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                        input=True, frames_per_buffer=CHUNK)
    frames = [stream.read(CHUNK) for _ in range(int(RATE / CHUNK * RECORD_SECONDS))]
    stream.stop_stream(); stream.close(); audio.terminate()
    status_ph.empty()
    return np.frombuffer(b"".join(frames), np.int16).astype(np.float32) / 32768.0

def stt():
    audio_data = record_audio(st.session_state.get("stt_status_ph"))
    return whisper.load_model("base").transcribe(audio_data, language="ko")["text"]

def build_prompt(system, history, user_input):
    prompt = f"{BOS}\n{SYS_TAG}\n{system.strip()}\n{EOT}\n"
    for u, b in history:
        if u: prompt += f"{USER_TAG}\n{u.strip()}\n{EOT}\n"
        if b: prompt += f"{ASSISTANT_TAG}\n{b.strip()}\n{EOT}\n"
    prompt += f"{USER_TAG}\n{user_input.strip()}\n{EOT}\n{ASSISTANT_TAG}\n"
    return prompt

def clean_response(text): return text.split(EOT)[0].strip()

def chatbot_response(user_input, history):
    prompt = build_prompt(SYSTEM_PROMPT, history, user_input)
    out = model.generate(prompt=prompt)['results'][0]['generated_text']
    return sanitize_role_prefixes(clean_response(out))

def speak(text):
    payload = {
        "text": text, "language": "ko", "style": "Sad", "model": "sona_speech_1",
        "output_format": "wav",
        "voice_settings": {"pitch_shift": 0, "pitch_variance": 1, "speed": 1.1}
    }
    headers = {"x-sup-api-key": SUPERTONE_API, "x-tts-engine": "supercage", "Content-Type": "application/json"}
    response = requests.post(f"https://supertoneapi.com/v1/text-to-speech/{VOICE_ID}", json=payload, headers=headers)
    if "audio/" in response.headers.get("Content-Type", ""):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            temp_audio.write(response.content); path = temp_audio.name
        pygame.mixer.init(); pygame.mixer.music.load(path); pygame.mixer.music.play()
        while pygame.mixer.music.get_busy(): pygame.time.Clock().tick(10)

def get_next_indexed_filename(folder, base_name, ext="txt"):
    folder_path = os.path.join(BASE_DIR, folder)
    os.makedirs(folder_path, exist_ok=True)
    existing = [f for f in os.listdir(folder_path) if f.startswith(base_name) and f.endswith(f".{ext}")]
    indices = [int(re.findall(rf"{base_name}_(\d+)\.{ext}", f)[0]) for f in existing if re.findall(rf"{base_name}_(\d+)\.{ext}", f)]
    next_index = max(indices) + 1 if indices else 1
    return os.path.join(folder_path, f"{base_name}_{next_index}.{ext}")

def summarize_conversation(conversation):
    prompt = f"{BOS}\n{SYS_TAG}\n{DIARY_PROMPT.strip()}\n{EOT}\n"
    for u, b in conversation:
        prompt += f"{USER_TAG}\n{(u or '').strip()}\n{EOT}\n"
        prompt += f"{ASSISTANT_TAG}\n{(b or '').strip()}\n{EOT}\n"
    prompt += f"{ASSISTANT_TAG}\n"
    out = model.generate(prompt=prompt)['results'][0]['generated_text']
    return sanitize_role_prefixes(clean_response(out))

# ───── 스타일 ─────
st.set_page_config(page_title="Chat whit MUMU!", page_icon=PAGE_ICON, layout="centered")

st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"], .stApp, .block-container { background-color: #ffffff !important; }
[data-testid="stSidebar"], [data-testid="stToolbar"] { display: none !important; }

/* 좌측 사이드 버튼 영역 */
.side-start { margin-top: 6px; }
.side-start .stButton > button {
    width: 100% !important;  /* 두 컬럼에 맞춰 꽉 차게 */
    background-color: #ffd8b1 !important;
    color: #000 !important; font-weight: 700; font-size: 14px;
    border: 1px solid #e0a96d; border-radius: 10px; padding: .5em .8em;
    white-space: nowrap;  /* 줄바꿈 방지: '대화하기' 한 줄로 */
}
.side-start .stButton > button:hover { background-color: #ffc699 !important; border: 1px solid #cc8a48; }

/* 모바일 프레임 */
.mobile-wrap { width: min(92vw, 430px); margin: 0 auto; position: relative; 
            border-radius: 28px; border: 1.5px solid #e0a96d; 
            box-shadow: 0 10px 24px rgba(0,0,0,.08), 0 2px 6px rgba(0,0,0,.06); 
            overflow: hidden;  background: #fffaf3;}
.mobile-bg   { width: 100%; height: auto; display: block; }

/* 백버튼 */
.back-btn { position: absolute; top: 3.5%; left: 3.5%; width: 8%; height: auto; display: block; }
.back-btn-img { width: 100%; height: auto; display: block; }

/* 콘텐츠 오버레이: 내부 스크롤 + 투명 배경 */
.content-overlay {
    position: absolute; top: 22%; left: 0; right: 0; bottom: 0;
    padding: 12px 12px 80px 12px;

    overflow-y: auto;
    background: transparent;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior: contain;
}

/* 스크롤바(웹킷) - 투명 트랙 */
.content-overlay::-webkit-scrollbar       { width: 6px; }
.content-overlay::-webkit-scrollbar-track { background: transparent; }
.content-overlay::-webkit-scrollbar-thumb { background: rgba(0,0,0,.18); border-radius: 999px; }

/* 파이어폭스 등 */
@supports (scrollbar-color: auto) {
  .content-overlay { scrollbar-color: rgba(0,0,0,.25) transparent; scrollbar-width: thin; }
}

/* st.info 텍스트 색 보정 */
.stAlert, .stInfo { color: #000 !important; }
.stAlert p, .stInfo p, .stAlert span, .stInfo span, .stAlert div, .stInfo div { color: #000 !important; }

/* 말풍선 */
.bubble-wrapper { display: flex; margin: 10px 0; }
.bubble { padding: 10px 12px; max-width: 78%; font-size: 15px; color: #000; border-radius: 12px; }
.bubble-left  { background: #ffffff; margin-right: auto;  border-bottom-left-radius: 0; }
.bubble-right { background: #d4eac7; margin-left:  auto;  border-bottom-right-radius: 0; }

/* 저장 결과 박스 */
.summary-box { background-color: #ffffff; padding: 1em 1.2em; margin-top: 12px; border-radius: 12px; border: 1px solid #ccc; color: #000; font-size: 15px; line-height: 1.5; }
</style>
""", unsafe_allow_html=True)

# ───── 에셋 로드 ─────
BACKGROUND_PATH = find_asset(("img","chat","background.png"), ("img","main","background.png"))
BACKBTN_PATH    = find_asset(("img","chat","btn_back.png"),   ("img","main","btn_back.png"))

try:    bg_base64 = image_to_base64(BACKGROUND_PATH)
except: st.error(f"background.png 파일을 찾을 수 없습니다: {BACKGROUND_PATH}"); bg_base64 = ""
try:    back_base64 = image_to_base64(BACKBTN_PATH)
except: st.error(f"btn_back.png 파일을 찾을 수 없습니다: {BACKBTN_PATH}"); back_base64 = ""

# ───── 렌더러 ─────
def render_phone(history):
    bubbles_html = []
    if not history:
        bubbles_html.append('<div class="bubble-wrapper"><div class="bubble bubble-left"><strong>무무:</strong> 안녕! 난 무무야 👋</div></div>')
        bubbles_html.append('<div class="bubble-wrapper"><div class="bubble bubble-right"><strong>유저:</strong> 대화하기 버튼을 눌러보세요</div></div>')
    else:
        for u, b in history:
            if u:
                bubbles_html.append(f'<div class="bubble-wrapper"><div class="bubble bubble-right"><strong>유저:</strong> {u}</div></div>')
            if b:
                bubbles_html.append(f'<div class="bubble-wrapper"><div class="bubble bubble-left"><strong>무무:</strong> {b}</div></div>')

    autoscroll_js = """
    <script>
      (function(){
        const boxes = window.parent.document.querySelectorAll('.content-overlay');
        const el = boxes[boxes.length - 1];
        if (el) el.scrollTop = el.scrollHeight;
      })();
    </script>
    """

    html = f"""
    <div class="mobile-wrap">
        {"<img class='mobile-bg' src='data:image/png;base64," + bg_base64 + "' />" if bg_base64 else ""}
        {f"<a href='/' target='_self' class='back-btn'><img class='back-btn-img' src='data:image/png;base64,{back_base64}' /></a>" if back_base64 else ""}
        <div class="content-overlay">
            {''.join(bubbles_html)}
        </div>
    </div>
    {autoscroll_js}
    """
    phone_placeholder.markdown(html, unsafe_allow_html=True)

# ───── 세션 ─────
if "history" not in st.session_state:
    st.session_state.history = []

left, right = st.columns([1.5, 3], vertical_alignment="top")

with left:
    st.markdown('<div class="side-start">', unsafe_allow_html=True)

    col_start, col_reset = st.columns([4, 3], vertical_alignment="top")  # ← 대화하기 살짝 넓힘
    with col_start:
        start_clicked = st.button("대화하기", key="start_chat")
    with col_reset:
        reset_clicked = st.button("초기화", key="reset_chat")

    st.session_state["stt_status_ph"] = st.empty()
    st.markdown('</div>', unsafe_allow_html=True)

if 'reset_clicked_once' not in st.session_state:
    st.session_state.reset_clicked_once = False

if reset_clicked and not st.session_state.reset_clicked_once:
    st.session_state.reset_clicked_once = True
    st.session_state.history = []
    if st.session_state.get("stt_status_ph"):
        try:
            st.session_state["stt_status_ph"].empty()
        except Exception:
            pass
    st.rerun()

with right:
    phone_placeholder = st.empty()
    render_phone(st.session_state.history)

# ───── 대화 루프 (버튼 누르면 시작) ─────
if start_clicked:
    # 인사(라벨 없이 저장)
    greeting = "안녕~ 나는 무무야! 같이 얘기하자"
    st.session_state.history.append(("", greeting))
    render_phone(st.session_state.history)
    try: speak(greeting)
    except: pass

    while True:
        try:
            user_input = stt().strip()
        except Exception as e:
            st.error(f"STT 오류: {e}")
            break

        # 유저 말풍선
        st.session_state.history.append((user_input, ""))
        render_phone(st.session_state.history)

        # 종료 조건
        if user_input.lower() in END_PHRASES:
            bye = "다음에 또 얘기하자~ 잘 가!"   # 라벨 없이
            st.session_state.history[-1] = (user_input, bye)
            render_phone(st.session_state.history)
            try: speak(bye)
            except: pass
            break

        # 봇 응답(라벨 제거 후 저장)
        try:
            bot_output = chatbot_response(user_input, st.session_state.history)
        except Exception as e:
            st.error(f"챗봇 응답 오류: {e}")
            break

        st.session_state.history[-1] = (user_input, bot_output)
        render_phone(st.session_state.history)
        try: speak(bot_output)
        except: pass

    # ── 대화 종료: 기록/요약 저장 ──
    try:
        log_path = get_next_indexed_filename("log_DB", "log")
        with open(log_path, "w", encoding="utf-8") as f:
            for user, bot in st.session_state.history:
                f.write(f"유저 >> {user}\n무무 >> {bot}\n\n")
        st.success(f"📄 대화 저장됨: {log_path}")
    except Exception as e:
        st.error(f"대화 저장 실패: {e}")

    try:
        summary = summarize_conversation(st.session_state.history)
        diary_path = get_next_indexed_filename("diary_DB", "diary")
        with open(diary_path, "w", encoding="utf-8") as f: f.write(summary)
        st.success(f"📝 요약 저장됨: {diary_path}")
        st.session_state["last_diary_path"] = diary_path

    except Exception as e:
        st.error(f"요약 저장 실패: {e}")
