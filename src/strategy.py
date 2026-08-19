"""Motore decisionale esploitativo: equity esatta + pot odds + sfruttamento avversari.

Preflop: range di apertura per posizione con aggiustamenti esploitativi.
Postflop: confronto equity vs pot odds con margini e soglie di raise calibrate
sull'aggressivita' percepita degli avversari.
"""
from __future__ import annotations

_RANK_ORDER = {r: i for i, r in enumerate("23456789TJQKA")}


def _hand_tier(cards: list[str]) -> int:
    """Tier preflop 0..9 (9 = mani premium AA/KK)."""
    if len(cards) != 2:
        return -1
    r1, r2 = _RANK_ORDER[cards[0][0]], _RANK_ORDER[cards[1][0]]
    s1, s2 = cards[0][1], cards[1][1]
    hi, lo = max(r1, r2), min(r1, r2)
    paired = r1 == r2
    suited = s1 == s2
    gap = hi - lo

    if paired:
        if hi >= 11:  # AA KK
            return 9
        if hi >= 9:   # QQ JJ
            return 8
        if hi >= 7:   # TT 99
            return 7
        if hi >= 4:   # 88..66
            return 6
        return 5      # 55..22
    if hi == 12 and lo == 11:  # AK
        return 8 if suited else 7
    if hi == 12 and lo >= 9:   # AQ AJ AT A9
        return 7 if suited else 6
    if hi == 11 and lo >= 10:  # KQ
        return 6 if suited else 5
    if hi == 12 and lo >= 7:   # A8 A7 A6 A5
        return 6 if suited else 5
    if hi == 10 and lo >= 9 and gap == 1:  # QJ
        return 5 if suited else 4
    if hi == 12 and lo >= 3:   # A4..A2 + A5 (speculative ace)
        return 4 if suited else 3
    if gap == 1 and hi >= 7:   # JT T9 98 87
        return 5 if suited else 4
    if gap <= 3 and hi >= 9:   # connettori/broadway speculativi
        return 4 if suited else 3
    if hi >= 11 and lo >= 9:   # broadway
        return 3 if suited else 2
    if gap <= 2 and hi >= 5:   # connettori medi
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
        if tier >= needed - 2 and to_call <= pot * 0.5 + 1:
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