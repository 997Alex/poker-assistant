"""Rilevamento automatico del layout del tavolo (scenario learning).

Il programma impara la disposizione di una piattaforma sconosciuta:
- tavolo: segmentazione HSV del feltro verde -> ellisse (cv2.fitEllipse)
- seggiolini: clustering delle carte rilevate da YOLO su piu' frame
- board: cluster centrale (vicino al centro dell'ellisse)
- pot: area sotto il board (per OCR)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

# Intervalli HSV tipici del feltro dei client poker (configurabili)
GREEN_RANGES: list[tuple[tuple, tuple]] = [
    ((35, 40, 40), (85, 255, 255)),    # verde classico
    ((30, 30, 30), (95, 255, 255)),    # verde scuro/chiaro
    ((20, 60, 40), (45, 255, 255)),    # verde oliva / marrone-verde
    ((95, 40, 40), (135, 255, 255)),   # blu/azzurro (alcuni skin)
    ((170, 40, 40), (185, 255, 255)),  # rosso bordeaux (alcuni tavoli VIP)
]


@dataclass
class Layout:
    """Layout imparato di un tavolo, in coordinate schermo."""

    table_rect: tuple  # (x, y, w, h)
    seats: list[dict]  # [{"label", "is_hero", "rect": [x,y,w,h]}]
    board_rect: tuple
    pot_rect: tuple | None
    confidence: float

    def to_cfg(self, monitor: int, screen_size: list[int], name: str = "") -> dict:
        cfg = {
            "name": name,
            "monitor": monitor,
            "screen_size": screen_size,
            "seats": self.seats,
            "board_rect": list(self.board_rect),
        }
        if self.pot_rect:
            cfg["pot_rect"] = list(self.pot_rect)
        return cfg


def detect_table(img_bgr: np.ndarray) -> tuple | None:
    """Trova il rettangolo del tavolo: maschera colore -> contorno maggiore -> ellisse.

    Ritorna ((x, y, w, h), (cx, cy, rx, ry, angle)) o None se non trovato.
    Centro e raggi derivano dal bounding rect del contorno (robusto rispetto
    all'angolo restituito da cv2.fitEllipse, che puo' scambiare gli assi).
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for low, high in GREEN_RANGES:
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(low), np.array(high)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    best = max(contours, key=cv2.contourArea)
    if cv2.contourArea(best) < 0.02 * mask.size:
        return None
    rect = cv2.boundingRect(best)
    cx = rect[0] + rect[2] / 2.0
    cy = rect[1] + rect[3] / 2.0
    rx, ry = rect[2] / 2.0, rect[3] / 2.0
    return rect, (cx, cy, rx, ry, 0.0)


def _guess_seats(table_rect: tuple, card_w: float, card_h: float) -> int:
    """Stima il numero di seggiolini dalla dimensione del tavolo."""
    tw, th = table_rect[2], table_rect[3]
    perimeter = np.pi * (tw + th) / 2.0
    seat_space = max(card_w * 2.2, card_h * 1.6, 120.0)
    n = int(round(perimeter / seat_space))
    return max(2, min(n, 9))


def _geometric_seats(cx: float, cy: float, rx: float, ry: float, n: int) -> list[dict]:
    """Seggiolini equidistanti sulla circonferenza dell'ellisse, hero in basso."""
    seats = []
    # angoli: 90 gradi = sotto (hero), poi in senso orario; si salta l'angolo
    # del fondo solo se n lo richiede, cosi' l'hero resta ben visibile.
    angles = np.linspace(90, 90 + 360, n + 1)[:n]  # va da 90 in giu' in senso orario
    card_w = max(60, int(rx * 0.14))
    card_h = max(84, int(ry * 0.20))
    for i, deg in enumerate(angles):
        rad = np.deg2rad(deg)
        sx = cx + rx * np.cos(rad)
        sy = cy + ry * np.sin(rad)
        seat_rect = (int(sx - card_w * 1.1), int(sy - card_h * 0.7),
                     int(card_w * 2.2), int(card_h * 1.6))
        hero = i == 0  # il primo angolo (90deg) e' in basso
        seats.append({
            "label": "Hero (tu)" if hero else "Seggiolino",
            "is_hero": hero,
            "rect": list(seat_rect),
        })
    return seats


def _board_from_geometry(table_rect: tuple, cx: float, cy: float, ry: float,
                         card_w: float, card_h: float) -> tuple:
    tw, th = table_rect[2], table_rect[3]
    bw = max(120, int(tw * 0.28))
    bh = max(84, int(card_h * 1.1))
    x = int(cx - bw / 2)
    y = int(cy - bh / 2)
    return (x, y, bw, bh)


def _pot_from_geometry(cx: float, cy: float, ry: float, board_rect: tuple, h: int) -> tuple:
    bw, bh = board_rect[2], board_rect[3]
    pw, ph = int(bw * 1.35), int(bh * 0.7)
    y = min(int(cy + ry * 0.30), h - ph - 4)
    return (int(cx - pw / 2), y, pw, ph)


def _cluster_centers(points: np.ndarray, eps: float) -> list[np.ndarray]:
    """Raggruppa punti vicini (region growing semplice, senza sklearn)."""
    points = list(points)
    clusters: list[list[np.ndarray]] = []
    for p in points:
        best_idx = None
        best_d = eps
        for i, c in enumerate(clusters):
            d = np.linalg.norm(p - np.mean(c, axis=0))
            if d < best_d:
                best_idx, best_d = i, d
        if best_idx is None:
            clusters.append([p])
        else:
            clusters[best_idx].append(p)
    # merge cluster vicini tra loro
    merged = True
    while merged:
        merged = False
        out: list[list[np.ndarray]] = []
        used = [False] * len(clusters)
        for i, a in enumerate(clusters):
            if used[i]:
                continue
            group = list(a)
            for j in range(i + 1, len(clusters)):
                if used[j]:
                    continue
                ca, cb = np.mean(a, axis=0), np.mean(clusters[j], axis=0)
                if np.linalg.norm(ca - cb) < eps:
                    group.extend(clusters[j])
                    used[j] = True
                    merged = True
            out.append(group)
        clusters = out
    return [np.mean(c, axis=0) for c in clusters]


def build_layout(
    frame_dets: list[list[dict]],
    img_bgr: np.ndarray,
    table: tuple | None = None,
    min_frames: int = 8,
) -> Layout | None:
    """Costruisce il layout da detezioni raccolte su piu' frame.

    frame_dets: lista (una per frame) di detezioni con "box" e "conf".
    img_bgr: screenshot (uno qualsiasi) per la rilevazione del tavolo.
    """
    h, w = img_bgr.shape[:2]
    if table is None:
        table = detect_table(img_bgr)
    if table is None:
        return None

    rect, (tcx, tcy, trx, try_, angle) = table

    # raccogli centri e box di tutte le carte
    centers: list[np.ndarray] = []
    boxes: list[tuple] = []
    confs: list[float] = []
    for dets in frame_dets:
        for d in dets:
            x1, y1, x2, y2 = d["box"]
            centers.append(np.array([(x1 + x2) / 2.0, (y1 + y2) / 2.0]))
            boxes.append((x1, y1, x2, y2))
            confs.append(float(d.get("conf", 0.5)))

    # Card stimate per il caso "poche/zero carte rilevate":
    # le usiamo per dimensionare seggiolini e board in modo geometrico.
    est_card_w = max(50, int(trx * 0.14))
    est_card_h = max(70, int(try_ * 0.20))
    if centers:
        boxes_arr = np.array(boxes)
        est_card_w = max(est_card_w, int(np.median(boxes_arr[:, 2] - boxes_arr[:, 0])))
        est_card_h = max(est_card_h, int(np.median(boxes_arr[:, 3] - boxes_arr[:, 1])))
    else:
        boxes_arr = np.zeros((0, 4))

    # Zero carte rilevate: seggiolini geometrici sull'ellisse (stima 6-max).
    if not centers:
        n_geo = _guess_seats(rect, est_card_w, est_card_h)
        geo = _geometric_seats(tcx, tcy, trx, try_, n_geo)
        board_rect = _board_from_geometry(rect, tcx, tcy, try_, est_card_w, est_card_h)
        pot_rect = _pot_from_geometry(tcx, tcy, try_, board_rect, h)
        return Layout(
            table_rect=tuple(int(v) for v in rect),
            seats=geo,
            board_rect=board_rect,
            pot_rect=pot_rect,
            confidence=0.35,
        )

    centers_arr = np.array(centers)
    med_w = float(np.median(boxes_arr[:, 2] - boxes_arr[:, 0]))
    med_h = float(np.median(boxes_arr[:, 3] - boxes_arr[:, 1]))
    eps = max(med_w * 1.4, med_h * 1.2, 30.0)

    clusters = _cluster_centers(centers_arr, eps)

    # Se ci sono carte ma non bastano a fare i cluster dei seggiolini,
    # usa i seggiolini geometrici sull'ellisse (default 6-max).
    if len(clusters) < 2:
        n_geo = _guess_seats(rect, med_w, med_h)
        geo = _geometric_seats(tcx, tcy, trx, try_, n_geo)
        board_rect = _board_from_geometry(rect, tcx, tcy, try_, med_w, med_h)
        pot_rect = _pot_from_geometry(tcx, tcy, try_, board_rect, h)
        return Layout(
            table_rect=tuple(int(v) for v in rect),
            seats=geo,
            board_rect=board_rect,
            pot_rect=pot_rect,
            confidence=0.45,
        )

    # il cluster piu' vicino al centro del tavolo = board
    dists = [np.linalg.norm(c - np.array([tcx, tcy])) for c in clusters]
    board_idx = int(np.argmin(dists))
    board_center = clusters[board_idx]

    # box board = bbox di tutte le carte del cluster board
    board_mask = np.linalg.norm(centers_arr - board_center, axis=1) < eps
    bbox = boxes_arr[board_mask]
    if len(bbox) == 0:
        return None
    bx1, by1 = bbox[:, 0].min(), bbox[:, 1].min()
    bx2, by2 = bbox[:, 2].max(), bbox[:, 3].max()
    pad = max(6, int(med_h * 0.12))
    board_rect = (int(bx1 - pad), int(by1 - pad), int(bx2 - bx1 + 2 * pad), int(by2 - by1 + 2 * pad))

    # seggiolini = gli altri cluster, validati sulla circonferenza dell'ellisse
    seats: list[dict] = []
    radius = (trx + try_) / 2.0
    for i, c in enumerate(clusters):
        if i == board_idx:
            continue
        d_edge = abs(np.linalg.norm(c - np.array([tcx, tcy])) - radius)
        if d_edge > radius * 0.55:
            continue
        mask = np.linalg.norm(centers_arr - c, axis=1) < eps
        sb = boxes_arr[mask]
        if len(sb) == 0:
            continue
        sx1, sy1 = sb[:, 0].min(), sb[:, 1].min()
        sx2, sy2 = sb[:, 2].max(), sb[:, 3].max()
        sw, sh = sx2 - sx1, sy2 - sy1
        seat_rect = (
            int(c[0] - sw * 1.1), int(c[1] - sh * 0.7),
            int(sw * 2.2), int(sh * 1.6),
        )
        seats.append({"label": "Seggiolino", "is_hero": False, "rect": list(seat_rect)})
    if not seats:
        return None

    # hero = seggiolino piu' vicino al bordo inferiore dello schermo
    bottom_idx = max(range(len(seats)), key=lambda i: seats[i]["rect"][1] + seats[i]["rect"][3])
    seats[bottom_idx]["is_hero"] = True
    seats[bottom_idx]["label"] = "Hero (tu)"

    # area pot: sotto il centro del board
    pw, ph = board_rect[2] * 1.35, board_rect[3] * 0.7
    pot_rect = (
        int(tcx - pw / 2),
        min(int(tcy + try_ * 0.35), h - int(ph) - 4),
        int(pw),
        int(ph),
    )

    # confidenza: frequenza e qualita' delle detezioni sui seggiolini
    seat_conf = float(np.mean(confs)) if confs else 0.0
    frames_with_cards = sum(1 for dets in frame_dets if dets)
    coverage = frames_with_cards / max(1, len(frame_dets))
    confidence = min(1.0, seat_conf * coverage * 2.0)

    return Layout(
        table_rect=tuple(int(v) for v in rect),
        seats=seats,
        board_rect=board_rect,
        pot_rect=pot_rect,
        confidence=confidence,
    )


def render_preview(img_bgr: np.ndarray, layout: Layout) -> np.ndarray:
    """Disegna il layout proposto sullo screenshot (per conferma)."""
    out = img_bgr.copy()
    colors = {"hero": (0, 200, 0), "opp": (0, 160, 255), "board": (255, 150, 0)}
    for s in layout.seats:
        x, y, w, h = s["rect"]
        c = colors["hero"] if s["is_hero"] else colors["opp"]
        cv2.rectangle(out, (x, y), (x + w, y + h), c, 3)
        cv2.putText(out, s["label"], (x + 4, y + 20), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, c, 2, cv2.LINE_AA)
    bx, by, bw, bh = layout.board_rect
    cv2.rectangle(out, (bx, by), (bx + bw, by + bh), colors["board"], 3)
    cv2.putText(out, "Board", (bx + 4, by + 20), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, colors["board"], 2, cv2.LINE_AA)
    if layout.pot_rect:
        px, py, pw, ph = layout.pot_rect
        cv2.rectangle(out, (px, py), (px + pw, py + ph), (255, 80, 200), 2)
        cv2.putText(out, "Pot", (px + 4, py + 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 80, 200), 2, cv2.LINE_AA)
    tx, ty, tw, th = layout.table_rect
    cv2.rectangle(out, (tx, ty), (tx + tw, ty + th), (255, 255, 255), 1)
    return out