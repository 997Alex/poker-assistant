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
    "Pair": "Coppia",
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

    # Scalabili: usa ranghi unici ordinati, con A basso e A alto.
    # Calcola i ranghi che completano davvero una scala di 5: sono gli outs reali
    # del draw. Poi classifica:
    #   - 4 ranghi consecutivi presenti completabili a entrambi i lati = open-ended
    #   - due completamenti separati = doppio buco
    #   - altrimenti = gutshot
    unique = sorted(set(ranks))
    if 14 in unique:  # A basso
        unique.append(1)
    full = set(unique)
    completers = []
    for r in range(1, 15):
        if r in full:
            continue
        cand = full | {r}
        if any(all(q in cand for q in range(s, s + 5)) for s in range(1, 11)):
            completers.append(r)
    if completers and len(board) < 5:
        # 4 consecutivi presenti => i due esterni sono i completamenti OESD
        oesd = False
        for s in range(1, 12):
            four = set(range(s, s + 4))
            if four.issubset(full) and (s - 1) in completers and (s + 4) in completers:
                oesd = True
                break
        if oesd:
            draws.append("Scala bilaterale (open-ended)")
        elif len(completers) >= 2:
            draws.append("Scala interna (doppio buco)")
        else:
            draws.append("Scala interna (gutshot)")
    return list(dict.fromkeys(draws))