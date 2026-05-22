#!/usr/bin/env python3
"""
SecVA Clip Processor
Reads a clip-job.json file, downloads the source video via yt-dlp,
and cuts individual clips via ffmpeg with re-encoded H.264 + AAC output.
"""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


def load_job(job_path: str) -> dict:
    """Load and validate a clip job JSON file."""
    with open(job_path, "r", encoding="utf-8") as f:
        job = json.load(f)

    required_keys = ["youtube_url", "clips"]
    for key in required_keys:
        if key not in job:
            print(f"ERROR: clip-job.json is missing required key: '{key}'")
            sys.exit(1)

    return job


def download_video(youtube_url: str, output_dir: Path) -> Path:
    """Download the video via yt-dlp. Returns the path to the downloaded file."""
    output_template = str(output_dir / "source.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", output_template,
    ]

    # Use cookies file if present (needed for datacenter IPs)
    cookies_path = Path(__file__).parent / "cookies.txt"
    if cookies_path.exists():
        cmd.extend(["--cookies", str(cookies_path)])
        print("Using cookies.txt for authentication")

    cmd.append(youtube_url)
    print(f"\n{'='*60}")
    print(f"DOWNLOADING VIDEO")
    print(f"{'='*60}")
    print(f"URL: {youtube_url}")
    subprocess.run(cmd, check=True)

    # Find the downloaded file
    for f in output_dir.glob("source.*"):
        if f.suffix in (".mp4", ".mkv", ".webm"):
            print(f"Downloaded: {f.name} ({f.stat().st_size / (1024*1024):.1f} MB)")
            return f

    print("ERROR: Could not find downloaded video file")
    sys.exit(1)


def timestamp_to_seconds(ts: str) -> float:
    """Convert HH:MM:SS.mmm or MM:SS.mmm or SS.mmm to seconds."""
    parts = ts.replace(",", ".").split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    else:
        return float(parts[0])


def seconds_to_srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def cut_clip(
    source_video: Path,
    clip: dict,
    output_dir: Path,
    padding: float = 0.5,
) -> Path:
    """Cut a single clip from the source video using ffmpeg with re-encoding."""
    clip_id = clip["clip_id"]
    slug = clip["slug"]
    start_sec = timestamp_to_seconds(clip["start"]) - padding
    end_sec = timestamp_to_seconds(clip["end"]) + padding

    # Clamp start to 0
    start_sec = max(0.0, start_sec)
    duration = end_sec - start_sec

    output_file = output_dir / f"{clip_id}-{slug}.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start_sec),
        "-i", str(source_video),
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_file),
    ]

    print(f"\n  Cutting {clip_id}: {clip.get('title', slug)}")
    print(f"    {clip['start']} -> {clip['end']} (padded: {start_sec:.1f}s - {end_sec:.1f}s)")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    ERROR: ffmpeg failed for {clip_id}")
        print(f"    {result.stderr[-500:]}")
        return None

    size_mb = output_file.stat().st_size / (1024 * 1024)
    print(f"    Output: {output_file.name} ({size_mb:.1f} MB)")
    return output_file


def write_srt(clip: dict, output_dir: Path, padding: float = 0.5) -> Path:
    """Write the per-clip SRT file with timestamps zeroed to clip start."""
    clip_id = clip["clip_id"]
    slug = clip["slug"]
    srt_file = output_dir / f"{clip_id}-{slug}.en_US.srt"

    if "srt_cues" not in clip:
        print(f"    No SRT cues for {clip_id}, skipping SRT")
        return None

    clip_start = timestamp_to_seconds(clip["start"]) - padding
    clip_start = max(0.0, clip_start)

    with open(srt_file, "w", encoding="utf-8") as f:
        for i, cue in enumerate(clip["srt_cues"], 1):
            cue_start = max(0.0, timestamp_to_seconds(cue["start"]) - clip_start)
            cue_end = max(0.0, timestamp_to_seconds(cue["end"]) - clip_start)
            f.write(f"{i}\n")
            f.write(f"{seconds_to_srt_timestamp(cue_start)} --> {seconds_to_srt_timestamp(cue_end)}\n")
            f.write(f"{cue['text']}\n\n")

    return srt_file


def package_clip(clip_video: Path, clip_srt: Path, output_dir: Path) -> Path:
    """Create a zip file containing the clip video and SRT."""
    zip_name = clip_video.stem + ".zip"
    zip_path = output_dir / zip_name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(clip_video, clip_video.name)
        if clip_srt and clip_srt.exists():
            zf.write(clip_srt, clip_srt.name)

    return zip_path


def main():
    # Find the job file
    job_dir = Path(__file__).parent / "jobs"
    job_files = sorted(job_dir.glob("clip-job*.json"), reverse=True)

    if not job_files:
        print("No clip-job.json found in the jobs/ folder.")
        print("Upload your clip-job.json file to the jobs/ folder and run again.")
        sys.exit(1)

    job_path = job_files[0]  # Most recent job
    print(f"Loading job: {job_path.name}")
    job = load_job(str(job_path))

    # Setup output directory
    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    # Clean previous output (but keep source video if pre-uploaded)
    for f in output_dir.iterdir():
        if f.is_file() and not f.name.startswith("source."):
            f.unlink()

    # Download the video (or use pre-uploaded source)
    source_candidates = list(output_dir.glob("source.*"))
    source_video = None
    for sc in source_candidates:
        if sc.suffix in (".mp4", ".mkv", ".webm"):
            source_video = sc
            print(f"Using pre-uploaded video: {sc.name} ({sc.stat().st_size / (1024*1024):.1f} MB)")
            break

    if source_video is None:
        source_video = download_video(job["youtube_url"], output_dir)

    # Cut each clip
    print(f"\n{'='*60}")
    print(f"CUTTING {len(job['clips'])} CLIPS")
    print(f"{'='*60}")

    padding = job.get("padding", 0.5)
    results = []

    for clip in job["clips"]:
        clip_video = cut_clip(source_video, clip, output_dir, padding)
        clip_srt = write_srt(clip, output_dir, padding)

        if clip_video:
            zip_path = package_clip(clip_video, clip_srt, output_dir)
            results.append({
                "clip_id": clip["clip_id"],
                "title": clip.get("title", ""),
                "video": clip_video.name,
                "srt": clip_srt.name if clip_srt else None,
                "zip": zip_path.name,
            })

    # Summary
    print(f"\n{'='*60}")
    print(f"DONE — {len(results)}/{len(job['clips'])} clips processed")
    print(f"{'='*60}")
    print(f"\nOutput directory: {output_dir}")
    print(f"\nFiles ready for download:")
    for r in results:
        print(f"  {r['zip']}")

    print(f"\n  source video: {source_video.name}")
    print(f"\nRight-click files in VS Code Explorer → Download")


if __name__ == "__main__":
    main()
