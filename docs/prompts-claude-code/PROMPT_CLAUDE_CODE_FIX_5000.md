# Prompt Claude Code — Fix + Optimisation EmpireAgentIA v3 (Objectif 5000$/mois)

Copie-colle le bloc ci-dessous dans Claude Code :

---

```
Tu es chargé de corriger ET optimiser le bot de trading EmpireAgentIA v3.

## CONTEXTE CRITIQUE

Le bot ne prend AUCUN trade à cause de 3 problèmes simultanés :
1. Tous les 9 agents timeout à 10 secondes → score=0, confluence=0
2. Les hard filters exigent score>=8.0 et confluence>=5 (inatteignable)
3. Telegram en boucle d'erreur (474+ retries)

## OBJECTIF DE PERFORMANCE

Objectif : 5000$/mois = ~161$/jour sur 9 symboles (~18$/jour/symbole).
Equity de départ : 1000$.
Actuellement les paramètres sont TROP conservateurs pour atteindre cet objectif :
- max_trades_per_day: 6 (global) → trop peu
- default_max_per_symbol: 2 → trop peu
- cooldown after_trade_min: 8 → trop long
- cooldown after_win_min: 5 → trop long
- Heures bloquées : 12h/24 → perd la moitié des opportunités
- risk_per_trade: 0.3% sur USDJPY et AUDUSD → trop faible pour générer du profit

Applique TOUTES les modifications ci-dessous de manière précise.

---

## PARTIE A — CORRECTIONS CRITIQUES (le bot ne trade PAS sans ça)

### A1. Augmenter le timeout des agents

Fichier : `orchestrator/orchestrator.py`
Chercher `_AGENT_TIMEOUT = 10` (vers la ligne 3938) et remplacer par :
```python
_AGENT_TIMEOUT = 45  # secondes — FIX 2026-03-06: 10s causait 100% timeout
```

### A2. Abaisser les hard filters par défaut

Fichier : `orchestrator/orchestrator.py`
Chercher ces deux lignes (vers les lignes 754-755) :
```python
self._hf_min_score: float = float(_hf.get("min_score", 8.0))
self._hf_min_confluence: int = int(_hf.get("min_confluence", 5))
```
Remplacer par :
```python
self._hf_min_score: float = float(_hf.get("min_score", 2.5))  # FIX 2026-03-06: 8.0 inatteignable
self._hf_min_confluence: int = int(_hf.get("min_confluence", 3))  # FIX 2026-03-06: 5 inatteignable
```

### A3. Ajouter la section hard_filters dans config.yaml

Fichier : `config/config.yaml`
Dans la section `orchestrator:`, juste après la ligne `min_rr_required: 1.2`, ajouter ce bloc (respecter l'indentation de 2 espaces) :

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

### A4. Corriger les seuils USDJPY dans profiles.yaml

Fichier : `config/profiles.yaml`
Dans le profil USDJPY, section `orchestrator:`, chercher :
```yaml
      min_score_for_proposal: 8.0   # NOUVEAU - Score minimum plus élevé
      min_confluence: 5             # NOUVEAU - Plus de confirmation requise
```
Remplacer par :
```yaml
      min_score_for_proposal: 2.5   # FIX 2026-03-06: aligné avec config global (objectif 5000$/mois)
      min_confluence: 3             # FIX 2026-03-06: aligné avec config global
```

### A5. Réduire les timeframes pour éviter les timeouts

Fichier : `config/config.yaml`
Chercher la section `multi_timeframes:` et remplacer :
```yaml
multi_timeframes:
  enabled: true
  tfs: [D1, H4, H1, M30, M5, M1]
  tf_weights:
    D1: 1.2
    H4: 1.1
    H1: 1.0
    M30: 0.9
    M5: 0.8
    M1: 0.7
```
Par :
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

### A6. Réduire le nombre de barres dans les agents

Pour chacun de ces fichiers, chercher la méthode `_get_rates` et changer le paramètre `count` par défaut :

Fichier : `agents/technical.py`
Chercher `def _get_rates(self, timeframe: str, count: int = 300)` → remplacer par `count: int = 150`

Fichier : `agents/scalping.py`
Chercher `def _get_rates(self, timeframe: str, count: int = 250)` → remplacer par `count: int = 150`

Pour `agents/swing.py` et `agents/structure.py` : chercher toute méthode `_get_rates` et si le count par défaut est > 150, le réduire à `count: int = 150`.

---

## PARTIE B — OPTIMISATION PERFORMANCE (objectif 161$/jour)

### B1. Augmenter le nombre de trades autorisés

Fichier : `config/config.yaml`
Chercher et remplacer ces valeurs dans la section `orchestrator:` :

```yaml
  max_trades_per_day: 6
```
→ remplacer par :
```yaml
  max_trades_per_day: 15         # OPT 2026-03-06: 6→15 pour objectif 5000$/mois
```

```yaml
    default_max_per_symbol: 2
```
→ remplacer par :
```yaml
    default_max_per_symbol: 3     # OPT 2026-03-06: 2→3 pour plus d'opportunités
```

Et dans la sous-section `limits:` juste en dessous, remplacer :
```yaml
    limits:
      NAS100: 3                   # Moteur principal - plus de trades
      SP500: 3                    # Moteur principal
      AUDUSD: 2                   # Standard
      XAUUSD: 2                   # Standard
```
Par :
```yaml
    limits:
      NAS100: 4                   # OPT 2026-03-06: Moteur principal
      SP500: 4                    # OPT 2026-03-06: Moteur principal
      XAUUSD: 3                   # OPT 2026-03-06: Or très actif
      BTCUSD: 3                   # OPT 2026-03-06: Bitcoin
      AUDUSD: 3                   # OPT 2026-03-06
```

```yaml
  max_trades_per_hour: 3
```
→ remplacer par :
```yaml
  max_trades_per_hour: 5          # OPT 2026-03-06: 3→5 pour ne pas rater les signaux
```

### B2. Réduire les cooldowns

Fichier : `config/config.yaml`
Dans la section `cooldown:`, remplacer :
```yaml
  cooldown:
    enabled: true
    after_trade_min: 8           # FIX 2026-03-05: ajusté pour débloquer trading
    after_loss_min: 30           # Pause 30 min après une perte
    after_win_min: 5             # FIX 2026-03-05: ajusté pour débloquer trading
    after_reject_min: 5          # AUGMENTÉ 3→5 min après un rejet
    after_streak_n: 3            # Nombre de pertes consécutives pour pause longue
    after_streak_min: 45         # FIX 2026-03-05: ajusté pour débloquer trading
```
Par :
```yaml
  cooldown:
    enabled: true
    after_trade_min: 3           # OPT 2026-03-06: 8→3 min (objectif 5000$/mois)
    after_loss_min: 15           # OPT 2026-03-06: 30→15 min
    after_win_min: 2             # OPT 2026-03-06: 5→2 min (capitaliser sur momentum)
    after_reject_min: 2          # OPT 2026-03-06: 5→2 min
    after_streak_n: 3            # Inchangé - 3 pertes consécutives = pause
    after_streak_min: 30         # OPT 2026-03-06: 45→30 min
```

### B3. Ouvrir les heures de trading

Fichier : `orchestrator/orchestrator.py`
Chercher (vers la ligne 764) :
```python
self._hf_blocked_hours: list = list(_session_cfg.get("blocked_hours_utc", [0,1,2,3,4,5,18,19,20,21,22,23]))
```
Remplacer par :
```python
# FIX 2026-03-06: Heures bloquées réduites — cryptos 24/7, forex/indices horaires étendus
self._hf_blocked_hours: list = list(_session_cfg.get("blocked_hours_utc", [2,3,4]))
self._hf_blocked_hours_forex: list = list(_session_cfg.get("blocked_hours_forex_utc", [0,1,2,3,4,5,22,23]))
```

Ensuite, chercher dans le code de `_run_agents_and_decide` l'endroit où `self._hf_blocked_hours` est utilisé pour bloquer le trading (chercher `_hf_blocked_hours` dans la méthode). Modifier la logique pour que :
- Les symboles crypto (définis dans `self._hf_crypto_symbols` qui contient BTCUSD, ETHUSD, LTCUSD, BNBUSD, ADAUSD, SOLUSD) utilisent `self._hf_blocked_hours` (seules 3 heures bloquées : 2h-4h UTC)
- Les symboles forex et indices utilisent `self._hf_blocked_hours_forex` (8 heures bloquées)

Le code devrait ressembler à ceci — chercher le if qui vérifie l'heure et remplacer la logique :
```python
# Déterminer les heures bloquées selon le type d'actif
_blocked = self._hf_blocked_hours if self.symbol in self._hf_crypto_symbols else getattr(self, '_hf_blocked_hours_forex', self._hf_blocked_hours)
current_hour_utc = datetime.now(timezone.utc).hour
if current_hour_utc in _blocked:
    # ... logique de blocage existante ...
```

### B4. Augmenter le risk_per_trade pour USDJPY et AUDUSD

Fichier : `config/profiles.yaml`

Pour USDJPY (section `risk:`), chercher :
```yaml
      risk_per_trade: 0.003   # RÉDUIT 0.005→0.003 (OPTIMISATION 2025-12-13)
```
Remplacer par :
```yaml
      risk_per_trade: 0.008   # OPT 2026-03-06: 0.003→0.008 (objectif 5000$/mois, reste conservateur)
```

Pour AUDUSD (section `risk:`), chercher :
```yaml
      risk_per_trade: 0.003  # Réduit de 1% à 0.3% (2025-12-08) - symbole problématique
```
Remplacer par :
```yaml
      risk_per_trade: 0.008  # OPT 2026-03-06: 0.003→0.008 (objectif 5000$/mois)
```

### B5. Étendre les heures de dernière entrée (overrides.yaml)

Fichier : `config/overrides.yaml`
Chercher :
```yaml
  eod_close_time_utc: "19:30"
  last_entry_time_utc: "18:00"
```
Remplacer par :
```yaml
  eod_close_time_utc: "21:00"        # OPT 2026-03-06: 19:30→21:00 (couvrir session US)
  last_entry_time_utc: "20:00"       # OPT 2026-03-06: 18:00→20:00 (ne pas couper session US)
```

### B6. Circuit-breaker Telegram (stopper la boucle d'erreur)

Fichier : `utils/telegram_client_async.py`
Chercher la classe principale (AsyncTelegramClient). Dans le `__init__`, ajouter ces attributs :
```python
# FIX 2026-03-06: Circuit-breaker pour éviter boucle d'erreur
self._tg_consecutive_errors = 0
self._tg_max_errors = 10
self._tg_pause_until = 0.0  # timestamp unix
```

Puis trouver la méthode principale d'envoi de message. AVANT chaque tentative d'envoi, ajouter :
```python
import time as _time
if _time.time() < self._tg_pause_until:
    return  # Circuit-breaker actif — en pause
```

APRÈS chaque exception/erreur d'envoi (dans le except), ajouter :
```python
self._tg_consecutive_errors += 1
if self._tg_consecutive_errors >= self._tg_max_errors:
    self._tg_pause_until = _time.time() + 300  # Pause 5 minutes
    logger.warning(f"[TG] Circuit-breaker: {self._tg_consecutive_errors} erreurs → pause 5 min")
    self._tg_consecutive_errors = 0
```

APRÈS chaque envoi réussi, ajouter :
```python
self._tg_consecutive_errors = 0
self._tg_pause_until = 0.0
```

---

## VÉRIFICATION FINALE

Après toutes les modifications :
1. Vérifie la syntaxe Python de tous les fichiers .py modifiés avec `python -c "import ast; ast.parse(open('FICHIER').read())"`
2. Vérifie le YAML avec `python -c "import yaml; yaml.safe_load(open('config/config.yaml')); print('OK')"`
3. Vérifie `python -c "import yaml; yaml.safe_load(open('config/profiles.yaml')); print('OK')"`
4. Vérifie `python -c "import yaml; yaml.safe_load(open('config/overrides.yaml')); print('OK')"`
5. Fais un récapitulatif de TOUS les fichiers modifiés avec un résumé de chaque changement

NE crée PAS de commit automatiquement, attends ma confirmation.
```

---

## Calcul de rentabilité après corrections

Avec les paramètres optimisés :
- 9 symboles actifs × 3 trades/jour/symbole = 27 trades potentiels/jour (plafonné à 15 global)
- Risk 1% de 1000$ = 10$/trade, R:R moyen 2:1
- Win rate estimé 55% → espérance = 0.55×20 - 0.45×10 = $6.50/trade
- 15 trades × $6.50 = **~97$/jour**
- Pour atteindre 161$/jour : augmenter equity progressivement grâce aux gains cumulés
- À 2000$ d'equity (atteint en ~2 semaines) : 15 × $13 = **~195$/jour** → objectif dépassé
