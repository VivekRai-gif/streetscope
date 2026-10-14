"""Voice-over with Veena, an open Indian-English/Hindi TTS model (Maya Research, Apache 2.0), run locally on the GPU.

Why: it was trained on Indian speakers, so Connaught Place, Charminar and Gandhinagar sound the way people in India say
them, and the delivery is more natural than the older neural voices.

Each sentence is spoken separately. Whisper listens back to every take and a take is kept only when it says every word
(otherwise it is spoken again with a new seed, best of up to 6). Word timings come from forced alignment (torchaudio
MMS_FA) against the exact words, so captions and on-screen cues land on the right word.

Text markup in narration.json: {1.57|one point five seven} shows "1.57" in captions and says the words.
Run (from the repo root): video\\.venv\\Scripts\\python.exe video\\tts_veena.py [shot ids]
Writes video/build/tts/<shot>.mp3 and <shot>.json (same format as tts.py).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "tts"
SR = 24000
SOS, EOS, SOH, EOH, SOA, EOA, AUDIO0 = 128257, 128258, 128259, 128260, 128261, 128262, 128266


def parse(text: str) -> list[tuple[str, list[str]]]:
    """[(caption token, [spoken words])] from text with {shown|said} groups."""
    out = []
    for m in re.finditer(r"\{([^|}]*)\|([^}]*)\}(\S*)|(\S+)", text):
        if m.group(4):
            out.append((m.group(4), [m.group(4)]))
        else:
            out.append((m.group(1) + m.group(3), m.group(2).split() + ([m.group(3)] if m.group(3) else [])))
    return out


def spoken(tokens) -> str:
    return " ".join(w for _, ws in tokens for w in ws)


def norm(s: str) -> str:
    return re.sub(r"[^a-z' ]", "", s.lower().replace("-", " ")).strip()


def sentences(tokens):
    """Split into sentences at . ? ! (keeping the caption tokens with their words)."""
    cur, out = [], []
    for tok in tokens:
        cur.append(tok)
        if re.search(r"[.?!]$", tok[1][-1]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


class Voice:
    def __init__(self, speaker: str):
        from snac import SNAC
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, pipeline

        q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
        self.model = AutoModelForCausalLM.from_pretrained("maya-research/Veena", quantization_config=q, device_map="cuda", trust_remote_code=True)
        self.tok = AutoTokenizer.from_pretrained("maya-research/Veena", trust_remote_code=True)
        self.snac = SNAC.from_pretrained("hubertsiuzdak/snac_24khz").eval().cuda()
        self.asr = pipeline("automatic-speech-recognition", model="openai/whisper-large-v3-turbo", torch_dtype=torch.float16, device="cuda")
        import torchaudio

        self.ta = torchaudio
        b = torchaudio.pipelines.MMS_FA
        self.fa = b.get_model(with_star=False).cuda().eval()
        self.fa_tok, self.fa_align = b.get_tokenizer(), b.get_aligner()
        self.speaker = speaker

    @torch.no_grad()
    def say(self, text: str, seed: int, temperature: float = 0.4) -> np.ndarray:
        torch.manual_seed(seed)
        ids = self.tok.encode(f"<spk_{self.speaker}> {text}", add_special_tokens=False)
        inp = torch.tensor([[SOH, *ids, EOH, SOA, SOS]], device="cuda")
        out = self.model.generate(inp, max_new_tokens=min(4200, int(len(text) * 1.6) * 7 + 70), do_sample=True, temperature=temperature,
                                  top_p=0.9, repetition_penalty=1.05, pad_token_id=self.tok.pad_token_id, eos_token_id=[EOS, EOA])
        gen = [t for t in out[0, inp.shape[1]:].tolist() if AUDIO0 <= t < AUDIO0 + 7 * 4096]
        gen = gen[: len(gen) // 7 * 7]
        if not gen:
            return np.zeros(0, np.float32)
        lv = [[], [], []]
        for i in range(0, len(gen), 7):
            f = [gen[i + k] - AUDIO0 - k * 4096 for k in range(7)]
            lv[0].append(f[0])
            lv[1] += [f[1], f[4]]
            lv[2] += [f[2], f[3], f[5], f[6]]
        codes = [torch.tensor(l, dtype=torch.int32, device="cuda").unsqueeze(0) for l in lv]
        if any(((c < 0) | (c > 4095)).any() for c in codes):
            return np.zeros(0, np.float32)
        return self.snac.decode(codes).squeeze().clamp(-1, 1).float().cpu().numpy()

    def hear(self, wav: np.ndarray) -> str:
        w16 = self.ta.functional.resample(torch.from_numpy(wav), SR, 16000).numpy()
        return self.asr({"raw": w16, "sampling_rate": 16000}, generate_kwargs={"language": "en"})["text"]

    @torch.no_grad()
    def align(self, wav: np.ndarray, words: list[str]) -> list[tuple[float, float]]:
        w16 = self.ta.functional.resample(torch.from_numpy(wav).unsqueeze(0), SR, 16000).cuda()
        em, _ = self.fa(w16)
        clean = [norm(w).replace(" ", "") or "a" for w in words]
        spans = self.fa_align(em[0], self.fa_tok(clean))
        k = w16.shape[1] / em.shape[1] / 16000
        return [(s[0].start * k, s[-1].end * k) for s in spans]


def trim(wav: np.ndarray, pad: float = 0.04) -> np.ndarray:
    """Cut silence at both ends (keeping a short pad)."""
    if not len(wav):
        return wav
    e = np.convolve(np.abs(wav), np.ones(240) / 240, "same")
    on = np.nonzero(e > 0.012)[0]
    if not len(on):
        return wav
    a, b = max(0, on[0] - int(pad * SR)), min(len(wav), on[-1] + int(pad * SR))
    return wav[a:b]


def words_of(s: str) -> list[str]:
    """Normalised words: numbers spelt out, '%' as percent, spelt letters (I I T) joined, 'and' dropped."""
    from num2words import num2words

    s = s.replace("%", " percent").replace("×", " times")
    s = re.sub(r"(\d+)(?:st|nd|rd|th)\b", lambda m: num2words(int(m.group(1)), to="ordinal"), s)
    s = re.sub(r"\d[\d,]*(\.\d+)?", lambda m: " " + num2words(float(m.group(0).replace(",", "")) if "." in m.group(0) else int(m.group(0).replace(",", ""))) + " ", s)
    joined, run = [], ""
    for x in (x for x in norm(s).split() if x != "and"):
        if len(x) == 1:
            run += x
            continue
        if run:
            joined.append(run)
            run = ""
        joined.append(x)
    if run:
        joined.append(run)
    return joined


def wer(ref: str, hyp: str, names: tuple = ()) -> float:
    """Word error rate; substituting a proper name costs nothing (the voice may say it the Indian way, Whisper may not)."""
    r, h = words_of(ref), words_of(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw and rw not in names))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


def pitch(wav: np.ndarray, sr: int = SR) -> float:
    """Median voice pitch in Hz (YIN on voiced frames). Used to reject a take whose voice drifted to another speaker."""
    x, sr = wav[::2], sr // 2
    fmin, fmax, frame, hop = 70, 400, 1024, 480
    tmin, tmax = int(sr / fmax), int(sr / fmin)
    f0 = []
    for st in range(0, len(x) - frame - tmax, hop):
        f = x[st:st + frame + tmax]
        if np.sqrt((f[:frame] ** 2).mean()) < 0.02:
            continue
        d = np.array([np.sum((f[:frame] - f[t:t + frame]) ** 2) for t in range(tmax + 1)])
        dn = np.ones_like(d)
        dn[1:] = d[1:] * np.arange(1, tmax + 1) / np.maximum(np.cumsum(d[1:]), 1e-9)
        c = np.nonzero(dn[tmin:] < 0.12)[0]
        if len(c):
            t = c[0] + tmin
            while t + 1 <= tmax and dn[t + 1] < dn[t]:
                t += 1
            f0.append(sr / t)
    return float(np.median(f0)) if f0 else 0.0


def main() -> None:
    cfg = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))
    vc = cfg.get("veena", {})
    only = sys.argv[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    v = Voice(vc.get("speaker", "kavya"))
    gap = vc.get("sentence_gap_s", 0.32)
    lo, hi = vc.get("f0_range", [0, 1000])
    names = tuple(vc.get("names", []))
    for s in cfg["shots"]:
        if only and s["id"] not in only:
            continue
        toks = parse(s["text"])
        parts, words = [], []
        t = 0.0
        for sen in sentences(toks):
            said = spoken(sen)
            best = None
            for seed in range(vc.get("tries", 6)):
                wav = trim(v.say(said, 1000 * seed + 7, vc.get("temperature", 0.4)))
                if len(wav) < SR * 0.3:
                    continue
                heard = v.hear(wav)
                e = wer(said, heard, names)
                rate = len(said) / (len(wav) / SR)
                f0 = pitch(wav)
                same_voice = lo <= f0 <= hi
                score = e + (0.5 if not 9 <= rate <= 21 else 0) + (2 if not same_voice else 0)
                print(f"  {s['id']} seed {seed}: wer {e:.2f}, {rate:.1f} chars/s, pitch {f0:.0f} Hz  heard: {heard.strip()[:90]}", flush=True)
                if best is None or score < best[0]:
                    best = (score, wav, heard)
                if e == 0 and 9 <= rate <= 21 and same_voice:
                    break
            if best is None or best[0] >= 2:
                raise SystemExit(f"no take in the chosen voice for: {said}")
            wav = best[1]
            wav = np.clip(wav * (0.085 / max(1e-4, float(np.sqrt(np.mean(wav[np.abs(wav) > 0.01] ** 2))))), -0.98, 0.98)   # same loudness per sentence
            spans = v.align(wav, [w for _, ws in sen for w in ws])
            k = 0
            for cap, ws in sen:
                a, b = spans[k][0], spans[k + len(ws) - 1][1]
                words.append({"w": cap, "t0": round(t + a, 3), "t1": round(t + b, 3)})
                k += len(ws)
            parts += [wav, np.zeros(int(gap * SR), np.float32)]
            t += len(wav) / SR + gap
        audio = np.concatenate(parts[:-1])
        wav_path = OUT / f"{s['id']}.wav"
        sf.write(wav_path, audio, SR)
        mp3 = OUT / f"{s['id']}.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-ar", "48000", "-b:a", "192k", str(mp3)], check=True)
        caption = " ".join(c for c, _ in toks)
        d = len(audio) / SR
        (OUT / f"{s['id']}.json").write_text(json.dumps({"id": s["id"], "text": caption, "duration": d, "words": words,
                                                          "voice": f"Veena {v.speaker}"}, indent=1), encoding="utf-8")
        print(f"{s['id']:14s} {d:5.1f} s  {len(words)} words", flush=True)


if __name__ == "__main__":
    main()
