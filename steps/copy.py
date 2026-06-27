"""
Step 6: Copy to NAS
Copies processed photos to the configured NAS mount point.
Uses rsync for resumable, reliable transfer with progress reporting.
Falls back to shutil for environments without rsync.
"""

import logging
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

log = logging.getLogger(__name__)


def copy_to_nas(config: dict) -> None:
    scratch = Path(config["paths"]["scratch"])
    processed_dir = scratch / "processed"
    nas_output = Path(config["paths"]["nas_output"])
    review_src = Path(config["paths"]["review"])

    use_rsync = config["copy"]["use_rsync"]
    delete_after = config["copy"]["delete_after_copy"]

    if not processed_dir.exists():
        raise FileNotFoundError(
            f"Processed directory not found: {processed_dir}\n"
            "Run the moments step first."
        )

    nas_output.mkdir(parents=True, exist_ok=True)

    # Also copy the review folder so nothing is lost
    review_dest = nas_output / "_review"
    review_dest.mkdir(parents=True, exist_ok=True)

    log.info(f"Copying processed photos → {nas_output}")
    _do_copy(processed_dir, nas_output, use_rsync)

    if review_src.exists():
        log.info(f"Copying review folder → {review_dest}")
        _do_copy(review_src, review_dest, use_rsync)

    if delete_after:
        log.info("Cleaning up scratch processed directory...")
        shutil.rmtree(processed_dir)
        log.info("Scratch cleanup complete.")

    log.info("Copy to NAS complete.")


def _do_copy(src: Path, dest: Path, use_rsync: bool) -> None:
    if use_rsync and shutil.which("rsync"):
        _rsync_copy(src, dest)
    else:
        if use_rsync:
            log.warning("rsync not found — falling back to Python copy.")
        _python_copy(src, dest)


def _rsync_copy(src: Path, dest: Path) -> None:
    """Use rsync for robust, resumable transfer with progress."""
    cmd = [
        "rsync",
        "-av",                    # Archive mode + verbose
        "--progress",             # Per-file progress
        "--partial",              # Keep partial transfers (resumable)
        "--ignore-existing",      # Skip files already at destination
        f"{src}/",                # Trailing slash = copy contents, not folder
        str(dest),
    ]
    log.info(f"rsync: {src} → {dest}")
    result = subprocess.run(cmd)
    if result.returncode not in (0, 23, 24):  # 23/24 = partial transfer warnings
        raise RuntimeError(f"rsync failed with code {result.returncode}")


def _python_copy(src: Path, dest: Path) -> None:
    """Python fallback copy using shutil with basic progress."""
    all_files = list(src.rglob("*"))
    files = [f for f in all_files if f.is_file()]
    total = len(files)
    log.info(f"Copying {total} files...")

    copied = 0
    for file in files:
        rel = file.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(str(file), str(target))
        copied += 1
        if copied % 100 == 0:
            log.info(f"  Progress: {copied}/{total} files")

    log.info(f"Copy complete: {copied} files → {dest}")
