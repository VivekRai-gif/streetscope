"""Background music and sound effects for the submission video, synthesised here so there is no licence question.

music.wav : a slow ambient pad in A minor (Am9 - Fmaj9 - Cadd9 - G6), a soft plucked arpeggio and a sub bass, with reverb
click.wav : a short soft UI tick
whoosh.wav: a filtered-noise sweep for chapter changes
Run: python video/music.py [seconds]
"""
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

SR = 48000
OUT = Path(__file__).resolve().parent / "build" / "audio"
rng = np.random.default_rng(7)


def hz(note: str) -> float:
    names = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4, "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}
    n, octv = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((names[n] + 12 * (octv - 4)) / 12)


CHORDS = [  # (pad voicing, arpeggio notes, bass)
    (["A2", "E3", "B3", "C4", "E4", "G4"], ["A4", "C5", "E5", "B4", "G4", "E5"], "A1"),
    (["F2", "C3", "A3", "E4", "G4", "C5"], ["F4", "A4", "C5", "G4", "E5", "C5"], "F1"),
    (["C3", "G3", "D4", "E4", "G4", "B4"], ["C5", "E5", "G4", "D5", "B4", "G4"], "C2"),
    (["G2", "D3", "B3", "E4", "G4", "D5"], ["G4", "B4", "D5", "E5", "D5", "B4"], "G1"),
]


def pad_voice(f: float, n: int, t: np.ndarray) -> np.ndarray:
    out = np.zeros_like(t)
    for det in (-0.07, 0.0, 0.08):   # three slightly detuned voices
        ff = f * 2 ** (det / 12)
        ph = rng.uniform(0, 2 * np.pi)
        for h in range(1, 9):        # soft saw, high harmonics rolled off
            out += np.sin(2 * np.pi * ff * h * t + ph * h) / (h ** 1.6)
    return out / 3


def music(seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    L = np.zeros(n)
    R = np.zeros(n)
    bar = 8.0                                    # seconds per chord
    k = 0
    while k * bar < seconds + bar:
        voicing, arp, bass = CHORDS[k % 4]
        t0 = k * bar - 1.5                       # overlap chords for a smooth crossfade
        a, b = max(0, int(t0 * SR)), min(n, int((t0 + bar + 3.0) * SR))
        if b <= a:
            k += 1
            continue
        tt = t[a:b] - t0
        env = np.clip(tt / 2.2, 0, 1) * np.clip((bar + 3.0 - tt) / 2.4, 0, 1)
        env = env ** 1.5
        for i, note in enumerate(voicing):
            v = pad_voice(hz(note), b - a, tt) * env * 0.05
            pan = 0.5 + (i / (len(voicing) - 1) - 0.5) * 0.7
            L[a:b] += v * (1 - pan)
            R[a:b] += v * pan
        sub = np.sin(2 * np.pi * hz(bass) * tt) * env * 0.11
        L[a:b] += sub
        R[a:b] += sub
        # plucked arpeggio, eighth notes at 90 bpm, only after the intro
        if k * bar >= 8:
            step = 60 / 90 / 2
            for j in range(int(bar / step)):
                s0 = k * bar + j * step
                note = arp[j % len(arp)]
                i0 = int(s0 * SR)
                ln = int(1.6 * SR)
                if i0 >= n:
                    break
                i1 = min(n, i0 + ln)
                u = np.arange(i1 - i0) / SR
                f = hz(note)
                pl = (np.sin(2 * np.pi * f * u) + 0.3 * np.sin(4 * np.pi * f * u) * np.exp(-u * 9)) * np.exp(-u * 3.2) * (1 - np.exp(-u * 400))
                g = 0.022 * (0.8 if j % 2 else 1.0)
                pan = 0.3 if j % 2 else 0.7
                L[i0:i1] += pl * g * (1 - pan)
                R[i0:i1] += pl * g * pan
        k += 1
    sos = butter(2, 5200, "low", fs=SR, output="sos")
    L, R = sosfilt(sos, L), sosfilt(sos, R)
    # reverb: decaying stereo noise impulse
    ir_n = int(3.2 * SR)
    u = np.arange(ir_n) / SR
    irl = rng.standard_normal(ir_n) * np.exp(-u * 2.1)
    irr = rng.standard_normal(ir_n) * np.exp(-u * 2.1)
    sos_ir = butter(2, 3800, "low", fs=SR, output="sos")
    irl, irr = sosfilt(sos_ir, irl), sosfilt(sos_ir, irr)
    irl /= np.sqrt((irl ** 2).sum())
    irr /= np.sqrt((irr ** 2).sum())
    wl = fftconvolve(L, irl)[:n]
    wr = fftconvolve(R, irr)[:n]
    L, R = 0.65 * L + 0.55 * wl, 0.65 * R + 0.55 * wr
    fade_in, fade_out = int(2.5 * SR), int(4.0 * SR)
    env = np.ones(n)
    env[:fade_in] = np.linspace(0, 1, fade_in) ** 2
    env[-fade_out:] = np.linspace(1, 0, fade_out) ** 1.5
    st = np.stack([L * env, R * env], 1)
    return st / np.abs(st).max() * 0.7


def click() -> np.ndarray:
    n = int(0.09 * SR)
    u = np.arange(n) / SR
    x = (np.sin(2 * np.pi * 2300 * u) * 0.6 + np.sin(2 * np.pi * 1150 * u) * 0.4) * np.exp(-u * 70)
    x += rng.standard_normal(n) * np.exp(-u * 300) * 0.15
    return np.stack([x, x], 1) * 0.5


def whoosh() -> np.ndarray:
    n = int(1.1 * SR)
    u = np.arange(n) / SR
    x = rng.standard_normal(n)
    out = np.zeros(n)
    blk = 1024
    for i in range(0, n, blk):   # band-pass sweeping upward
        c = 300 + 3500 * (i / n) ** 1.4
        sos = butter(2, [c * 0.7, c * 1.4], "band", fs=SR, output="sos")
        out[i:i + blk] = sosfilt(sos, x[max(0, i - 2048):i + blk])[-len(out[i:i + blk]):]
    env = np.sin(np.pi * np.clip(u / 1.1, 0, 1)) ** 2
    out = out * env
    out /= np.abs(out).max()
    return np.stack([out * 0.9, out], 1) * 0.35


def save(name: str, x: np.ndarray) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    wavfile.write(OUT / name, SR, (np.clip(x, -1, 1) * 32767).astype(np.int16))


if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 160
    save("music.wav", music(secs))
    save("click.wav", click())
    save("whoosh.wav", whoosh())
    print("wrote", OUT)
