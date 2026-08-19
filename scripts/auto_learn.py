"""Apprendimento automatico del layout da riga di comando (per debug).

Cattura N frame dallo schermo, rileva le carte con YOLO, costruisce il
layout del tavolo e lo salva come profilo piattaforma.

Uso: .venv/bin/python scripts/auto_learn.py [nome_profilo] [--frames 12] [--monitor 1]
"""
from __future__ import annotations

import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from src.capture import ScreenCapture
from src.detector import CardDetector
from src.table_detector import build_layout, render_preview
from src import profiles

MODEL_PATH = os.path.join(BASE, "models", "poker_best.pt")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    name = args[0] if args else None
    frames = 12
    monitor = 1
    if "--frames" in sys.argv:
        frames = int(sys.argv[sys.argv.index("--frames") + 1])
    if "--monitor" in sys.argv:
        monitor = int(sys.argv[sys.argv.index("--monitor") + 1])

    cap = ScreenCapture(monitor)
    detector = CardDetector(MODEL_PATH, conf=0.4, imgsz=640)
    dets_all = []
    screenshot = None
    screen_size = None
    for i in range(frames):
        img = cap.grab_full()
        if i == 0:
            screenshot = img
            screen_size = list(cap.size)
        dets = detector.detect(img)
        dets_all.append(dets)
        print(f"frame {i + 1}/{frames}: {len(dets)} carte")
        time.sleep(0.6)
    cap.close()

    layout = build_layout(dets_all, screenshot)
    if layout is None:
        print("Layout non riconosciuto: tieni il tavolo in vista e riprova con piu' frame.")
        return 1

    print(f"\nTavolo: {layout.table_rect}")
    print(f"Seggiolini ({len(layout.seats)}):")
    for s in layout.seats:
        role = "HERO" if s["is_hero"] else "opp "
        print(f"  [{role}] {s['rect']}")
    print(f"Board: {layout.board_rect}")
    print(f"Pot:   {layout.pot_rect}")
    print(f"Confidenza: {layout.confidence:.0%}")

    import cv2
    preview = render_preview(screenshot, layout)
    out = os.path.join(BASE, "logs", f"preview_{time.strftime('%Y%m%d_%H%M%S')}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cv2.imwrite(out, preview)
    print(f"Anteprima salvata: {out}")

    if name:
        profiles.complete_profile(name, layout.to_cfg(monitor, screen_size), layout.table_rect)
        print(f"Profilo '{name}' salvato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())