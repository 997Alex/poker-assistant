"""Test end-to-end del main loop con cattura simulata (nessun 888 necessario)."""
import sys, os, time
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import cv2
from PyQt5.QtWidgets import QApplication
from src.qt_env import fix_qt_plugins
fix_qt_plugins()
from PyQt5.QtCore import QTimer

from src.main import PokerAssistant
from src.hud import Hud

class FakeCapture:
    def __init__(self, img_path):
        self.img = cv2.imread(img_path)
        self.offset = (0, 0)
    def grab_region(self, left, top, width, height):
        return self.img  # ignora la regione: stessa immagine ogni frame
    def close(self):
        pass

def main():
    img_path = "/tmp/opencode/yolo11-poker/images/real_img_2.png"
    img = cv2.imread(img_path)
    h, w = img.shape[:2]
    cfg = {
        "monitor": 1,
        "screen_size": [w, h],
        "seats": [
            {"label": "Hero", "is_hero": True, "rect": [0, 0, w // 4, h], "range": "random", "aggression": 1.0},
            {"label": "Opp", "is_hero": False, "rect": [3 * w // 4, 0, w // 4, h], "range": "loose25", "aggression": 0.8},
        ],
        "board_rect": [w // 4, 0, w // 2, h],
        "settings": {"fps": 4, "conf_threshold": 0.5, "mc_iterations": 10000, "imgsz": 640,
                     "position": "middle", "open_tiers": {"early": 7, "middle": 6, "late": 5, "blind": 6},
                     "raise_equity_threshold": 0.62, "fold_margin": 0.03, "raise_threshold": 0.6, "bet_pct": 0.66},
    }

    app = QApplication(sys.argv)
    hud = Hud(callbacks={"toggle": lambda: None, "reset": lambda: None})
    hud.show()
    hud.pos_combo.setCurrentIndex(2)  # late
    hud.limper_spin.setValue(1)
    hud.set_pot_values(100, 20)

    pa = PokerAssistant(cfg, hud)
    pa.capture = FakeCapture(img_path)

    # 6 tick per il lock delle carte e il calcolo equity
    for _ in range(6):
        pa.tick()
        app.processEvents()

    # attende il thread di equity e il consiglio (fino a 15s)
    for _ in range(150):
        if pa._last_equity and pa._last_equity["hero"] and pa._last_rec:
            break
        time.sleep(0.1)
        app.processEvents()

    hero = pa.state.hero_cards(0)
    opp = pa.state.opponent_cards(0)
    board = pa.state.board_cards()
    print(f"Hero: {hero} | Opp: {opp} | Board: {board}")
    print(f"Equity: {pa._last_equity and pa._last_equity['hero']}")
    print(f"Consiglio: {pa._last_rec}")
    print(f"Mano: {pa._last_bh and pa._last_bh['label']} | draw outs: {pa._last_od and pa._last_od['draw_count']}")
    print(f"Posizione HUD: {hud.position()} | limper: {hud.limpers()}")

    assert hero, "hero cards non rilevate"
    assert pa._last_equity and pa._last_equity["hero"], "equity non calcolata"
    assert pa._last_rec and pa._last_rec["action"] in ("fold", "check", "call", "raise"), "consiglio mancante"
    assert pa._last_bh and pa._last_bh["category"], "analisi mano mancante"
    assert pa._last_od is not None, "analisi outs mancante"
    assert hud.position() == "late" and hud.limpers() == 1, "posizione/limper HUD"
    assert os.path.exists(pa._log.path) and os.path.getsize(pa._log.path) > 0, "log sessione vuoto"
    print("LOG scritto in:", pa._log.path)
    print("TEST E2E OK")

if __name__ == "__main__":
    main()