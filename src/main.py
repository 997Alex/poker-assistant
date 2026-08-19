"""Poker Assistant — main loop: cattura -> YOLO -> stato -> equity -> consiglio -> HUD."""
from __future__ import annotations

import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication

from src.capture import ScreenCapture
from src.detector import CardDetector
from src.equity import EquityCalculator, run_async
from src.state_tracker import GameState
from src.strategy import Strategy
from src.hand_analyzer import best_hand, outs_and_draws
from src.session_log import SessionLog
from src import profiles, paths

CONFIG_PATH = profiles.LEGACY_PATH
MODEL_PATH = paths.model_path()


def resolve_profile(monitor: int = 1) -> tuple[dict, str | None]:
    """Sceglie il profilo da usare: --profile esplicito, auto-match, migrazione, apprendimento."""
    paths.bootstrap()
    if "--profile" in sys.argv:
        name = sys.argv[sys.argv.index("--profile") + 1]
        if name not in profiles.list_profiles():
            print(f"Profilo '{name}' non trovato. Profili disponibili: {profiles.list_profiles()}")
            sys.exit(1)
        return profiles.load_profile(name), name

    if profiles.list_profiles():
        try:
            cap = ScreenCapture(monitor)
            img = cap.grab_full()
            screen_size = list(cap.size)
            cap.close()
            from src.table_detector import detect_table
            trect = detect_table(img)
            match = profiles.match_profile(monitor, screen_size, trect and trect[0])
            if match:
                return profiles.load_profile(match), match
        except Exception as e:  # noqa: BLE001
            print(f"auto-match fallito ({e}), uso la selezione manuale")

    migrated = profiles.migrate_legacy()
    if migrated:
        return profiles.load_profile(migrated), migrated

    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f), None

    print("Nessun profilo trovato: avvio l'apprendimento automatico del tavolo...")
    from src.seat_config import SeatConfigWindow
    app = QApplication.instance() or QApplication(sys.argv)
    win = SeatConfigWindow(monitor=monitor)
    win.show()
    app.exec_()
    name = profiles.get_current()
    if not name:
        print("Configurazione annullata.")
        sys.exit(0)
    return profiles.load_profile(name), name


class PokerAssistant(QObject):
    _equity_ready = pyqtSignal(object)

    def __init__(self, cfg: dict, hud, profile_name: str | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.profile_name = profile_name
        self.hud = hud
        s = cfg["settings"]

        self.capture = ScreenCapture(cfg["monitor"])
        self.detector = CardDetector(MODEL_PATH, conf=s["conf_threshold"], imgsz=s["imgsz"])
        self.equity_calc = EquityCalculator(iterations=s["mc_iterations"])
        self.strategy = Strategy(s)
        self.fps = s["fps"]

        self.seats = cfg["seats"]
        self.hero_seat = next(i for i, x in enumerate(self.seats) if x["is_hero"])
        labels = [x["label"] for x in self.seats]
        self.state = GameState(labels)
        self._table_rect = self._compute_table_rect()

        self.running = True
        self._last_state_key = None
        self._equity_pending = False
        self._last_equity = None
        self._last_rec = None
        self._last_analysis = None
        self._last_bh = None
        self._last_od = None
        self._hand_logged_start = False
        self._log = SessionLog(paths.logs_dir())
        self._ocr = None
        self._frame = 0

        # auto-adeguamento dei seggiolini
        self._seat_samples: dict[int, list[tuple[float, float]]] = {}
        self._seat_moves: dict[int, int] = {}
        self._last_hand_for_adapt = 1

        # segnale queued: il thread worker puo' notificare il main thread in sicurezza
        self._equity_ready.connect(self._apply_equity)

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(int(1000 / self.fps))

    def reload_profile(self, name: str) -> None:
        """Cambia piattaforma al volo: ricarica regioni, stato e strategia."""
        cfg = profiles.load_profile(name)
        s = cfg["settings"]
        self.cfg = cfg
        self.profile_name = name
        self.capture.close()
        self.capture = ScreenCapture(cfg["monitor"])
        self.detector.conf = s["conf_threshold"]
        self.detector.imgsz = s["imgsz"]
        self.strategy = Strategy(s)
        self.fps = s["fps"]
        self.seats = cfg["seats"]
        self.hero_seat = next(i for i, x in enumerate(self.seats) if x["is_hero"])
        self.state = GameState([x["label"] for x in self.seats])
        self._table_rect = self._compute_table_rect()
        self._seat_samples = {}
        self._seat_moves = {}
        self._last_hand_for_adapt = 1
        self.reset_hand()
        self.timer.setInterval(int(1000 / self.fps))
        profiles.set_current(name)
        self._log.log("profile_switch", profile=name)
        self.hud.set_profile_status(name)

    def _compute_table_rect(self) -> tuple:
        rects = [x["rect"] for x in self.seats] + [self.cfg["board_rect"]]
        x1 = min(r[0] for r in rects)
        y1 = min(r[1] for r in rects)
        x2 = max(r[0] + r[2] for r in rects)
        y2 = max(r[1] + r[3] for r in rects)
        pad_x = max(20, int((x2 - x1) * 0.08))
        pad_y = max(20, int((y2 - y1) * 0.08))
        return (max(0, x1 - pad_x), max(0, y1 - pad_y),
                x2 - x1 + 2 * pad_x, y2 - y1 + 2 * pad_y)

    def _zone_for(self, cx: float, cy: float) -> tuple[int, str] | None:
        pad = 8
        for i, seat in enumerate(self.seats):
            x, y, w, h = seat["rect"]
            if x - pad <= cx <= x + w + pad and y - pad <= cy <= y + h + pad:
                return i, "seat"
        bx, by, bw, bh = self.cfg["board_rect"]
        if bx - pad <= cx <= bx + bw + pad and by - pad <= cy <= by + bh + pad:
            return -1, "board"
        return None

    def tick(self) -> None:
        if not self.running:
            return
        t0 = time.time()
        try:
            left, top, w, h = self._table_rect
            img = self.capture.grab_region(left, top, w, h)
            dets = self.detector.detect(img)

            per_seat: dict[int, list] = {}
            board_dets: list = []
            for d in dets:
                x1, y1, x2, y2 = d["box"]
                cx = left + (x1 + x2) / 2
                cy = top + (y1 + y2) / 2
                zone = self._zone_for(cx, cy)
                if zone is None:
                    continue
                idx, kind = zone
                item = (d["name"], d["conf"])
                if kind == "seat":
                    per_seat.setdefault(idx, []).append(item)
                    x, y, w, h = self.seats[idx]["rect"]
                    samples = self._seat_samples.setdefault(idx, [])
                    if len(samples) < 300:
                        samples.append((cx - (x + w / 2), cy - (y + h / 2)))
                else:
                    board_dets.append(item)

            for idx, items in per_seat.items():
                self.state.update_seat(idx, items)
            self.state.update_board(board_dets)

            reset = self.state.tick()
            if reset:
                self._log.hand_end(self.state.hand_number)
                self._hand_logged_start = False
                self._last_equity = None
                self._last_rec = None
                self._last_bh = None
                self._last_od = None
                self.hud.set_equity(None)
                self.hud.set_action(None)
                self.hud.set_hand_analysis({}, {})
                self._maybe_adapt_seats()
                self._maybe_ocr_pot()

            self._update_hud_cards()
            self._maybe_log_hand_start()
            self._maybe_recompute()
            self._frame += 1
            if self._frame % 15 == 0:
                self._maybe_ocr_pot()
            self.hud.set_running(True)
        except Exception as e:  # noqa: BLE001 — nessun crash su frame difettosi
            print(f"tick error: {e}")

    def _maybe_adapt_seats(self) -> None:
        """Corregge i rettangoli dei seggiolini verso la posizione media delle carte.

        Scatta ogni N mani (N = settings.adapt_hands) se le detezioni sono
        stabili: spostamento massimo 12px, max 3 correzioni per seggiolino.
        """
        s = self.cfg["settings"]
        if not s.get("adapt_seats", True):
            return
        every = max(3, s.get("adapt_hands", 10))
        if self.state.hand_number - self._last_hand_for_adapt < every:
            return
        self._last_hand_for_adapt = self.state.hand_number

        moved_any = False
        for i, seat in enumerate(self.seats):
            samples = self._seat_samples.get(i, [])
            if len(samples) < 8:
                continue
            mx = sum(p[0] for p in samples) / len(samples)
            my = sum(p[1] for p in samples) / len(samples)
            dist = (mx * mx + my * my) ** 0.5
            moves = self._seat_moves.get(i, 0)
            if dist < 6 or moves >= 3:
                continue
            cap = min(dist, 12.0)
            fx, fy = mx / dist * cap, my / dist * cap
            x, y, w, h = seat["rect"]
            seat["rect"] = [int(x + fx), int(y + fy), w, h]
            self._seat_moves[i] = moves + 1
            moved_any = True
            self._log.log("seat_adapt", seat=i, dx=round(fx, 1), dy=round(fy, 1), dist=round(dist, 1))
        self._seat_samples = {}
        if moved_any:
            self._table_rect = self._compute_table_rect()
            self._log.log("table_rect_updated")

    def _update_hud_cards(self) -> None:
        hero = self.state.hero_cards(self.hero_seat)
        board = self.state.board_cards()
        opps = self.state.opponent_cards(self.hero_seat)
        self.hud.set_hand(hero, board, opps)
        if hero and board:
            bh = best_hand(hero, board)
            od = outs_and_draws(hero, board)
            self._last_bh, self._last_od = bh, od
            self.hud.set_hand_analysis(bh, od)
        else:
            self._last_bh, self._last_od = None, None
            self.hud.set_hand_analysis({}, {})

    def _maybe_log_hand_start(self) -> None:
        hero = self.state.hero_cards(self.hero_seat)
        if hero and not self._hand_logged_start:
            self._hand_logged_start = True
            self._log.hand_start(self.state.hand_number, hero,
                                 self.state.opponent_cards(self.hero_seat),
                                 self.state.board_cards())

    def _maybe_ocr_pot(self) -> None:
        """Lettura opzionale del pot dall'area selezionata (se easyocr e' installato)."""
        if not self.cfg["settings"].get("use_ocr") or "pot_rect" not in self.cfg:
            return
        try:
            import re
            import easyocr  # noqa: PLC0415 — dipendenza opzionale
            x, y, w, h = self.cfg["pot_rect"]
            img = self.capture.grab_region(x, y, w, h)
            if self._ocr is None:
                self._ocr = easyocr.Reader(["en"], gpu=False, verbose=False)
            text = self._ocr.readtext(img, detail=0, allowlist="0123456789,")
            digits = re.sub(r"[^0-9]", "", "".join(text))
            if digits:
                self.hud.set_pot_values(int(digits), self.hud.spin_to_call.value())
        except ImportError:
            print("OCR opzionale: installa con  .venv/bin/pip install easyocr")
        except Exception as e:  # noqa: BLE001
            print(f"ocr error: {e}")

    def _state_key(self) -> str:
        hero = self.state.hero_cards(self.hero_seat)
        board = self.state.board_cards()
        opps = self.state.opponent_cards(self.hero_seat)
        return f"{hero}|{board}|{sorted(opps.items())}"

    def _maybe_recompute(self) -> None:
        key = self._state_key()
        if key == self._last_state_key or self._equity_pending:
            return
        hero = self.state.hero_cards(self.hero_seat)
        if len(hero) < 2:
            self._last_state_key = key
            self.hud.set_equity(None)
            return
        self._last_state_key = key
        self._equity_pending = True

        opps = []
        for i, seat in enumerate(self.seats):
            if i == self.hero_seat:
                continue
            cards = self.state.seats[i].locked_cards()
            opps.append({
                "cards": cards if len(cards) == 2 else None,
                "range": seat.get("range", "random"),
                "aggression": seat.get("aggression", 1.0),
            })

        board = self.state.board_cards()
        run_async(self.equity_calc, hero, opps, board, self._on_equity)

    def _on_equity(self, result: dict) -> None:
        self._equity_pending = False
        self._last_equity = result
        # il segnale queued consegna il risultato al thread principale
        self._equity_ready.emit(result)

    def _apply_equity(self, result: dict) -> None:
        self.hud.set_equity(result, result.get("elapsed_ms", 0))
        self._maybe_recommend(result)
        self._log.analysis(
            self.state.hand_number,
            equity=result.get("hero"),
            recommendation=self._last_rec,
            outs=self._last_od and self._last_od.get("draw_count", 0),
            hand_label=self._last_bh and self._last_bh.get("label"),
            pot=self.hud.spin_pot.value(),
            to_call=self.hud.spin_to_call.value(),
            position=self.hud.position(),
            limpers=self.hud.limpers(),
        )

    def _maybe_recommend(self, equity: dict) -> None:
        hero = self.state.hero_cards(self.hero_seat)
        if not equity.get("hero"):
            return
        hero_eq = equity["hero"]
        pot, to_call = self.hud.pot_values()
        board = self.state.board_cards()
        street = "preflop" if not board else ("flop" if len(board) == 3 else
                                              "turn" if len(board) == 4 else "river")
        opps = []
        for i, seat in enumerate(self.seats):
            if i == self.hero_seat:
                continue
            opps.append({"aggression": seat.get("aggression", 1.0),
                         "range": seat.get("range", "random")})
        ctx = {
            "hero_cards": hero,
            "board_cards": board,
            "pot": pot,
            "to_call": to_call,
            "street": street,
            "hero_equity": hero_eq["win"] / 100.0 + hero_eq["tie"] / 200.0,
            "position": self.hud.position(),
            "limpers": self.hud.limpers(),
            "opponents": opps,
        }
        rec = self.strategy.recommend(ctx)
        self._last_rec = rec
        self.hud.set_action(rec)

    def toggle(self) -> None:
        self.running = not self.running
        self.hud.set_running(self.running)

    def reset_hand(self) -> None:
        self.state.reset()
        self._log.hand_end(self.state.hand_number)
        self._hand_logged_start = False
        self._last_state_key = None
        self._last_equity = None
        self._last_rec = None
        self._last_bh = None
        self._last_od = None
        self._equity_pending = False
        self.hud.set_equity(None)
        self.hud.set_action(None)
        self.hud.set_hand_analysis({}, {})
        self._update_hud_cards()

    def close(self) -> None:
        self.capture.close()
        self._log.close()


def main() -> int:
    from src.qt_env import fix_qt_plugins
    fix_qt_plugins()
    app = QApplication.instance() or QApplication(sys.argv)
    from src.monitor_picker import ask_monitor
    monitor = ask_monitor(app.activeWindow()) or 1
    cfg, profile_name = resolve_profile(monitor)
    cfg["monitor"] = monitor
    from src.hud import Hud
    assistant = PokerAssistant(cfg, None, profile_name=profile_name)
    hud = Hud(callbacks={
        "toggle": assistant.toggle,
        "reset": assistant.reset_hand,
        "profile": assistant.reload_profile,
        "profiles": profiles.list_profiles(),
        "profile_current": profile_name,
    })
    assistant.hud = hud
    hud.show()
    if profile_name:
        hud.set_profile_status(profile_name)
    app.aboutToQuit.connect(assistant.close)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())