"""Fine-tuning del modello YOLO11 sulle carte reali della tua piattaforma.

Prerequisito: dataset/crops/ (generato da capture_training.py).
Da eseguire idealmente su Google Colab (GPU); qui funziona su CPU ma e' lento.

Su Colab:
  !pip install ultralytics
  !cp -r dataset crops_poker (upload i crop)
  !python finetune.py --crops crops_poker --epochs 30
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

LABELS = ["2C","2D","2H","2S","3C","3D","3H","3S","4C","4D","4H","4S",
          "5C","5D","5H","5S","6C","6D","6H","6S","7C","7D","7H","7S",
          "8C","8D","8H","8S","9C","9D","9H","9S","10C","10D","10H","10S",
          "JC","JD","JH","JS","QC","QD","QH","QS","KC","KD","KH","KS",
          "AC","AD","AH","AS"]


def build_dataset(crops_dir: str, out_dir: str, val_split: float = 0.15) -> str:
    """Converte i crop in formato YOLO (images + labels) e crea data.yaml."""
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    for split in ("train", "val"):
        os.makedirs(os.path.join(out_dir, "images", split), exist_ok=True)
        os.makedirs(os.path.join(out_dir, "labels", split), exist_ok=True)

    rng = random.Random(42)
    total = 0
    for cls_name in LABELS:
        folder = os.path.join(crops_dir, cls_name)
        if not os.path.isdir(folder):
            continue
        files = [f for f in os.listdir(folder) if f.endswith(".png")]
        rng.shuffle(files)
        n_val = max(1, int(len(files) * val_split))
        for i, f in enumerate(files):
            split = "val" if i < n_val else "train"
            src = os.path.join(folder, f)
            dst_img = os.path.join(out_dir, "images", split, f"{cls_name}_{i}.png")
            shutil.copy(src, dst_img)
            label = f"{LABELS.index(cls_name)} 0.5 0.5 1.0 1.0\n"
            dst_lbl = os.path.join(out_dir, "labels", split, f"{cls_name}_{i}.txt")
            with open(dst_lbl, "w") as lf:
                lf.write(label)
            total += 1
    if total == 0:
        raise SystemExit(f"Nessun crop in {crops_dir}: prima lancia capture_training.py")

    yaml_path = os.path.join(out_dir, "data.yaml")
    with open(yaml_path, "w") as f:
        f.write(f"path: {os.path.abspath(out_dir)}\n")
        f.write("train: images/train\nval: images/val\n")
        f.write(f"names: {LABELS}\n")
    print(f"Dataset pronto: {total} immagini in {out_dir}")
    return yaml_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crops", default=os.path.join(BASE, "dataset", "crops"))
    ap.add_argument("--out", default=os.path.join(BASE, "dataset", "yolo"))
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--weights", default=os.path.join(BASE, "models", "poker_best.pt"))
    ap.add_argument("--val-split", type=float, default=0.15)
    args = ap.parse_args()

    yaml_path = build_dataset(args.crops, args.out, args.val_split)

    from ultralytics import YOLO
    model = YOLO(args.weights)
    model.train(data=yaml_path, epochs=args.epochs, imgsz=args.imgsz,
                batch=16, device="cpu")
    best = os.path.join(args.out, "runs", "detect", "train", "weights", "best.pt")
    if os.path.exists(best):
        dst = os.path.join(BASE, "models", "poker_best_ft.pt")
        shutil.copy(best, dst)
        print("Modello fine-tunato salvato in", dst)


if __name__ == "__main__":
    main()