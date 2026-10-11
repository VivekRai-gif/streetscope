# Submission video

The video is made by code, so every number on screen and in the voice-over comes from the twins and can be re-made.

| Step | Command (from the repo root) | What it does |
|---|---|---|
| 1 | `scripts\run_all.bat` (or `python scripts/serve.py` and `python scripts/dev_api.py`) | Web app on 8765, doctor and twin builder on 8766 |
| 2 | `video\.venv\Scripts\python.exe video\import_voice.py "video\gemini\<file>.wav"` | The voice-over. We read the spoken side of `video/narration.json` with **Gemini 3.8 Flash TTS** in Google AI Studio (12 speech blocks, one per shot, an Indian English narrator persona) and saved one WAV in `video/gemini/`. The importer finds every word with forced alignment (torchaudio MMS_FA), cuts the shots in the silences, writes word timings for captions and on-screen cues, and has Whisper listen to each shot as a check. Without a recording, `tts_veena.py` (open Veena model, local GPU) or `tts.py` (Edge voices) make the voice instead. |
| 3 | `python video/music.py` | Synthesised ambient music, a UI click and a whoosh (no licences needed) |
| 4 | `cd video` then `node shots.mjs` | Drives the real app in headless Chrome on the GPU and records each shot frame by frame at 30 fps |
| 5 | `python video/edit.py` | Crossfades, word-timed captions, voice, ducked music and clicks. Writes `video/out/GreenCityAI_submission.mp4` and `.srt` |

Local voice setup (once, about 10 GB; also needed by the importer for alignment and Whisper): `cd video`, `uv venv .venv --python 3.11`, then
`uv pip install --python .venv/Scripts/python.exe torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124` and
`uv pip install --python .venv/Scripts/python.exe "transformers>=4.46,<4.56" accelerate snac bitsandbytes soundfile num2words`.
In `narration.json`, `{1.57|one point five seven}` shows "1.57" in the captions and says the words. The speaker is `maitri`:
in our tests the other voices sometimes switched between a male and a female voice from one take to the next, Maitri never did.
`python video/tts.py` is the older fallback (Microsoft Edge voices, needs internet).

Drone scan for shots 9 to 11: the public IIT Gandhinagar campus survey (Mendeley Data, doi:10.17632/nmxysw8ybx.1,
CC BY-NC 3.0, 4.6 GB CloudCompare `.bin` mesh). We took the mesh vertices in CloudCompare
(`-EXTRACT_VERTICES -SS SPATIAL 0.25`), cropped a 920 m square around UTM 43N 263200 E, 2568700 N with laspy, and saved it as
`C:\hackathon\drone_data\IIT_Gandhinagar_campus.laz` (12.6 M points, EPSG:32643 in the header, the credit in the LAS
system identifier). Before re-shooting shots 8 and 9, delete `web/data/charminar` and `web/data/iit_gandhinagar_campus` and
their lines in `web/data/index.json`, because both are built live on camera.

How the recorder works (`rec.mjs`): page time is virtual. Each video frame moves the page clock by exactly 1/30 s
(requestAnimationFrame, `performance.now`, `Date.now`, timers and CSS animations), so camera flights stay smooth however long
a frame takes to draw. Real time only passes while the app waits for the network, such as Claude's answer or a twin build;
builds are shown as labelled time-lapses. File uploads go through Chrome's file-chooser interception.

The shots (`shots.mjs`), all on Indian sites:

1. Title over Connaught Place, New Delhi.
2. The twin from open data: 212 buildings (OpenStreetMap), 936 trees (canopy map on AWS Open Data), sun for 15 May.
3. Hourly shade: a third of the walkway shaded at 07:00, 4% at noon with the sun 79° high; the sun-exposure hex map.
4. The city around it, and the observed / computed / simulated / proposed labels.
5. Analyze Middle Circle × Radial Road 2: 1.57 times assumed capacity (simulated), 85% of walkway in sun at 15:00.
6. Claude Sonnet 5.5 explains it through the measuring tools; the checker badge.
7. Simulate: diversion 1.57 to 1.44, 200 trees lift day-mean walkway shade 13.9% to 17.0%, cost marked assumed.
8. Search Charminar, Hyderabad, and build a new twin live.
9. Upload a drone scan (IIT Gandhinagar campus, 12.6 M points); the twin builds itself where the file says; 71 of 73 buildings measured, 2,380 tree tops.
10. The scan as points: rising into place, photo colours, then classes.
11. The same scan as gaussian splats with the reveal animation.
12. Credits: data, stack, repo.
