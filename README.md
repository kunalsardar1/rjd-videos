# rjd-videos

Ten times a day this repository makes one 15-second job video for Remote Job Drop and posts it to Instagram,
Facebook, YouTube, Threads and Telegram.

How it works:

1. `make-video.js` asks the RJD Autopilot web app (Apps Script) for the next job. The web app picks the job, writes
   the Hinglish voice script and captions, and makes the female voice (Gemini).
2. `template.html` is drawn frame by frame in Chromium, timed to the voice. `audio.py` adds slow music and sound
   effects under the voice.
3. The MP4 goes back to the web app, which posts it. The posting tokens stay in Apps Script; this repository only has
   two secrets: `RJD_URL` (the web app address) and `RJD_KEY` (VIDEO_KEY from Apps Script).

The schedule is in `.github/workflows/video.yml`. Every run adds a line to `videos-log.txt`, and the video stays under
the run's **Artifacts** for 7 days.

To make one now: **Actions > Job video > Run workflow**.

Local test (no posting): `npm ci && FIXTURE=fixture.json SKIP_POST=1 node make-video.js` (needs Chromium from
`npx playwright-core install chromium`, ffmpeg, and Python with numpy and scipy). The video is `out/video.mp4`.
