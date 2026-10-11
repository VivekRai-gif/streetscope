"""Voice-over for the submission video: one clip per shot, with word timings for captions and cue points.

Uses Microsoft Edge neural voices through the edge-tts package (Indian English, en-IN). Needs internet.
Run: python video/tts.py [shot ids]   ->  video/build/tts/<shot>.mp3 and <shot>.json
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import edge_tts

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "tts"


async def speak(text: str, voice: str, rate: str, mp3: Path) -> list[dict]:
    com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words = []
    with mp3.open("wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                words.append({"w": ch["text"], "t0": ch["offset"] / 1e7, "t1": (ch["offset"] + ch["duration"]) / 1e7})
    return words


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


async def main() -> None:
    cfg = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0.0
    only = sys.argv[1:]
    for s in cfg["shots"]:
        if only and s["id"] not in only:
            continue
        mp3 = OUT / f"{s['id']}.mp3"
        words = await speak(s["text"], cfg["voice"], cfg["rate"], mp3)
        d = duration(mp3)
        total += d
        (OUT / f"{s['id']}.json").write_text(json.dumps({"id": s["id"], "text": s["text"], "duration": d, "words": words}, indent=1), encoding="utf-8")
        print(f"{s['id']:14s} {d:5.1f} s  {len(words)} words")
    print(f"voice total {total:.1f} s")


if __name__ == "__main__":
    asyncio.run(main())
