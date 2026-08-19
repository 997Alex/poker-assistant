"""Analisi della mano corrente: categoria della mano + outs esatti e disegni.

Gli outs sono calcolati esattamente: per ogni carta rimasta nel mazzo simula il
completamento del board e verifica se il giocatore migliora la categoria della mano.
"""
from __future__ import annotations

from collections import Counter

from treys import Card, Deck, Evaluator

from src.equity import card_to_int

_HAND_IT = {
    "High Card": "Niente — carta alta",
    "One Pair": "Coppia",
    "Two Pair": "Doppia coppia",
    "Three of a Kind": "Tris (tre uguali)",
    "Straight": "Scala (cinque in fila)",
    "Flush": "Colore (cinque dello stesso seme)",
    "Full House": "Full House (tris + coppia)",
    "Four of a Kind": "Poker (quattro uguali)",
    "Straight Flush": "Scala di colore",
    "Royal Flush": "Scala reale (la mano più forte)",
}


def best_hand(hero: list[str], board: list[str]) -> dict:
    """Ritorna la categoria della migliore mano a 5 carte e una descrizione."""
    if len(hero) < 2 or len(hero) + len(board) < 5:
        return {"category": None, "label": "—", "english": None}
    ev = Evaluator()
    cards = [card_to_int(c) for c in hero] + [card_to_int(c) for c in board]
    score = ev.evaluate([card_to_int(c) for c in hero], [card_to_int(c) for c in board])
    eng = ev.class_to_string(ev.get_rank_class(score))
    return {
        "category": eng,
        "english": eng,
        "label": _HAND_IT.get(eng, eng),
    }


def outs_and_draws(hero: list[str], board: list[str]) -> dict:
    """Outs esatti e disegni (draw) per migliorare la mano corrente.

    Ritorna:
      'outs'        : tutte le carte che migliorano la classe di mano
      'count'       : len(outs)
      'draws'       : [str...] disegni rilevati
      'draw_outs'   : carte che completano un draw specifico
      'draw_count'  : outs del draw principale
    """
    if len(hero) < 2 or len(board) < 3 or len(board) >= 5:
        return {"outs": [], "count": 0, "draws": [], "draw_outs": [], "draw_count": 0}

    ev = Evaluator()
    hero_i = [card_to_int(c) for c in hero]
    board_i = [card_to_int(c) for c in board]
    used = set(hero_i) | set(board_i)

    current_score = ev.evaluate(hero_i, board_i)
    current_class = ev.get_rank_class(current_score)

    outs = []
    for card in Deck.GetFullDeck():
        if card in used:
            continue
        new_score = ev.evaluate(hero_i, board_i + [card])
        if ev.get_rank_class(new_score) < current_class:  # classe migliore = punteggio piu' basso
            outs.append(card)

    draws = _detect_draws(hero_i, board_i)
    draw_outs: list[int] = []
    for card in outs:
        if _completes_draw(card, hero_i, board_i, draws):
            draw_outs.append(card)

    return {
        "outs": outs,
        "count": len(outs),
        "draws": draws,
        "draw_outs": draw_outs,
        "draw_count": len(draw_outs),
    }


def _completes_draw(card: int, hero: list[int], board: list[int], draws: list[str]) -> bool:
    if not draws:
        return False
    ranks = [Card.get_rank_int(c) for c in hero + board] + [Card.get_rank_int(card)]
    suits = [Card.get_suit_int(c) for c in hero + board]
    if any("flush" in d.lower() for d in draws):
        flush_suit = max(set(suits), key=suits.count)
        if Card.get_suit_int(card) == flush_suit and suits.count(flush_suit) + 1 >= 5:
            return True
    if any("Scala" in d for d in draws):
        uniq = sorted(set(ranks))
        if 14 in uniq:
            uniq.append(1)
        for start in range(min(uniq), max(uniq) - 3):
            seq = list(range(start, start + 5))
            if all(r in uniq for r in seq):
                return True
    return False


def _detect_draws(hero: list[int], board: list[int]) -> list[str]:
    draws: list[str] = []
    all_cards = hero + board
    ranks = [Card.get_rank_int(c) for c in all_cards]  # 2..14 (A=14)
    suits = [Card.get_suit_int(c) for c in all_cards]

    # Flush draw: 4 carte dello stesso seme in mano+board (almeno 1 in mano)
    suit_count = Counter(suits)
    for s, n in suit_count.items():
        in_hand = any(Card.get_suit_int(c) == s for c in hero)
        if n == 4 and in_hand and len(board) < 5:
            draws.append("Colore in arrivo (flush draw)")
            break

    # Scalabili: usa ranghi unici ordinati, con A basso e A alto
    unique = sorted(set(ranks))
    if 14 in unique:  # A basso
        unique.append(1)
    for start in range(min(unique), max(unique) - 3):
        needed = [r for r in range(start, start + 4)]
        have = sum(1 for r in unique if r in needed or (r == 14 and 1 in needed))
        # count = quante carte di una sequenza di 4 abbiamo
        seq = [r for r in range(start, start + 4)]
        present = [r for r in seq if r in ranks or (r == 1 and 14 in ranks)]
        if len(present) == 3 and len(board) < 5:
            # gutshot se il quarto completa, OESD se due combo completano
            gaps = [r for r in seq if r not in present]
            if len(gaps) == 1:
                # controllo che sia davvero OESD: i due completamenti
                outs_seq = [seq[0] - 1, seq[-1] + 1]
                real = [o for o in outs_seq if 1 <= o <= 14 or (o == 15 and 1 in ranks)]
                if len(real) >= 2:
                    draws.append("Scala bilaterale (open-ended)")
                else:
                    draws.append("Scala interna (gutshot)")
            break
    return list(dict.fromkeys(draws))