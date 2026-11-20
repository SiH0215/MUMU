import whisper
import pyaudio
import numpy as np

# 설정값
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024
RECORD_SECONDS = 5

def record_audio():
    print("🎙️ 말하세요... (녹음 중)")
    audio = pyaudio.PyAudio()
    stream = audio.open(format=FORMAT, channels=CHANNELS,
                        rate=RATE, input=True, frames_per_buffer=CHUNK)
    frames = [stream.read(CHUNK) for _ in range(int(RATE / CHUNK * RECORD_SECONDS))]
    stream.stop_stream()
    stream.close()
    audio.terminate()
    return np.frombuffer(b''.join(frames), np.int16).astype(np.float32) / 32768.0

def transcribe():
    audio = record_audio()
    result = whisper.load_model("base").transcribe(audio, language="ko")
    print(result["text"])

if __name__ == "__main__":
    transcribe()
