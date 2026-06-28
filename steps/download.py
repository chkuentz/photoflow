"""
Step 1: Download
Handles resumable download of Google Takeout zip(s).

Supports two methods:
  - rclone: Authenticate via OAuth — no public link needed (recommended)
  - wget:   Direct download URL (requires a public or signed link)
"""

import logging
import subprocess
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


def download_takeout(config: dict) -> None:
    scratch = Path(config["paths"]["scratch"])
    zip_dir = scratch / config["download"]["zip_dir"]
    zip_dir.mkdir(parents=True, exist_ok=True)

    method = config["download"].get("method", "wget").lower()

    if method == "rclone":
        _download_rclone(config, zip_dir)
    else:
        _download_wget(config, zip_dir)


# ---------------------------------------------------------------------------
# rclone (OAuth / private Google Drive — recommended)
# ---------------------------------------------------------------------------

def _download_rclone(config: dict, zip_dir: Path) -> None:
    if not shutil.which("rclone"):
        raise EnvironmentError(
            "rclone not found. Install it with: sudo apt install rclone\n"
            "Then run: rclone config  (to authorize your Google account)"
        )

    remote = config["download"].get("rclone_remote", "google")
    paths = config["download"].get("rclone_paths", [])
    single = config["download"].get("rclone_path", "").strip()
    if single:
        paths = [single] + [p for p in paths if p != single]

    if not paths:
        raise ValueError(
            "No rclone path configured. Set download.rclone_path in config.yaml.\n"
            "Example: rclone_path: 'Takeout/takeout-20240101.zip'"
        )

    for i, rclone_path in enumerate(paths, 1):
        source = f"{remote}:{rclone_path}"
        log.info(f"Downloading {i}/{len(paths)} via rclone: {source}")

        cmd = [
            "rclone", "copy",
            source,
            str(zip_dir),
            "--progress",
            "--transfers=1",       # One file at a time for large zips
            "--drive-chunk-size=256M",  # Larger chunks = faster for big files
        ]

        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"rclone download failed for: {source}")

        log.info(f"Downloaded: {rclone_path}")

    log.info(f"All files saved to: {zip_dir}")


# ---------------------------------------------------------------------------
# wget (direct URL — requires public or signed link)
# ---------------------------------------------------------------------------

def _download_wget(config: dict, zip_dir: Path) -> None:
    if not shutil.which("wget"):
        raise EnvironmentError(
            "wget not found. Install it with: sudo apt install wget"
        )

    urls = []
    primary = config["download"].get("url", "").strip()
    if primary:
        urls.append(primary)
    extras = config["download"].get("extra_urls", []) or []
    urls.extend([u for u in extras if u.strip()])

    if not urls:
        raise ValueError(
            "No download URL configured. Set download.url in config.yaml "
            "or pass --url on the command line.\n"
            "Tip: Use method: rclone to download privately without a public link."
        )

    for i, url in enumerate(urls, 1):
        log.info(f"Downloading zip {i}/{len(urls)}: {url}")
        filename = _filename_from_url(url, i)
        dest = zip_dir / filename

        cmd = [
            "wget",
            "--continue",
            "--show-progress",
            "--progress=bar:force",
            "-O", str(dest),
            url,
        ]

        log.info(f"Saving to: {dest}")
        result = subprocess.run(cmd)

        if result.returncode != 0:
            raise RuntimeError(f"Download failed for: {url}")

        log.info(f"Downloaded: {dest} ({_human_size(dest.stat().st_size)})")


def _filename_from_url(url: str, index: int) -> str:
    path_part = url.split("?")[0].rstrip("/")
    name = path_part.split("/")[-1]
    if name.endswith(".zip"):
        return name
    return f"takeout-{index:02d}.zip"


def _human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
