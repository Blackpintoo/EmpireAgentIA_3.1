# -*- coding: utf-8 -*-
# FICHIER GENERE — NE PAS EDITER A LA MAIN.
# Produit par tools/gen_legacy_guards.py depuis le commit dff6ec7.
# Contient la bande de gardes de execute_trade telle qu'elle etait AVANT
# l'extraction P2, copiee verbatim, rendue executable pour le test
# differentiel tests/test_trade_guards_equivalence.py.
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def legacy_guards(self, signal, _mt5, logger, broker_to_canon, canon_to_broker,
                  get_qr_cooldown, BLACKLIST_OVERRIDE_WHITELIST):
    """Renvoie False si un garde bloque, sinon un dict des variables cles."""
    symbol = self.symbol
    # Re-vérifie la fenêtre au moment de l'exécution
    if not self._is_symbol_profile_active_now():
        self._send_telegram(
            f"⏳ Fenêtre fermée pour {self.symbol} (planning profiles.schedule).",
            kind="status", force=True
        )
        return False
    if not self._is_in_trading_window():
        self._send_telegram(
            f"⏳ Fenêtre fermée pour {self.symbol} (orchestrator.trading_window).",
            kind="status", force=True
        )
        return False

    # --- PHASE 4: Vérification sessions de trading par type d'actif ---
    if self.asset_manager:
        try:
            now = datetime.now(ZoneInfo("Europe/Zurich"))
            allowed, reason = self.asset_manager.is_trading_allowed(self.symbol, now)
            if not allowed:
                self._send_telegram(
                    f"⏰ [PHASE4] Session fermée pour {self.symbol}: {reason}",
                    kind="status", force=True
                )
                logger.info(f"[PHASE4] Trading not allowed for {self.symbol}: {reason}")
                return False
            logger.debug(f"[PHASE4] Trading session OK for {self.symbol}: {reason}")
        except Exception as e:
            logger.warning(f"[PHASE4] Session check failed: {e}, continuing anyway")

        # Vérification des corrélations (éviter de trader symboles corrélés simultanément)
        try:
            # Récupérer les positions ouvertes
            open_positions = []
            positions = _mt5.positions_get() if _mt5 else []
            for pos in positions or []:
                pos_symbol = broker_to_canon(str(getattr(pos, "symbol", "")))
                if pos_symbol:
                    open_positions.append(pos_symbol)

            # Vérifier conflit de corrélation
            if open_positions:
                conflict = self.asset_manager.check_correlation_conflict(self.symbol, open_positions)
                if conflict:
                    self._send_telegram(
                        f"🔗 [PHASE4] Conflit de corrélation pour {self.symbol} (positions: {', '.join(open_positions)})",
                        kind="status", force=True
                    )
                    logger.info(f"[PHASE4] Correlation conflict for {self.symbol} with {open_positions}")
                    return False
        except Exception as e:
            logger.warning(f"[PHASE4] Correlation check failed: {e}, continuing anyway")
    # --- FIN PHASE 4 ---

    # FIX 2026-03-23 R15: Vérification cooldown anti-QUICK_REVERSAL
    if get_qr_cooldown is not None:
        import time as _time_mod
        _qr_until = get_qr_cooldown(symbol)
        if _time_mod.time() < _qr_until:
            _remaining = int((_qr_until - _time_mod.time()) / 60)
            logger.warning(
                f"[COOLDOWN] {symbol}: trade bloqué — cooldown QUICK_REVERSAL "
                f"encore {_remaining} min"
            )
            return False

    sig = (signal or "").upper().strip()

    # ══════════════════════════════════════════════════════════════════════
    # FIX 2026-04-10 R18: REVERSAL COOLDOWN — Anti-whipsaw (corrigé)
    # R17 original ne produisait jamais de log car les symboles LONG only
    # ne peuvent pas avoir de reversal. Ajout de logs debug pour diagnostic.
    # ══════════════════════════════════════════════════════════════════════
    # R19: Confirmation passage dans la zone REVERSAL_COOLDOWN
    logger.info(
        f"[REV_COOLDOWN_ZONE] {symbol}: entrée dans la zone REVERSAL_COOLDOWN — "
        f"last_trade_result={'SET' if getattr(self, '_last_trade_result', None) is not None else 'None'}"
    )
    try:
        _rev_cooldown_min = int(
            (self.cfg.get("orchestrator", {}).get("cooldown", {})
             .get("reversal_cooldown_min", 60))
        )
        if _rev_cooldown_min > 0 and self._last_trade_result is not None:
            _ltr = self._last_trade_result
            _last_dir = _ltr.get("direction", "")
            _last_pnl = float(_ltr.get("pnl", 0))
            _last_ts = float(_ltr.get("close_ts", 0))
            _now_ts = time.time()

            if _last_pnl < 0 and _last_dir and _last_dir != sig and _last_ts > 0:
                _elapsed_min = (_now_ts - _last_ts) / 60.0
                if _elapsed_min < _rev_cooldown_min:
                    _remaining = int(_rev_cooldown_min - _elapsed_min)
                    logger.warning(
                        f"[REVERSAL_COOLDOWN] {symbol}: {sig} bloqué — dernier trade "
                        f"était {_last_dir} (perte ${abs(_last_pnl):.0f}), "
                        f"cooldown encore {_remaining} min"
                    )
                    self._send_telegram(
                        f"🔄 [ANTI-WHIPSAW] {symbol}: {sig} bloqué\n"
                        f"Dernier trade: {_last_dir} (perte)\n"
                        f"Cooldown inversé: encore {_remaining} min",
                        kind="status", force=True
                    )
                    return False
                else:
                    logger.debug(
                        f"[REVERSAL_COOLDOWN] {symbol}: reversal {_last_dir}→{sig} "
                        f"mais cooldown expiré ({_elapsed_min:.0f} min > {_rev_cooldown_min} min) → PASS"
                    )
            elif _last_dir == sig:
                logger.debug(
                    f"[REVERSAL_COOLDOWN] {symbol}: même direction {sig} → pas de reversal → PASS"
                )
            elif _last_pnl >= 0:
                logger.debug(
                    f"[REVERSAL_COOLDOWN] {symbol}: dernier trade {_last_dir} était gagnant → PASS"
                )
        elif self._last_trade_result is None:
            logger.debug(
                f"[REVERSAL_COOLDOWN] {symbol}: aucun trade précédent enregistré → PASS"
            )
    except Exception as _rev_err:
        logger.debug(f"[REVERSAL_COOLDOWN] {symbol}: erreur — {_rev_err}")
    # ══════════════════════════════════════════════════════════════════════
    if sig not in ("LONG", "SHORT"):
        raise ValueError("Signal invalide")

    if not self._last_proposal or self._last_proposal.get("side") != sig:
        logger.error("[EXEC] Aucun payload compatible en mémoire.")
        self._send_telegram("⚠️ Aucun trade prêt à exécuter.", kind="status")
        return False

    # FIX 2026-03-24 R16: Anti-spam — pas de nouveau trade si position déjà ouverte même symbole
    try:
        if _mt5 is not None:
            _existing_pos = _mt5.positions_get(symbol=self.broker_symbol)
            if _existing_pos and len(_existing_pos) > 0:
                logger.info(
                    f"[ANTI_SPAM] {self.symbol}: {len(_existing_pos)} position(s) déjà "
                    f"ouverte(s) → pas de nouvel ordre"
                )
                return False
    except Exception as _asp_err:
        logger.debug(f"[ANTI_SPAM] {self.symbol}: check échoué ({_asp_err}) — PASS")

    # --- TTL ---
    try:
        exp = self._last_proposal.get("expires_at")
        if exp:
            exp_dt = datetime.fromisoformat(exp)
            now_dt = datetime.now(timezone.utc)
            if now_dt > exp_dt:
                # log l'expiration
                self._log_proposal_csv(
                    self._last_proposal.get("side"),
                    self._last_proposal.get("entry"),
                    self._last_proposal.get("sl"),
                    self._last_proposal.get("tp"),
                    self._last_proposal.get("lots"),
                    self._last_proposal.get("score"),
                    self._last_proposal.get("confluence"),
                    self.proposal_ttl_secs,
                    expired=True,
                    executed=False
                )
                self._send_telegram(
                    f"⌛ Proposition expirée pour {self.symbol} → rejet automatique.",
                    kind="status", force=True
                )
                return False
    except Exception:
        pass

    p = self._last_proposal
    self._last_proposal = None  # FIX R16: Consommer la proposal (empêche re-exécution)
    symbol = p["symbol"]          # canonique
    broker_symbol = canon_to_broker(symbol) or self.broker_symbol
    entry = float(p.get("entry", 0.0))
    lots = float(p["lots"])
    sl = float(p["sl"])
    tp = float(p["tp"])
    action = "BUY" if sig == "LONG" else "SELL"

    # ══════════════════════════════════════════════════════════════════════
    # (2026-02-04) HOUR FILTER - Bloquer heures non rentables par symbole
    # Vérifie blocked_hours_utc (blacklist) et allowed_hours_utc (whitelist)
    # (2026-02-11) Logs améliorés avec mode BLACKLIST/WHITELIST explicite
    # ══════════════════════════════════════════════════════════════════════
    current_hour_utc = datetime.now(timezone.utc).hour
    orch_cfg = (self.profile.get("orchestrator") or {})

    # FIX 2026-04-19 D4: Union blacklist globale + locale.
    # FIX 2026-04-30: Sémantique stricte. Seuls les symboles listés dans
    # BLACKLIST_OVERRIDE_WHITELIST peuvent contourner la blacklist globale via
    # leur allowed_hours_utc local (cas XAUUSD documenté). Pour tous les autres
    # symboles, la blacklist globale s'applique inconditionnellement.
    local_blocked = list(orch_cfg.get("blocked_hours_utc", []) or [])
    allowed_hours = orch_cfg.get("allowed_hours_utc", None)
    _global_blocked: list = []
    try:
        from utils.config import get_overrides as _get_overrides
        _ov = _get_overrides() or {}
        _global_blocked = list(
            ((_ov.get("GLOBAL") or {}).get("orchestrator") or {}).get("blocked_hours_utc", []) or []
        )
    except Exception:
        _global_blocked = []

    _sym_upper = (symbol or "").upper()
    if _sym_upper in BLACKLIST_OVERRIDE_WHITELIST:
        # Exception nommée: la whitelist locale a priorité sur la blacklist globale
        _allowed_set = set(allowed_hours or [])
        blocked_hours = sorted(
            (set(local_blocked) | set(_global_blocked)) - _allowed_set
        )
        # Log des heures où l'exception s'applique (heure courante incluse si
        # l'heure était globalement blacklistée mais est autorisée localement)
        _bypass_now = (
            current_hour_utc in _global_blocked
            and current_hour_utc in _allowed_set
            and current_hour_utc not in blocked_hours
        )
        if _bypass_now:
            logger.info(
                f"[HOUR_FILTER][EXCEPTION] {symbol} autorisé sur h{current_hour_utc} "
                f"via allowed_hours_utc local malgré blacklist globale"
            )
    else:
        # Mode strict: union global ∪ local, sans soustraire allowed_local
        blocked_hours = sorted(set(local_blocked) | set(_global_blocked))

    # Détection automatique du mode ([] = pas de restriction, donc pas de whitelist)
    hour_filter_mode = "WHITELIST" if allowed_hours else "BLACKLIST" if blocked_hours else None

    # Mode blacklist: si l'heure est dans blocked_hours
    if blocked_hours and current_hour_utc in blocked_hours:
        logger.info(
            f"[HOUR_FILTER][BLACKLIST] Trade {symbol} bloqué - heure {current_hour_utc}h UTC dans blocked_hours {blocked_hours}"
        )
        self._send_telegram(
            f"⏰ [HOUR FILTER][BLACKLIST] {symbol}: Trade bloqué\n"
            f"Heure actuelle: {current_hour_utc}h UTC\n"
            f"Heures bloquées: {blocked_hours}\n"
            f"→ Trade rejeté",
            kind="status", force=True
        )
        return False

    # Mode whitelist: si allowed_hours existe ET n'est pas vide, et l'heure n'y est pas
    # FIX 2026-03-08: allowed_hours=[] signifie "toutes heures autorisées" (pas de restriction)
    if allowed_hours and current_hour_utc not in allowed_hours:
        logger.info(
            f"[HOUR_FILTER][WHITELIST] Trade {symbol} bloqué - heure {current_hour_utc}h UTC pas dans allowed_hours {allowed_hours}"
        )
        self._send_telegram(
            f"⏰ [HOUR FILTER][WHITELIST] {symbol}: Trade bloqué\n"
            f"Heure actuelle: {current_hour_utc}h UTC\n"
            f"Heures autorisées: {allowed_hours}\n"
            f"→ Trade rejeté",
            kind="status", force=True
        )
        return False

    # Log si le filtre est passé (info pour visibilité)
    if hour_filter_mode:
        logger.info(
            f"[HOUR_FILTER][{hour_filter_mode}] {symbol}: heure {current_hour_utc}h UTC autorisée "
            f"(blocked={blocked_hours}, allowed={allowed_hours})"
        )
    # ══════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # FIX 2026-04-10 R18: ASIA BLOCK — Bloquer entries 00-07 UTC non-crypto
    # Diagnostic 14j: session Asie = -$1,113 (93% des pertes), 13.3% HR
    # ══════════════════════════════════════════════════════════════════════
    try:
        _asia_cfg = (self.cfg.get("orchestrator", {})
                    .get("hard_filters", {})
                    .get("asia_block", {}))
        if _asia_cfg.get("enabled", False):
            _asia_hours = _asia_cfg.get("hours_utc", [0, 1, 2, 3, 4, 5, 6, 7])
            _asia_exempt = _asia_cfg.get("exempt_crypto", True)
            _is_crypto_asia = symbol.upper() in self._hf_crypto_symbols

            if current_hour_utc in _asia_hours and not (_asia_exempt and _is_crypto_asia):
                logger.warning(
                    f"[ASIA_BLOCK] {symbol}: entry bloquée — heure {current_hour_utc}h UTC "
                    f"en session Asie (00-07 UTC). Non-crypto interdit."
                )
                self._send_telegram(
                    f"🌙 [ASIA_BLOCK] {symbol}: entry bloquée\n"
                    f"Heure: {current_hour_utc}h UTC (session Asie)\n"
                    f"→ Seules les cryptos sont autorisées 00-07 UTC",
                    kind="status", force=True
                )
                return False
            elif current_hour_utc in _asia_hours and _asia_exempt and _is_crypto_asia:
                logger.debug(
                    f"[ASIA_BLOCK] {symbol}: crypto exemptée — heure {current_hour_utc}h UTC PASS"
                )
    except Exception as _asia_err:
        logger.debug(f"[ASIA_BLOCK] {symbol}: erreur — {_asia_err}")
    # ══════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # FIX 2026-04-10 R18: LOG PROBATION — Identifier les symboles en probation
    # ══════════════════════════════════════════════════════════════════════
    _is_probation = bool(self.ori_cfg.get("probation", False))
    if _is_probation:
        logger.info(
            f"[PROBATION] {symbol}: symbole en MODE PROBATION — "
            f"restrictions max (1 trade/jour, risk 0.1%, score 7.0+, 4 votes)"
        )
    # ══════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # HARD FILTERS - Qualité minimum absolue (FIX 2025-12-17)
    # Ces filtres ne peuvent PAS être contournés, même par auto_execute
    # ══════════════════════════════════════════════════════════════════════
    score_agr = float(p.get("score", 0.0) or 0.0)
    confluence = int(p.get("confluence", 0) or 0)
    tracker_vote = float(p.get("tracker_vote", 0.0) or 0.0)

    # R17: Adaptive score boost
    _adaptive_boost = self._get_adaptive_score_boost()

    # R18: Pénalité session basse liquidité (corrigé — R17 ne se déclenchait jamais)
    # R19: Confirmation passage dans la zone LIQ_PENALTY
    logger.info(
        f"[LIQ_PENALTY_ZONE] {symbol}: entrée dans la zone LIQ_PENALTY — "
        f"hour={current_hour_utc}, crypto={symbol.upper() in self._hf_crypto_symbols}"
    )
    _liq_penalty = 0.0
    _hf_cfg_r17 = self.cfg.get("orchestrator", {}).get("hard_filters", {})
    _liq_hours = _hf_cfg_r17.get("low_liquidity_hours_utc", [0, 1, 2, 3, 4, 5, 6, 7, 22, 23])
    _is_crypto_r17 = symbol.upper() in self._hf_crypto_symbols
    if not _is_crypto_r17 and current_hour_utc in _liq_hours:
        _liq_penalty = float(_hf_cfg_r17.get("low_liquidity_score_penalty", 2.0))
        logger.info(
            f"[LIQ_PENALTY] {symbol}: heure {current_hour_utc}h UTC → "
            f"penalty +{_liq_penalty} sur min_score"
        )
    else:
        logger.debug(
            f"[LIQ_PENALTY] {symbol}: heure {current_hour_utc}h UTC → "
            f"pas de penalty (crypto={_is_crypto_r17}, in_liq_hours={current_hour_utc in _liq_hours})"
        )

    # 1) HARD FILTER: Score minimum absolu (config: orchestrator.hard_filters.min_score)
    HARD_MIN_SCORE = self._hf_min_score + _adaptive_boost + _liq_penalty
    if _adaptive_boost > 0 or _liq_penalty > 0:
        logger.info(f"[ADAPTIVE_SCORE] {symbol}: min_score ajusté {self._hf_min_score} + adaptive={_adaptive_boost} + liq={_liq_penalty} = {HARD_MIN_SCORE}")
    if score_agr < HARD_MIN_SCORE:
        logger.warning(f"[HARD_FILTER] {symbol}: score {score_agr:.4f} < {HARD_MIN_SCORE} → REJET")
        self._send_telegram(
            f"⛔ [QUALITÉ] {symbol}: score {score_agr:.1f} trop faible (min={HARD_MIN_SCORE}) → rejet",
            kind="status", force=True
        )
        return False

    # 2) HARD FILTER: Confluence minimum absolue (config: orchestrator.hard_filters.min_confluence)
    HARD_MIN_CONFLUENCE = self._hf_min_confluence
    if confluence < HARD_MIN_CONFLUENCE:
        logger.warning(f"[HARD_FILTER] {symbol}: confluence {confluence} < {HARD_MIN_CONFLUENCE} → REJET")
        self._send_telegram(
            f"⛔ [QUALITÉ] {symbol}: confluence {confluence} trop faible (min={HARD_MIN_CONFLUENCE}) → rejet",
            kind="status", force=True
        )
        return False

    # 3) HARD FILTER: Tracker vote contradictoire
    # Si le tracker historique indique que les agents ont mal performé dans cette direction
    TRACKER_CONTRADICTION_THRESHOLD = self._hf_tracker_contradiction
    tracker_contradicts = (
        (sig == "LONG" and tracker_vote < -TRACKER_CONTRADICTION_THRESHOLD) or
        (sig == "SHORT" and tracker_vote > TRACKER_CONTRADICTION_THRESHOLD)
    )
    if tracker_contradicts:
        logger.warning(f"[HARD_FILTER] {symbol}: tracker_vote {tracker_vote:+.2f} contradictoire avec {sig} → REJET")
        self._send_telegram(
            f"⛔ [QUALITÉ] {symbol}: tracker {tracker_vote:+.2f} contradictoire avec {sig} → rejet",
            kind="status", force=True
        )
        return False

    logger.info(f"[HARD_FILTER] {symbol}: PASS score={score_agr:.1f} conf={confluence} tracker={tracker_vote:+.2f}")

    # ══════════════════════════════════════════════════════════════════════
    # FIX 2026-04-03 R17: SHORT PENALTY — Score plus élevé requis pour SHORT
    # Données: SHORT 20.7% HR vs LONG 58.3% HR → asymétrie structurelle
    # ══════════════════════════════════════════════════════════════════════
    _short_penalty = float(
        (self.cfg.get("orchestrator", {}).get("hard_filters", {})
         .get("short_score_penalty", 1.5))
    )
    if sig == "SHORT" and _short_penalty > 0:
        _short_min = HARD_MIN_SCORE + _short_penalty
        if score_agr < _short_min:
            logger.warning(
                f"[SHORT_PENALTY] {symbol}: score {score_agr:.4f} < "
                f"{_short_min:.1f} (base {HARD_MIN_SCORE} + penalty {_short_penalty}) → REJET SHORT"
            )
            self._send_telegram(
                f"⬇️ [SHORT_PENALTY] {symbol}: score {score_agr:.1f} trop faible pour SHORT "
                f"(min={_short_min:.1f}) → rejet",
                kind="status", force=True
            )
            return False
        logger.info(f"[SHORT_PENALTY] {symbol}: score {score_agr:.1f} >= {_short_min:.1f} → SHORT autorisé")
    # ══════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # FIX 2026-02-24: HARD FILTER — Filtre directionnel par symbole (Directive 2)
    # ══════════════════════════════════════════════════════════════════════
    _allowed_dirs = self.ori_cfg.get("allowed_directions")
    if _allowed_dirs is not None and sig not in _allowed_dirs:
        logger.warning(f"[DIRECTION_FILTER] {symbol}: {sig} bloqué — allowed={_allowed_dirs}")
        self._send_telegram(
            f"\U0001f6ab [DIRECTION_FILTER] {symbol}: {sig} bloqué (seuls {_allowed_dirs} autorisés)",
            kind="status", force=True
        )
        return False
    # ══════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # (2026-01-06) HARD FILTER 4: DAILY LOSS LIMIT - Blocage si pertes journalières > 2%
    # Calcule le P&L réel depuis MT5 et bloque si limite atteinte
    # ══════════════════════════════════════════════════════════════════════
    try:
        risk_cfg = self.cfg.get("risk", {})
        daily_limit = float(risk_cfg.get("daily_loss_limit_pct", 0.02))

        if _mt5 and hasattr(_mt5, 'account_info'):
            account_info = _mt5.account_info()
            if account_info:
                equity = float(account_info.equity)
                balance = float(account_info.balance)
                # P&L du jour = équité - balance de début de journée
                # Approximation: utiliser le profit flottant + réalisé du jour
                floating_pnl = float(account_info.profit)
                daily_pnl_pct = floating_pnl / balance if balance > 0 else 0

                if daily_pnl_pct <= -daily_limit:
                    logger.warning(f"[DAILY_LOSS] {symbol}: P&L journalier {daily_pnl_pct:.2%} <= -{daily_limit:.0%} → REJET")
                    self._send_telegram(
                        f"🛑 [DAILY LOSS] {symbol}: Limite journalière atteinte\n"
                        f"P&L: {daily_pnl_pct:.2%} (limite: -{daily_limit:.0%})\n"
                        f"Trading bloqué jusqu'à demain",
                        kind="alert", force=True
                    )
                    return False
    except Exception as e:
        logger.debug(f"[DAILY_LOSS] Erreur calcul: {e}")
    # ══════════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════════
    # (2026-01-06) HARD FILTER 5: SESSION FILTER - Blocage heures toxiques
    # Bloque 0-5h et 18-23h UTC sauf crypto
    # ══════════════════════════════════════════════════════════════════════
    try:
        vol_cfg = self.cfg.get("volatility_filter", {})
        if vol_cfg.get("avoid_low_liquidity", True):
            current_hour_utc = datetime.now(timezone.utc).hour
            # FIX 2026-03-06: heures bloquées différenciées crypto vs forex/indices
            is_crypto = symbol.upper() in self._hf_crypto_symbols
            asset_override = vol_cfg.get("asset_overrides", {}).get("crypto", {})
            crypto_exempt = is_crypto and not asset_override.get("avoid_low_liquidity", False)
            blocked_hours = vol_cfg.get("low_liquidity_hours_utc",
                                        self._hf_blocked_hours if is_crypto else self._hf_blocked_hours_extended)

            if current_hour_utc in blocked_hours and not crypto_exempt:
                logger.warning(f"[SESSION_FILTER] {symbol}: heure {current_hour_utc}h UTC bloquée → REJET")
                self._send_telegram(
                    f"🕐 [SESSION] {symbol}: Heure toxique {current_hour_utc}h UTC\n"
                    f"Trading bloqué 0-5h et 18-23h UTC\n→ Trade rejeté",
                    kind="status", force=True
                )
                return False
    except Exception as e:
        logger.debug(f"[SESSION_FILTER] Erreur: {e}")

    return {
        "verdict": True,
        "sig": sig,
        "symbol": symbol,
        "broker_symbol": broker_symbol,
        "entry": entry,
        "lots": lots,
        "sl": sl,
        "tp": tp,
        "action": action,
        "current_hour_utc": current_hour_utc,
        "blocked_hours": blocked_hours,
        "allowed_hours": allowed_hours,
        "HARD_MIN_SCORE": HARD_MIN_SCORE,
        "score_agr": score_agr,
        "confluence": confluence,
        "tracker_vote": tracker_vote,
    }
