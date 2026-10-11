"""Use a voice-over recorded elsewhere (for example Gemini 3.8 Flash TTS in Google AI Studio) instead of tts_veena.py.

Give it one audio file with all the shots read in order (or one file per shot, sorted by name). The words come from
narration.json (the spoken side of {shown|said}). Forced alignment (torchaudio MMS_FA) finds every word in the audio,
the audio is cut between shots in the silences, and each shot gets build/tts/<shot>.mp3 + .json with word timings, the
same format as tts.py, so shots.mjs and edit.py work unchanged. Whisper listens to each cut as a check.

Run (from the repo root): video\\.venv\\Scripts\\python.exe video\\import_voice.py "video\\gemini\\<file>.wav" [more files]
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tts_veena import parse, norm, wer  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "tts"
SR = 16000


def load(paths: list[str]) -> tuple[np.ndarray, int]:
    parts, sr0 = [], None
    for p in paths:
        a, sr = sf.read(p, dtype="float32", always_2d=True)
        a = a.mean(1)
        sr0 = sr0 or sr
        if sr != sr0:
            a = torchaudio.functional.resample(torch.from_numpy(a), sr, sr0).numpy()
        parts += [a, np.zeros(int(0.4 * sr0), np.float32)]
    return np.concatenate(parts), sr0


@torch.no_grad()
def emissions(model, wav16: torch.Tensor, win: float = 20.0, edge: float = 1.5) -> torch.Tensor:
    """Frame-level emissions for a long recording, computed in overlapping windows and stitched."""
    n, w, e = wav16.shape[1], int(win * SR), int(edge * SR)
    out, start = [], 0
    while True:
        a = max(0, start - e)
        b = min(n, start + w + e)
        em, _ = model(wav16[:, a:b])
        k = em.shape[1] / (b - a)
        lo = int(round((start - a) * k))
        hi = int(round((min(n, start + w) - a) * k))
        out.append(em[:, lo:hi])
        start += w
        if start >= n:
            break
    return torch.cat(out, 1)


def main() -> None:
    cfg = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))
    files = sys.argv[1:]
    if not files:
        raise SystemExit("give the recorded audio file(s)")
    audio, sr = load(files)
    wav16 = torchaudio.functional.resample(torch.from_numpy(audio), sr, SR).unsqueeze(0).cuda()
    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(with_star=False).cuda().eval()
    tok, aligner = bundle.get_tokenizer(), bundle.get_aligner()
    em = emissions(model, wav16)
    sec_per_frame = wav16.shape[1] / em.shape[1] / SR

    shots = [(s["id"], parse(s["text"])) for s in cfg["shots"]]
    words = [w for _, toks in shots for _, ws in toks for w in ws]
    clean = [norm(w).replace(" ", "") or "a" for w in words]
    spans = aligner(em[0], tok(clean))
    times = [(s[0].start * sec_per_frame, s[-1].end * sec_per_frame) for s in spans]

    # cut between shots in the middle of the silence
    k, bounds = 0, []
    for sid, toks in shots:
        n = sum(len(ws) for _, ws in toks)
        bounds.append((k, k + n))
        k += n
    cuts = [0.0]
    for (a, b), (c, d) in zip(bounds, bounds[1:]):
        cuts.append((times[b - 1][1] + times[c][0]) / 2)
    cuts.append(len(audio) / sr)

    from transformers import pipeline
    asr = pipeline("automatic-speech-recognition", model="openai/whisper-large-v3-turbo", torch_dtype=torch.float16, device="cuda")
    names = tuple(cfg.get("veena", {}).get("names", []))
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0.0
    for i, ((sid, toks), (a, b)) in enumerate(zip(shots, bounds)):
        t0 = max(cuts[i], times[a][0] - 0.06)               # keep a short breath before the first word
        t1 = min(cuts[i + 1], times[b - 1][1] + 0.18)
        seg = audio[int(t0 * sr):int(t1 * sr)]
        out_words, j = [], a
        for cap, ws in toks:
            out_words.append({"w": cap, "t0": round(times[j][0] - t0, 3), "t1": round(times[j + len(ws) - 1][1] - t0, 3)})
            j += len(ws)
        wav_path = OUT / f"{sid}.wav"
        sf.write(wav_path, seg, sr)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-ar", "48000", "-b:a", "192k", str(OUT / f"{sid}.mp3")], check=True)
        d = len(seg) / sr
        total += d
        (OUT / f"{sid}.json").write_text(json.dumps({"id": sid, "text": " ".join(c for c, _ in toks), "duration": d, "words": out_words,
                                                      "voice": cfg.get("voice_label", "recorded")}, indent=1), encoding="utf-8")
        said = " ".join(w for _, ws in toks for w in ws)
        heard = asr({"raw": torchaudio.functional.resample(torch.from_numpy(seg), sr, 16000).numpy(), "sampling_rate": 16000},
                    generate_kwargs={"language": "en"})["text"].strip()
        e = wer(said, heard, names)
        print(f"{sid:14s} {d:5.1f} s  wer {e:.2f}  heard: {heard}", flush=True)
    print(f"voice total {total:.1f} s")


if __name__ == "__main__":
    main()
