import os
import re
from dotenv import load_dotenv
import requests
import pygame
import tempfile

load_dotenv()
SUPERTONE_API = os.environ['SUPERTONE_API']  # 사용 예정
VOICE_ID = os.environ['VOICE_ID']
TEXT = "안녕..? 내 이름은 무무야..!"

payload = {
    "text": TEXT,
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

response = requests.post(f"https://supertoneapi.com/v1/text-to-speech/{VOICE_ID}",
                         json=payload, headers=headers)

if "audio/" in response.headers.get("Content-Type", ""):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
        temp_audio.write(response.content)
        temp_audio_path = temp_audio.name

    pygame.mixer.init()
    pygame.mixer.music.load(temp_audio_path)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
