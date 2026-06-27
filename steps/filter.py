"""
Step 4: AI Filter
Flags and routes photos to review folders for:
  - Blurry / empty / low-content shots   → _review/flagged_blurry/
  - Sensitive / NSFW content             → _review/flagged_sensitive/
  - Tiny / low-quality files             → _review/flagged_low_quality/

Uses:
  - OpenCV Laplacian variance for blur detection (lightweight, no model needed)
  - AdamCodd/vit-base-nsfw-detector (HuggingFace ViT, ~350MB, free, local)
"""

import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

# Lazy imports so the pipeline can still run other steps if these aren't installed
_cv2 = None
_pil = None
_pipeline = None


def _load_cv2():
    global _cv2
    if _cv2 is None:
        import cv2
        _cv2 = cv2
    return _cv2


def _load_pil():
    global _pil
    if _pil is None:
        from PIL import Image
        _pil = Image
    return _pil


def _load_nsfw_pipeline(model_name: str):
    global _pipeline
    if _pipeline is None:
        log.info(f"Loading NSFW detection model: {model_name}")
        log.info("(First run downloads ~350MB — this may take a few minutes)")
        from transformers import pipeline as hf_pipeline
        _pipeline = hf_pipeline(
            "image-classification",
            model=model_name,
            device=-1,  # CPU; change to 0 for GPU if available
        )
        log.info("NSFW model loaded.")
    return _pipeline


def filter_photos(config: dict) -> None:
    scratch = Path(config["paths"]["scratch"])
    extracted_dir = scratch / config["extract"]["output_dir"]
    extensions = config["metadata"]["extensions"]

    blur_threshold = config["filter"]["blur_threshold"]
    nsfw_threshold = config["filter"]["nsfw_threshold"]
    min_size_kb = config["filter"]["min_size_kb"]
    nsfw_model = config["filter"]["nsfw_model"]

    review_dirs = {
        key: Path(config["paths"]["review"]).parent / val
        for key, val in config["filter"]["review_dirs"].items()
    }
    for d in review_dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    # Find all media files (images only for AI filtering; videos pass through)
    image_exts = {"jpg", "jpeg", "png", "heic"}
    media_files = []
    for ext in extensions:
        if ext.lower() in image_exts:
            media_files.extend(extracted_dir.rglob(f"*.{ext}"))
            media_files.extend(extracted_dir.rglob(f"*.{ext.upper()}"))

    log.info(f"Filtering {len(media_files)} image files...")

    nsfw_pipe = _load_nsfw_pipeline(nsfw_model)

    flagged = {"nsfw": 0, "blurry": 0, "tiny": 0}
    kept = 0

    for img_path in media_files:
        reason = _check_image(
            img_path, blur_threshold, nsfw_threshold, min_size_kb, nsfw_pipe
        )
        if reason:
            dest_dir = review_dirs.get(reason, review_dirs["nsfw"])
            _move_to_review(img_path, dest_dir)
            flagged[reason] = flagged.get(reason, 0) + 1
        else:
            kept += 1

    log.info(
        f"Filter complete: {kept} kept | "
        f"{flagged['nsfw']} sensitive | "
        f"{flagged['blurry']} blurry | "
        f"{flagged['tiny']} low-quality"
    )


def _check_image(
    img_path: Path,
    blur_threshold: float,
    nsfw_threshold: float,
    min_size_kb: int,
    nsfw_pipe,
) -> str | None:
    """Returns the flag reason string, or None if the image is clean."""

    # 1. Size check (fast, no I/O beyond stat)
    size_kb = img_path.stat().st_size / 1024
    if size_kb < min_size_kb:
        return "tiny"

    try:
        cv2 = _load_cv2()
        Image = _load_pil()

        # 2. Blur / empty check using Laplacian variance
        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            log.warning(f"Could not read image: {img_path.name}")
            return None

        variance = cv2.Laplacian(img, cv2.CV_64F).var()
        if variance < blur_threshold:
            return "blurry"

        # 3. NSFW / sensitive content check
        pil_img = Image.open(img_path).convert("RGB")
        results = nsfw_pipe(pil_img)

        # Model returns [{label: "nsfw"/"sfw", score: float}]
        for result in results:
            if result["label"].lower() == "nsfw" and result["score"] >= nsfw_threshold:
                log.info(
                    f"Sensitive: {img_path.name} "
                    f"(score={result['score']:.2f})"
                )
                return "nsfw"

    except Exception as e:
        log.warning(f"Filter error for {img_path.name}: {e}")

    return None


def _move_to_review(src: Path, dest_dir: Path) -> None:
    """Move a flagged photo to the review directory, avoiding overwrites."""
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest_dir / f"{src.stem}_{src.stat().st_ino}{src.suffix}"
    shutil.move(str(src), str(dest))
    log.debug(f"Moved to review: {src.name} → {dest_dir.name}/")
