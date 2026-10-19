"""v0.4 收到訊息時的「汪！」：程式合成 assets/sounds/bark.wav（不見了會自動重做）。
Evan 想換成真的狗叫聲，直接把 bark.wav 換掉就好（建議 1 秒內、wav 格式）。
"""
from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

from .pomodoro import Ding


def make_bark_wav(path: Path, sr: int = 44100) -> Path:
    """兩聲短短的「汪汪」：音高先上再往下掉、很多泛音（像鋸齒波）、兩個共振峰、一點氣音。"""
    rng = random.Random(7)                      # 固定亂數：每次合成都一樣
    barks = [(0.0, 1.0, 1.0), (0.24, 0.92, 0.85)]   # (開始秒數, 音高倍率, 音量)
    dur = 0.58
    n = int(sr * dur)
    buf = [0.0] * n
    for start, pk, vol in barks:
        phase = 0.0
        length = 0.17
        i0 = int(start * sr)
        for i in range(int(length * sr)):
            t = i / sr
            k = t / length
            # 音高：480 → 640 Hz（很快）→ 降到 330 Hz
            f = (480 + 160 * min(1.0, k / 0.15) - 310 * max(0.0, (k - 0.15) / 0.85) ** 0.8) * pk
            phase += 2 * math.pi * f / sr
            v = 0.0
            for h in range(1, 14):
                fh = f * h
                if fh > sr / 2:
                    break
                formant = math.exp(-((fh - 950) / 420) ** 2) + 0.55 * math.exp(-((fh - 2300) / 650) ** 2) + 0.12
                v += math.sin(h * phase) * formant / h ** 0.7
            v += rng.uniform(-1, 1) * 0.35 * (1 - k)          # 氣音
            env = min(1.0, t / 0.008) * (math.exp(-max(0.0, t - 0.05) * 22))
            j = i0 + i
            if j < n:
                buf[j] += v * env * vol
    peak = max(abs(x) for x in buf) or 1.0
    frames = bytearray()
    for x in buf:
        y = math.tanh(1.6 * x / peak) / math.tanh(1.6) * 0.8
        frames += struct.pack("<h", int(max(-1.0, min(1.0, y)) * 32767))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))
    return path


class Bark(Ding):
    FILE = "bark.wav"

    @staticmethod
    def make(path: Path) -> Path:
        return make_bark_wav(path)
