# PROMPT CLAUDE CODE — Fix Opérationnel (Round 11)

## Contexte

Diagnostic post-Round 10 (14 mars) :
- ✅ Outcome tracker persistance R10 fonctionne (JSON créé avec 2 positions)
- ✅ HARD_FILTER à min_score=4.0 donne 70% de rejet (dans la cible)
- ⚠️ Réconciliation R10 skippée (normal : premier run post-R10, pas de données sauvegardées avant)
- ⚠️ Finnhub auto-disable ne se déclenche pas (compteur probablement réinitialisé par les cache hits)
- ❌ PM_PARTIAL_EXEC loop : le Position Manager retente les fermetures partielles de SOLUSD toutes les 20s sans succès, indéfiniment
- ❌ SL discordance : `tracked_positions.json` sauvegarde le SL initial mais pas le SL trailé par le PM
- ❌ Fear & Greed API : 35 timeouts en 1h30 sans backoff

**4 fixes à appliquer :**

---

## FIX 1 — Outcome Tracker : synchroniser SL/TP avec les positions MT5 actuelles

### Problème

Dans `_poll_and_update()`, seul le `volume` est mis à jour quand une position est déjà trackée (ligne ~846). Le SL et le TP ne sont PAS synchronisés. Quand le Position Manager déplace le SL (breakeven, trailing), le tracker garde l'ancien SL. Conséquences :
- `tracked_positions.json` contient un SL obsolète (88.67 vs 87.76 actuel pour SOLUSD)
- Au redémarrage, la réconciliation R10 utilisera le mauvais SL pour détecter l'exit_type

### Solution

**Fichier** : `utils/trade_outcome_tracker.py`

Dans `_poll_and_update()`, chercher le bloc qui met à jour le volume (vers la ligne ~840-846) :

```python
                    # 3. Mettre à jour le volume courant des positions trackées
                    # (le volume diminue après un partial close dans MT5)
                    for ticket, pos in current_positions.items():
                        if ticket in self._tracked_positions:
                            tracked = self._tracked_positions[ticket]
                            # Conserver initial_volume et initial_risk d'origine
                            # mais mettre à jour volume courant pour la détection
                            tracked.volume = pos.volume
```

Remplacer par :
```python
                    # 3. Mettre à jour les positions trackées avec l'état MT5 actuel
                    # FIX 2026-03-14 R11: Synchroniser volume + SL/TP (trailing/BE)
                    for ticket, pos in current_positions.items():
                        if ticket in self._tracked_positions:
                            tracked = self._tracked_positions[ticket]
                            # Conserver initial_volume et initial_risk d'origine
                            # mais mettre à jour volume, SL et TP courants
                            tracked.volume = pos.volume
                            tracked.sl = pos.sl
                            tracked.tp = pos.tp
```

**Résultat** : `tracked_positions.json` reflète toujours le SL/TP actuel de MT5. La réconciliation au redémarrage utilisera les bons prix.

**Note** : `initial_risk` et `initial_volume` restent intacts (calculés à l'ouverture). Seuls les prix SL/TP et le volume courant sont synchronisés.

---

## FIX 2 — PM : limiter les tentatives de fermeture partielle

### Problème

Le Position Manager tente une fermeture partielle de SOLUSD (#980491037) toutes les 20s. La condition `rr_now >= p.rr` est vraie mais `_close_partial()` échoue (probablement erreur MT5). Le niveau R:R n'est pas ajouté à `partials_done`, donc la tentative se répète indéfiniment à chaque cycle.

Cela génère du bruit dans les logs et consomme des appels MT5 COM inutiles.

### Solution

**Fichier** : `utils/position_manager.py`

**Étape 2a** — Ajouter un compteur d'échecs dans l'état par ticket.

Chercher la méthode `_apply_partials` (vers la ligne ~610). Trouver le bloc qui appelle `_close_partial` (vers la ligne ~627) :

```python
                ok = self._close_partial(ticket, to_close)
```

Ajouter un mécanisme de cooldown autour de l'appel. Remplacer le bloc qui contient l'appel `_close_partial` et la gestion du résultat :

Chercher le pattern complet (qui ressemble à) :
```python
                ok = self._close_partial(ticket, to_close)
                if ok:
```

Remplacer ce bloc (du `ok = self._close_partial(...)` jusqu'au `done.add(p.rr)` inclus) par :
```python
                # FIX 2026-03-14 R11: Limiter les tentatives de partial close
                _partial_fail_key = f"partial_fail_{p.rr}"
                _partial_fails = st.get(_partial_fail_key, 0)
                if _partial_fails >= 5:
                    # Abandonner après 5 échecs (~ 100s à 20s/cycle)
                    if _partial_fails == 5:
                        logger.warning(
                            f"[PM] Partial close #{ticket} R:R={p.rr} abandonné "
                            f"après 5 échecs consécutifs"
                        )
                        st[_partial_fail_key] = 6  # Éviter de logger à chaque cycle
                    continue

                ok = self._close_partial(ticket, to_close)
                if ok:
                    st[_partial_fail_key] = 0  # Reset sur succès
```

Et garder le reste du bloc `if ok:` tel quel (ajout à `done`, log, etc.).

**Si la structure exacte est différente**, appliquer le même principe : avant d'appeler `_close_partial`, vérifier un compteur d'échecs dans `st` (le state dict du ticket). Si ≥ 5 échecs, skip avec un warning (une seule fois). Incrémenter le compteur en cas d'échec, le remettre à 0 en cas de succès.

Ajouter AUSSI après le `if ok:` existant un `else:` qui incrémente le compteur :

```python
                else:
                    st[_partial_fail_key] = _partial_fails + 1
                    if _partial_fails < 5:
                        logger.info(
                            f"[PM] Partial close #{ticket} R:R={p.rr} échoué "
                            f"({_partial_fails + 1}/5)"
                        )
```

**Résultat** : Après 5 échecs consécutifs (~100s), le PM arrête de retenter cette fermeture partielle pour ce niveau de R:R. Plus de boucle infinie.

---

## FIX 3 — Finnhub : auto-disable basé sur le temps (remplace le compteur)

### Problème

Le compteur d'erreurs R10 dans `connectors/finnhub_calendar.py` ne fonctionne pas correctement. Le compteur est probablement réinitialisé par les cache hits (le reset `_finnhub_consecutive_errors = 0` sur succès inclut les lectures de cache, pas seulement les appels API réussis).

### Solution

Remplacer le mécanisme compteur par un mécanisme basé sur le temps : après la première erreur 403, désactiver Finnhub pour 1 heure.

**Fichier** : `connectors/finnhub_calendar.py`

**Étape 3a** — Remplacer les variables module-level existantes.

Chercher les variables ajoutées en R10 :
```python
# FIX 2026-03-14 R10: Finnhub graceful fallback
_finnhub_consecutive_errors: int = 0
_finnhub_max_errors: int = 3
_finnhub_disabled: bool = False
```

Remplacer par :
```python
# FIX 2026-03-14 R11: Finnhub disable basé sur le temps (remplace compteur R10)
_finnhub_disabled_until: float = 0.0  # timestamp Unix — 0 = actif
_FINNHUB_DISABLE_DURATION: float = 3600.0  # 1 heure de cooldown après erreur 403
```

**Étape 3b** — Modifier le guard check.

Chercher le guard existant (R10) dans la méthode qui fait l'appel API :
```python
        global _finnhub_consecutive_errors, _finnhub_disabled
        if _finnhub_disabled:
            return []
```

Remplacer par :
```python
        global _finnhub_disabled_until
        if _finnhub_disabled_until > time.time():
            return []
```

**Note** : S'assurer que `import time` est présent en haut du fichier.

**Étape 3c** — Modifier la gestion d'erreur.

Chercher le bloc except qui incrémente le compteur R10. Remplacer toute la logique de compteur par :

```python
        except requests.exceptions.HTTPError as e:
            global _finnhub_disabled_until
            status = getattr(e.response, 'status_code', 0) if hasattr(e, 'response') else 0
            if status in (403, 429):
                _finnhub_disabled_until = time.time() + _FINNHUB_DISABLE_DURATION
                logger.warning(
                    f"[FINNHUB] HTTP {status} — désactivé pour 1h. Cache CSV uniquement."
                )
            else:
                logger.debug(f"[FINNHUB] Erreur HTTP {status}")
            return []
        except Exception as e:
            _finnhub_disabled_until = time.time() + _FINNHUB_DISABLE_DURATION
            logger.warning(f"[FINNHUB] Erreur — désactivé pour 1h: {e}")
            return []
```

**Étape 3d** — Supprimer le reset du compteur sur succès (la ligne `_finnhub_consecutive_errors = 0`). Elle n'est plus nécessaire.

**Résultat** : Dès la première erreur 403, Finnhub est désactivé pendant 1 heure. Plus d'appels inutiles pendant cette période. Après 1 heure, un nouvel essai est fait. Si la clé est toujours invalide, re-désactivation pour 1 heure.

---

## FIX 4 — Fear & Greed API : backoff après timeout

### Problème

L'API Fear & Greed Index génère 35 timeouts en 1h30. Pas de backoff — chaque appel rate et retente au prochain cycle.

Il y a deux endroits qui appellent cette API :
1. `connectors/fear_greed_index.py` (connecteur principal, cache 1h)
2. `agents/sentiment.py` (agent sentiment, appel direct)

### Solution

Appliquer le même pattern de disable temporaire.

**Fichier** : `connectors/fear_greed_index.py`

Ajouter en haut du fichier (après les imports) :
```python
# FIX 2026-03-14 R11: Backoff après timeout
import time as _time_mod
_fg_disabled_until: float = 0.0
_FG_DISABLE_DURATION: float = 1800.0  # 30 min de cooldown après erreur
```

Dans la méthode qui fait le `requests.get` (vers la ligne ~129-133), ajouter le guard en début de méthode :
```python
        global _fg_disabled_until
        if _fg_disabled_until > _time_mod.time():
            return {"error": "API disabled (backoff)", "value": None, "classification": None}
```

Dans le bloc `except` de la même méthode, ajouter :
```python
        except Exception as e:
            global _fg_disabled_until
            _fg_disabled_until = _time_mod.time() + _FG_DISABLE_DURATION
            logger.warning(f"[FearGreed] Erreur API — désactivé 30min: {e}")
            return {"error": str(e), "value": None, "classification": None}
```

**Fichier** : `agents/sentiment.py`

Même pattern. Ajouter après les imports (vers le haut du fichier) :
```python
# FIX 2026-03-14 R11: Backoff Fear & Greed
import time as _time_mod
_fg_api_disabled_until: float = 0.0
```

Dans `fetch_fear_greed()` (vers la ligne ~16-42), ajouter le guard au début :
```python
    global _fg_api_disabled_until
    if _fg_api_disabled_until > _time_mod.time():
        return None, None, None
```

Et dans le bloc except existant :
```python
    except Exception as exc:
        global _fg_api_disabled_until
        _fg_api_disabled_until = _time_mod.time() + 1800.0  # 30 min
        logger.error(f"[SENT] Erreur API FG — backoff 30min: {exc}")
        return None, None, None
```

**Résultat** : Après le premier timeout, plus d'appels à l'API pendant 30 minutes. Réduit les 35 timeouts/1h30 à 3 maximum.

---

## Résumé des 4 fixes

| Fix | Fichier(s) | Criticité | Impact |
|-----|-----------|-----------|--------|
| 1 | `utils/trade_outcome_tracker.py` | IMPORTANT | SL/TP sync → réconciliation précise |
| 2 | `utils/position_manager.py` | IMPORTANT | Partial close loop → max 5 tentatives |
| 3 | `connectors/finnhub_calendar.py` | MINEUR | Disable 1h après 403 (remplace compteur R10) |
| 4 | `connectors/fear_greed_index.py` + `agents/sentiment.py` | MINEUR | Backoff 30min après timeout |

## Vérification après modification

```bash
python -m py_compile utils/trade_outcome_tracker.py
python -m py_compile utils/position_manager.py
python -m py_compile connectors/finnhub_calendar.py
python -m py_compile connectors/fear_greed_index.py
python -m py_compile agents/sentiment.py
```

## Vérification en production

1. **SL/TP sync** : après un trailing par le PM, vérifier que `data/tracked_positions.json` a le nouveau SL.
   ```bash
   type data\tracked_positions.json
   ```
   Comparer le SL avec `data/open_positions.json`. Ils doivent être identiques.

2. **PM partial loop** : chercher `[PM] Partial close` dans les logs.
   - `Partial close #ticket R:R=X échoué (N/5)` → compteur actif
   - `Partial close #ticket R:R=X abandonné après 5 échecs` → loop stoppée
   - Plus de `PM_PARTIAL_EXEC` répétitif toutes les 20s → OK

3. **Finnhub** : chercher `[FINNHUB] HTTP 403 — désactivé pour 1h` dans les logs.
   - 1 seule occurrence (puis silence pendant 1h) → OK
   - Si encore des 403 toutes les heures → OK (re-essai après cooldown, re-disable)

4. **Fear & Greed** : chercher `[FearGreed] Erreur API — désactivé 30min` dans les logs.
   - Nombre de timeouts attendu : ≤ 3/heure (vs 35/1h30 avant)

## IMPORTANT — Test du Outcome Tracker R10

Le vrai test de la persistance R10 se fera au **prochain redémarrage** du bot. Les 2 positions actuelles (SOLUSD + BTCUSD) sont sauvegardées dans `tracked_positions.json` (avec les SL/TP synchronisés grâce au FIX 1 ci-dessus). Quand le bot redémarrera :

1. Si les positions sont encore ouvertes → `[OUTCOME] Réconciliation: N positions sauvegardées, toutes encore ouvertes`
2. Si une position a fermé → `[OUTCOME] Réconciliation: #{ticket} ... P&L=... (fermé pendant l'arrêt du bot)`

C'est le test décisif de toute la série R8-R10. Surveille les logs au prochain restart.

## RÈGLES

1. **Applique les fixes dans l'ordre 1 → 4.**
2. **Ne change rien d'autre.**
3. **Compile chaque fichier après modification.**
4. **Le FIX 2 (PM partial loop) nécessite d'adapter au code exact** — la structure décrite est approximative. Cherche `_close_partial` et `_apply_partials` dans `position_manager.py` et applique le principe du compteur d'échecs.
