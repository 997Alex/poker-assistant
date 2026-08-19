"""Stato della partita: carte per seggiolino, board, debounce e reset automatico."""
from __future__ import annotations

from dataclasses import dataclass, field

LOCK_FRAMES = 2        # frame consecutivi per considerare una carta "stabile"
UNLOCK_FRAMES = 5      # frame consecutivi di assenza per rimuovere una carta
HAND_RESET_FRAMES = 3  # frame con board vuoto dopo aver avuto carte -> nuova mano
IDLE_RESET_FRAMES = 60  # frame senza alcuna carta -> reset forzato


@dataclass
class CardState:
    name: str
    conf: float
    frames_visible: int = 0
    frames_missing: int = 0

    @property
    def locked(self) -> bool:
        return self.frames_visible >= LOCK_FRAMES


@dataclass
class ZoneState:
    label: str
    max_cards: int
    cards: dict[str, CardState] = field(default_factory=dict)

    def update(self, names: list[tuple[str, float]]) -> None:
        seen = set()
        for name, conf in names:
            seen.add(name)
            if name in self.cards:
                self.cards[name].conf = conf
                self.cards[name].frames_visible += 1
                self.cards[name].frames_missing = 0
            else:
                self.cards[name] = CardState(name=name, conf=conf, frames_visible=1)
        for name in list(self.cards):
            if name not in seen:
                self.cards[name].frames_missing += 1
        for name in list(self.cards):
            if self.cards[name].frames_missing >= UNLOCK_FRAMES:
                del self.cards[name]

    def locked_cards(self) -> list[str]:
        cards = sorted(
            (c for c in self.cards.values() if c.locked),
            key=lambda c: c.frames_visible,
            reverse=True,
        )
        return [c.name for c in cards[: self.max_cards]]


class GameState:
    """Stato dell'intera mano. Se separa le carte per soggetto (seggiolino/board)."""

    def __init__(self, seat_labels: list[str], board_max: int = 5) -> None:
        self.seats = {i: ZoneState(label, 2) for i, label in enumerate(seat_labels)}
        self.board = ZoneState("Board", board_max)
        self.board_clean_frames = 0
        self.hand_number = 1
        self._idle = 0
        self._had_board = False

    def update_seat(self, seat_id: int, detections: list[tuple[str, float]]) -> None:
        self.seats[seat_id].update(detections)

    def update_board(self, detections: list[tuple[str, float]]) -> None:
        if not detections:
            self.board_clean_frames += 1
        else:
            self.board_clean_frames = 0
        self.board.update(detections)

    def hero_cards(self, hero_seat: int = 0) -> list[str]:
        if hero_seat in self.seats:
            return self.seats[hero_seat].locked_cards()
        return []

    def board_cards(self) -> list[str]:
        return self.board.locked_cards()

    def opponent_cards(self, hero_seat: int = 0) -> dict[int, list[str]]:
        return {
            i: s.locked_cards()
            for i, s in self.seats.items()
            if i != hero_seat and s.locked_cards()
        }

    def hand_active(self) -> bool:
        return bool(self.board_cards()) or any(s.locked_cards() for s in self.seats.values())

    def tick(self) -> bool:
        """Avanza il contatore di idle; ritorna True se la mano va resettata."""
        if self.hand_active():
            self._idle = 0
        else:
            self._idle += 1

        if self.board_cards():
            self._had_board = True

        if self._had_board and self.board_clean_frames >= HAND_RESET_FRAMES:
            self.reset()
            return True

        if self._idle >= IDLE_RESET_FRAMES:
            self.reset()
            return True
        return False

    def reset(self) -> None:
        for s in self.seats.values():
            s.cards.clear()
        self.board.cards.clear()
        self.board_clean_frames = 0
        self._had_board = False
        self._idle = 0
        self.hand_number += 1