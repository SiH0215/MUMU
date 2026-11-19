import argparse
import csv
from pathlib import Path
from statistics import median
from time import perf_counter
import unicodedata
import wave

import torch
from silero_vad import VADIterator

from turns import FRAME_SAMPLES, SAMPLE_RATE, TurnDetector, Utterance
from voice import load_transcriber, load_vad, speech_probability, transcribe, waveform


def replay_fixed(pcm):
    limit = 5 * SAMPLE_RATE * 2
    yield Utterance(pcm[:limit].ljust(limit, b"\0"), 5000)


def replay(pcm, vad, silence_ms):
    vad.reset_states()
    detector = TurnDetector(silence_ms)
    frame_bytes = FRAME_SAMPLES * 2
    pcm += bytes((silence_ms * SAMPLE_RATE // 1000 + FRAME_SAMPLES * 2) * 2)
    for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        frame = pcm[offset : offset + frame_bytes]
        turn = detector.push(frame, speech_probability(vad, frame))
        if turn is not None:
            yield turn


def replay_default_vad(pcm, vad):
    iterator = VADIterator(vad, sampling_rate=SAMPLE_RATE)
    frame_bytes = FRAME_SAMPLES * 2
    pcm += bytes(frame_bytes * 8)
    start = 0
    for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        event = iterator(waveform(pcm[offset : offset + frame_bytes]))
        if event is None:
            continue
        if "start" in event:
            start = event["start"]
        else:
            yield Utterance(pcm[start * 2 : event["end"] * 2],
                            (offset + frame_bytes) * 1000 // (SAMPLE_RATE * 2))


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFC", text) if c.isalnum()).casefold()


def edit_distance(ref, hyp):
    row = list(range(len(hyp) + 1))
    for i, a in enumerate(ref, start=1):
        next_row = [i]
        for j, b in enumerate(hyp, start=1):
            next_row.append(min(row[j] + 1, next_row[-1] + 1, row[j - 1] + (a != b)))
        row = next_row
    return row[-1]


def read_clip(manifest, sample):
    path = manifest.parent / sample["wav"]
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16_000, 1, 2):
            raise ValueError(f"{path}: 16kHz mono PCM16 WAV가 필요합니다.")
        return wav.readframes(wav.getnframes())


def main():
    parser = argparse.ArgumentParser(description="같은 WAV로 5초 녹음과 VAD 조건을 비교합니다.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--silence-ms", type=int, default=800)
    args = parser.parse_args()
    if not 100 <= args.silence_ms <= 3000:
        parser.error("--silence-ms는 100~3000 사이여야 합니다.")
    with args.manifest.open(encoding="utf-8-sig", newline="") as file:
        samples = list(csv.DictReader(file))
    if not samples:
        parser.error("평가 녹음 목록이 비어 있습니다.")

    torch.set_num_threads(min(torch.get_num_threads(), 4))
    model = load_transcriber()
    vad = load_vad()
    transcribe(model, bytes(SAMPLE_RATE * 2))  # Warm up once before timing.
    modes = (
        ("fixed 5s", replay_fixed),
        ("Silero default", lambda pcm: replay_default_vad(pcm, vad)),
        (f"MUMU VAD {args.silence_ms}ms", lambda pcm: replay(pcm, vad, args.silence_ms)),
    )
    for label, replay_clip in modes:
        errors = chars = early = false_transcripts = missed = 0
        waits = []
        for sample in samples:
            pcm = read_clip(args.manifest, sample)
            end_ms = int(sample["speech_end_ms"]) if sample["speech_end_ms"].strip() else None
            reference = normalize(sample["reference"])
            if bool(reference) != (end_ms is not None):
                raise ValueError(f'{sample["wav"]}: 발화가 있는 경우 정답과 말끝 시각을 모두 적으세요.')
            turns = list(replay_clip(pcm))
            texts = []
            completion_times = []
            transcription_ms = 0.0
            for turn in turns:
                started = perf_counter()
                result = transcribe(model, turn.pcm)
                inference_ms = (perf_counter() - started) * 1000
                transcription_ms += inference_ms
                if result:
                    texts.append(result)
                    completion_times.append(turn.end_ms + inference_ms)
            hypothesis = normalize(" ".join(texts))
            if end_ms is None:
                false_transcripts += bool(hypothesis)
            else:
                errors += edit_distance(reference, hypothesis)
                chars += len(reference)
                early += bool(turns and turns[0].end_ms < end_ms)
                missed += not hypothesis
                if completion_times and turns[0].end_ms >= end_ms:
                    waits.append(completion_times[-1] - end_ms)
            print(f'{label} | {sample["wav"]} | turns={len(turns)} | '
                  f'whisper={transcription_ms:.0f}ms | {" / ".join(texts) or "(empty)"}')
        cer = f"{errors / chars:.1%}" if chars else "n/a"
        wait = f"{median(waits):.0f}ms" if waits else "n/a"
        print(f"{label} | CER={cer} | 조기 종료={early} | 미전사={missed} | "
              f"무발화 오인식={false_transcripts} | 정상 종료 후 전사 대기 추정 중앙값={wait}")


if __name__ == "__main__":
    main()
