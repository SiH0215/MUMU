from importlib.resources import files
from io import BytesIO
from pathlib import Path

import numpy as np
import sounddevice as sd
import torch
import whisper

from turns import FRAME_SAMPLES, SAMPLE_RATE, TurnDetector

FINE_TUNED_MODELS = {
    "fine-tuned": "mumu-whisper-small",
    "ksponspeech": "mumu-whisper-small-ksponspeech",
}


def waveform(pcm):
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


@torch.inference_mode()
def speech_probability(vad, frame):
    return vad(torch.from_numpy(waveform(frame)), SAMPLE_RATE).item()


def transcribe(model, pcm):
    if isinstance(model, TransformersWhisper):
        return model.transcribe(waveform(pcm))
    return model.transcribe(
        waveform(pcm), language="ko", temperature=0, beam_size=5,
        fp16=False, verbose=None,
    )["text"].strip()


class TransformersWhisper:
    def __init__(self, model_dir):
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        self.processor = WhisperProcessor.from_pretrained(model_dir, local_files_only=True)
        self.model = WhisperForConditionalGeneration.from_pretrained(
            model_dir, local_files_only=True, use_safetensors=True,
        ).eval()

    @torch.inference_mode()
    def transcribe(self, audio):
        inputs = self.processor(
            audio, sampling_rate=SAMPLE_RATE, return_tensors="pt",
            return_attention_mask=True, truncation=False,
        )
        tokens = self.model.generate(
            **inputs, language="ko", task="transcribe", num_beams=5,
            do_sample=False,
            return_timestamps=audio.size > self.processor.feature_extractor.n_samples,
        )
        text, = self.processor.batch_decode(
            tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False,
        )
        return text.strip()


def load_vad():
    # Load via bytes because TorchScript cannot open some Windows Unicode paths.
    weights = files("silero_vad").joinpath("data", "silero_vad.jit").read_bytes()
    return torch.jit.load(BytesIO(weights), map_location="cpu").eval()


def load_transcriber(model_name="base"):
    cache = Path(__file__).resolve().parent / ".cache" / "whisper"
    if model_name in FINE_TUNED_MODELS:
        model_dir = cache / FINE_TUNED_MODELS[model_name]
        if not (model_dir / "model.safetensors").is_file():
            raise FileNotFoundError(f"파인튜닝 모델을 찾을 수 없습니다: {model_dir}")
        return TransformersWhisper(model_dir)
    return whisper.load_model(model_name, device="cpu", download_root=str(cache))


def load_voice_models(model_name):
    torch.set_num_threads(min(torch.get_num_threads(), 4))
    return load_transcriber(model_name), load_vad()


def voice_input(silence_ms, model_name="base", *, status=None, should_stop=None, models=None):
    if status is None:
        def status(message):
            print(message, flush=True)

    def stopped():
        return should_stop is not None and should_stop()

    if models is None:
        status(f"Whisper {model_name} 모델을 불러오고 있어요...")
        models = load_voice_models(model_name)
    if stopped():
        return
    model, vad = models
    detector = TurnDetector(silence_ms)
    vad.reset_states()

    try:
        with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                               blocksize=FRAME_SAMPLES) as stream:
            status("듣고 있어요. 편하게 말해 주세요.")
            while not stopped():
                data, overflowed = stream.read(FRAME_SAMPLES)
                if stopped():
                    break
                if overflowed:
                    detector = TurnDetector(silence_ms)
                    vad.reset_states()
                    status("마이크 입력이 잠깐 끊겼어요.")
                    continue
                frame = bytes(data)
                turn = detector.push(frame, speech_probability(vad, frame))
                if turn is None:
                    continue
                stream.abort(ignore_errors=False)
                status("말씀을 받아쓰고 있어요...")
                text = transcribe(model, turn.pcm)
                if stopped():
                    break
                if text:
                    if should_stop is None:
                        print(f"나: {text}", flush=True)
                    status("무무가 답변을 준비하고 있어요...")
                    # The caller finishes replying before requesting the next turn.
                    yield text
                if stopped():
                    break
                detector = TurnDetector(silence_ms)
                vad.reset_states()
                stream.start()
                status("듣고 있어요. 이어서 말해 주세요.")
    except sd.PortAudioError as error:
        raise RuntimeError(f"기본 마이크 입력에 실패했습니다. {error}") from error
