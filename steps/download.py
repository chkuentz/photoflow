"""
Step 1: Download
Handles resumable download of Google Takeout zip(s) using wget.
Supports single URL or multiple URLs for split exports.
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

    urls = []
    primary = config["download"].get("url", "").strip()
    if primary:
        urls.append(primary)
    extras = config["download"].get("extra_urls", []) or []
    urls.extend([u for u in extras if u.strip()])

    if not urls:
        raise ValueError(
            "No download URL configured. Set download.url in config.yaml "
            "or pass --url on the command line."
        )

    if not shutil.which("wget"):
        raise EnvironmentError(
            "wget not found. Install it with: sudo apt install wget"
        )

    for i, url in enumerate(urls, 1):
        log.info(f"Downloading zip {i}/{len(urls)}: {url}")
        filename = _filename_from_url(url, i)
        dest = zip_dir / filename

        cmd = [
            "wget",
            "--continue",          # Resume partial downloads
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
    """Extract a filename from URL or generate a fallback."""
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
