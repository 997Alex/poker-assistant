"""Percorsi consapevoli del bundle PyInstaller.

- app_dir(): risorse di sola lettura (modello YOLO) — dentro l'exe se congelato
- user_dir(): dati utente scrivibili (config, profili, log)
    * Windows standalone: %APPDATA%/PokerAssistant
    * Linux dev/standalone: ~/.poker-assistant
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Directory delle risorse in sola lettura (modello, ecc.)."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return BASE


def user_dir() -> str:
    """Directory scrivibile per config, profili e log.

    Windows standalone: %APPDATA%/PokerAssistant
    Linux (dev e standalone): ~/.poker-assistant
    """
    if is_frozen() and os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "PokerAssistant")
    else:
        d = os.path.expanduser("~/.poker-assistant")
    os.makedirs(d, exist_ok=True)
    return d


def config_dir() -> str:
    d = os.path.join(user_dir(), "config")
    os.makedirs(d, exist_ok=True)
    return d


def logs_dir() -> str:
    d = os.path.join(user_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def model_path() -> str:
    return os.path.join(app_dir(), "models", "poker_best.pt")


def bootstrap() -> None:
    """Migra una configurazione legacy dal progetto alla user dir, se manca."""
    from . import profiles
    if profiles.list_profiles():
        return
    src_cfg = os.path.join(BASE, "config", "config.json")
    if os.path.exists(src_cfg):
        import json
        with open(src_cfg) as f:
            cfg = json.load(f)
        profiles.save_profile("default", cfg)
        profiles.set_current("default")