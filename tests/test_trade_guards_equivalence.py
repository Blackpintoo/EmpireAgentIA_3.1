# -*- coding: utf-8 -*-
"""
Preuve d'equivalence P2 : orchestrator/trade_guards.py decide exactement
comme le code d'origine de execute_trade.

Methode
-------
La reference n'est pas une reecriture : `tests/_legacy_guards_ref.py` est
genere par `tools/gen_legacy_guards.py`, qui extrait la bande de gardes
VERBATIM du commit dff6ec7 (etat d'avant l'extraction) et la rend
executable. On tire ensuite des milliers de scenarios aleatoires et on
verifie que les deux chemins produisent :

  - le meme verdict (autorise / bloque / exception),
  - le meme message Telegram (texte, kind, force),
  - le meme log de refus (niveau, texte).

Pourquoi pas un rejeu des decisions journalisees, comme demande
-------------------------------------------------------------
`data/proposals_log.csv` ne contient que
ts_utc,symbol,side,price,sl,tp,lots,score,confluence,ttl_sec,expired,executed.
Il n'enregistre ni le garde declencheur, ni la config effective du moment,
ni l'etat MT5 (equity, positions, tick, spread), ni les valeurs derivees
(seuil effectif, boost adaptatif, penalite de liquidite). Rejouer les
decisions a partir de ce journal est impossible : 2 des 20 gardes seulement
y sont observables. Le tirage aleatoire couvre au contraire l'espace complet
des entrees, y compris les combinaisons jamais rencontrees en production.
"""
import random
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from orchestrator import trade_guards as TG
from tests import _legacy_guards_ref as LEGACY

WHITELIST_OVERRIDE = ("XAUUSD",)
CRYPTOS = {"BTCUSD", "SOLUSD", "BNBUSD", "LTCUSD", "ETHUSD"}
SYMBOLES = ["BTCUSD", "XAUUSD", "NAS100", "AUDUSD", "SOLUSD"]

HEURE_FIXE = datetime(2026, 7, 30, 14, 0, 0, tzinfo=timezone.utc)


def _base_dt(s: dict) -> datetime:
    """Horloge du scenario : seule l'heure UTC varie."""
    return HEURE_FIXE.replace(hour=s["heure"])


class _FauxDatetime:
    """Horloge figee, pour que les deux chemins voient la meme heure."""
    _now = HEURE_FIXE

    @classmethod
    def now(cls, tz=None):
        return cls._now if tz is None else cls._now.astimezone(tz)

    @staticmethod
    def fromisoformat(s):
        return datetime.fromisoformat(s)


class _Journal:
    """Capture les effets, des deux cotes, dans le meme format."""

    def __init__(self):
        self.telegram = []
        self.logs = []

    def _log(self, niveau):
        def f(msg, *a, **k):
            texte = msg % a if a else msg
            if niveau in ("warning", "error", "info"):
                self.logs.append((niveau, texte))
        return f

    def comme_logger(self):
        return SimpleNamespace(
            debug=lambda *a, **k: None,
            info=self._log("info"),
            warning=self._log("warning"),
            error=self._log("error"),
        )


def _tire_scenario(rnd: random.Random) -> dict:
    symbol = rnd.choice(SYMBOLES)
    est_crypto = symbol in CRYPTOS
    heure = rnd.randrange(24)
    side = rnd.choice(["LONG", "SHORT"])
    return {
        "symbol": symbol,
        "est_crypto": est_crypto,
        "heure": heure,
        "profil_actif": rnd.random() > 0.15,
        "dans_window": rnd.random() > 0.15,
        "asset_manager": rnd.random() > 0.3,
        "session_ok": rnd.random() > 0.25,
        "session_motif": rnd.choice(["hors session", "session US", "week-end"]),
        "positions": rnd.choice([[], ["BTCUSD"], ["NAS100", "SP500"]]),
        "conflit": rnd.random() > 0.7,
        "qr_offset_min": rnd.choice([-120.5, -5.5, 0.0, 7.5, 45.5]),
        "ltr": rnd.choice([
            None,
            {"direction": "LONG", "pnl": -150.0, "offset_min": 10.5},
            {"direction": "SHORT", "pnl": -80.0, "offset_min": 90.5},
            {"direction": "LONG", "pnl": 200.0, "offset_min": 5.5},
            {"direction": "SHORT", "pnl": -40.0, "offset_min": 0.5},
        ]),
        "reversal_cooldown_min": rnd.choice([0, 30, 60]),
        "signal": rnd.choice(["LONG", "SHORT", "LONG", "SHORT", "FLAT", ""]),
        "proposal_side": rnd.choice([side, "LONG", "SHORT"]),
        "proposal_absente": rnd.random() > 0.85,
        "nb_positions_symbole": rnd.choice([0, 0, 0, 1, 3]),
        "ttl_offset_s": rnd.choice([-600, -30, 60, 900, None]),
        "local_blocked": rnd.choice([[], [3, 4], [14], [22, 23]]),
        "global_blocked": rnd.choice([[], [0, 1, 2], [14, 15]]),
        "allowed_hours": rnd.choice([None, [], [8, 9, 10, 14], [14]]),
        "asia_enabled": rnd.random() > 0.4,
        "asia_hours": [0, 1, 2, 3, 4, 5, 6, 7],
        "asia_exempt": rnd.random() > 0.3,
        "score": round(rnd.uniform(2.0, 12.0), 4),
        "confluence": rnd.randrange(0, 8),
        "tracker_vote": round(rnd.uniform(-1.5, 1.5), 3),
        "hf_min_score": rnd.choice([4.0, 6.0, 8.0]),
        "hf_min_confluence": rnd.choice([2, 3, 4]),
        "hf_tracker": rnd.choice([0.3, 0.5]),
        "adaptive_boost": rnd.choice([0.0, 0.5, 1.0]),
        "liq_hours": [0, 1, 2, 3, 4, 5, 6, 7, 22, 23],
        "liq_penalty_cfg": rnd.choice([0.0, 2.0]),
        "short_penalty": rnd.choice([0.0, 1.5]),
        "allowed_directions": rnd.choice([None, ["LONG"], ["SHORT"], ["LONG", "SHORT"]]),
        "compte_present": rnd.random() > 0.2,
        "balance": rnd.choice([0.0, 50000.0]),
        "profit": round(rnd.uniform(-2500.0, 800.0), 2),
        "daily_limit": rnd.choice([0.02, 0.05]),
        "avoid_low_liq": rnd.random() > 0.3,
        "sess_blocked": rnd.choice([[0, 1, 2, 3, 4, 5], [18, 19, 20, 21, 22, 23], [14]]),
        "crypto_override_avoid": rnd.random() > 0.6,
        "probation": rnd.random() > 0.8,
    }


def _relaxe(s: dict, rnd: random.Random) -> dict:
    """
    Desactive les gardes amont pour que les gardes aval soient reellement
    atteints. Sans cela, un garde en position 19 sur 20 ne serait jamais
    exerce : la comparaison ne prouverait rien a son sujet.
    """
    s.update({
        "profil_actif": True, "dans_window": True, "asset_manager": False,
        "qr_offset_min": -120.5, "ltr": None, "reversal_cooldown_min": 0,
        "signal": rnd.choice(["LONG", "SHORT"]), "proposal_absente": False,
        "nb_positions_symbole": 0, "ttl_offset_s": 900,
        "local_blocked": [], "global_blocked": [], "allowed_hours": None,
        "asia_enabled": False, "score": round(rnd.uniform(9.0, 14.0), 4),
        "confluence": 7, "tracker_vote": 0.0, "hf_min_score": 4.0,
        "hf_min_confluence": 2, "short_penalty": 0.0,
        "allowed_directions": None, "liq_penalty_cfg": 0.0,
        "adaptive_boost": 0.0, "compte_present": True, "balance": 50000.0,
    })
    s["proposal_side"] = s["signal"]
    return s


def _stub_self(s: dict, journal: _Journal, ref_time: float):
    """Orchestrateur factice, alimente uniquement par le scenario."""
    prop = None
    if not s["proposal_absente"]:
        expires = None
        if s["ttl_offset_s"] is not None:
            expires = (_base_dt(s) + timedelta(seconds=s["ttl_offset_s"])).isoformat()
        prop = {
            "side": s["proposal_side"], "symbol": s["symbol"], "entry": 100.0,
            "lots": 0.1, "sl": 99.0, "tp": 102.0, "score": s["score"],
            "confluence": s["confluence"], "tracker_vote": s["tracker_vote"],
            "expires_at": expires,
        }

    asset_manager = None
    if s["asset_manager"]:
        asset_manager = SimpleNamespace(
            is_trading_allowed=lambda sym, now: (s["session_ok"], s["session_motif"]),
            check_correlation_conflict=lambda sym, pos: s["conflit"],
        )

    cfg = {
        "orchestrator": {
            "cooldown": {"reversal_cooldown_min": s["reversal_cooldown_min"]},
            "hard_filters": {
                "asia_block": {
                    "enabled": s["asia_enabled"], "hours_utc": s["asia_hours"],
                    "exempt_crypto": s["asia_exempt"],
                },
                "low_liquidity_hours_utc": s["liq_hours"],
                "low_liquidity_score_penalty": s["liq_penalty_cfg"],
                "short_score_penalty": s["short_penalty"],
            },
        },
        "risk": {"daily_loss_limit_pct": s["daily_limit"]},
        "volatility_filter": {
            "avoid_low_liquidity": s["avoid_low_liq"],
            "low_liquidity_hours_utc": s["sess_blocked"],
            "asset_overrides": {"crypto": {"avoid_low_liquidity": s["crypto_override_avoid"]}},
        },
    }

    ltr = None
    if s["ltr"]:
        ltr = {"direction": s["ltr"]["direction"], "pnl": s["ltr"]["pnl"],
               "close_ts": ref_time - s["ltr"]["offset_min"] * 60.0}

    return SimpleNamespace(
        symbol=s["symbol"],
        broker_symbol=s["symbol"],
        cfg=cfg,
        profile={"orchestrator": {"blocked_hours_utc": s["local_blocked"],
                                  "allowed_hours_utc": s["allowed_hours"]}},
        ori_cfg={"allowed_directions": s["allowed_directions"],
                 "probation": s["probation"]},
        asset_manager=asset_manager,
        _last_trade_result=ltr,
        _last_proposal=prop,
        proposal_ttl_secs=300,
        _hf_crypto_symbols=CRYPTOS,
        _hf_min_score=s["hf_min_score"],
        _hf_min_confluence=s["hf_min_confluence"],
        _hf_tracker_contradiction=s["hf_tracker"],
        _hf_blocked_hours=s["sess_blocked"],
        _hf_blocked_hours_extended=s["sess_blocked"],
        _is_symbol_profile_active_now=lambda: s["profil_actif"],
        _is_in_trading_window=lambda: s["dans_window"],
        _get_adaptive_score_boost=lambda: s["adaptive_boost"],
        _send_telegram=lambda texte, kind="status", force=False: journal.telegram.append(
            (texte, kind, force)),
        _log_proposal_csv=lambda *a, **k: None,
    )


def _contexte(s: dict, ref_time: float) -> dict:
    """Le contexte tel que l'orchestrateur le construira."""
    heure = s["heure"]
    est_crypto = s["symbol"].upper() in CRYPTOS

    blocked_hours, _ = TG.calculer_blocked_hours(
        s["symbol"], s["local_blocked"], s["global_blocked"], s["allowed_hours"],
        WHITELIST_OVERRIDE, heure)

    liq_penalty = TG.calculer_liq_penalty(est_crypto, heure, s["liq_hours"],
                                          s["liq_penalty_cfg"])
    hard_min = s["hf_min_score"] + s["adaptive_boost"] + liq_penalty

    daily_evaluable = s["compte_present"]
    daily_pnl_pct = TG.calculer_daily_pnl_pct(s["profit"], s["balance"])

    crypto_exempt = TG.calculer_crypto_exempt(
        est_crypto, {"avoid_low_liquidity": s["crypto_override_avoid"]})

    ltr = None
    if s["ltr"]:
        ltr = {"direction": s["ltr"]["direction"], "pnl": s["ltr"]["pnl"],
               "close_ts": ref_time - s["ltr"]["offset_min"] * 60.0}

    ttl_expiree = False
    if s["ttl_offset_s"] is not None and not s["proposal_absente"]:
        base = _base_dt(s)
        ttl_expiree = base > base + timedelta(seconds=s["ttl_offset_s"])

    prop = None
    if not s["proposal_absente"]:
        prop = {"side": s["proposal_side"]}

    return {
        "symbol_self": s["symbol"],
        "symbol": s["symbol"],
        "sig": (s["signal"] or "").upper().strip(),
        "profil_actif_maintenant": s["profil_actif"],
        "dans_trading_window": s["dans_window"],
        "session_autorisee": (s["session_ok"] if s["asset_manager"] else True),
        "session_motif": s["session_motif"],
        "positions_ouvertes": (s["positions"] if s["asset_manager"] else []),
        "conflit_correlation": (s["conflit"] if s["asset_manager"] else False),
        "now_ts": ref_time,
        "qr_cooldown_until": ref_time + s["qr_offset_min"] * 60.0,
        "reversal_cooldown_min": s["reversal_cooldown_min"],
        "last_trade_result": ltr,
        "proposal": prop,
        "nb_positions_symbole": s["nb_positions_symbole"],
        "ttl_expiree": ttl_expiree,
        "current_hour_utc": heure,
        "blocked_hours": blocked_hours,
        "allowed_hours": s["allowed_hours"],
        "asia_enabled": s["asia_enabled"],
        "asia_hours": s["asia_hours"],
        "asia_exempt": s["asia_exempt"],
        "est_crypto": est_crypto,
        "score_agr": float(s["score"]),
        "confluence": int(s["confluence"]),
        "tracker_vote": float(s["tracker_vote"]),
        "hard_min_score": hard_min,
        "hard_min_confluence": s["hf_min_confluence"],
        "tracker_contradiction_seuil": s["hf_tracker"],
        "short_penalty": s["short_penalty"],
        "allowed_directions": s["allowed_directions"],
        "daily_loss_evaluable": daily_evaluable,
        "daily_pnl_pct": daily_pnl_pct,
        "daily_limit": s["daily_limit"],
        "session_filter_actif": s["avoid_low_liq"],
        "session_blocked_hours": s["sess_blocked"],
        "crypto_exempt": crypto_exempt,
    }


def _joue_legacy(s: dict, ref_time: float, monkeypatch):
    journal = _Journal()
    stub = _stub_self(s, journal, ref_time)

    mt5 = SimpleNamespace(
        positions_get=lambda symbol=None: (
            [SimpleNamespace(symbol=x) for x in range(s["nb_positions_symbole"])]
            if symbol is not None
            else [SimpleNamespace(symbol=x) for x in s["positions"]]
        ),
        account_info=lambda: (SimpleNamespace(equity=s["balance"] + s["profit"],
                                              balance=s["balance"], profit=s["profit"])
                              if s["compte_present"] else None),
    )

    import utils.config as _uc
    monkeypatch.setattr(_uc, "get_overrides",
                        lambda: {"GLOBAL": {"orchestrator": {
                            "blocked_hours_utc": s["global_blocked"]}}},
                        raising=False)
    _FauxDatetime._now = _base_dt(s)
    monkeypatch.setattr(LEGACY, "datetime", _FauxDatetime, raising=True)

    try:
        res = LEGACY.legacy_guards(
            stub, s["signal"], mt5, journal.comme_logger(),
            lambda x: str(x), lambda x: s["symbol"],
            lambda sym: ref_time + s["qr_offset_min"] * 60.0,
            WHITELIST_OVERRIDE,
        )
        verdict = "PASS" if isinstance(res, dict) else "BLOCK"
    except ValueError as e:
        verdict, res = "RAISE", str(e)
    return verdict, journal


def _joue_nouveau(s: dict, ref_time: float):
    journal = _Journal()
    ctx = _contexte(s, ref_time)
    refus = TG.evaluer(TG.ORDRE, ctx)
    if refus is None:
        return "PASS", journal
    if refus.log:
        journal.logs.append(refus.log)
    if refus.telegram:
        journal.telegram.append(refus.telegram)
    if refus.leve:
        return "RAISE", journal
    return "BLOCK", journal


@pytest.mark.parametrize("graine", list(range(40)))
def test_equivalence_gardes(graine, monkeypatch):
    """
    2000 scenarios par graine, 40 graines = 80 000 comparaisons.
    Toute divergence de verdict ou d'effet Telegram fait echouer le test.
    """
    rnd = random.Random(graine)
    # Le code d'origine appelle time.time() en interne : on ne peut pas le
    # figer sans le modifier. On prend donc l'horloge reelle comme reference
    # et on choisit des decalages a la demi-minute, loin des bornes int().
    ref_time = time.time()

    for i in range(2000):
        s = _tire_scenario(rnd)
        if rnd.random() < 0.4:
            s = _relaxe(s, rnd)
        v_old, j_old = _joue_legacy(s, ref_time, monkeypatch)
        v_new, j_new = _joue_nouveau(s, ref_time)

        assert v_old == v_new, (
            "verdict divergent (graine=%d i=%d)\nscenario=%r\nold=%s new=%s"
            % (graine, i, s, v_old, v_new))
        assert j_old.telegram == j_new.telegram, (
            "Telegram divergent (graine=%d i=%d)\nscenario=%r\nold=%r\nnew=%r"
            % (graine, i, s, j_old.telegram, j_new.telegram))
        # Le log de refus doit exister a l'identique cote origine. On ne
        # compare pas la liste entiere : le code d'origine emet aussi des
        # logs informatifs (REV_COOLDOWN_ZONE, LIQ_PENALTY_ZONE, HARD_FILTER
        # PASS...) qui restent dans l'orchestrateur, pas dans le module.
        for entree in j_new.logs:
            assert entree in j_old.logs, (
                "log de refus absent de l'origine (graine=%d i=%d)\n"
                "scenario=%r\nattendu=%r\norigine=%r"
                % (graine, i, s, entree, j_old.logs))


def test_couverture_des_gardes(monkeypatch):
    """
    Verifie que le tirage declenche reellement chaque garde au moins une
    fois : sans cela, l'equivalence ne prouverait rien sur les gardes
    jamais atteints.
    """
    rnd = random.Random(12345)
    ref_time = time.time()
    vus = set()
    for _ in range(20000):
        s = _tire_scenario(rnd)
        if rnd.random() < 0.4:
            s = _relaxe(s, rnd)
        refus = TG.evaluer(TG.ORDRE, _contexte(s, ref_time))
        if refus:
            vus.add(refus.garde)
    manquants = sorted(set(TG.ORDRE) - vus)
    assert not manquants, "gardes jamais declenches par le tirage : %s" % manquants


# ══════════════════════════════════════════════════════════════════════════
# AJOUT 2026-08-02 — journalisation du garde qui refuse.
# Sans elle, 99,3 % des propositions mouraient sans laisser de trace
# exploitable : impossible de distinguer un filtrage sain d'un blocage.
# ══════════════════════════════════════════════════════════════════════════

def test_chaque_refus_est_journalise(tmp_path, monkeypatch):
    import orchestrator.orchestrator as O

    ecrits = []
    monkeypatch.setattr(O, "_record_guard_event",
                        lambda sym, tag, msg: ecrits.append((sym, tag, msg)))

    faux = SimpleNamespace(
        symbol="XAUUSD",
        _send_telegram=lambda *a, **k: None,
    )
    refus = TG.Refus(garde="hard_min_score", motif="3.9|8.0",
                     log=None, telegram=None, retour=False, leve=None)
    retour = O.Orchestrator._appliquer_refus(faux, refus)

    assert retour is False
    assert ecrits == [("XAUUSD", "garde:hard_min_score", "3.9|8.0")]


def test_les_vingt_gardes_ont_un_nom_journalisable():
    """Un nom vide ou duplique rendrait l'agregation inexploitable."""
    noms = [g.nom for g in TG.GARDES]
    assert len(noms) == len(set(noms)) == 20
    assert all(n and n.replace("_", "").isalnum() for n in noms)
