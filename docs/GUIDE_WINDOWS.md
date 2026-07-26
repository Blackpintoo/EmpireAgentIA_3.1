# 🪟 GUIDE DE LANCEMENT WINDOWS - EMPIRE AGENT IA v3

**Date** : 2025-11-30

---

## 🚀 LANCEMENT RAPIDE (2 MÉTHODES)

### Méthode 1 : Nouveau script simplifié (RECOMMANDÉ)

**Fichier** : `START_EMPIRE.bat` (créé aujourd'hui)

1. **Double-cliquer** sur `START_EMPIRE.bat`
2. Le script vérifie automatiquement :
   - ✅ Python installé
   - ✅ Dépendances présentes
   - ✅ Configuration (.env, config.yaml)
   - ✅ MetaTrader5 disponible
3. Lance le bot en mode **DRY-RUN** (simulation)

**Avantages** :
- ✅ Vérifications automatiques
- ✅ Installation dépendances si manquantes
- ✅ Messages clairs en français
- ✅ Gestion erreurs

### Méthode 2 : Ancien script

**Fichier** : `start-empire.bat` (ancien système)

⚠️ **ATTENTION** : Ce script :
- Utilise `scripts\start_empire.py` (ancien système)
- Lance en mode **REAL** par défaut (argent réel !)
- Nécessite des fichiers de configuration spécifiques

**Recommandation** : Utilisez `START_EMPIRE.bat` (nouveau)

---

## 📋 ÉTAPES DÉTAILLÉES (Première utilisation)

### ÉTAPE 1 : Prérequis Windows

**1.1 - Installer Python pour Windows**

Si Python n'est pas déjà installé :
1. Télécharger : https://www.python.org/downloads/
2. **IMPORTANT** : Cocher ☑️ "Add Python to PATH" pendant l'installation
3. Installer Python (version 3.10 ou 3.11 recommandée)

**Vérifier installation** :
```powershell
python --version
# Devrait afficher : Python 3.10.x ou 3.11.x
```

**1.2 - Installer MetaTrader 5 (optionnel pour tests)**

Pour trading RÉEL uniquement :
1. Télécharger : https://www.metatrader5.com/
2. Installer MT5
3. Créer/configurer compte (VantageInternational-Demo ou autre courtier)

**Note** : Pas nécessaire pour tester les API externes ou développer

---

### ÉTAPE 2 : Configuration

**2.1 - Vérifier/Créer .env**

Si `.env` n'existe pas, le script `START_EMPIRE.bat` le créera depuis `.env.example`.

**Éditer** `.env` avec vos valeurs :
```bash
# META TRADER 5
MT5_ACCOUNT=10960352
MT5_PASSWORD=votre_mot_de_passe
MT5_SERVER=VantageInternational-Demo

# Mode (0=REAL, 1=SIMULATION)
MT5_DRY_RUN=1

# TELEGRAM
TELEGRAM_TOKEN=votre_token
TELEGRAM_CHAT_ID=votre_chat_id

# API EXTERNES
FINNHUB_API_KEY=d4lc3o1r01qt7v19s4a0d4lc3o1r01qt7v19s4ag
ALPHA_VANTAGE_API_KEY=F7Z2Q1U4SPFS9BOS
```

**2.2 - Installer dépendances**

Dans PowerShell ou CMD :
```powershell
cd C:\EmpireAgentIA_3
pip install -r requirements.txt
```

OU laissez `START_EMPIRE.bat` les installer automatiquement.

---

### ÉTAPE 3 : Lancement

**3.1 - Double-cliquer sur `START_EMPIRE.bat`**

**3.2 - OU lancer depuis PowerShell** :
```powershell
cd C:\EmpireAgentIA_3
.\START_EMPIRE.bat
```

**3.3 - OU lancer Python directement** :
```powershell
cd C:\EmpireAgentIA_3
python main.py --dry-run
```

---

## 🎯 MODES DE FONCTIONNEMENT

### Mode DRY-RUN (Simulation) - PAR DÉFAUT

**Configuration** : `MT5_DRY_RUN=1` dans `.env`

**Ce qui fonctionne** :
- ✅ Tests API externes (Finnhub, Alpha Vantage, Fear & Greed)
- ✅ Agents de trading (signaux générés)
- ✅ Orchestrateur (voting system)
- ✅ Telegram notifications
- ✅ Logs complets
- ✅ Health monitoring (http://localhost:9108/healthz)

**Ce qui NE fonctionne PAS** :
- ❌ Connexion MT5 réelle
- ❌ Ordres envoyés au courtier
- ❌ Argent réel

**Utilité** :
- Tester le système
- Vérifier API externes
- Développer nouveaux agents
- Optimiser paramètres

### Mode REAL (Trading réel)

**Configuration** : `MT5_DRY_RUN=0` dans `.env`

**⚠️ ATTENTION** : Trading avec argent RÉEL !

**Prérequis** :
- ✅ MetaTrader 5 installé sur Windows
- ✅ Compte courtier configuré (credentials dans .env)
- ✅ Tests DEMO validés (1 semaine minimum)
- ✅ Risk management configuré (0.5% par trade au départ)

**Activation** :
1. Éditer `.env` :
   ```
   MT5_DRY_RUN=0
   ```
2. Vérifier `config/config.yaml` :
   ```yaml
   risk:
     risk_per_trade_pct: 0.005  # 0.5% (prudent)
   ```
3. Lancer avec précaution

---

## ❓ RÉPONSES À VOS QUESTIONS

### Q1 : Comment lancer le programme à partir de Windows ?

**Réponse** : 3 méthodes

**Méthode A - Simple** (recommandée) :
1. Double-cliquer sur `START_EMPIRE.bat`
2. C'est tout !

**Méthode B - PowerShell** :
```powershell
cd C:\EmpireAgentIA_3
python main.py --dry-run
```

**Méthode C - Ancien système** :
```powershell
.\start-empire.bat
```
⚠️ Lance en mode REAL par défaut !

---

### Q2 : Est-ce que startempire.bat est fonctionnel ?

**Réponse** : Oui, MAIS...

**Fichier** : `start-empire.bat` (avec tiret)

**Ce qu'il fait** :
- ✅ Lance `scripts\start_empire.py`
- ✅ Mode REAL par défaut (⚠️ argent réel)
- ✅ Crée configuration `config\presets\overrides.real.yaml`
- ✅ Lance Orchestrator + Scheduler séparément

**Problèmes potentiels** :
- ⚠️ Utilise ancien système (scripts\start_empire.py au lieu de main.py)
- ⚠️ Mode REAL par défaut (dangereux si non intentionnel)
- ⚠️ Nécessite structure spécifique (config\presets\)

**Recommandation** : Utilisez `START_EMPIRE.bat` (nouveau) qui :
- ✅ Utilise `main.py` (système actuel)
- ✅ Mode DRY-RUN par défaut (sécurisé)
- ✅ Vérifications automatiques
- ✅ Simplifié

---

### Q3 : Est-ce que l'empire s'optimise automatiquement ?

**Réponse** : NON, l'optimisation est MANUELLE

**Configuration actuelle** :

```yaml
# config/config.yaml
optuna:
  n_trials: 50        # Nombre d'essais pour optimisation
  timeout: 600        # Timeout 10 minutes
```

**Ce que ça fait** :
- ℹ️ Configuration pour Optuna (outil d'optimisation)
- ℹ️ Utilisé UNIQUEMENT quand vous lancez manuellement une optimisation
- ❌ PAS d'optimisation automatique en arrière-plan

**Comment optimiser MANUELLEMENT** :

**Option A - Via script d'optimisation** :
```powershell
cd C:\EmpireAgentIA_3
python -m optimization.optimizer --agent scalping --symbol BTCUSD
```

**Option B - Via Streamlit dashboard** :
```powershell
streamlit run dashboard/dashboard.py
```
Puis aller dans section "Optimization"

**Quand optimiser ?** :
- Après 1-2 semaines de données réelles
- Quand performances se dégradent
- Pour adapter à nouveau marché
- Avant passage DEMO → REAL

**À quelle fréquence ?** :
- ⏱️ **Hebdomadaire** : Trop fréquent (overfitting)
- ✅ **Mensuel** : Bon équilibre
- ✅ **Trimestriel** : Conservative

**Optimisation automatique (FUTURE)** :

Si vous voulez activer optimisation automatique hebdomadaire :

**Créer** `config/optimization_schedule.yaml` :
```yaml
auto_optimization:
  enabled: true
  frequency: weekly
  day: Sunday
  time: "02:00"
  agents:
    - scalping
    - swing
    - technical
  symbols:
    - BTCUSD
    - EURUSD
  optuna:
    n_trials: 30
    timeout: 300
```

**Modifier** `orchestrator/orchestrator.py` pour ajouter job APScheduler

**MAIS** : Pas recommandé au départ (complexe, overfitting risk)

---

## 🔧 DÉPANNAGE

### Problème 1 : "Python n'est pas reconnu"

**Erreur** : `'python' n'est pas reconnu en tant que commande interne`

**Solution** :
1. Réinstaller Python en cochant "Add to PATH"
2. OU ajouter Python au PATH manuellement :
   - Variables d'environnement → PATH
   - Ajouter : `C:\Users\VotreNom\AppData\Local\Programs\Python\Python310\`

### Problème 2 : "ModuleNotFoundError: No module named 'pandas'"

**Solution** :
```powershell
pip install -r requirements.txt
```

### Problème 3 : "MetaTrader5 module non trouvé"

**Solution** :
```powershell
pip install MetaTrader5
```

**Note** : Requis seulement pour trading RÉEL

### Problème 4 : "Erreur connexion MT5"

**Vérifications** :
1. MetaTrader 5 est lancé
2. Credentials dans `.env` corrects
3. Serveur `VantageInternational-Demo` existe
4. Compte actif

### Problème 5 : "API keys invalides"

**Solution** :
1. Vérifier `.env` :
   ```
   FINNHUB_API_KEY=votre_vraie_cle
   ALPHA_VANTAGE_API_KEY=votre_vraie_cle
   ```
2. Obtenir clés gratuites :
   - Finnhub : https://finnhub.io/register
   - Alpha Vantage : https://www.alphavantage.co/support/#api-key

---

## 📊 MONITORING

### Health Check

URL : http://localhost:9108/healthz

**Vérifications** :
- ✅ Orchestrator actif
- ✅ Agents fonctionnels
- ✅ MT5 connexion (si mode REAL)
- ✅ API externes disponibles

### Logs

**Fichiers** : `logs/empire_agent_*.log`

**Commandes utiles** :
```powershell
# Voir logs en temps réel
Get-Content logs\empire_agent_*.log -Wait -Tail 50

# Chercher erreurs
Select-String -Path logs\*.log -Pattern "ERROR"

# Analyser trades
Select-String -Path logs\*.log -Pattern "Order placed"
```

### Telegram

Si configuré (`TELEGRAM_TOKEN` et `TELEGRAM_CHAT_ID` dans `.env`) :
- ✅ Notifications trades
- ✅ Daily digest (10h00 et 19h00)
- ✅ Alertes erreurs

---

## 🎯 CHECKLIST DE LANCEMENT

### Première fois (Windows) :
- [ ] Python 3.10+ installé
- [ ] `.env` créé et configuré (API keys)
- [ ] Dépendances installées (`pip install -r requirements.txt`)
- [ ] MetaTrader5 installé (optionnel pour tests)
- [ ] Mode DRY-RUN activé (`MT5_DRY_RUN=1`)
- [ ] Lancer `START_EMPIRE.bat`
- [ ] Vérifier logs (pas d'erreurs)
- [ ] Tester API : `python test_all_apis.py`

### Avant passage REAL :
- [ ] Tests DEMO validés (1 semaine minimum)
- [ ] Volume trades : 20-40/semaine
- [ ] Taux succès MT5 : >80%
- [ ] News freeze periods fonctionnent
- [ ] Performance positive
- [ ] Risk à 0.5% configuré
- [ ] Commencer avec 1-2 symboles (EURUSD + BTCUSD)
- [ ] Changer `MT5_DRY_RUN=0`
- [ ] Monitoring intensif

---

## 📚 DOCUMENTATION COMPLÉMENTAIRE

- **RESULTAT_FINAL.md** - Synthèse projet complète
- **PHASE_5_COMPLETE.md** - Guide Phase 5 (API externes)
- **INSTALLATION.md** - Guide installation complet
- **QUICK_START.md** - Démarrage rapide
- **STATUS_INSTALLATION.md** - Solutions problèmes WSL
- **CHANGELOG.md** - Historique modifications

---

## 💡 CONSEILS

### Démarrage prudent :
1. ✅ Commencer en **DRY-RUN** (simulation)
2. ✅ Tester 1 semaine minimum
3. ✅ Analyser logs quotidiennement
4. ✅ Vérifier API externes fonctionnent
5. ✅ Commencer REAL avec **0.5% risk**
6. ✅ **1-2 symboles** au départ (EURUSD + BTCUSD)
7. ✅ Augmenter progressivement

### Optimisation :
- ⏰ **Mensuelle** (pas hebdomadaire - risque overfitting)
- 📊 Après accumulation données (min 1 mois)
- 🎯 Agent par agent (pas tous simultanément)
- 💾 Garder backups configurations avant optimisation

### Monitoring :
- 📈 Daily digest Telegram
- 📊 Health check : http://localhost:9108/healthz
- 📝 Logs : `logs/empire_agent_*.log`
- 💰 Performance tracking quotidien

---

## 🚀 COMMANDES RAPIDES

```powershell
# Lancer bot DEMO
.\START_EMPIRE.bat

# OU
python main.py --dry-run

# Tester API externes
python test_all_apis.py

# Vérifier dépendances
python -c "import pandas, MetaTrader5, requests, yaml; print('OK')"

# Optimiser un agent (manuel)
python -m optimization.optimizer --agent scalping --symbol BTCUSD

# Lancer dashboard Streamlit
streamlit run dashboard/dashboard.py

# Voir logs temps réel
Get-Content logs\empire_agent_*.log -Wait -Tail 50
```

---

**Empire Agent IA v3 - Guide Windows - 2025-11-30**
