import os
import re
import whisper
import pyaudio
import numpy as np
import pygame
import requests
import tempfile
from dotenv import load_dotenv
from ibm_watson_machine_learning.foundation_models import Model
from ibm_watson_machine_learning.metanames import GenTextParamsMetaNames as GenParams

# 환경 변수 로드
load_dotenv()
WATSONX_API = os.environ['API_KEY']
PROJECT_ID = os.environ['PROJECT_ID']
IBM_URL = os.environ['IBM_CLOUD_URL']
SUPERTONE_API = os.environ['SUPERTONE_API']
VOICE_ID = os.environ['VOICE_ID']

# 시스템 프롬프트 로드
with open("SYSTEMPROMPT.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()
with open("DIARYPROMPT.txt", "r", encoding="utf-8") as f:
    DIARY_PROMPT = f.read()

# 특수 토큰
BOS = "<|begin_of_text|>"
EOT = "<|eot|>"
USER_TAG = "<|header_start|>user<|header_end|>"
SYS_TAG = "<|header_start|>system<|header_end|>"
ASSISTANT_TAG = "<|header_start|>assistant<|header_end|>"

# WatsonX 모델 초기화 (공용 사용)
model = Model(
    model_id="meta-llama/llama-4-maverick-17b-128e-instruct-fp8",
    params={GenParams.MAX_NEW_TOKENS: 900, "stop_sequences": [EOT]},
    credentials={"apikey": WATSONX_API, "url": IBM_URL},
    project_id=PROJECT_ID
)

# STT 설정
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024
RECORD_SECONDS = 5

def record_audio():
    print("말하세요... (녹음 중)")
    audio = pyaudio.PyAudio()
    stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                        input=True, frames_per_buffer=CHUNK)
    frames = [stream.read(CHUNK) for _ in range(int(RATE / CHUNK * RECORD_SECONDS))]
    stream.stop_stream()
    stream.close()
    audio.terminate()
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
        "text": text,
        "language": "ko",
        "style": "Sad",
        "model": "sona_speech_1",
        "output_format": "wav",
        "voice_settings": {
            "pitch_shift": 0,
            "pitch_variance": 1,
            "speed": 1.1
        }
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

# 음성 대화 루프 실행
if __name__ == "__main__":
    conversation_history = []
    salutation = "무무 >> 안녕~ 나는 무무야! 같이 얘기하자"
    print(salutation)
    speak(salutation.replace("무무 >> ", ""))

    while True:
        user_input = stt().strip()
        print("너 >>", user_input)

        if user_input.lower() in ["종료", "잘가", "그만", "나중에 봐", "다음에 더 얘기하자"]:
            farewell = "무무 >> 다음에 또 얘기하자~ 잘 가!"
            print(farewell)
            speak(farewell.replace("무무 >> ", ""))
            break

        if user_input == "초기화":
            conversation_history.clear()
            print("무무 >> 내가 까먹었어~ 처음부터 다시 얘기하자 :)")
            continue

        bot_output = chatbot_response(user_input, conversation_history)
        print("무무 >>", bot_output)
        conversation_history.append((user_input, bot_output))
        speak(bot_output)

    # 전체 대화 저장 (log_DB 폴더)
    log_filename = get_next_indexed_filename("log_DB", "log")
    with open(log_filename, "w", encoding="utf-8") as f:
        for user, bot in conversation_history:
            f.write(f"너 >> {user}\n")
            f.write(f"무무 >> {bot}\n\n")
    print(f"[✅] 대화 기록 저장됨: {log_filename}")

    # 요약본 저장 (diary_DB 폴더)
    summary = summarize_conversation(conversation_history)
    diary_filename = get_next_indexed_filename("diary_DB", "diary")
    with open(diary_filename, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"[📝] 요약본 저장됨: {diary_filename}")
