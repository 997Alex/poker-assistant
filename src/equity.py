"""Equity esatta via Monte Carlo con treys. Supporta range avversari preflop."""
from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor

from treys import Card, Deck, Evaluator

_RANKS = "23456789TJQKA"
_SUITS = "shdc"

# Range preflop per categoria (classi di mani). Concretizzate in combinazioni.
RANGES: dict[str, list[str]] = {
    "random": [],  # qualsiasi combinazione
    "tight10": [
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77",
        "AKs", "AKo", "AQs", "AQo", "AJs", "ATs",
        "KQs", "KQo", "KJs", "QJs",
    ],
    "loose25": [
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44",
        "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs", "ATo", "A9s", "A8s", "A7s", "A6s", "A5s",
        "KQs", "KQo", "KJs", "KJo", "KTs", "K9s",
        "QJs", "QJo", "QTs", "Q9s",
        "JTs", "J9s", "T9s", "T8s", "98s", "87s", "76s",
    ],
    "loose50": [
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
        "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs", "ATo", "A9s", "A8s", "A7s", "A6s", "A5s",
        "A4s", "A3s", "A2s", "KQs", "KQo", "KJs", "KJo", "KTs", "KTo", "K9s", "K8s", "K7s",
        "QJs", "QJo", "QTs", "QTo", "Q9s", "Q8s", "JTs", "JTo", "J9s", "J8s",
        "T9s", "T8s", "T7s", "98s", "97s", "87s", "86s", "76s", "75s", "65s", "64s", "54s",
    ],
}

_MAX_CORES = 4


def card_to_int(name: str) -> int:
    """Converte un nome carta YOLO ('AC', '10D') nel formato treys."""
    name = name.upper()
    if name.startswith("10"):
        rank, suit = "T", name[2]
    else:
        rank, suit = name[0], name[1]
    return Card.new(rank + suit.lower())


def _combos_for(hand_class: str) -> list[tuple[int, int]]:
    """Combinazioni concrete (Card int) per una classe di mani es. 'AKs'."""
    if len(hand_class) == 2:
        r = hand_class[0]
        return [(Card.new(r + s1), Card.new(r + s2))
                for i, s1 in enumerate(_SUITS) for s2 in _SUITS[i + 1:]]
    r1, r2, suited = hand_class[0], hand_class[1], hand_class[2] == "s"
    out = []
    for s1 in _SUITS:
        for s2 in _SUITS:
            if suited and s1 == s2:
                out.append((Card.new(r1 + s1), Card.new(r2 + s2)))
            elif not suited and s1 != s2:
                out.append((Card.new(r1 + s1), Card.new(r2 + s2)))
    return out


class EquityCalculator:
    """Calcola win/tie/lose per ogni giocatore. Gli avversari senza carte note
    vengono pescati dal range assegnato (default: random)."""

    def __init__(self, iterations: int = 30000) -> None:
        self.iterations = iterations

    def run(
        self,
        hero_cards: list[str],
        opponents: list[dict],
        board_cards: list[str],
    ) -> dict:
        """opponents: lista di dict {'cards': [...]|None, 'range': 'random'|'tight10'|...}.

        Ritorna {'hero': {'win':..,'tie':..,'lose':..}, 'opponents': [{...}]}
        """
        if len(hero_cards) != 2:
            return {"hero": None, "opponents": [], "error": "servono 2 carte hero"}

        ev = Evaluator()
        hero = [card_to_int(c) for c in hero_cards]
        board = [card_to_int(c) for c in board_cards]
        opp_hands = []
        for o in opponents:
            if o.get("cards") and len(o["cards"]) == 2:
                opp_hands.append({"fixed": [card_to_int(c) for c in o["cards"]], "range": None})
            else:
                opp_hands.append({"fixed": None, "range": o.get("range", "random")})

        rng = random.Random()
        wins = {"win": 0, "tie": 0, "lose": 0}
        opp_res = [{"win": 0, "tie": 0, "lose": 0} for _ in opp_hands]
        total = self.iterations

        for _ in range(total):
            deck = Deck()
            used = set(hero) | set(board)
            deal = []
            for h in opp_hands:
                if h["fixed"]:
                    cards = list(h["fixed"])
                else:
                    cards = self._sample_range(h["range"], used, deck, rng)
                deal.append(cards)
                used.update(cards)

            remaining = [c for c in Deck.GetFullDeck() if c not in used]
            rng.shuffle(remaining)
            full_board = board + remaining[: 5 - len(board)]

            scores = [ev.evaluate(hero, full_board)]
            for h in deal:
                scores.append(ev.evaluate(h, full_board))

            best = min(scores)
            winners = [i for i, s in enumerate(scores) if s == best]
            for i in winners:
                if i == 0:
                    if len(winners) == 1:
                        wins["win"] += 1
                    else:
                        wins["tie"] += 1
                else:
                    if len(winners) == 1:
                        opp_res[i - 1]["win"] += 1
                    else:
                        opp_res[i - 1]["tie"] += 1
            if 0 not in winners:
                wins["lose"] += 1

        def pct(x: int) -> float:
            return round(100.0 * x / total, 1)

        result = {
            "hero": {"win": pct(wins["win"]), "tie": pct(wins["tie"]), "lose": pct(wins["lose"])},
            "opponents": [{"win": pct(r["win"]), "tie": pct(r["tie"]), "lose": pct(r["lose"])} for r in opp_res],
            "iterations": total,
            "elapsed_ms": 0,
        }
        return result

    @staticmethod
    def _sample_range(range_name: str, used: set, deck: Deck, rng: random.Random) -> list[int]:
        pool = RANGES.get(range_name)
        while True:
            if pool:
                hand_class = rng.choice(pool)
                combos = _combos_for(hand_class)
                if not combos:
                    continue
                c1, c2 = rng.choice(combos)
            else:
                c1 = deck.draw(1)[0]
                c2 = deck.draw(1)[0]
            if c1 not in used and c2 not in used and c1 != c2:
                used.update((c1, c2))
                return [c1, c2]
            # combinazione in conflitto: riprova


def run_async(calc: EquityCalculator, hero_cards, opponents, board_cards, on_done):
    """Esegue il calcolo in un thread separato."""

    def _work():
        t0 = time.time()
        try:
            result = calc.run(hero_cards, opponents, board_cards)
            result["elapsed_ms"] = int((time.time() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            print(f"equity error: {e}")
            result = {"hero": None, "opponents": [], "error": str(e)}
        on_done(result)

    ThreadPoolExecutor(max_workers=1).submit(_work)