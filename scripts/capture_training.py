"""Cattura i crop delle carte rilevate a schermo per il fine-tuning del modello.

Uso: python scripts/capture_training.py [--min-conf 0.5] [--out dataset/crops]
Salva ogni carta rilevata in dataset/crops/{NomeCarta}/*.png (1 crop ogni 5 frame
per evitare duplicati). Il fine-tuning si lancia poi con scripts/finetune.py
"""
from __future__ import annotations

import argparse
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import cv2  # noqa: E402

from src.capture import ScreenCapture  # noqa: E402
from src.detector import CardDetector  # noqa: E402

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--out", default=os.path.join(BASE, "dataset", "crops"))
    ap.add_argument("--seconds", type=float, default=0, help="0 = illimitato")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    cap = ScreenCapture(1)
    det = CardDetector(os.path.join(BASE, "models", "poker_best.pt"),
                       conf=args.min_conf, imgsz=640)
    print("Cattura attiva: gioca una partita e lascia che le carte passino sotto la finestra.")
    print("CTRL+C per fermare. Salvataggio in", args.out)

    last_save = {}
    t0 = time.time()
    try:
        while True:
            img = cap.grab_full()
            dets = det.detect(img)
            for d in dets:
                name = d["name"]
                x1, y1, x2, y2 = [int(v) for v in d["box"]]
                m = 4
                crop = img[max(0, y1 - m):y2 + m, max(0, x1 - m):x2 + m]
                if crop.size == 0:
                    continue
                now = time.time()
                if now - last_save.get(name, 0) < 1.0:
                    continue
                last_save[name] = now
                folder = os.path.join(args.out, name)
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, f"{int(now * 1000)}.png")
                cv2.imwrite(path, crop)
                print(f"salvata {name} -> {path}")
            if args.seconds and time.time() - t0 > args.seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cap.close()
    print("Fine cattura.")

if __name__ == "__main__":
    main()