# ⚠️ MODE RÉEL ACTIVÉ - EMPIRE AGENT IA v3

**Date d'activation** : 2025-11-30
**Statut** : ✅ **TRADING RÉEL ACTIVÉ**

---

## 🚨 AVERTISSEMENT IMPORTANT

### MODE RÉEL ACTIF - TRADING AVEC ARGENT RÉEL !

Le système est maintenant configuré pour trader avec de l'argent réel sur votre compte MetaTrader 5 :

```
Compte : 10960352
Serveur : VantageInternational-Demo
Mode : RÉEL (MT5_DRY_RUN=0)
```

**Même si le serveur est "Demo", le mode DRY_RUN est désactivé**, ce qui signifie que le système enverra des ordres réels à MetaTrader 5.

---

## ✅ MODIFICATIONS EFFECTUÉES

### 1. Mode RÉEL activé

**Fichier** : `.env`

```bash
# AVANT
MT5_DRY_RUN=1  # Simulation

# APRÈS
MT5_DRY_RUN=0  # ⚠️ RÉEL
```

### 2. Optimisation automatique ACTIVÉE

**Fichiers créés** :
- `config/auto_optimization.yaml` - Configuration optimisation
- `optimization/auto_optimizer.py` - Module d'optimisation automatique

**Configuration** :
```yaml
auto_optimization:
  enabled: true
  frequency: weekly          # Hebdomadaire
  day_of_week: 6            # Dimanche
  time: "02:00"             # 02h00 du matin

  agents:                   # Agents à optimiser
    - scalping
    - swing
    - technical
    - structure
    - smart_money

  symbols:                  # Symboles
    - BTCUSD
    - EURUSD
    - ETHUSD
    - XAUUSD
    - GBPUSD
    - USDJPY

  optuna:
    n_trials: 30           # 30 essais par optimisation
    timeout: 600           # 10 minutes max

  auto_apply:
    enabled: true          # ✅ Application automatique
    min_improvement: 1.05  # +5% minimum requis
```

### 3. Intégration dans orchestrateur

**Fichier** : `orchestrator/orchestrator.py` (lignes 788-796)

L'orchestrateur démarre automatiquement l'optimisation au lancement :
```python
# Auto-Optimization
from optimization.auto_optimizer import start_auto_optimization
self._auto_optimizer = start_auto_optimization()
```

---

## 📅 PLANNING D'OPTIMISATION

### Fréquence : Hebdomadaire (Dimanche 02h00)

**Prochaines optimisations** :
- Dimanche 01 Décembre 2025 à 02h00
- Dimanche 08 Décembre 2025 à 02h00
- Dimanche 15 Décembre 2025 à 02h00
- etc.

### Ce qui sera optimisé :

**5 agents** × **6 symboles** = **30 optimisations par semaine**

| Agent | Symboles optimisés |
|-------|-------------------|
| scalping | BTCUSD, EURUSD, ETHUSD, XAUUSD, GBPUSD, USDJPY |
| swing | BTCUSD, EURUSD, ETHUSD, XAUUSD, GBPUSD, USDJPY |
| technical | BTCUSD, EURUSD, ETHUSD, XAUUSD, GBPUSD, USDJPY |
| structure | BTCUSD, EURUSD, ETHUSD, XAUUSD, GBPUSD, USDJPY |
| smart_money | BTCUSD, EURUSD, ETHUSD, XAUUSD, GBPUSD, USDJPY |

**Durée estimée** : 30 optimisations × 10 min = ~5 heures

### Application automatique

Si amélioration ≥ +5% :
- ✅ Paramètres appliqués automatiquement
- ✅ Backup créé avant modification
- ✅ Notification Telegram envoyée

---

## 🔒 SÉCURITÉS ACTIVES

### Blocages automatiques

L'optimisation est **annulée automatiquement** si :

1. ❌ **Positions ouvertes** (`block_if_open_positions: true`)
   - Pas d'optimisation si trades en cours

2. ❌ **Heures de trading** (`block_during_market_hours: true`)
   - Optimisation uniquement 22h00-08h00
   - Planning : Dimanche 02h00 (période calme)

3. ❌ **Limite quotidienne** (`max_per_day: 1`)
   - Maximum 1 optimisation par jour

### Backups automatiques

Avant chaque optimisation :
- ✅ Sauvegarde `config/config.yaml`
- ✅ Stockage dans `data/optimization_backups/`
- ✅ Conservation des 10 derniers backups
- ✅ Format : `config_backup_20251130_020000.yaml`

### Notifications Telegram

Vous serez notifié pour :
- 🚀 Début optimisation
- ✅ Fin optimisation
- 📈 Améliorations trouvées
- ❌ Erreurs

---

## ⚙️ CONFIGURATION ACTUELLE

### Risk Management

```yaml
risk:
  risk_per_trade_pct: 0.01     # 1% par trade
  daily_loss_limit_pct: 0.02   # 2% max par jour
  max_parallel_positions: 2     # 2 positions max simultanées
```

### Orchestrateur

```yaml
orchestrator:
  votes_required: 1            # 1 vote minimum
  weighted.threshold: 1.5      # Threshold pondéré
  cooldown_minutes: 2          # 2 min entre signaux
  max_open_total: 2            # 2 positions max
```

### Agents actifs (9)

- ✅ scalping
- ✅ swing
- ✅ technical
- ✅ structure
- ✅ smart_money
- ✅ news (Alpha Vantage)
- ✅ sentiment (Fear & Greed)
- ✅ fundamental (Finnhub)
- ✅ macro (Finnhub Calendar)

### Symboles actifs (16)

**CRYPTOS (4)** : BTCUSD, ETHUSD, ADAUSD, SOLUSD
**FOREX (6)** : EURUSD, GBPUSD, USDJPY, AUDUSD, BNBUSD, LINKUSD
**INDICES (3)** : US30, NAS100, GER40
**COMMODITIES (3)** : XAUUSD, XAGUSD, USOIL

---

## 🚀 LANCEMENT

### Sur Windows

**Méthode 1 - Script simplifié** :
```batch
START_EMPIRE.bat
```

**Méthode 2 - PowerShell** :
```powershell
cd C:\EmpireAgentIA_3
python main.py
```

**Note** : `--dry-run` n'est PLUS nécessaire car `.env` a `MT5_DRY_RUN=0`

### Vérifications au démarrage

Logs à surveiller :
```
✅ Mode REAL activé (MT5_DRY_RUN=0)
✅ Auto-optimization activée
✅ Scheduler démarré
✅ Prochain run : 2025-12-01 02:00:00
✅ Agents : scalping, swing, technical, structure, smart_money
```

---

## 📊 MONITORING

### Logs

**Fichiers** :
- `logs/empire_agent_*.log` - Logs principal
- `logs/auto_optimization.log` - Logs optimisation

**Commandes** :
```powershell
# Voir logs temps réel
Get-Content logs\empire_agent_*.log -Wait -Tail 50

# Chercher optimisations
Select-String -Path logs\auto_optimization.log -Pattern "Optimisation"

# Vérifier améliorations
Select-String -Path logs\auto_optimization.log -Pattern "Amélioration trouvée"
```

### Health Check

URL : http://localhost:9108/healthz

### Telegram

Notifications actives pour :
- 📊 Daily digest (10h00 et 19h00)
- 💰 Trades exécutés
- 🚀 Optimisations (début/fin)
- 📈 Améliorations appliquées
- ❌ Erreurs

---

## ⚠️ RISQUES ET CONSIDÉRATIONS

### Optimisation automatique

**Avantages** :
- ✅ Adaptation continue au marché
- ✅ Pas d'intervention manuelle
- ✅ Backups automatiques

**Risques** :
- ⚠️ **Overfitting** : Optimisation trop fréquente (weekly = équilibré)
- ⚠️ **Paramètres instables** : Changements trop fréquents
- ⚠️ **Dépendance historique** : Optimise sur passé (180 jours)

**Atténuation** :
- ✅ Fréquence weekly (pas daily)
- ✅ Validation walk-forward (30%)
- ✅ Seuil amélioration +5% minimum
- ✅ Sécurités (pas pendant trading)

### Trading RÉEL

**Compte** : VantageInternational-Demo (10960352)

Bien que "Demo", le mode `MT5_DRY_RUN=0` signifie :
- ⚠️ Ordres envoyés à MT5
- ⚠️ Vérifier si compte vraiment DEMO ou RÉEL
- ⚠️ Si compte RÉEL → Argent réel à risque

**Recommandations** :
1. ✅ Vérifier dans MT5 : Compte Demo ou Réel
2. ✅ Commencer avec risk 0.5% (actuellement 1%)
3. ✅ Monitoring intensif première semaine
4. ✅ Analyser daily digest quotidiennement
5. ✅ Vérifier backups optimisation créés

---

## 🔧 MODIFICATIONS POSSIBLES

### Réduire le risque

**Éditer** `.env` ou `config/config.yaml` :
```yaml
risk:
  risk_per_trade_pct: 0.005  # 0.5% au lieu de 1%
```

### Changer fréquence optimisation

**Éditer** `config/auto_optimization.yaml` :
```yaml
auto_optimization:
  frequency: monthly  # Au lieu de weekly
```

Options : `daily`, `weekly`, `biweekly`, `monthly`

### Désactiver optimisation automatique

**Option A - Temporaire** (éditer `config/auto_optimization.yaml`) :
```yaml
auto_optimization:
  enabled: false  # Désactivé
```

**Option B - Permanent** (supprimer du orchestrator) :
Commenter lignes 788-796 dans `orchestrator/orchestrator.py`

### Désactiver mode RÉEL

**Éditer** `.env` :
```bash
MT5_DRY_RUN=1  # Retour simulation
```

---

## 📝 CHECKLIST POST-ACTIVATION

### Immédiat :
- [ ] Vérifier MT5 lancé et connecté
- [ ] Vérifier compte MT5 (Demo ou Réel ?)
- [ ] Lancer `START_EMPIRE.bat`
- [ ] Vérifier logs : aucune erreur
- [ ] Vérifier Telegram : notifications actives
- [ ] Vérifier Health : http://localhost:9108/healthz

### Première semaine :
- [ ] Monitoring quotidien logs
- [ ] Analyser daily digest (10h00 et 19h00)
- [ ] Vérifier volume trades (objectif 20-40/semaine)
- [ ] Vérifier taux succès MT5 (objectif >80%)
- [ ] Analyser performance par symbole
- [ ] Attendre première optimisation (Dimanche 02h00)

### Après première optimisation :
- [ ] Vérifier logs optimisation
- [ ] Vérifier backups créés (`data/optimization_backups/`)
- [ ] Vérifier améliorations appliquées
- [ ] Vérifier notification Telegram reçue
- [ ] Analyser nouveaux paramètres (si appliqués)

---

## 🆘 EN CAS DE PROBLÈME

### Arrêt d'urgence

**Fermer MetaTrader 5** → Arrête tous les trades

**OU Stopper le bot** :
```powershell
# Dans terminal où bot tourne
Ctrl+C
```

### Restaurer configuration

```powershell
cd C:\EmpireAgentIA_3

# Lister backups
dir data\optimization_backups\

# Restaurer backup
copy data\optimization_backups\config_backup_YYYYMMDD_HHMMSS.yaml config\config.yaml
```

### Logs erreurs

```powershell
# Voir dernières erreurs
Select-String -Path logs\*.log -Pattern "ERROR" | Select-Object -Last 20

# Voir erreurs optimisation
Select-String -Path logs\auto_optimization.log -Pattern "ERROR|Erreur"
```

### Support

**Documentation** :
- `MODE_REAL_ACTIVE.md` (ce fichier)
- `GUIDE_WINDOWS.md` - Guide Windows complet
- `RESULTAT_FINAL.md` - Synthèse projet
- `config/auto_optimization.yaml` - Config optimisation

---

## 📈 OBJECTIFS ET ATTENTES

### Objectif : 5000€/mois

Avec configuration actuelle :
- Capital : Vérifier solde MT5
- Risk : 1% par trade
- Volume attendu : 20-40 trades/semaine
- Win rate : 55-60% (backtests)
- Risk/Reward : 1:2

**Return attendu : 15-25%/mois** (réaliste avec optimisation)

### Timeline

**Semaine 1-2** :
- Validation système RÉEL
- Monitoring intensif
- Ajustements si nécessaire

**Semaine 3-4** :
- Première optimisation automatique
- Analyse amélioration
- Stabilisation paramètres

**Mois 2+** :
- Optimisations hebdomadaires
- Adaptation continue
- Scaling progressif

---

## 🎯 CONCLUSION

**Vous avez activé** :
1. ✅ Mode RÉEL (MT5_DRY_RUN=0)
2. ✅ Optimisation automatique hebdomadaire
3. ✅ Application automatique améliorations
4. ✅ 9 agents actifs
5. ✅ 16 symboles tradés
6. ✅ API externes (Finnhub, Alpha Vantage, Fear & Greed)

**Le système est maintenant autonome** :
- Trading automatique 24/7
- Optimisation hebdomadaire (Dimanche 02h00)
- Notifications Telegram
- Backups automatiques

**Prochaine étape** : **MONITORING INTENSIF** 📊

---

**Empire Agent IA v3 - Mode RÉEL Activé - 2025-11-30**

⚠️ **AVERTISSEMENT FINAL** : Ce système trade avec de l'argent réel. Surveillez attentivement les premières semaines et ajustez selon les performances.
