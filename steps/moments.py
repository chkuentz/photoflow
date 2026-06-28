"""
Step 5: Group into Moments
Clusters photos by time proximity and GPS location into named "moment" folders,
similar to Google Photos' automatic grouping.

Output structure:
  processed/
    2024/
      2024-07-04 - Austin TX/
      2024-12-25 - Home/
    2023/
      2023-06-10/        ← no GPS data, date-only name
"""

import json
import logging
import math
import shutil
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

log = logging.getLogger(__name__)


def group_into_moments(config: dict) -> None:
    scratch = Path(config["paths"]["scratch"])
    extracted_dir = scratch / config["extract"]["output_dir"]
    processed_dir = scratch / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    extensions = config["metadata"]["extensions"]
    time_gap_hours = config["moments"]["time_gap_hours"]
    distance_km = config["moments"]["distance_km"]
    min_cluster_size = config["moments"]["min_cluster_size"]
    date_fmt = config["moments"]["folder_date_format"]
    exiftool = config["metadata"]["exiftool_path"]

    # Collect all media files
    media_files = []
    for ext in extensions:
        media_files.extend(extracted_dir.rglob(f"*.{ext}"))
        media_files.extend(extracted_dir.rglob(f"*.{ext.upper()}"))

    if not media_files:
        log.warning("No media files found to group.")
        return

    log.info(f"Reading metadata from {len(media_files)} files for moment grouping...")

    # Read EXIF metadata for each file
    file_meta = _read_exif_batch(exiftool, media_files)

    # Sort by date
    file_meta.sort(key=lambda x: x["datetime"] or datetime.min.replace(tzinfo=timezone.utc))

    # Cluster into moments
    clusters = _cluster_by_time_and_location(
        file_meta, time_gap_hours, distance_km
    )

    log.info(f"Formed {len(clusters)} moment clusters.")

    # Name and write clusters to processed/
    placed = 0
    total_files = sum(len(c) for c in clusters)

    with tqdm(total=total_files, desc="Grouping into moments", unit="file", dynamic_ncols=True) as pbar:
        for cluster in clusters:
            folder_name = _name_cluster(cluster, date_fmt, min_cluster_size)
            year = (cluster[0]["datetime"] or datetime.now(tz=timezone.utc)).strftime("%Y")
            dest_dir = processed_dir / year / folder_name
            dest_dir.mkdir(parents=True, exist_ok=True)

            for item in cluster:
                src = item["path"]
                dest = dest_dir / src.name
                if dest.exists():
                    dest = dest_dir / f"{src.stem}_{src.stat().st_ino}{src.suffix}"
                shutil.copy2(str(src), str(dest))
                placed += 1
                pbar.update(1)
                pbar.set_postfix({"moment": folder_name[:30]})

    log.info(f"Grouped {placed} files into {len(clusters)} moment folders in: {processed_dir}")


EXIFTOOL_BATCH_SIZE = 500  # Stay well under OS arg limit


def _read_exif_batch(exiftool: str, paths: list[Path]) -> list[dict]:
    """Use exiftool JSON output to batch-read metadata, avoiding arg list limits."""
    raw = []
    total = len(paths)

    for i in range(0, total, EXIFTOOL_BATCH_SIZE):
        batch = paths[i:i + EXIFTOOL_BATCH_SIZE]
        log.info(f"  Reading EXIF: {min(i + EXIFTOOL_BATCH_SIZE, total)}/{total}")

        result = subprocess.run(
            [exiftool, "-json", "-DateTimeOriginal", "-GPSLatitude", "-GPSLongitude",
             "-n",  # numeric GPS values
             *[str(p) for p in batch]],
            capture_output=True, text=True
        )

        if result.returncode == 0 and result.stdout.strip():
            try:
                raw.extend(json.loads(result.stdout))
            except json.JSONDecodeError:
                log.warning(f"Could not parse exiftool JSON for batch at {i}; skipping.")

    meta_by_path = {item.get("SourceFile"): item for item in raw}

    file_meta = []
    for path in paths:
        raw_item = meta_by_path.get(str(path), {})
        dt = _parse_exif_date(raw_item.get("DateTimeOriginal"))
        if dt is None:
            dt = _date_from_filename(path)

        lat = raw_item.get("GPSLatitude")
        lon = raw_item.get("GPSLongitude")

        file_meta.append({
            "path": path,
            "datetime": dt,
            "lat": float(lat) if lat else None,
            "lon": float(lon) if lon else None,
        })

    return file_meta


def _parse_exif_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _date_from_filename(path: Path) -> datetime | None:
    """Try to extract a date from common filename patterns like IMG_20240704_..."""
    import re
    m = re.search(r"(\d{4})(\d{2})(\d{2})", path.stem)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km between two GPS points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _cluster_by_time_and_location(
    file_meta: list[dict],
    time_gap_hours: float,
    distance_km: float,
) -> list[list[dict]]:
    """Group files into clusters based on time proximity and GPS proximity."""
    if not file_meta:
        return []

    clusters = []
    current_cluster = [file_meta[0]]

    for item in file_meta[1:]:
        prev = current_cluster[-1]

        # Time gap check
        if item["datetime"] and prev["datetime"]:
            gap = abs((item["datetime"] - prev["datetime"]).total_seconds()) / 3600
            time_close = gap < time_gap_hours
        else:
            time_close = True  # No date info; group together

        # Location check
        if (
            item["lat"] and item["lon"] and
            prev["lat"] and prev["lon"]
        ):
            dist = _haversine_km(prev["lat"], prev["lon"], item["lat"], item["lon"])
            loc_close = dist < distance_km
        else:
            loc_close = True  # No GPS; rely on time only

        if time_close and loc_close:
            current_cluster.append(item)
        else:
            clusters.append(current_cluster)
            current_cluster = [item]

    clusters.append(current_cluster)
    return clusters


# Cache geocode results: round to ~5km grid to maximise hits
_geocode_cache: dict[tuple, str | None] = {}
_last_geocode_time: float = 0.0
_GEOCODE_GRID = 0.05   # ~5km rounding
_GEOCODE_RATE  = 1.05  # seconds between Nominatim calls (their limit is 1/s)


def _name_cluster(cluster: list[dict], date_fmt: str, min_cluster_size: int) -> str:
    """
    Generate a human-readable folder name for a moment cluster.
    Tries to reverse-geocode the location using Nominatim (free, no API key).
    Falls back to date-only name.
    """
    anchor = cluster[0]
    dt = anchor["datetime"] or datetime.now(tz=timezone.utc)
    date_str = dt.strftime(date_fmt)

    if len(cluster) >= min_cluster_size and anchor["lat"] and anchor["lon"]:
        location = _reverse_geocode_cached(anchor["lat"], anchor["lon"])
        if location:
            safe_loc = "".join(c if c.isalnum() or c in " -," else "" for c in location)
            safe_loc = safe_loc.strip().rstrip(",")
            return f"{date_str} - {safe_loc}"

    return date_str


def _reverse_geocode_cached(lat: float, lon: float) -> str | None:
    """Cached wrapper around _reverse_geocode. Rounds coords to a ~5km grid."""
    global _last_geocode_time

    key = (round(lat / _GEOCODE_GRID) * _GEOCODE_GRID,
           round(lon / _GEOCODE_GRID) * _GEOCODE_GRID)

    if key in _geocode_cache:
        return _geocode_cache[key]

    # Rate-limit: Nominatim allows max 1 request/second
    elapsed = time.monotonic() - _last_geocode_time
    if elapsed < _GEOCODE_RATE:
        time.sleep(_GEOCODE_RATE - elapsed)

    result = _reverse_geocode(lat, lon)
    _last_geocode_time = time.monotonic()
    _geocode_cache[key] = result
    return result


def _reverse_geocode(lat: float, lon: float) -> str | None:
    """
    Reverse geocode using Nominatim (OpenStreetMap), free and no API key required.
    Returns a short location string like "Austin, TX" or None on failure.
    """
    try:
        import urllib.request
        import urllib.parse

        params = urllib.parse.urlencode({
            "lat": lat,
            "lon": lon,
            "format": "json",
            "zoom": 10,
        })
        url = f"https://nominatim.openstreetmap.org/reverse?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "PhotoFlow/1.0"})

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        addr = data.get("address", {})
        parts = []
        city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet")
        state = addr.get("state")
        if city:
            parts.append(city)
        if state:
            parts.append(_us_state_abbr(state) or state)
        return ", ".join(parts) if parts else None

    except Exception:
        return None


_US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}


def _us_state_abbr(state: str) -> str | None:
    return _US_STATES.get(state)
