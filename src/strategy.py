"""Motore decisionale esploitativo: equity esatta + pot odds + sfruttamento avversari.

Preflop: range di apertura per posizione con aggiustamenti esploitativi.
Postflop: confronto equity vs pot odds con margini e soglie di raise calibrate
sull'aggressivita' percepita degli avversari.
"""
from __future__ import annotations

_RANK_ORDER = {r: i for i, r in enumerate("23456789TJQKA")}


def _rank_suit(card: str) -> tuple[str, str]:
    """Estrae rank e seme da un nome carta ('10C' -> 'T','C'; 'AS' -> 'A','S')."""
    if len(card) >= 3 and card[:2] == "10":
        return "T", card[2]
    return card[0], card[1]


def _hand_tier(cards: list[str]) -> int:
    """Tier preflop 0..9 (9 = mani premium AA/KK). I valori usano i ranghi 2..14."""
    if len(cards) != 2:
        return -1
    r1, s1 = _rank_suit(cards[0])
    r2, s2 = _rank_suit(cards[1])
    if r1 not in _RANK_ORDER or r2 not in _RANK_ORDER:
        return -1
    v1, v2 = _RANK_ORDER[r1] + 2, _RANK_ORDER[r2] + 2  # 2..14
    hi, lo = max(v1, v2), min(v1, v2)
    paired = v1 == v2
    suited = s1 == s2
    gap = hi - lo

    if paired:
        if hi >= 13:  # AA KK
            return 9
        if hi >= 11:  # QQ JJ
            return 8
        if hi >= 9:   # TT 99
            return 7
        if hi >= 6:   # 88..66
            return 6
        return 5      # 55..22
    if hi == 14 and lo == 13:  # AK
        return 8 if suited else 7
    if hi == 14 and lo >= 9:   # AQ AJ AT A9
        return 7 if suited else 6
    if hi == 13 and lo == 12:  # KQ
        return 6 if suited else 5
    if hi == 14 and lo >= 5:   # A8..A5
        return 6 if suited else 5
    if hi == 12 and lo == 11:  # QJ
        return 5 if suited else 4
    if hi == 14 and lo >= 2:   # A4..A2 (speculative ace)
        return 4 if suited else 3
    if gap == 1 and hi >= 9:   # JT T9 98 87
        return 5 if suited else 4
    if gap <= 3 and hi >= 11:  # connettori/broadway speculativi
        return 4 if suited else 3
    if hi >= 13 and lo >= 11:  # broadway (KJ KT QT)
        return 3 if suited else 2
    if gap <= 2 and hi >= 7:   # connettori medi
        return 3 if suited else 2
    return 1 if suited else 0


class Strategy:
    """Motore esploitativo. Tutte le soglie sono in config.json."""

    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self.raise_equity_threshold = cfg.get("raise_equity_threshold", 0.62)
        self.fold_margin = cfg.get("fold_margin", 0.03)      # cuscinetto sotto pot odds
        self.raise_threshold = cfg.get("raise_threshold", 0.60)  # equity per 3-bet postflop
        self.bet_pct = cfg.get("bet_pct", 0.66)
        # range di apertura preflop per posizione (early/middle/late/blind)
        self.open_tiers = cfg.get("open_tiers", {"early": 7, "middle": 6, "late": 5, "blind": 6})

    def recommend(self, ctx: dict) -> dict:
        """ctx: hero_cards, board_cards, pot, to_call, street,
        hero_equity (float 0..1), opponents (lista con aggression/range),
        position ('early'|'middle'|'late'|'blind'), num_opponents.
        """
        hero = ctx.get("hero_cards") or []
        board = ctx.get("board_cards") or []
        pot = max(0.0, float(ctx.get("pot", 0)))
        to_call = max(0.0, float(ctx.get("to_call", 0)))
        street = ctx.get("street", "preflop")
        equity = float(ctx.get("hero_equity", 0))
        position = ctx.get("position", "middle")
        opps = ctx.get("opponents") or []

        if street == "preflop" or not board:
            return self._preflop(hero, pot, to_call, position, opps, ctx)
        return self._postflop(hero, board, pot, to_call, equity, street, opps)

    def _preflop(self, hero, pot, to_call, position, opps, ctx) -> dict:
        tier = _hand_tier(hero)
        if tier < 0:
            return {"action": "check", "reason": "carte non rilevate", "amount": 0}

        limpers = int(ctx.get("limpers", 0))
        # Esploitativo: con limper passivi iso-raise piu' grosso
        exploit = 1 if limpers > 0 else 0
        needed = self.open_tiers.get(position, 6) + exploit

        if tier >= needed:
            base = max(pot * 3.0, 3.0) if pot else 3.0
            if limpers:
                base = max(base, pot * (3.5 + limpers))
            amt = max(3.0, round(base))
            if limpers:
                reason = (f"Hai una mano forte e giocatori sono già entrati con poco "
                          f"({limpers} limper): alza per isolarli e rubare il piatto")
            else:
                reason = f"Hai una mano forte e sei in {position}: apri con un rilancio"
            return {
                "action": "raise",
                "amount": amt,
                "reason": reason,
            }
        if tier >= needed - 2 and to_call > 0 and to_call <= pot * 0.5 + 1:
            return {"action": "call", "amount": to_call,
                    "reason": "Mano discreta e entrare costa poco: puoi vedere le prossime carte"}
        if tier >= needed - 3 and to_call == 0:
            return {"action": "check", "amount": 0, "reason": "Mano appena sufficiente: non puntare, guarda gratis"}
        return {"action": "fold", "amount": 0, "reason": "Hai una mano debole prima del flop: lascia perdere"}

    def _postflop(self, hero, board, pot, to_call, equity, street, opps) -> dict:
        if to_call <= 0:
            # nessuna puntata da chiamare
            if equity >= self.raise_equity_threshold:
                return {"action": "raise", "amount": round(max(pot * self.bet_pct, 2.0)),
                        "reason": f"Probabilità di vincere alta ({equity:.0%}): punta per guadagnare di più"}
            if equity >= 0.35:
                return {"action": "check", "amount": 0,
                        "reason": f"Buone probabilità ({equity:.0%}) ma il piatto è tuo da controllare: non rischiare"}
            return {"action": "check", "amount": 0,
                    "reason": f"Probabilità basse ({equity:.0%}) ma nessuno ha puntato: guarda gratis"}

        pot_odds = to_call / (pot + to_call)

        # Aggressivita' media degli avversari (1.0 = neutro, >1 aggressivo, <1 passivo)
        agg = 1.0
        if opps:
            agg = sum(float(o.get("aggression", 1.0)) for o in opps) / len(opps)

        # Esploitativo: contro passivi raise con meno equity (incassano con mani peggiori),
        # contro aggressivi serve piu' equity per alzare (possono 3-bettare).
        raise_need = self.raise_threshold + 0.06 * (agg - 1.0)
        call_need = pot_odds + self.fold_margin

        if equity >= raise_need:
            size = round(max(pot * self.bet_pct, to_call * 2.0))
            return {"action": "raise", "amount": size,
                    "reason": f"Vinci spesso ({equity:.0%}): rilanciare qui è conveniente "
                              f"({'gli avversari giocano passivi' if agg < 1 else 'mantieni la pressione'})"}
        if equity >= call_need:
            if equity >= pot_odds + 0.12 and street == "river":
                size = round(max(pot * self.bet_pct, to_call * 2.0))
                return {"action": "raise", "amount": size,
                        "reason": f"Ultima carta già uscita e vinci il {equity:.0%} delle volte: punta, hai quasi vinto"}
            return {"action": "call", "amount": to_call,
                    "reason": f"Chiamare conviene: vinci il {equity:.0%} delle volte e ti basta il {pot_odds:.0%}"}
        return {"action": "fold", "amount": 0,
                "reason": f"Meglio lasciare: vinci solo il {equity:.0%} delle volte ma il costo è il {pot_odds:.0%} del piatto"}