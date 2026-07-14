import argparse
import subprocess
from pathlib import Path


def find_ffmpeg(project_root):
    candidates = [
        project_root / "tools" / "ffmpeg",
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
    ]
    for base in candidates:
        if not base.exists():
            continue
        matches = list(base.rglob("ffmpeg.exe"))
        if matches:
            return matches[0]
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", help="Path to the reference mp4")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--out", default="reports/video_refs")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ffmpeg = find_ffmpeg(root)
    if ffmpeg is None:
        raise SystemExit("ffmpeg.exe not found. Run the setup script with -DownloadFfmpeg first.")

    video = Path(args.video).resolve()
    out_dir = (root / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    pattern = out_dir / "friday_ref_%02d.png"
    command = [
        str(ffmpeg),
        "-y",
        "-i",
        str(video),
        "-vf",
        f"fps={args.count}/40",
        "-frames:v",
        str(args.count),
        str(pattern),
    ]
    subprocess.run(command, check=True)
    print(out_dir)


if __name__ == "__main__":
    main()
