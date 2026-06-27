#!/usr/bin/env python3
"""Config loader for PhotoFlow."""

import yaml
from pathlib import Path


def load_config(path: str = "config.yaml") -> dict:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy config.example.yaml to config.yaml and edit your paths."
        )
    with open(config_path) as f:
        return yaml.safe_load(f)
