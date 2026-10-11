# Submission video

The video is made by code, so every number on screen and in the voice-over comes from the twins and can be re-made.

| Step | Command (from the repo root) | What it does |
|---|---|---|
| 1 | `scripts\run_all.bat` (or `python scripts/serve.py` and `python scripts/dev_api.py`) | Web app on 8765, doctor and twin builder on 8766 |
| 2 | `python video/tts.py` | Voice-over from `video/narration.json`, Indian English neural voice (edge-tts, needs internet), with word timings |
| 3 | `python video/music.py` | Synthesised ambient music, a UI click and a whoosh (no licences needed) |
| 4 | `cd video` then `node shots.mjs` | Drives the real app in headless Chrome on the GPU and records each shot frame by frame at 30 fps |
| 5 | `python video/edit.py` | Crossfades, word-timed captions, voice, ducked music and clicks. Writes `video/out/GreenCityAI_submission.mp4` and `.srt` |

How the recorder works (`rec.mjs`): page time is virtual. Each video frame moves the page clock by exactly 1/30 s
(requestAnimationFrame, `performance.now`, `Date.now`, timers and CSS animations), so camera flights stay smooth however long
a frame takes to draw. Real time only passes while the app waits for the network, such as Claude's answer or a twin build;
the build is shown as a labelled time-lapse.

The shots (`shots.mjs`), all on Indian sites:

1. Title over Connaught Place, New Delhi.
2. The twin from open data: 212 buildings (OpenStreetMap), 936 trees (canopy map on AWS Open Data), sun for 15 May.
3. Hourly shade: 33% of walkway shaded at 07:00, 4% at noon with the sun 79° high; the sun-exposure hex map.
4. The city around it: 658 buildings, 111 junctions, 27 bus stops; the observed / computed / simulated / proposed labels.
5. Analyze Middle Circle × Radial Road 2: 1.57 times assumed capacity (simulated), 85.1% of walkway in sun at 15:00.
6. Claude Sonnet 5.5 explains it through the measuring tools; the checker badge.
7. Simulate: diversion 1.57 to 1.44, 200 trees lift day-mean walkway shade 13.9% to 17.0%, cost marked assumed.
8. Search Charminar, Hyderabad, and build a new twin live.
9. Credits: data, stack, repo.

Change the voice in `narration.json` (`en-IN-PrabhatNeural` is the male Indian English voice), then repeat steps 2, 4 and 5.
