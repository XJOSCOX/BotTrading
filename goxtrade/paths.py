"""Stable paths shared by UI, workers, and local configuration."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "goxtrade" / "config"
