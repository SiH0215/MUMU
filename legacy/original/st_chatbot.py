import os
import re
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
import base64

# ───── 설정 ─────
load_dotenv()
WATSONX_API = os.environ['API_KEY']
PROJECT_ID = os.environ['PROJECT_ID']
IBM_URL = os.environ['IBM_CLOUD_URL']
SUPERTONE_API = os.environ['SUPERTONE_API']
VOICE_ID = os.environ['VOICE_ID']

model = Model(
    model_id="meta-llama/llama-4-maverick-17b-128e-instruct-fp8",
    params={GenParams.MAX_NEW_TOKENS: 900, "stop_sequences": ["<|eot|>"]},
    credentials={"apikey": WATSONX_API, "url": IBM_URL},
    project_id=PROJECT_ID
)

with open("SYSTEMPROMPT.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()
with open("DIARYPROMPT.txt", "r", encoding="utf-8") as f:
    DIARY_PROMPT = f.read()

# ───── 토큰 ─────
BOS = "<|begin_of_text|>"
EOT = "<|eot|>"
USER_TAG = "<|header_start|>user<|header_end|>"
SYS_TAG = "<|header_start|>system<|header_end|>"
ASSISTANT_TAG = "<|header_start|>assistant<|header_end|>"

# ───── 오디오 설정 ─────
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024
RECORD_SECONDS = 5

# ───── 기능 함수 ─────

def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def record_audio():
    status = st.empty()
    status.info("말하세요... (녹음 중)")
    audio = pyaudio.PyAudio()
    stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                        input=True, frames_per_buffer=CHUNK)
    frames = [stream.read(CHUNK) for _ in range(int(RATE / CHUNK * RECORD_SECONDS))]
    stream.stop_stream()
    stream.close()
    audio.terminate()
    status.empty()
    return np.frombuffer(b''.join(frames), np.int16).astype(np.float32) / 32768.0

def stt():
    return whisper.load_model("base").transcribe(record_audio(), language="ko")["text"]

def build_prompt(system, history, user_input):
    prompt = f"{BOS}\n{SYS_TAG}\n{system.strip()}\n{EOT}\n"
    for u, b in history:
        prompt += f"{USER_TAG}\n{u.strip()}\n{EOT}\n"
        prompt += f"{ASSISTANT_TAG}\n{b.strip()}\n{EOT}\n"
    prompt += f"{USER_TAG}\n{user_input.strip()}\n{EOT}\n"
    prompt += f"{ASSISTANT_TAG}\n"
    return prompt

def clean_response(text):
    return text.split(EOT)[0].strip()

def chatbot_response(user_input, history):
    prompt = build_prompt(SYSTEM_PROMPT, history, user_input)
    return clean_response(model.generate(prompt=prompt)['results'][0]['generated_text'])

def speak(text):
    payload = {
        "text": text, "language": "ko", "style": "Sad", "model": "sona_speech_1",
        "output_format": "wav",
        "voice_settings": {"pitch_shift": 0, "pitch_variance": 1, "speed": 1.1}
    }
    headers = {
        "x-sup-api-key": SUPERTONE_API,
        "x-tts-engine": "supercage",
        "Content-Type": "application/json"
    }
    response = requests.post(
        f"https://supertoneapi.com/v1/text-to-speech/{VOICE_ID}",
        json=payload, headers=headers
    )
    if "audio/" in response.headers.get("Content-Type", ""):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            temp_audio.write(response.content)
            path = temp_audio.name
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)

def get_next_indexed_filename(folder, base_name, ext="txt"):
    os.makedirs(folder, exist_ok=True)
    existing = [f for f in os.listdir(folder) if f.startswith(base_name) and f.endswith(f".{ext}")]
    indices = [int(re.findall(rf"{base_name}_(\d+)\.{ext}", f)[0]) for f in existing if re.findall(rf"{base_name}_(\d+)\.{ext}", f)]
    next_index = max(indices) + 1 if indices else 1
    return os.path.join(folder, f"{base_name}_{next_index}.{ext}")

def summarize_conversation(conversation):
    prompt = f"{BOS}\n{SYS_TAG}\n{DIARY_PROMPT.strip()}\n{EOT}\n"
    for u, b in conversation:
        prompt += f"{USER_TAG}\n{u.strip()}\n{EOT}\n"
        prompt += f"{ASSISTANT_TAG}\n{b.strip()}\n{EOT}\n"
    prompt += f"{ASSISTANT_TAG}\n"
    return clean_response(model.generate(prompt=prompt)['results'][0]['generated_text'])

def render_bubble(text, sender="user"):
    if sender == "user":
        side = "bubble-right"
        label = "유저"
    else:
        side = "bubble-left"
        label = "무무"
    st.markdown(f"""
    <div class="bubble-wrapper">
        <div class="bubble {side}">
            <strong>{label}:</strong> {text}
        </div>
    </div>
    """, unsafe_allow_html=True)

# ───── Streamlit ─────

st.set_page_config(page_title="Me & U Mellow Unit!", page_icon="img/main/web_icon.png", layout="centered")

# 이미지 base64
main_bg_base64 = image_to_base64("img/main/main_bg.png")
maintitle_base64 = image_to_base64("img/main/maintitle.png")
subtitle_base64 = image_to_base64("img/main/subtitle.png")
mascot_base64 = image_to_base64("img/main/mascot.png")

st.markdown(f"""
<style>
/* 배경 통일 */
html, body, [data-testid="stAppViewContainer"], .stApp, .block-container {{
    background-color: #fdf1e5 !important;
}}

/* 툴바 & 사이드바 제거 */
[data-testid="stSidebar"], [data-testid="stToolbar"] {{
    display: none !important;
}}

/* 말풍선 스타일 */
.bubble-wrapper {{
    display: flex;
    margin: 10px 0;
}}

.bubble {{
    padding: 10px 15px;
    max-width: 70%;
    font-size: 16px;
    color: black;
    border-radius: 12px;
    position: relative;
}}

.bubble-left {{
    background-color: white;
    margin-right: auto;
    border-bottom-left-radius: 0px;  /* 좌하단 각지게 */
}}

.bubble-right {{
    background-color: #d4eac7;
    margin-left: auto;
    border-bottom-right-radius: 0px;  /* 우하단 각지게 */
}}

/* 알림창 커스터마이징 */
.stAlert, .stSuccess, .stInfo, .stError {{
    font-size: 16px;
    opacity: 1.0 !important;
    padding: 0.75em 1em;
    border-radius: 10px;
    color : black !important;
}}

.stSuccess {{
    background-color: #91F590 !important;
    color: #1a1a1a;
    border-left: 6px solid #34a853;
    border-radius: 8px;
    padding: 1em;
    font-size: 16px;
    font-weight: bold;
    box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
}}

.stInfo {{    
    background-color: #7678FF !important;
    color: #1a1a1a;
    border-radius: 10px;
    font-size: 16px;
    font-weight: bold;
    padding: 1em;
    box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
}}

.stError {{
    background-color: #f5c9c9 !important;
    color: black !important;
}}

.stButton > button {{
    background-color: #ffd8b1 !important;
    color: black !important;
    font-weight: bold;
    font-size: 16px;
    border: 1px solid #e0a96d;
    border-radius: 10px;
    padding: 0.6em 1.2em;
    transition: background-color 0.3s ease;
}}
.stButton > button:hover {{
    background-color: #ffc699 !important;
    color: black !important;
    border: 1px solid #cc8a48;
}}


/* 요약 내용 박스 */
.summary-box {{
    background-color: white;
    padding: 1em 1.2em;
    margin-top: 20px;
    border-radius: 12px;
    border: 1px solid #ccc;
    color: black;
    font-size: 16px;
    line-height: 1.5;
}}
</style>
""", unsafe_allow_html=True)



if "history" not in st.session_state:
    st.session_state.history = []

# 이미지 출력
st.markdown(f"""
<div style='text-align: center; margin-bottom: 20px;'>
    <div><img src='data:image/png;base64,{maintitle_base64}' style='width: 30%; margin: 0 auto; display: block;'/></div>
    <div><img src='data:image/png;base64,{subtitle_base64}' style='width: 30%; margin: 0 auto; display: block;'/></div>
    <div><img src='data:image/png;base64,{mascot_base64}' style='width: 30%; margin: 0 auto; display: block;'/></div>
</div>
""", unsafe_allow_html=True)

if st.button("대화 시작", use_container_width=True):
    greeting = "무무 >> 안녕~ 나는 무무야! 같이 얘기하자"
    st.session_state.history.append(("", greeting))
    render_bubble(greeting.replace("무무 >> ", ""), sender="mumu")
    speak(greeting.replace("무무 >> ", ""))

    while True:
        user_input = stt().strip()
        render_bubble(user_input, sender="user")

        if user_input.lower() in ["종료", "잘가", "그만", "나중에 봐", "다음에 더 얘기하자"]:
            bye = "무무 >> 다음에 또 얘기하자~ 잘 가!"
            st.session_state.history.append((user_input, bye))
            render_bubble(bye.replace("무무 >> ", ""), sender="mumu")
            speak(bye.replace("무무 >> ", ""))
            break

        if user_input == "초기화":
            st.session_state.history = []
            st.success("대화 초기화됨")
            continue

        bot_output = chatbot_response(user_input, st.session_state.history)
        st.session_state.history.append((user_input, f"무무 >> {bot_output}"))
        render_bubble(bot_output, sender="mumu")
        speak(bot_output)

    # 저장
    log_path = get_next_indexed_filename("log_DB", "log")
    with open(log_path, "w", encoding="utf-8") as f:
        for user, bot in st.session_state.history:
            f.write(f"유저 >> {user}\n무무 >> {bot}\n\n")
    st.success(f"📄 대화 저장됨: {log_path}")

    summary = summarize_conversation(st.session_state.history)
    diary_path = get_next_indexed_filename("diary_DB", "diary")
    with open(diary_path, "w", encoding="utf-8") as f:
        f.write(summary)
    st.info(f"📝 요약 저장됨: {diary_path}")
    st.markdown(f"""
    <div class="summary-box">
    <strong>📝 요약 내용:</strong><br>{summary}
    </div>
    """, unsafe_allow_html=True)