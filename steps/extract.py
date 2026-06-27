"""
Step 2: Extract
Streaming unzip of large Google Takeout archives.
Handles 50GB+ without loading everything into memory.
"""

import logging
import zipfile
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


def extract_zips(config: dict) -> None:
    scratch = Path(config["paths"]["scratch"])
    zip_dir = scratch / config["download"]["zip_dir"]
    output_dir = scratch / config["extract"]["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    zips = sorted(zip_dir.glob("*.zip"))
    if not zips:
        raise FileNotFoundError(
            f"No zip files found in {zip_dir}. "
            "Run the download step first, or place your zip files there manually."
        )

    log.info(f"Found {len(zips)} zip file(s) to extract.")

    for i, zip_path in enumerate(zips, 1):
        log.info(f"Extracting {i}/{len(zips)}: {zip_path.name}")
        _extract_zip(zip_path, output_dir)

    log.info(f"Extraction complete. Files in: {output_dir}")


def _extract_zip(zip_path: Path, dest: Path) -> None:
    """Extract a zip file using streaming to handle large archives."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()
            total = len(members)
            log.info(f"  {total} files to extract from {zip_path.name}")

            for idx, member in enumerate(members, 1):
                target = dest / member.filename

                # Skip if already extracted (allows re-runs)
                if target.exists() and not member.is_dir():
                    continue

                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)

                # Stream extract to avoid memory issues with large files
                with zf.open(member) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, length=1024 * 1024)  # 1MB chunks

                if idx % 500 == 0:
                    log.info(f"  Progress: {idx}/{total} files")

    except zipfile.BadZipFile:
        raise RuntimeError(
            f"Corrupt or incomplete zip: {zip_path.name}. "
            "Re-download this file and try again."
        )
