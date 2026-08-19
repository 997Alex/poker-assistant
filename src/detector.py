"""Rilevamento carte con YOLO (modello 52 classi, formato 'As', '2c', ...)."""
from __future__ import annotations

from ultralytics import YOLO

DETECTION = dict  # {name, conf, box:(x1,y1,x2,y2)}


def _iou(a: tuple, b: tuple) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter)


class CardDetector:
    """Wrapper sul modello YOLO addestrato sulle carte da gioco."""

    def __init__(self, weights: str, conf: float = 0.6, imgsz: int = 640, device: str = "cpu") -> None:
        self.model = YOLO(weights, task="detect")
        self.model.to(device)
        self.conf = conf
        self.imgsz = imgsz

    def detect(self, img_bgr) -> list[DETECTION]:
        """Rileva le carte in un'immagine BGR.

        Ritorna detezioni deduplicate (box sovrapposti -> solo il piu' fidato).
        """
        res = self.model.predict(
            img_bgr, conf=self.conf, imgsz=self.imgsz, verbose=False, device="cpu"
        )[0]
        boxes = []
        for b in res.boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            boxes.append(
                {
                    "name": res.names[int(b.cls[0])],
                    "conf": float(b.conf[0]),
                    "box": (x1, y1, x2, y2),
                }
            )
        boxes.sort(key=lambda d: d["conf"], reverse=True)
        kept: list[DETECTION] = []
        for d in boxes:
            if all(_iou(d["box"], k["box"]) < 0.5 for k in kept):
                kept.append(d)
        return kept