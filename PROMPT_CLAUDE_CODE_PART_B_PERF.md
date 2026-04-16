# Prompt Claude Code — Partie B : Optimisation Performance (objectif 5000$/mois)

Copie-colle le bloc ci-dessous dans Claude Code :

---

```
Les corrections critiques (Partie A) ont déjà été appliquées (timeout, hard filters, USDJPY, timeframes, barres agents, heures bloquées, circuit-breaker Telegram).

Maintenant applique les optimisations de PERFORMANCE suivantes. L'objectif est 5000$/mois = 161$/jour avec 9 symboles et 1000$ d'equity de départ.

Actuellement les paramètres sont TROP conservateurs :
- max_trades_per_day: 6 → trop peu pour 161$/jour
- default_max_per_symbol: 2 → trop peu
- cooldowns trop longs (8 min après trade, 5 min après win)
- risk_per_trade à 0.3% sur USDJPY et AUDUSD → insuffisant
- Dernière entrée à 18h UTC → coupe la session US

Applique TOUTES les modifications ci-dessous.

---

## 1. Augmenter le nombre de trades autorisés

Fichier : `config/config.yaml`

Dans la section `orchestrator:`, chercher et remplacer :

```yaml
  max_trades_per_day: 6          # 2026-01-26: 10→6 - Moins de trades = moins d'exposition
```
Par :
```yaml
  max_trades_per_day: 15         # OPT 2026-03-06: 6→15 pour objectif 5000$/mois
```

Chercher et remplacer :
```yaml
    default_max_per_symbol: 2     # Par défaut: max 2 trades/jour/symbole
```
Par :
```yaml
    default_max_per_symbol: 3     # OPT 2026-03-06: 2→3 pour plus d'opportunités
```

Chercher et remplacer la sous-section `limits:` :
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

Chercher et remplacer :
```yaml
  max_trades_per_hour: 3          # 2026-01-26: 5→3 - Moins de concentration
```
Par :
```yaml
  max_trades_per_hour: 5          # OPT 2026-03-06: 3→5 pour ne pas rater les signaux
```

## 2. Réduire les cooldowns

Fichier : `config/config.yaml`

Chercher et remplacer le bloc `cooldown:` complet :
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

## 3. Augmenter le risk_per_trade sur USDJPY et AUDUSD

Fichier : `config/profiles.yaml`

Dans le profil USDJPY, section `risk:`, chercher :
```yaml
      risk_per_trade: 0.003   # RÉDUIT 0.005→0.003 (OPTIMISATION 2025-12-13)
```
Remplacer par :
```yaml
      risk_per_trade: 0.008   # OPT 2026-03-06: 0.003→0.008 (objectif 5000$/mois)
```

Dans le profil AUDUSD, section `risk:`, chercher :
```yaml
      risk_per_trade: 0.003  # Réduit de 1% à 0.3% (2025-12-08) - symbole problématique
```
Remplacer par :
```yaml
      risk_per_trade: 0.008  # OPT 2026-03-06: 0.003→0.008 (objectif 5000$/mois)
```

## 4. Étendre la session US (heures de dernière entrée)

Fichier : `config/overrides.yaml`

Chercher :
```yaml
  eod_close_time_utc: "19:30"
  last_entry_time_utc: "18:00"
```
Remplacer par :
```yaml
  eod_close_time_utc: "21:00"        # OPT 2026-03-06: couvrir fin de session US
  last_entry_time_utc: "20:00"       # OPT 2026-03-06: ne pas couper session US
```

## 5. Augmenter le cooldown_after_loss_minutes global

Fichier : `config/config.yaml`

Chercher :
```yaml
  cooldown_after_loss_minutes: 30  # Pause 30 min après une perte
```
Remplacer par :
```yaml
  cooldown_after_loss_minutes: 15  # OPT 2026-03-06: 30→15 min (aligné avec cooldown.after_loss_min)
```

---

## VÉRIFICATION

1. Vérifie le YAML : `python -c "import yaml; yaml.safe_load(open('config/config.yaml')); print('config.yaml OK')"`
2. Vérifie le YAML : `python -c "import yaml; yaml.safe_load(open('config/profiles.yaml')); print('profiles.yaml OK')"`
3. Vérifie le YAML : `python -c "import yaml; yaml.safe_load(open('config/overrides.yaml')); print('overrides.yaml OK')"`
4. Fais un récapitulatif de TOUS les fichiers modifiés

NE crée PAS de commit, attends ma confirmation.
```
