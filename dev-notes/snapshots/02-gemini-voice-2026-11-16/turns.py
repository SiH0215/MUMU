from collections import deque
from dataclasses import dataclass

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512
FRAME_MS = FRAME_SAMPLES * 1000 // SAMPLE_RATE


@dataclass(frozen=True)
class Utterance:
    pcm: bytes
    end_ms: int


class TurnDetector:
    """Group consecutive 32 ms microphone frames into a single user turn."""

    def __init__(self, silence_ms=800):
        self.end_frames = (silence_ms + FRAME_MS - 1) // FRAME_MS
        self.pre_roll = deque(maxlen=7)  # 224 ms before speech onset
        self.frames = []
        self.position = 0
        self.speech_frames = 0
        self.quiet_frames = 0

    def push(self, pcm, speech_probability):
        self.position += 1
        if not self.frames:
            if speech_probability < 0.5:
                self.pre_roll.append(pcm)
                return None
            self.frames = [*self.pre_roll, pcm]
            self.pre_roll.clear()
            self.speech_frames = 1
            return None

        self.frames.append(pcm)
        if speech_probability >= 0.35:
            self.speech_frames += 1
            self.quiet_frames = 0
        else:
            self.quiet_frames += 1

        if self.quiet_frames < self.end_frames and len(self.frames) < 25_000 // FRAME_MS:
            return None

        # Keep a short tail for quiet consonants, then trim the detection wait.
        trim = max(0, self.quiet_frames - 3)
        frames = self.frames[:-trim] if trim else self.frames
        utterance = (
            Utterance(b"".join(frames), self.position * FRAME_MS)
            if self.speech_frames >= 3 else None
        )
        self.frames = []
        self.speech_frames = 0
        self.quiet_frames = 0
        return utterance
