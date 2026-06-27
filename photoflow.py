#!/usr/bin/env python3
"""
PhotoFlow - Google Takeout to Plex Pipeline
Orchestrates: download → extract → metadata fix → AI filter → moment grouping → copy to NAS
"""

import argparse
import logging
import sys
from pathlib import Path

from steps.download import download_takeout
from steps.extract import extract_zips
from steps.metadata import fix_metadata
from steps.filter import filter_photos
from steps.moments import group_into_moments
from steps.copy import copy_to_nas
from config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("photoflow.log"),
    ],
)
log = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="PhotoFlow: Google Takeout → Plex pipeline"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument(
        "--step",
        choices=["download", "extract", "metadata", "filter", "moments", "copy", "all"],
        default="all",
        help="Run a specific step or all steps (default: all)",
    )
    parser.add_argument(
        "--url", help="Direct download URL for the Google Takeout zip (overrides config)"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)

    if args.url:
        config["download"]["url"] = args.url

    log.info("=== PhotoFlow Starting ===")
    log.info(f"Scratch dir : {config['paths']['scratch']}")
    log.info(f"NAS output  : {config['paths']['nas_output']}")
    log.info(f"Review dir  : {config['paths']['review']}")

    step = args.step

    try:
        if step in ("download", "all"):
            log.info("--- Step 1: Download ---")
            download_takeout(config)

        if step in ("extract", "all"):
            log.info("--- Step 2: Extract ---")
            extract_zips(config)

        if step in ("metadata", "all"):
            log.info("--- Step 3: Fix Metadata ---")
            fix_metadata(config)

        if step in ("filter", "all"):
            log.info("--- Step 4: AI Filter ---")
            filter_photos(config)

        if step in ("moments", "all"):
            log.info("--- Step 5: Group into Moments ---")
            group_into_moments(config)

        if step in ("copy", "all"):
            log.info("--- Step 6: Copy to NAS ---")
            copy_to_nas(config)

    except KeyboardInterrupt:
        log.warning("PhotoFlow interrupted by user.")
        sys.exit(1)
    except Exception as e:
        log.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)

    log.info("=== PhotoFlow Complete ===")


if __name__ == "__main__":
    main()
