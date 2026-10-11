"""Cut the submission video: clips + crossfades + word-timed captions + voice + ducked music + UI sounds.

Inputs (from tts.py, music.py and shots.mjs): build/tts/*.mp3|json, build/audio/*.wav, build/clips/*.mp4|json
Output: out/GreenCityAI_submission.mp4 and out/GreenCityAI_submission.srt (captions for YouTube)
Run: python video/edit.py
"""
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
B = HERE / "build"
OUT = HERE / "out"
NARR = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))
FADE = {"s1_twin": 0.04, "s9_points": 0.04, "s10_splats": 0.04, "s11_outro": 0.04}   # continuous camera: a straight cut. Everything else crossfades.
XF = 0.5
TOP_CAPTIONS = {"s6_simulate", "s7_anywhere", "s8_drone"}    # panels sit at the bottom in these shots


def clip_meta():
    shots = []
    for s in NARR["shots"]:
        m = json.loads((B / "clips" / f"{s['id']}.json").read_text(encoding="utf-8"))
        m["tts"] = json.loads((B / "tts" / f"{s['id']}.json").read_text(encoding="utf-8"))
        shots.append(m)
    t = 0.0
    for i, m in enumerate(shots):
        d = 0 if i == 0 else FADE.get(m["id"], XF)
        m["xf"] = d
        m["start"] = t - d if i else 0.0
        t = m["start"] + m["len"]
    return shots, t


def word_times(tts: dict) -> list[tuple[str, float, float]]:
    """Original words with punctuation, timed by the voice's word boundaries."""
    words = tts["text"].split()
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    out, wi = [], 0
    for b in tts["words"]:
        target, acc, start = norm(b["w"]), "", wi
        while wi < len(words) and len(acc) < len(target):
            acc += norm(words[wi])
            wi += 1
        for k in range(start, wi):
            out.append((words[k], b["t0"], b["t1"]))
    while wi < len(words):
        out.append((words[wi], out[-1][2], out[-1][2] + .2))
        wi += 1
    return out


def voice_map(m: dict, t: float) -> float | None:
    """Clip time of a moment t in the voice file."""
    for seg in m["voice"]:
        if seg["from"] - 1e-6 <= t <= seg["to"] + 1e-6:
            return m["start"] + seg["at"] + (t - seg["from"])
    return None


def lines(wt: list) -> list[list]:
    """Caption lines: clauses at punctuation, short ones merged, long ones split evenly (no one-word orphans)."""
    txt = lambda ws: " ".join(w[0] for w in ws)
    clauses, cur = [], []
    for x in wt:
        cur.append(x)
        if re.search(r"[,.:;]$", x[0]):
            clauses.append(cur)
            cur = []
    if cur:
        clauses.append(cur)
    merged = []
    for c in clauses:
        if merged and len(txt(merged[-1] + c)) <= 50 and not re.search(r"[.]$", merged[-1][-1][0]):
            merged[-1] = merged[-1] + c
        else:
            merged.append(c)
    out = []
    for c in merged:
        n = len(txt(c))
        k = max(1, -(-n // 52))
        if k == 1:
            out.append(c)
            continue
        part, done = [], 0
        for x in c:
            part.append(x)
            if done < k - 1 and len(txt(part)) >= n / k * 0.92:
                out.append(part)
                part, done = [], done + 1
        if part:
            if len(txt(part)) < 12 and out:
                out[-1] = out[-1] + part
            else:
                out.append(part)
    return out


def captions(shots) -> list[list]:
    caps = []
    for m in shots:
        seg = lambda t: next((k for k, v in enumerate(m["voice"]) if v["from"] - 1e-6 <= t <= v["to"] + 1e-6), -1)
        for ln in lines(word_times(m["tts"])):
            groups = []
            for w in ln:   # a line never spans a pause in the voice
                if groups and seg(w[1]) == seg(groups[-1][-1][1]):
                    groups[-1].append(w)
                else:
                    groups.append([w])
            for g in groups:
                a, e = voice_map(m, g[0][1]), voice_map(m, min(g[-1][2], m["voice"][seg(g[-1][1])]["to"]))
                if a is not None and e is not None:
                    caps.append([a, e + .25, " ".join(w[0] for w in g), m["id"] in TOP_CAPTIONS])
    for i in range(len(caps) - 1):   # no overlaps, small gaps closed
        if caps[i + 1][0] - caps[i][1] < .35:
            caps[i][1] = caps[i + 1][0] - .02
    return caps


def ts_ass(t: float) -> str:
    h, r = divmod(max(0, t), 3600)
    mi, s = divmod(r, 60)
    return f"{int(h)}:{int(mi):02d}:{s:05.2f}"


def ts_srt(t: float) -> str:
    ms = int(round(max(0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    mi, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{mi:02d}:{s:02d},{ms:03d}"


def write_subs(caps) -> None:
    ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "WrapStyle: 0", "",
           "[V4+ Styles]",
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
           "Style: Cap,Segoe UI Semibold,40,&H00FFFFFF,&H00FFFFFF,&H5A08101A,&H5A08101A,0,0,0,0,100,100,0.2,0,3,14,0,2,200,200,118,1",
           "Style: Top,Segoe UI Semibold,40,&H00FFFFFF,&H00FFFFFF,&H5A08101A,&H5A08101A,0,0,0,0,100,100,0.2,0,3,14,0,8,200,200,168,1",
           "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    srt = []
    for i, (a, e, text, top) in enumerate(caps, 1):
        ass.append(f"Dialogue: 0,{ts_ass(a)},{ts_ass(e)},{'Top' if top else 'Cap'},,0,0,0,,{{\\fad(120,120)}}{text}")
        srt += [str(i), f"{ts_srt(a)} --> {ts_srt(e)}", text, ""]
    (B / "captions.ass").write_text("\n".join(ass) + "\n", encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "GreenCityAI_submission.srt").write_text("\n".join(srt), encoding="utf-8")


def main() -> None:
    shots, total = clip_meta()
    caps = captions(shots)
    write_subs(caps)
    print(f"{len(shots)} clips, {total:.1f} s, {len(caps)} captions")

    inputs, fc = [], []
    for m in shots:
        inputs += ["-i", str(B / "clips" / f"{m['id']}.mp4")]
    # video: chain of crossfades
    prev = "0:v"
    for i, m in enumerate(shots[1:], 1):
        lab = f"v{i}"
        fc.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={m['xf']:.3f}:offset={m['start']:.3f}[{lab}]")
        prev = lab
    fc.append(f"[{prev}]subtitles=captions.ass,fade=t=in:st=0:d=0.6,fade=t=out:st={total - 1.0:.3f}:d=1.0,format=yuv420p[vout]")

    # audio: voice segments, clicks, whooshes, music
    n = len(shots)
    a_idx = n
    voice_labels, sfx_labels = [], []
    for m in shots:
        inputs += ["-i", str(B / "tts" / f"{m['id']}.mp3")]
        for k, seg in enumerate(m["voice"]):
            lab = f"vo{a_idx}_{k}"
            at = int(round((m["start"] + seg["at"]) * 1000))
            fc.append(f"[{a_idx}:a]atrim={seg['from']:.3f}:{seg['to']:.3f},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,adelay={at}|{at}[{lab}]")
            voice_labels.append(lab)
        a_idx += 1
    inputs += ["-i", str(B / "audio" / "click.wav")]
    click_i = a_idx
    a_idx += 1
    clicks = [m["start"] + c for m in shots for c in m["clicks"]]
    if clicks:
        fc.append(f"[{click_i}:a]asplit={len(clicks)}" + "".join(f"[ck{k}]" for k in range(len(clicks))))
        for k, c in enumerate(clicks):
            ms = int(round(c * 1000))
            fc.append(f"[ck{k}]volume=0.55,adelay={ms}|{ms}[ckd{k}]")
            sfx_labels.append(f"ckd{k}")
    inputs += ["-i", str(B / "audio" / "whoosh.wav")]
    wh_i = a_idx
    a_idx += 1
    whs = [max(0, m["start"] - .45) for m in shots[1:] if m["xf"] > .1]
    fc.append(f"[{wh_i}:a]asplit={len(whs)}" + "".join(f"[wh{k}]" for k in range(len(whs))))
    for k, w in enumerate(whs):
        ms = int(round(w * 1000))
        fc.append(f"[wh{k}]volume=0.5,adelay={ms}|{ms}[whd{k}]")
        sfx_labels.append(f"whd{k}")
    inputs += ["-i", str(B / "audio" / "music.wav")]
    mu_i = a_idx
    fc.append("".join(f"[{l}]" for l in voice_labels) + f"amix=inputs={len(voice_labels)}:normalize=0:duration=longest,apad=whole_dur={total:.3f},atrim=0:{total:.3f}[voice]")
    fc.append("[voice]asplit=2[vmix][vkey]")
    fc.append(f"[{mu_i}:a]atrim=0:{total:.3f},volume=0.30,afade=t=out:st={total - 3.5:.3f}:d=3.5[mus]")
    fc.append("[mus][vkey]sidechaincompress=threshold=0.02:ratio=5:attack=25:release=450:makeup=1[mduck]")
    fc.append("".join(f"[{l}]" for l in sfx_labels) + f"amix=inputs={len(sfx_labels)}:normalize=0:duration=longest,apad=whole_dur={total:.3f},atrim=0:{total:.3f}[sfx]")
    fc.append("[vmix][mduck][sfx]amix=inputs=3:normalize=0:weights=1 1 0.8,loudnorm=I=-15:TP=-1.5:LRA=9[aout]")

    script = B / "filter.txt"
    script.write_text(";\n".join(fc), encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "GreenCityAI_submission.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-/filter_complex", str(script), "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-t", f"{total:.3f}", str(out)]
    subprocess.run(cmd, check=True, cwd=B)
    print("wrote", out)


if __name__ == "__main__":
    main()
