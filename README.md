# SecVA Clip Processor

Codespace-based video clip processor for Secretary Collins media appearances.

## How it works

1. A clip job (JSON file) is generated locally by the `secva-youtube-clipper` Copilot skill
2. Upload the `clip-job.json` to the `jobs/` folder in this codespace
3. Run `python process.py`
4. Download your clips from the `output/` folder

## What it does

- Downloads the source video from YouTube via yt-dlp
- Cuts each clip with frame-accurate re-encoding (H.264 + AAC)
- Adds 0.5s padding before/after each clip
- Generates per-clip SRT subtitle files (timestamps zeroed to clip start)
- Packages each clip as a zip (video + SRT)

## Output

All files land in `output/`:
- `SC-01-slug.mp4` — individual clip videos
- `SC-01-slug.en_US.srt` — individual clip subtitles
- `SC-01-slug.zip` — packaged clip + SRT
- `source.mp4` — the full downloaded video
