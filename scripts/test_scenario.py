"""Test dello scenario learning: tavolo sintetico, profili, auto-adeguamento.

Uso: .venv/bin/python scripts/test_scenario.py
"""
from __future__ import annotations

import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import cv2
import numpy as np


def make_synthetic_table(w=1920, h=1080, seats_n=6, board_cards=3) -> tuple:
    """Disegna un tavolo verde a ellisse con carte bianche sui seggiolini e board."""
    img = np.full((h, w, 3), 40, dtype=np.uint8)

    # ellisse del tavolo (feltro verde)
    cx, cy = w // 2, h // 2
    rx, ry = int(w * 0.36), int(h * 0.30)
    cv2.ellipse(img, (cx, cy), (rx, ry), 0, 0, 360, (30, 120, 60), -1)
    cv2.ellipse(img, (cx, cy), (rx, ry), 0, 0, 360, (50, 150, 80), 4)

    # centro board: rettangoli carte bianchi
    board_rects = []
    card_w, card_h = 96, 136
    for k in range(board_cards):
        x = cx + (k - 1) * (card_w + 10) - card_w // 2
        y = cy - card_h // 2
        cv2.rectangle(img, (x, y), (x + card_w, y + card_h), (240, 240, 240), -1)
        cv2.rectangle(img, (x, y), (x + card_w, y + card_h), (120, 60, 60), 3)
        board_rects.append((x, y, x + card_w, y + card_h))

    # seggiolini: carte lungo la circonferenza (escludendo il fondo dove va l'hero)
    seat_boxes = []
    angles = np.linspace(180, 540, seats_n + 1)[:seats_n]  # 180..360 = giro completo senza fondo
    for k, deg in enumerate(angles):
        rad = np.deg2rad(deg)
        sx = int(cx + rx * np.cos(rad))
        sy = int(cy + ry * np.sin(rad))
        # due carte per seggiolino
        x = sx - card_w
        for j in range(2):
            xx = x + j * (card_w + 4) + (card_w // 2 if j else 0) - card_w // 2
            yy = sy - card_h // 2
            cv2.rectangle(img, (xx, yy), (xx + card_w, yy + card_h), (230, 230, 230), -1)
            cv2.rectangle(img, (xx, yy), (xx + card_w, yy + card_h), (60, 60, 120), 3)
            seat_boxes.append((xx, yy, xx + card_w, yy + card_h))

    dets = [{"name": "As", "conf": 0.9, "box": b} for b in board_rects + seat_boxes]
    return img, dets, cx, cy, rx, ry


def test_layout() -> int:
    from src.table_detector import build_layout, detect_table, render_preview

    img, dets, cx, cy, rx, ry = make_synthetic_table()
    trect = detect_table(img)
    assert trect is not None, "tavolo non rilevato"
    rect, ellipse = trect
    assert abs(ellipse[0] - cx) < 60 and abs(ellipse[1] - cy) < 60, "centro ellisse errato"

    frame_dets = [dets for _ in range(15)]
    layout = build_layout(frame_dets, img, table=trect)
    assert layout is not None, "layout non costruito"
    assert len(layout.seats) >= 5, f"attesi ~6 seggiolini, trovati {len(layout.seats)}"
    assert layout.board_rect[2] > 0 and layout.board_rect[3] > 0
    hero = [s for s in layout.seats if s["is_hero"]]
    assert len(hero) == 1, "serve un solo Hero"
    assert layout.pot_rect is not None

    prev = render_preview(img, layout)
    assert prev.shape == img.shape

    cfg = layout.to_cfg(1, [img.shape[1], img.shape[0]], "test")
    assert cfg["seats"] and cfg["board_rect"] and cfg["monitor"] == 1
    print(f"TEST LAYOUT OK: {len(layout.seats)} seggiolini, confidenza {layout.confidence:.0%}, board {layout.board_rect}")
    return 0


def test_profiles() -> int:
    from src import profiles

    tmp = tempfile.mkdtemp()
    profiles.PROFILES_DIR = tmp
    img, dets, *_ = make_synthetic_table()
    from src.table_detector import build_layout, detect_table

    trect = detect_table(img)
    layout = build_layout([dets] * 10, img, table=trect)
    cfg = layout.to_cfg(1, [1920, 1080], "sisal")
    path = profiles.save_profile("sisal", cfg)
    assert os.path.exists(path)
    loaded = profiles.load_profile("sisal")
    assert loaded["name"] == "sisal" and loaded["board_rect"]
    assert "sisal" in profiles.list_profiles()

    profiles.complete_profile("sisal", cfg, layout.table_rect)
    assert profiles.get_current() == "sisal"
    match = profiles.match_profile(1, [1920, 1080], layout.table_rect)
    assert match == "sisal", f"auto-match fallito: {match}"
    assert profiles.match_profile(1, [1024, 768], None) is None, "risoluzione diversa non deve combaciare"
    print("TEST PROFILI OK: salva/carica/auto-match funzionano")
    return 0


def test_adapt() -> int:
    from src.main import PokerAssistant
    import tempfile

    img, dets, *_ = make_synthetic_table()
    from src.table_detector import build_layout, detect_table

    trect = detect_table(img)
    layout = build_layout([dets] * 10, img, table=trect)
    cfg = layout.to_cfg(1, [1920, 1080], "adapt")
    cfg["settings"] = {"adapt_seats": True, "adapt_hands": 5, "conf_threshold": 0.6,
                       "imgsz": 640, "fps": 5, "mc_iterations": 3000}
    cfg["settings"].update({"position": "middle", "open_tiers": {}, "raise_equity_threshold": 0.62,
                            "fold_margin": 0.03, "raise_threshold": 0.6, "bet_pct": 0.66,
                            "opponent_ranges": {}})

    # simuliamo l'assistente con un oggetto leggero (senza QApplication: test della logica)
    from src import profiles as pr
    pr.PROFILES_DIR = tempfile.mkdtemp()
    pr.save_profile("adapt", cfg)
    cfg = pr.load_profile("adapt")

    class FakeHud:
        def set_profile_status(self, n): pass
        def pot_values(self): return (100, 20)
        def position(self): return "middle"
        def limpers(self): return 0
        def set_equity(self, *a, **k): pass
        def set_action(self, *a): pass
        def set_hand_analysis(self, *a): pass
        def set_hand(self, *a): pass
        def set_running(self, *a): pass
        def set_pot_values(self, *a): pass

    a = PokerAssistant.__new__(PokerAssistant)
    a.cfg = cfg
    a.seats = cfg["seats"]
    a.hero_seat = 0
    a.state = None
    a._last_hand_for_adapt = 1
    a._seat_samples = {i: [(30.0, 5.0)] * 20 for i in range(len(a.seats))}
    a._seat_moves = {}
    a._log = type("L", (), {"log": lambda *x, **k: None})()

    before = [s["rect"][0] for s in a.seats]
    a.state = type("S", (), {"hand_number": 6})()
    a._maybe_adapt_seats()
    after = [s["rect"][0] for s in a.seats]
    assert after[0] > before[0], "il seggiolino deve spostarsi verso +30px (cap a 12)"
    assert abs((after[0] - before[0]) - 12.0) < 1.5, "spostamento deve essere limitato a 12px"
    a._seat_samples = {i: [(30.0, 5.0)] * 20 for i in range(len(a.seats))}
    a._last_hand_for_adapt = 1
    a.state = type("S", (), {"hand_number": 11})()
    a._maybe_adapt_seats()
    assert a._seat_moves[0] >= 1, "seconda correzione ammessa (max 3)"
    print("TEST AUTO-ADEGUAMENTO OK: spostamento limitato e progressivo")
    return 0


def test_geometric_fallback() -> int:
    """Senza carte rilevate il layout si genera geometricamente (stima 6-max)."""
    from src.table_detector import build_layout, detect_table

    img = np.full((1080, 1920, 3), 40, dtype=np.uint8)
    cv2.ellipse(img, (960, 540), (680, 320), 0, 0, 360, (30, 120, 60), -1)
    trect = detect_table(img)
    assert trect is not None, "tavolo verde non rilevato"
    layout = build_layout([[]], img, table=trect)
    assert layout is not None, "fallback geometrico non attivato"
    assert len(layout.seats) >= 2, f"attesi seggiolini, trovati {len(layout.seats)}"
    assert sum(1 for s in layout.seats if s["is_hero"]) == 1
    for s in layout.seats:
        x, y, w, h = s["rect"]
        assert x >= 0 and y >= 0 and x + w <= 1920 and y + h <= 1080, f"seggiolino fuori schermo: {s['rect']}"
    assert layout.board_rect and layout.pot_rect
    print(f"TEST FALLBACK GEOMETRICO OK: {len(layout.seats)} seggiolini geometrici, hero in basso")
    return 0


def main() -> int:
    from src.qt_env import fix_qt_plugins
    fix_qt_plugins()
    test_layout()
    test_profiles()
    test_adapt()
    test_geometric_fallback()
    print("\nTUTTI I TEST SCENARIO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())