# Prompt Claude Code — Fix EmpireAgentIA v3

Copie-colle ce qui suit dans Claude Code :

---

```
Tu es chargé de corriger le bot de trading EmpireAgentIA v3 qui ne prend AUCUN trade. Voici le diagnostic complet et les corrections à appliquer. Applique TOUTES les modifications ci-dessous de manière précise.

## CONTEXTE

Le bot a 3 problèmes critiques simultanés :
1. Tous les 9 agents timeout à 10 secondes (score=0, confluence=0)
2. Les hard filters exigent score>=8.0 et confluence>=5 (inatteignable)
3. Telegram en boucle d'erreur (474+ retries)

## CORRECTION 1 — Augmenter le timeout des agents

Fichier : `orchestrator/orchestrator.py`
Ligne ~3938 : remplacer `_AGENT_TIMEOUT = 10` par `_AGENT_TIMEOUT = 45`

## CORRECTION 2 — Abaisser les hard filters par défaut

Fichier : `orchestrator/orchestrator.py`
Ligne ~754 : remplacer `self._hf_min_score: float = float(_hf.get("min_score", 8.0))` par `self._hf_min_score: float = float(_hf.get("min_score", 2.5))`
Ligne ~755 : remplacer `self._hf_min_confluence: int = int(_hf.get("min_confluence", 5))` par `self._hf_min_confluence: int = int(_hf.get("min_confluence", 3))`

## CORRECTION 3 — Ajouter la section hard_filters dans config.yaml

Fichier : `config/config.yaml`
Dans la section `orchestrator:` (après la ligne `min_rr_required: 1.2`), ajouter :

```yaml
  hard_filters:
    min_score: 2.5
    min_confluence: 3
    min_rr: 1.2
    tracker_contradiction: 0.25
    disagree_block_pct: 0.45
    disagree_penalty_pct: 0.35
    counter_trend_min_score: 6.0
    quiet_block_confidence: 0.7
```

## CORRECTION 4 — Corriger les seuils USDJPY dans profiles.yaml

Fichier : `config/profiles.yaml`
Dans le profil USDJPY (section `orchestrator:`), remplacer :
```yaml
      min_score_for_proposal: 8.0   # NOUVEAU - Score minimum plus élevé
      min_confluence: 5             # NOUVEAU - Plus de confirmation requise
```
par :
```yaml
      min_score_for_proposal: 2.5   # FIX 2026-03-06: aligné avec config global
      min_confluence: 3             # FIX 2026-03-06: aligné avec config global
```

## CORRECTION 5 — Réduire les timeframes pour éviter les timeouts

Fichier : `config/config.yaml`
Remplacer la section `multi_timeframes:` :
```yaml
multi_timeframes:
  enabled: true
  tfs: [D1, H4, H1, M30, M5, M1]
```
par :
```yaml
multi_timeframes:
  enabled: true
  tfs: [H4, H1, M15, M5]
  tf_weights:
    H4: 1.2
    H1: 1.1
    M15: 1.0
    M5: 0.9
```

## CORRECTION 6 — Réduire le nombre de barres dans les agents

Fichier : `agents/technical.py`
Dans la méthode `_get_rates`, remplacer le paramètre par défaut `count: int = 300` par `count: int = 150`

Fichier : `agents/scalping.py`
Dans la méthode `_get_rates`, remplacer le paramètre par défaut `count: int = 250` par `count: int = 150`

Fichier : `agents/swing.py`
Chercher toute méthode `_get_rates` et remplacer le count par défaut par `count: int = 150`

Fichier : `agents/structure.py`
Chercher toute méthode `_get_rates` et remplacer le count par défaut par `count: int = 150`

## CORRECTION 7 — Différencier les heures bloquées crypto vs forex

Fichier : `orchestrator/orchestrator.py`
Ligne ~764 : remplacer :
```python
self._hf_blocked_hours: list = list(_session_cfg.get("blocked_hours_utc", [0,1,2,3,4,5,18,19,20,21,22,23]))
```
par :
```python
self._hf_blocked_hours: list = list(_session_cfg.get("blocked_hours_utc", [0,1,2,3,4,5]))
self._hf_blocked_hours_extended: list = list(_session_cfg.get("blocked_hours_extended_utc", [0,1,2,3,4,5,22,23]))
```

Puis, dans la méthode qui vérifie les heures bloquées (chercher `_hf_blocked_hours` dans le code de décision), adapter la logique pour utiliser `_hf_blocked_hours` pour les cryptos et `_hf_blocked_hours_extended` pour forex/indices/commodities. Les cryptos sont identifiées par `self._hf_crypto_symbols` (déjà défini ligne ~765).

## CORRECTION 8 — Ajouter un circuit-breaker Telegram

Fichier : `utils/telegram_client_async.py`
Au début de la classe, ajouter un compteur d'erreurs :
```python
self._consecutive_errors = 0
self._max_consecutive_errors = 10
self._error_pause_until = None
```

Dans la méthode d'envoi, avant chaque tentative, vérifier :
```python
import time
if self._error_pause_until and time.time() < self._error_pause_until:
    return  # En pause après trop d'erreurs
```

Après chaque erreur :
```python
self._consecutive_errors += 1
if self._consecutive_errors >= self._max_consecutive_errors:
    self._error_pause_until = time.time() + 300  # Pause 5 minutes
    logger.warning(f"[TG] {self._consecutive_errors} erreurs consécutives — pause 5 min")
    self._consecutive_errors = 0
```

Après chaque succès :
```python
self._consecutive_errors = 0
self._error_pause_until = None
```

## VÉRIFICATION

Après toutes les modifications :
1. Vérifie qu'il n'y a pas d'erreur de syntaxe Python dans les fichiers modifiés
2. Vérifie que le YAML est valide dans config.yaml et profiles.yaml
3. Fais un récapitulatif des fichiers modifiés

Ne crée PAS de commit automatiquement, attends ma confirmation.
```

---
