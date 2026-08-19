"""Gestione profili per piattaforma (888, sisal, play-money, ...).

Ogni profilo e' un config.json salvato in config/profiles/<nome>.json.
La selezione automatica confronta la firma dello schermo (monitor +
risoluzione + posizione del tavolo rilevata) con i profili salvati.
"""
from __future__ import annotations

import json
import os

from src.paths import BASE, config_dir, is_frozen

PROFILES_DIR = os.path.join(config_dir(), "profiles")
LEGACY_PATH = os.path.join(config_dir(), "config.json")
CURRENT_PATH = os.path.join(config_dir(), "current.json")

DEFAULT_SETTINGS = {
    "fps": 5,
    "conf_threshold": 0.6,
    "mc_iterations": 30000,
    "imgsz": 640,
    "use_ocr": False,
    "position": "middle",
    "open_tiers": {"early": 7, "middle": 6, "late": 5, "blind": 6},
    "raise_equity_threshold": 0.62,
    "fold_margin": 0.03,
    "raise_threshold": 0.60,
    "bet_pct": 0.66,
    "opponent_ranges": {"tight": "tight10", "loose": "loose25", "aggressive": "loose50"},
    "adapt_seats": True,
    "adapt_hands": 10,
}


def list_profiles() -> list[str]:
    if not os.path.isdir(PROFILES_DIR):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(PROFILES_DIR)
        if f.endswith(".json") and not f.startswith("_")
    )


def profile_path(name: str) -> str:
    return os.path.join(PROFILES_DIR, f"{name}.json")


def load_profile(name: str) -> dict:
    with open(profile_path(name)) as f:
        cfg = json.load(f)
    cfg["name"] = name
    cfg.setdefault("settings", dict(DEFAULT_SETTINGS))
    return cfg


def save_profile(name: str, cfg: dict) -> str:
    os.makedirs(PROFILES_DIR, exist_ok=True)
    cfg = dict(cfg)
    cfg["name"] = name
    cfg.setdefault("settings", dict(DEFAULT_SETTINGS))
    path = profile_path(name)
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return path


def delete_profile(name: str) -> None:
    path = profile_path(name)
    if os.path.exists(path):
        os.remove(path)


def get_current() -> str | None:
    if os.path.exists(CURRENT_PATH):
        try:
            with open(CURRENT_PATH) as f:
                return json.load(f).get("name")
        except Exception:  # noqa: BLE001
            return None
    return None


def set_current(name: str) -> None:
    with open(CURRENT_PATH, "w") as f:
        json.dump({"name": name}, f)


def migrate_legacy() -> str | None:
    """Sposta config/config.json nel profilo 'default' se esiste ancora."""
    if not os.path.exists(LEGACY_PATH):
        return None
    with open(LEGACY_PATH) as f:
        cfg = json.load(f)
    save_profile("default", cfg)
    os.rename(LEGACY_PATH, LEGACY_PATH + ".backup")
    set_current("default")
    return "default"


def match_profile(monitor: int, screen_size: list[int], table_rect: tuple | None) -> str | None:
    """Sceglie il profilo che combacia con lo schermo attuale.

    La firma: stesso monitor, stessa risoluzione e (se possibile) tavolo
    con centro a meno del 6% dello schermo dal centro salvato.
    """
    best, best_score = None, -1.0
    for name in list_profiles():
        try:
            cfg = load_profile(name)
        except Exception:  # noqa: BLE001
            continue
        if cfg.get("monitor") != monitor:
            continue
        if list(cfg.get("screen_size", [])) != list(screen_size):
            continue
        score = 0.5
        if table_rect is not None:
            tx, ty, tw, th = table_rect
            cur = (tx + tw / 2, ty + th / 2)
            saved = cfg.get("table_center")
            if saved:
                dx = abs(cur[0] - saved[0]) / max(1, screen_size[0])
                dy = abs(cur[1] - saved[1]) / max(1, screen_size[1])
                if max(dx, dy) <= 0.06:
                    score = 1.0 - (dx + dy)
                else:
                    continue
        if score > best_score:
            best, best_score = name, score
    return best


def complete_profile(name: str, cfg: dict, table_rect: tuple | None) -> None:
    """Salva il profilo e registra la firma del tavolo per l'auto-selezione."""
    if table_rect:
        tx, ty, tw, th = table_rect
        cfg["table_center"] = [tx + tw / 2, ty + th / 2]
    save_profile(name, cfg)
    set_current(name)