# PhotoFlow 📸

**Google Takeout → Plex** photo pipeline for Ubuntu + Synology NAS.

Automates the full journey from a raw Google Takeout export to a clean, organized Plex photo library:

1. **Download** — Resumable download of 50GB+ Takeout zip(s)
2. **Extract** — Streaming unzip without memory issues
3. **Metadata fix** — Writes correct EXIF dates/GPS back from Google's JSON sidecars (handles all naming quirks)
4. **AI filter** — Flags blurry, low-quality, and sensitive/NSFW photos into a review folder (nothing deleted)
5. **Moments** — Groups photos into date+location folders (like Google's "moments")
6. **Copy** — Rsync to your NAS

---

## Requirements

### System packages (Ubuntu)
```bash
sudo apt update
sudo apt install rclone rsync libimage-exiftool-perl
```

### Authorize rclone with Google (one-time setup)
This lets PhotoFlow download directly from your private Google Drive — no public link needed.

```bash
rclone config
```
Walk through the prompts:
- Choose `n` for new remote
- Name it `google`
- Choose `Google Drive`
- Follow the OAuth browser flow to authorize your account

> **Tip:** Run `rclone ls google:Takeout/` after setup to confirm it can see your Takeout folder.

### Python packages
Ubuntu 23.04+ protects the system Python, so use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Note:** Run `source .venv/bin/activate` each time you open a new terminal before running PhotoFlow.

> **Note:** The AI filtering model (`AdamCodd/vit-base-nsfw-detector`, ~350MB) is downloaded from HuggingFace automatically on first run.

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/chkuentz/photoflow.git
cd photoflow

# 2. Copy and edit the config
cp config.example.yaml config.yaml
nano config.yaml   # Fill in your paths and download URL
```

### Key config values to set in `config.yaml`:

| Key | Example | Description |
|-----|---------|-------------|
| `paths.scratch` | `/mnt/scratch/photoflow` | Local working directory (needs ~2x zip size free) |
| `paths.nas_output` | `/mnt/synology/Photos` | NAS mount point for final output |
| `paths.review` | `/mnt/scratch/photoflow/_review` | Where flagged photos are moved |
| `download.method` | `rclone` | `rclone` (private OAuth) or `wget` (direct URL) |
| `download.rclone_remote` | `google` | Name of your rclone remote (set during `rclone config`) |
| `download.rclone_path` | `Takeout/takeout-001.zip` | Path to zip inside Google Drive |

---

## Usage

### Run the full pipeline
```bash
python3 photoflow.py
```

### Run a specific step (useful for resuming or re-processing)
```bash
python3 photoflow.py --step download
python3 photoflow.py --step extract
python3 photoflow.py --step metadata
python3 photoflow.py --step filter
python3 photoflow.py --step moments
python3 photoflow.py --step copy
```

### Pass the download URL directly
```bash
python3 photoflow.py --url "https://your-takeout-download-link"
```

### Multiple Takeout zips (split exports)
Google often splits large exports across multiple zips. List all paths in `config.yaml`:
```yaml
download:
  method: "rclone"
  rclone_remote: "google"
  rclone_path: "Takeout/takeout-20240101T000000Z-001.zip"
  rclone_paths:
    - "Takeout/takeout-20240101T000000Z-002.zip"
    - "Takeout/takeout-20240101T000000Z-003.zip"
```

### Using a direct download URL instead (wget)
If you prefer a public/signed URL:
```yaml
download:
  method: "wget"
  url: "https://your-takeout-download-link"
  extra_urls:
    - "https://part2-link"
```

---

## Output Structure (Plex-compatible)

```
/mnt/synology/Photos/
├── 2024/
│   ├── 2024-07-04 - Austin, TX/
│   │   ├── IMG_1234.jpg
│   │   └── IMG_1235.jpg
│   ├── 2024-12-25 - Home/
│   └── 2024-08-10/              ← date-only when no GPS
├── 2023/
│   └── ...
└── _review/
    ├── flagged_sensitive/       ← NSFW / private content
    ├── flagged_blurry/          ← blurry or empty shots
    └── flagged_low_quality/     ← tiny files / thumbnails
```

### Adding to Plex
In Plex → **Add Library** → **Photos** → point to `/mnt/synology/Photos`.

Plex will pick up the folder structure automatically. Each subfolder becomes an album.

---

## Review Folder
Nothing is ever deleted. Photos that don't make the cut are moved to `_review/` subdirectories:

| Subfolder | Why photos end up here |
|-----------|------------------------|
| `flagged_sensitive` | NSFW score above threshold, or sensitive content detected |
| `flagged_blurry` | Image too blurry or empty (low Laplacian variance) |
| `flagged_low_quality` | File too small (likely thumbnails or icons) |

You can adjust thresholds in `config.yaml` under the `filter` section.

---

## Handling Google's JSON Quirks

Google Takeout has notoriously inconsistent sidecar file naming. PhotoFlow handles all known variants:

- `photo.jpg.json`
- `photo.jpg.supplemental-metadata.json`
- `photo.jpg.supplemental-metad.json` ← truncated (46-char filename limit)
- `photo(1).jpg` → `photo.jpg(1).json` ← numbered duplicates
- `photo-edited.jpg` → `photo.json` ← edited variants

---

## License

MIT
