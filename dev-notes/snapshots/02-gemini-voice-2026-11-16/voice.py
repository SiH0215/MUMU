from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event

import numpy as np
import sounddevice as sd
import torch
import whisper

from turns import FRAME_SAMPLES, SAMPLE_RATE, TurnDetector


def waveform(pcm):
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def speech_probability(vad, frame):
    return vad(torch.from_numpy(waveform(frame)), SAMPLE_RATE).item()


def transcribe(model, pcm):
    return model.transcribe(
        waveform(pcm), language="ko", fp16=False, verbose=None,
    )["text"].strip()


def load_vad():
    # Load via bytes because TorchScript cannot open some Windows Unicode paths.
    weights = files("silero_vad").joinpath("data", "silero_vad.jit").read_bytes()
    return torch.jit.load(BytesIO(weights), map_location="cpu").eval()


def load_transcriber():
    cache = Path(__file__).resolve().parent / ".cache" / "whisper"
    return whisper.load_model("base", device="cpu", download_root=str(cache))


def voice_input(silence_ms):
    print("Whisper base를 불러오는 중입니다. 첫 실행에서는 모델을 내려받습니다.", flush=True)
    torch.set_num_threads(min(torch.get_num_threads(), 4))
    model = load_transcriber()
    vad = load_vad()
    ready = Queue(maxsize=4)
    stop = Event()

    def capture():
        detector = TurnDetector(silence_ms)
        with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                               blocksize=FRAME_SAMPLES) as stream:
            print("듣고 있어요. 종료하려면 Ctrl+C를 누르세요.", flush=True)
            while not stop.is_set():
                data, overflowed = stream.read(FRAME_SAMPLES)
                if overflowed:
                    detector = TurnDetector(silence_ms)
                    vad.reset_states()
                    print("마이크 입력이 끊겼어요. 다시 말해 주세요.", flush=True)
                    continue
                frame = bytes(data)
                turn = detector.push(frame, speech_probability(vad, frame))
                if turn is not None:
                    try:
                        ready.put_nowait(turn)
                    except Full:
                        print("처리 대기 중인 발화가 많아 이번 발화를 건너뛰었어요.", flush=True)

    with ThreadPoolExecutor(max_workers=1) as executor:
        capture_task = executor.submit(capture)
        try:
            while True:
                if capture_task.done():
                    try:
                        capture_task.result()
                    except sd.PortAudioError as error:
                        raise RuntimeError(f"기본 마이크 입력에 실패했습니다. {error}") from error
                    return
                try:
                    turn = ready.get(timeout=0.2)
                except Empty:
                    continue
                text = transcribe(model, turn.pcm)
                if text:
                    print(f"나: {text}", flush=True)
                    yield text
        finally:
            stop.set()
