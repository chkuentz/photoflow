"""
Step 3: Metadata Fix
Reads Google Takeout JSON sidecar files and writes correct EXIF metadata
back into photos using exiftool.

Handles Google's inconsistent sidecar naming:
  - photo.jpg.json
  - photo.json
  - photo.jpg.supplemental-metadata.json
  - photo.jpg.supplemental-metad.json  (truncated variants)
  - photo(1).jpg → photo.jpg(1).json   (numbered duplicates)
  - foo-edited.jpg → foo.json          (edited variants)
"""

import json
import logging
import re
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SUPPLEMENTAL_SUFFIXES = [
    ".supplemental-metadata.json",
    ".supplemental-metadat.json",
    ".supplemental-metada.json",
    ".supplemental-metad.json",
    ".supplemental-meta.json",
    ".supplemental-met.json",
    ".supplemental-me.json",
    ".supplemental-m.json",
    ".supplemental-.json",
    ".supplemental.json",
    ".supplemen.json",
]


def fix_metadata(config: dict) -> None:
    scratch = Path(config["paths"]["scratch"])
    extracted_dir = scratch / config["extract"]["output_dir"]
    exiftool = config["metadata"]["exiftool_path"]
    extensions = config["metadata"]["extensions"]

    if not shutil.which(exiftool):
        raise EnvironmentError(
            f"exiftool not found at '{exiftool}'.\n"
            "Install it with: sudo apt install libimage-exiftool-perl"
        )

    # Find all media files
    media_files = []
    for ext in extensions:
        media_files.extend(extracted_dir.rglob(f"*.{ext}"))
        media_files.extend(extracted_dir.rglob(f"*.{ext.upper()}"))

    log.info(f"Found {len(media_files)} media files to process.")
    fixed = skipped = failed = 0

    for media_path in media_files:
        json_path = _find_sidecar(media_path)
        if not json_path:
            log.debug(f"No sidecar found for: {media_path.name}")
            skipped += 1
            continue

        try:
            metadata = _parse_sidecar(json_path)
            _apply_exiftool(exiftool, media_path, metadata)
            fixed += 1
        except Exception as e:
            log.warning(f"Failed to fix metadata for {media_path.name}: {e}")
            failed += 1

    log.info(f"Metadata: {fixed} fixed, {skipped} skipped (no sidecar), {failed} failed")


def _find_sidecar(media_path: Path) -> Path | None:
    """Try all known Google Takeout sidecar naming patterns."""
    stem = media_path.stem
    name = media_path.name
    parent = media_path.parent

    candidates = [
        # Standard patterns
        parent / f"{name}.json",
        parent / f"{stem}.json",
        # New supplemental-metadata patterns (including truncations)
        *[parent / f"{name}{suffix}" for suffix in SUPPLEMENTAL_SUFFIXES],
        *[parent / f"{stem}{suffix}" for suffix in SUPPLEMENTAL_SUFFIXES],
    ]

    # Handle numbered duplicates: photo(1).jpg → photo.jpg(1).json
    numbered = re.match(r"^(.+)\((\d+)\)(\..+)$", name)
    if numbered:
        base, num, ext = numbered.groups()
        candidates += [
            parent / f"{base}{ext}({num}).json",
            parent / f"{base}({num}).json",
        ]

    # Handle edited variants: photo-edited.jpg → photo.jpg.json
    if "-edited" in stem:
        original_stem = stem.replace("-edited", "")
        candidates += [
            parent / f"{original_stem}{media_path.suffix}.json",
            parent / f"{original_stem}.json",
        ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def _parse_sidecar(json_path: Path) -> dict:
    """Extract useful fields from the Google Takeout JSON sidecar."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    metadata = {}

    # Date taken
    photo_taken = data.get("photoTakenTime", {})
    if photo_taken.get("timestamp"):
        ts = int(photo_taken["timestamp"])
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        metadata["DateTimeOriginal"] = dt.strftime("%Y:%m:%d %H:%M:%S")
        metadata["CreateDate"] = metadata["DateTimeOriginal"]

    # GPS coordinates
    geo = data.get("geoData") or data.get("geoDataExif", {})
    lat = geo.get("latitude", 0.0)
    lon = geo.get("longitude", 0.0)
    alt = geo.get("altitude", 0.0)
    if lat != 0.0 or lon != 0.0:
        metadata["GPSLatitude"] = abs(lat)
        metadata["GPSLatitudeRef"] = "N" if lat >= 0 else "S"
        metadata["GPSLongitude"] = abs(lon)
        metadata["GPSLongitudeRef"] = "E" if lon >= 0 else "W"
        metadata["GPSAltitude"] = alt

    # Description / caption
    desc = data.get("description", "").strip()
    if desc:
        metadata["ImageDescription"] = desc
        metadata["Caption-Abstract"] = desc

    # Title
    title = data.get("title", "").strip()
    if title:
        metadata["Title"] = title

    return metadata


def _apply_exiftool(exiftool: str, media_path: Path, metadata: dict) -> None:
    """Write metadata into the media file using exiftool."""
    if not metadata:
        return

    args = [exiftool, "-overwrite_original", "-q"]
    for tag, value in metadata.items():
        args.append(f"-{tag}={value}")
    args.append(str(media_path))

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
