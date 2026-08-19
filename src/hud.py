"""HUD sempre in primo piano: carte rilevate, equity, mossa consigliata, reset."""
from __future__ import annotations

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

ACTION_STYLE = {
    "fold": "background:#c62828;color:white;font-weight:bold;padding:6px;",
    "check": "background:#546e7a;color:white;font-weight:bold;padding:6px;",
    "call": "background:#1565c0;color:white;font-weight:bold;padding:6px;",
    "raise": "background:#2e7d32;color:white;font-weight:bold;padding:6px;",
}


ACTION_LABEL = {
    "fold": "FOLDA",
    "check": "CONTROLLA",
    "call": "CHIAMA",
    "raise": "RILANCIA",
}


class Hud(QWidget):
    def __init__(self, callbacks: dict, translucent: bool = False) -> None:
        super().__init__(None)
        self._cb = callbacks
        self.setWindowTitle("Assistente Poker")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self._translucent = translucent
        if translucent:
            # bello ma richiede un compositor X/WM (su Windows va con DWM)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setStyleSheet("background:rgba(20,20,30,230);color:white;border-radius:10px;")
        else:
            # robusto: funziona anche senza window manager / compositor
            self.setAttribute(Qt.WA_OpaquePaintEvent, True)
            self.setStyleSheet("background:#14141e;color:white;border:2px solid #4a4a5a;border-radius:8px;")
        self.setMinimumWidth(560)
        self.move(1280, 0)  # in alto a destra, visibile anche senza WM

        self.lbl_title = QLabel("Assistente Poker")
        self.lbl_title.setStyleSheet("font-weight:bold;font-size:14px;")
        self.lbl_status = QLabel("● Analisi attiva")
        self.lbl_status.setStyleSheet("color:#4caf50;")

        self.btn_toggle = QPushButton("Pausa")
        self.btn_toggle.setFixedWidth(60)
        self.btn_toggle.setToolTip("Metti in pausa o riprendi l'analisi")
        self.btn_toggle.clicked.connect(self._cb["toggle"])
        self.btn_reset = QPushButton("Nuova mano")
        self.btn_reset.setToolTip("Azzera le carte rilevate: lo fa anche da solo quando il tavolo si svuota")
        self.btn_reset.clicked.connect(self._cb["reset"])

        top = QHBoxLayout()
        top.addWidget(self.lbl_title)
        top.addStretch()
        top.addWidget(self.lbl_status)
        top.addWidget(self.btn_toggle)
        top.addWidget(self.btn_reset)

        self.lbl_hero = QLabel("Le tue carte: —")
        self.lbl_hero.setStyleSheet("font-size:16px;font-weight:bold;")
        self.lbl_hero_equity = QLabel("")
        self.lbl_board = QLabel("Carte comuni: —")
        self.lbl_board.setStyleSheet("font-size:14px;")

        self.lbl_opps = QLabel("Avversari: —")
        self.lbl_opps.setStyleSheet("font-size:13px;color:#e0e0e0;")

        self.lbl_hand = QLabel("La tua mano: —")
        self.lbl_hand.setStyleSheet("font-size:13px;color:#ffd54f;")

        self.lbl_action = QLabel("Nessun consiglio")
        self.lbl_action.setWordWrap(True)
        self.lbl_action.setAlignment(Qt.AlignCenter)
        self.lbl_reason = QLabel("")
        self.lbl_reason.setWordWrap(True)
        self.lbl_reason.setStyleSheet("font-size:11px;color:#bdbdbd;")

        self.spin_pot = QSpinBox()
        self.spin_pot.setRange(0, 10_000_000)
        self.spin_pot.setPrefix("Piatto: ")
        self.spin_pot.setToolTip("Piatto = totale di tutte le puntate già fatte in questa mano")
        self.spin_to_call = QSpinBox()
        self.spin_to_call.setRange(0, 10_000_000)
        self.spin_to_call.setPrefix("Da chiamare: ")
        self.spin_to_call.setToolTip("Quanto devi mettere per restare in gioco (la puntata davanti a te)")

        self.step_box = QSpinBox()
        self.step_box.setRange(1, 1000)
        self.step_box.setValue(25)
        self.step_box.setPrefix("passo ")
        self.step_box.setToolTip("Quanto fanno aumentare/diminuire i pulsanti + e −")

        def stepper(spin: QSpinBox, delta: int):
            return lambda: spin.setValue(spin.value() + delta * self.step_box.value())

        self.btn_pot_m = QPushButton("−")
        self.btn_pot_p = QPushButton("+")
        self.btn_pot_m.setFixedWidth(28)
        self.btn_pot_p.setFixedWidth(28)
        self.btn_pot_m.clicked.connect(stepper(self.spin_pot, -1))
        self.btn_pot_p.clicked.connect(stepper(self.spin_pot, 1))
        self.btn_call_m = QPushButton("−")
        self.btn_call_p = QPushButton("+")
        self.btn_call_m.setFixedWidth(28)
        self.btn_call_p.setFixedWidth(28)
        self.btn_call_m.clicked.connect(stepper(self.spin_to_call, -1))
        self.btn_call_p.clicked.connect(stepper(self.spin_to_call, 1))

        self.pos_combo = QComboBox()
        for key, label in (("early", "Prima posizione (UTG)"), ("middle", "Posizione centrale"),
                           ("late", "Ultima posizione (BTN/CO)"), ("blind", "Blind (buio)")):
            self.pos_combo.addItem(label, key)
        self.pos_combo.setToolTip("La tua posizione al tavolo: più sei in fondo, più forte puoi giocare")
        self.limper_spin = QSpinBox()
        self.limper_spin.setRange(0, 9)
        self.limper_spin.setPrefix("Limper: ")
        self.limper_spin.setToolTip("Limper = giocatori entrati solo chiamando il buio (senza alzare)")

        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Piattaforma: —", None)
        for name in callbacks.get("profiles", []):
            self.profile_combo.addItem(f"Piattaforma: {name}", name)
        cur = callbacks.get("profile_current")
        idx = self.profile_combo.findData(cur)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.setToolTip("Cambia piattaforma (888, sisal, play-money...): "
                                      "ricarica la disposizione del tavolo salvata per quel sito")
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.lbl_profile = QLabel("")
        self.lbl_profile.setStyleSheet("font-size:10px;color:#81c784;")

        self.lbl_timing = QLabel("")
        self.lbl_timing.setStyleSheet("font-size:10px;color:#888;")

        pot_row = QHBoxLayout()
        pot_row.addWidget(self.spin_pot)
        pot_row.addWidget(self.btn_pot_m)
        pot_row.addWidget(self.btn_pot_p)
        pot_row.addWidget(self.spin_to_call)
        pot_row.addWidget(self.btn_call_m)
        pot_row.addWidget(self.btn_call_p)
        pot_row.addWidget(self.step_box)
        pot_row.addStretch()
        pot_row.addWidget(self.lbl_timing)

        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("Posizione:"))
        pos_row.addWidget(self.pos_combo)
        pos_row.addWidget(self.limper_spin)
        pos_row.addStretch()
        pos_row.addWidget(self.lbl_profile)
        pos_row.addWidget(self.profile_combo)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.addLayout(top)
        layout.addWidget(self.lbl_hero)
        layout.addWidget(self.lbl_hero_equity)
        layout.addWidget(self.lbl_hand)
        layout.addWidget(self.lbl_board)
        layout.addWidget(self.lbl_opps)
        layout.addWidget(self.lbl_action)
        layout.addWidget(self.lbl_reason)
        layout.addLayout(pot_row)
        layout.addLayout(pos_row)

        self.setFixedWidth(560)

    def mousePressEvent(self, e) -> None:
        self._drag = (e.globalPos() - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, e) -> None:
        if hasattr(self, "_drag") and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag)

    # ---- API di aggiornamento (chiamate dal main loop) ----
    def set_running(self, running: bool) -> None:
        self.lbl_status.setText("● Analisi attiva" if running else "■ In pausa")
        self.lbl_status.setStyleSheet("color:#4caf50;" if running else "color:#ef5350;")
        self.btn_toggle.setText("Pausa" if running else "Riprendi")

    def set_hand(self, hero_cards, board_cards, opps) -> None:
        self.lbl_hero.setText("Le tue carte: " + (", ".join(hero_cards) if hero_cards else "—"))
        self.lbl_board.setText("Carte comuni: " + (", ".join(board_cards) if board_cards else "—"))
        if opps:
            txt = "Avversari: "
            txt += "  |  ".join(f"Avv.{k}: {', '.join(v)}" for k, v in opps.items())
            self.lbl_opps.setText(txt)
        else:
            self.lbl_opps.setText("Avversari: —")

    def set_hand_analysis(self, bh: dict, od: dict) -> None:
        if bh.get("category"):
            label = bh["label"]
            if od.get("draws"):
                label += f" · {' + '.join(od['draws'])} ({od.get('draw_count', 0)} carte utili)"
            elif od.get("count"):
                label += f" · {od['count']} carte per migliorare"
            self.lbl_hand.setText(f"La tua mano: {label}")
            self.lbl_hand.setStyleSheet("font-size:13px;color:#ffd54f;")
        else:
            self.lbl_hand.setText("La tua mano: —")
            self.lbl_hand.setStyleSheet("font-size:13px;color:#ffd54f;")

    def position(self) -> str:
        return self.pos_combo.currentData()

    def limpers(self) -> int:
        return self.limper_spin.value()

    def _profile_changed(self, idx: int) -> None:
        name = self.profile_combo.currentData()
        if name and "profile" in self._cb:
            self._cb["profile"](name)

    def set_profile_status(self, name: str) -> None:
        self.lbl_profile.setText(f"Profilo: {name}")

    def set_equity(self, equity: dict | None, elapsed_ms: int = 0) -> None:
        if not equity or not equity.get("hero"):
            self.lbl_hero_equity.setText("")
            return
        h = equity["hero"]
        self.lbl_hero_equity.setText(
            f"Probabilità di VINCERE: {h['win']}%  ·  PAREGGIO: {h['tie']}%  ·  PERDERE: {h['lose']}%"
        )
        self.lbl_hero_equity.setToolTip(
            "Stima su migliaia di mani simulate: quanto spesso la tua mano vincerà"
            " (considerando le carte che mancano da girare)"
        )
        self.lbl_timing.setText(f"Simulazioni: {equity.get('iterations', 0):,} · {elapsed_ms}ms")

    def set_action(self, rec: dict | None) -> None:
        if not rec:
            self.lbl_action.setText("Nessun consiglio")
            self.lbl_action.setStyleSheet("background:#37474f;color:white;padding:6px;")
            self.lbl_reason.setText("")
            return
        action = rec.get("action", "check")
        amount = rec.get("amount", 0)
        label = ACTION_LABEL.get(action, action.upper()) + (f" {amount:g}" if amount else "")
        self.lbl_action.setText(label)
        self.lbl_action.setToolTip(
            "Cosa suggerisce l'assistente: FOLDA = lasci perdere, CONTROLLA = non puntare, "
            "CHIAMA = pareggiare la puntata, RILANCIA = alzare la puntata"
        )
        self.lbl_action.setStyleSheet(ACTION_STYLE.get(action, ACTION_STYLE["check"]))
        self.lbl_reason.setText(rec.get("reason", ""))

    def pot_values(self) -> tuple[int, int]:
        return self.spin_pot.value(), self.spin_to_call.value()

    def set_pot_values(self, pot: int, to_call: int) -> None:
        self.spin_pot.setValue(pot)
        self.spin_to_call.setValue(to_call)


def make_hud(callbacks: dict) -> Hud:
    return Hud(callbacks)