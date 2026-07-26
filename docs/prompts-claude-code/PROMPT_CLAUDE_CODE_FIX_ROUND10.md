# PROMPT CLAUDE CODE — Fix Opérationnel (Round 10)

## Contexte

Après Round 9, le diagnostic du 14 mars révèle :
- ✅ Infrastructure stable (9/9 symboles, 0 erreur COM, 10h31 uptime)
- ✅ Risk cap $300 en place (risques $45/$55, pas d'activation)
- ✅ Score diagnostic OK (975 SCORE_DIAG, pas de biais directionnel bug)
- ⚠️ HARD_FILTER trop strict : 97% de rejet (66 REJECT / 2 PASS)
- ⚠️ Finnhub fallback R9 ne couvre pas `connectors/finnhub_calendar.py`
- ❌ **Outcome tracker toujours cassé** : 0 clôture depuis le 1er mars malgré des dizaines de trades

**Cause racine du outcome tracker** (identifiée) :
Le `_tracked_positions` est un dict en mémoire, jamais persisté sur disque. À chaque redémarrage du bot, le tracker repart à vide. Les positions ouvertes avant le restart sont perdues du tracking. Et les positions qui ont fermé pendant que le bot était arrêté (SL/TP touché overnight) ne sont jamais détectées.

Le retry R9 fonctionne pour le timing intra-session, mais ne résout PAS le problème inter-sessions.

**3 fixes à appliquer :**

---

## FIX 1 — Outcome Tracker : persistance + réconciliation au démarrage ⭐⭐ CRITIQUE

### Architecture de la solution

Deux mécanismes complémentaires :
- **A. Persistance** : Sauvegarder `_tracked_positions` sur disque à chaque poll, recharger au démarrage
- **B. Réconciliation** : Au démarrage, comparer les positions sauvegardées avec les positions MT5 actuelles. Celles qui ont disparu → chercher les deals de clôture dans l'historique MT5 et les enregistrer

### Fichier : `utils/trade_outcome_tracker.py`

### Étape 1a — Ajouter le chemin du fichier de persistance

En haut du fichier, après la ligne `_PM_STATE_PATH = ...` (vers la ligne ~70), ajouter :

```python
# FIX 2026-03-14 R10: Persistance des positions trackées
_TRACKED_STATE_PATH = os.path.join("data", "tracked_positions.json")
```

### Étape 1b — Ajouter les méthodes de persistance dans la classe `TradeOutcomeTracker`

Après la méthode `_load_history` (qui se termine vers la ligne ~285), ajouter ces 2 nouvelles méthodes :

```python
    # =========================================================================
    # PERSISTENCE (FIX 2026-03-14 R10)
    # =========================================================================

    def _save_tracked_state(self) -> None:
        """Persiste _tracked_positions sur disque pour survivre aux redémarrages."""
        try:
            state = {}
            for ticket, pos in self._tracked_positions.items():
                state[str(ticket)] = pos.to_dict()
            Path(_TRACKED_STATE_PATH).parent.mkdir(parents=True, exist_ok=True)
            tmp_path = _TRACKED_STATE_PATH + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, _TRACKED_STATE_PATH)
        except Exception as e:
            logger.debug(f"[OUTCOME] Erreur sauvegarde tracked state: {e}")

    def _load_tracked_state(self) -> Dict[int, TrackedPosition]:
        """Charge les positions trackées depuis le disque (état précédent)."""
        if not os.path.exists(_TRACKED_STATE_PATH):
            return {}
        try:
            with open(_TRACKED_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f) or {}
            result = {}
            for ticket_str, data in state.items():
                try:
                    ticket = int(ticket_str)
                    open_time = None
                    if data.get("open_time"):
                        open_time = datetime.fromisoformat(data["open_time"])
                    result[ticket] = TrackedPosition(
                        ticket=ticket,
                        symbol=data.get("symbol", ""),
                        direction=data.get("direction", "LONG"),
                        volume=float(data.get("volume", 0)),
                        price_open=float(data.get("price_open", 0)),
                        sl=float(data.get("sl", 0)),
                        tp=float(data.get("tp", 0)),
                        open_time=open_time or datetime.now(timezone.utc),
                        magic=int(data.get("magic", 0)),
                        comment=data.get("comment", ""),
                        initial_risk=float(data.get("initial_risk", 0)),
                        initial_volume=float(data.get("initial_volume", 0)),
                    )
                except Exception:
                    continue
            logger.info(f"[OUTCOME] Chargé {len(result)} positions trackées depuis le disque")
            return result
        except Exception as e:
            logger.warning(f"[OUTCOME] Erreur chargement tracked state: {e}")
            return {}
```

### Étape 1c — Ajouter la méthode de réconciliation au démarrage

Après les méthodes de persistance ajoutées à l'étape 1b, ajouter :

```python
    def _reconcile_at_startup(self) -> None:
        """
        Réconciliation au démarrage (FIX R10).

        Compare les positions sauvegardées avec les positions MT5 actuelles.
        Les positions sauvegardées absentes de MT5 → fermées pendant l'arrêt du bot.
        Cherche les deals de clôture et enregistre les résultats.
        """
        saved_positions = self._load_tracked_state()
        if not saved_positions:
            logger.info("[OUTCOME] Pas de positions sauvegardées — skip réconciliation")
            return

        current_positions = self._get_open_positions()
        current_tickets = set(current_positions.keys())

        # Positions qui étaient trackées mais ont disparu de MT5
        closed_during_downtime = set(saved_positions.keys()) - current_tickets

        if not closed_during_downtime:
            logger.info(
                f"[OUTCOME] Réconciliation: {len(saved_positions)} positions sauvegardées, "
                f"toutes encore ouvertes"
            )
            # Restaurer les positions sauvegardées dans le tracking
            for ticket, pos in saved_positions.items():
                if ticket not in self._tracked_positions and ticket not in self._closed_tickets:
                    self._tracked_positions[ticket] = pos
            return

        logger.info(
            f"[OUTCOME] Réconciliation: {len(closed_during_downtime)} positions fermées "
            f"pendant l'arrêt du bot"
        )

        # Récupérer les deals récents (7 jours pour couvrir les weekends)
        deals = self._get_recent_deals(since_days=7)

        reconciled = 0
        for ticket in closed_during_downtime:
            if ticket in self._closed_tickets:
                continue

            original = saved_positions[ticket]
            closing_deals = self._get_closing_deals_for_ticket(ticket, deals)

            if not closing_deals:
                logger.warning(
                    f"[OUTCOME] Réconciliation: deal non trouvé pour #{ticket} "
                    f"{original.symbol} — position perdue"
                )
                continue

            # Traiter la clôture
            if len(closing_deals) > 1:
                outcome = self._aggregate_partial_deals(original, closing_deals)
            else:
                outcome = self._process_closed_position(original, closing_deals[0])

            if outcome:
                self._outcomes.append(outcome)
                self._save_outcome(outcome)
                self._record_to_performance_tracker(outcome, original)
                self._analyze_loss_pattern(outcome, original)
                self._closed_tickets.add(ticket)
                self._total_closed += 1
                self._total_profit += outcome.profit
                reconciled += 1

                logger.info(
                    f"[OUTCOME] Réconciliation: #{ticket} {original.symbol} "
                    f"{outcome.exit_type.upper()} P&L={outcome.profit:.2f} "
                    f"(fermé pendant l'arrêt du bot)"
                )

        # Restaurer les positions encore ouvertes dans le tracking
        for ticket, pos in saved_positions.items():
            if ticket in current_tickets and ticket not in self._tracked_positions:
                self._tracked_positions[ticket] = pos

        logger.info(
            f"[OUTCOME] Réconciliation terminée: {reconciled} clôtures récupérées, "
            f"{len(current_tickets & set(saved_positions.keys()))} positions restaurées"
        )
```

### Étape 1d — Appeler la réconciliation au démarrage

Dans la méthode `start()` (vers la ligne ~934), ajouter l'appel de réconciliation AVANT le lancement du thread.

Chercher :
```python
    def start(self) -> None:
        """Démarre le worker de surveillance."""
        if self._running:
            logger.warning("[OUTCOME] Worker déjà en cours d'exécution")
            return

        if not MT5_AVAILABLE:
            logger.warning("[OUTCOME] MT5 non disponible - mode dégradé")

        self._running = True
        self._session_start = datetime.now(timezone.utc)
```

Remplacer par :
```python
    def start(self) -> None:
        """Démarre le worker de surveillance."""
        if self._running:
            logger.warning("[OUTCOME] Worker déjà en cours d'exécution")
            return

        if not MT5_AVAILABLE:
            logger.warning("[OUTCOME] MT5 non disponible - mode dégradé")

        # FIX 2026-03-14 R10: Réconciliation au démarrage
        try:
            self._reconcile_at_startup()
        except Exception as e:
            logger.warning(f"[OUTCOME] Erreur réconciliation au démarrage: {e}")

        self._running = True
        self._session_start = datetime.now(timezone.utc)
```

### Étape 1e — Sauvegarder l'état à chaque poll

Dans `_poll_and_update()`, à la fin du bloc `try:` principal (juste AVANT `time.sleep`), ajouter la sauvegarde.

Chercher (vers la ligne ~927-931) :
```python
            except Exception as e:
                logger.warning(f"[OUTCOME] Erreur dans la boucle: {e}")

            # Attendre avant le prochain poll
            time.sleep(self.config.poll_interval)
```

Remplacer par :
```python
            except Exception as e:
                logger.warning(f"[OUTCOME] Erreur dans la boucle: {e}")

            # FIX 2026-03-14 R10: Persister l'état à chaque poll
            try:
                self._save_tracked_state()
            except Exception:
                pass

            # Attendre avant le prochain poll
            time.sleep(self.config.poll_interval)
```

### Résultat attendu

1. Au démarrage : le tracker charge les positions sauvegardées du précédent run
2. Il compare avec MT5 : les positions disparues → closures récupérées via `history_deals_get()`
3. Les clôtures overnight sont enregistrées dans `trade_outcomes.csv`
4. Pendant le fonctionnement normal : l'état est sauvegardé à chaque cycle (toutes les 30s)
5. Au prochain redémarrage : le cycle recommence, rien n'est perdu

---

## FIX 2 — HARD_FILTER : baisser min_score de 5.0 à 4.0

### Problème

Le HARD_FILTER rejette 97% des signaux (66 REJECT / 2 PASS). BTCUSD a été rejeté 32 fois avec des scores de 4.2-4.3 avant de finalement passer à 5.1. Le seuil `min_score=5.0` est trop agressif pour les conditions actuelles.

### Solution

**Fichier** : `config/config.yaml`

Chercher dans la section `hard_filters:` :
```yaml
    min_score: 5.0                     # FIX 2026-03-13 R9: 2.5→5.0 (trop permissif, 0% rejet)
```

Remplacer par :
```yaml
    min_score: 4.0                     # FIX 2026-03-14 R10: 5.0→4.0 (97% rejet trop strict)
```

**Logique** : Les scores BTCUSD oscillaient entre 4.2-4.3. Avec un seuil à 4.0, ces signaux passeraient, mais les signaux vraiment faibles (<4.0) seraient toujours filtrés. Taux de rejet attendu : 40-70%.

---

## FIX 3 — Finnhub fallback dans `connectors/finnhub_calendar.py`

### Problème

Le fix R9 couvre `utils/event_guard.py` mais les erreurs 403 viennent principalement de `connectors/finnhub_calendar.py` (3 erreurs/jour). Ce module fait ses propres appels HTTP à Finnhub API.

### Solution

**Fichier** : `connectors/finnhub_calendar.py`

**Étape 3a** — Ajouter un compteur d'erreurs en haut du module (après les imports, avant les classes) :

```python
# FIX 2026-03-14 R10: Finnhub graceful fallback
_finnhub_consecutive_errors: int = 0
_finnhub_max_errors: int = 3
_finnhub_disabled: bool = False
```

**Étape 3b** — Dans la méthode qui fait le `requests.get` (vers la ligne ~172), ajouter un guard en début de méthode :

Identifier la méthode qui contient `requests.get(url, params=params, timeout=10)`. Au tout début de cette méthode, ajouter :

```python
        # FIX 2026-03-14 R10: Skip si Finnhub désactivé après trop d'erreurs
        global _finnhub_consecutive_errors, _finnhub_disabled
        if _finnhub_disabled:
            return []
```

**Étape 3c** — Dans le bloc `except` qui gère les erreurs HTTP (vers la ligne ~185-194), modifier pour comptabiliser :

Trouver le bloc except existant (qui gère `requests.exceptions.HTTPError` ou l'exception générale). Remplacer la logique d'erreur par :

```python
        except requests.exceptions.HTTPError as e:
            global _finnhub_consecutive_errors, _finnhub_disabled
            status = getattr(e.response, 'status_code', 0) if hasattr(e, 'response') else 0
            _finnhub_consecutive_errors += 1
            if _finnhub_consecutive_errors >= _finnhub_max_errors:
                _finnhub_disabled = True
                logger.warning(
                    f"[FINNHUB] Désactivé après {_finnhub_consecutive_errors} erreurs "
                    f"consécutives (HTTP {status}). Utiliser le cache uniquement."
                )
            else:
                logger.debug(f"[FINNHUB] Erreur HTTP {status} ({_finnhub_consecutive_errors}/{_finnhub_max_errors})")
            return []
        except Exception as e:
            _finnhub_consecutive_errors += 1
            if _finnhub_consecutive_errors >= _finnhub_max_errors:
                _finnhub_disabled = True
                logger.warning(
                    f"[FINNHUB] Désactivé après {_finnhub_consecutive_errors} erreurs: {e}"
                )
            else:
                logger.debug(f"[FINNHUB] Erreur {_finnhub_consecutive_errors}/{_finnhub_max_errors}: {e}")
            return []
```

**Important** : en cas de succès (réponse 200), remettre le compteur à zéro. Après la ligne `response.raise_for_status()` et le parsing réussi, ajouter :

```python
            # FIX R10: Reset compteur erreurs sur succès
            _finnhub_consecutive_errors = 0
```

**Résultat** : Après 3 erreurs consécutives (403, timeout, etc.), Finnhub est désactivé pour le reste de la session. Plus de spam d'erreurs dans les logs.

---

## Résumé des 3 fixes

| Fix | Fichier | Criticité | Impact |
|-----|---------|-----------|--------|
| 1 | `utils/trade_outcome_tracker.py` | ⭐⭐ CRITIQUE | Persistance + réconciliation → clôtures enfin enregistrées |
| 2 | `config/config.yaml` | ⭐ IMPORTANT | min_score 5.0→4.0 → ~50% rejet (vs 97%) |
| 3 | `connectors/finnhub_calendar.py` | MINEUR | Finnhub fallback → 0 spam 403 |

## Vérification après modification

```bash
python -m py_compile utils/trade_outcome_tracker.py
python -m py_compile connectors/finnhub_calendar.py
```

Vérifier aussi que le fichier `data/tracked_positions.json` se crée après le premier poll (30s après démarrage).

## Vérification en production

### Test immédiat (au démarrage)

1. **Réconciliation** : chercher `[OUTCOME] Réconciliation` dans les logs.
   - `Réconciliation: N positions fermées pendant l'arrêt du bot` → détection OK
   - `Réconciliation: #{ticket} ... P&L=... (fermé pendant l'arrêt du bot)` → clôture récupérée !
   - `Pas de positions sauvegardées — skip réconciliation` → premier run (normal)

2. **Persistance** : vérifier que `data/tracked_positions.json` existe et contient les positions :
   ```bash
   type data\tracked_positions.json
   ```

### Test après 2-4h de trading

3. **Outcome tracker** : chercher `[OUTCOME] Trade cloture` dans les logs.
   - Vérifier `data/trade_outcomes.csv` contient des entrées post-14 mars.

4. **HARD_FILTER** : compter PASS vs REJECT.
   - Taux rejet attendu : 40-70%.
   - Si >80% : baisser min_score à 3.5.
   - Si <20% : monter à 4.5.

5. **Finnhub** : chercher `[FINNHUB] Désactivé` dans les logs.

### Test après redémarrage (crucial)

6. **Redémarrer le bot** puis immédiatement chercher :
   - `[OUTCOME] Chargé N positions trackées depuis le disque` → persistance OK
   - `[OUTCOME] Réconciliation: N clôtures récupérées` → réconciliation OK
   - Vérifier que `trade_outcomes.csv` a de nouvelles entrées

## RÈGLES

1. **Applique les fixes dans l'ordre 1 → 3.**
2. **Ne change rien d'autre.**
3. **Compile chaque fichier après modification.**
4. **Le FIX 1 est le plus long et le plus important.** Prends le temps de bien placer chaque étape (1a→1e).
5. **Si un fix ne peut pas être appliqué** (code différent), signale-le et passe au suivant.
