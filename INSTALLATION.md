# 📦 GUIDE D'INSTALLATION - EMPIRE AGENT IA v3

**Date** : 2025-11-30
**Système** : Windows (WSL) + MetaTrader 5

---

## ⚠️ PROBLÈME DÉTECTÉ

Les dépendances Python ne sont pas installées sur votre système.

**Erreur rencontrée** :
```
ModuleNotFoundError: No module named 'pandas'
```

**Modules manquants** :
- pandas
- MetaTrader5
- feedparser
- requests
- python-telegram-bot
- pyyaml
- prometheus_client
- pytz
- aiogram
- apscheduler
- python-dotenv
- optuna
- textblob
- streamlit
- matplotlib

---

## 🔧 SOLUTIONS D'INSTALLATION

### Solution 1 : Installation via pip (RECOMMANDÉE)

#### Sur Windows (PowerShell ou CMD)

```bash
# Vérifier que Python est installé
python --version

# Installer pip si nécessaire
python -m ensurepip --upgrade

# Installer toutes les dépendances
pip install -r requirements.txt

# OU installer une par une
pip install pandas MetaTrader5 feedparser requests python-telegram-bot pyyaml prometheus_client six pytz aiogram apscheduler python-dotenv optuna textblob streamlit matplotlib
```

#### Sur WSL (Ubuntu/Debian)

```bash
# Vérifier que Python est installé
python3 --version

# Installer pip si nécessaire
sudo apt update
sudo apt install python3-pip -y

# Installer toutes les dépendances
pip3 install -r requirements.txt

# OU installer via apt + pip
sudo apt install python3-pandas python3-requests python3-yaml -y
pip3 install MetaTrader5 feedparser python-telegram-bot prometheus_client aiogram apscheduler python-dotenv optuna textblob streamlit matplotlib
```

### Solution 2 : Environnement virtuel Python (PROPRE)

#### Sur Windows

```bash
# Créer un environnement virtuel
python -m venv venv

# Activer l'environnement
venv\Scripts\activate

# Installer les dépendances
pip install -r requirements.txt
```

#### Sur WSL

```bash
# Créer un environnement virtuel
python3 -m venv venv

# Activer l'environnement
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

### Solution 3 : Utiliser Conda (si installé)

```bash
# Créer un environnement conda
conda create -n empire_agent python=3.10

# Activer l'environnement
conda activate empire_agent

# Installer les dépendances
pip install -r requirements.txt
```

---

## ✅ VÉRIFICATION DE L'INSTALLATION

Une fois les dépendances installées, vérifiez que tout fonctionne :

### Test 1 : Vérifier les modules Python

```bash
python3 -c "import pandas; print('✅ pandas OK')"
python3 -c "import MetaTrader5; print('✅ MetaTrader5 OK')"
python3 -c "import feedparser; print('✅ feedparser OK')"
python3 -c "import requests; print('✅ requests OK')"
python3 -c "import yaml; print('✅ pyyaml OK')"
python3 -c "import dotenv; print('✅ python-dotenv OK')"
```

**Output attendu** :
```
✅ pandas OK
✅ MetaTrader5 OK
✅ feedparser OK
✅ requests OK
✅ pyyaml OK
✅ python-dotenv OK
```

### Test 2 : Vérifier les API externes

```bash
python3 test_all_apis.py
```

**Output attendu** :
```
📊 Résultat global : 3/3 API fonctionnelles
🎉 TOUS LES TESTS RÉUSSIS !
```

### Test 3 : Lancer le système en dry-run

```bash
python3 main.py --dry-run
```

**Output attendu** :
```
[INIT] Empire Agent IA v3 - Démarrage en mode DRY-RUN
[INIT] Agents actifs: scalping, swing, technical, structure, smart_money, news, sentiment, fundamental, macro
[INIT] Symboles: BTCUSD, EURUSD, GBPUSD, ...
[MT5] Connexion réussie au compte 10960352
...
```

---

## 🐍 ENVIRONNEMENT PYTHON RECOMMANDÉ

### Configuration système optimale

| Composant | Version recommandée | Notes |
|-----------|-------------------|-------|
| **Python** | 3.10.x ou 3.11.x | Compatibilité MT5 |
| **OS** | Windows 10/11 | Pour MetaTrader 5 |
| **RAM** | 8 GB minimum | 16 GB recommandé |
| **Stockage** | 10 GB libre | Pour données backtests |

### Vérifier votre version Python

```bash
# Sur Windows
python --version

# Sur WSL
python3 --version
```

**Versions compatibles** :
- ✅ Python 3.10.x (recommandé)
- ✅ Python 3.11.x (recommandé)
- ✅ Python 3.9.x (minimal)
- ❌ Python 3.12+ (problèmes compatibilité MT5)
- ❌ Python 2.x (obsolète)

---

## 📁 STRUCTURE DU PROJET APRÈS INSTALLATION

```
/mnt/c/EmpireAgentIA_3/
├── .env                          ✅ Configuré avec API keys
├── requirements.txt              ✅ Liste des dépendances
├── main.py                       📌 Point d'entrée principal
├── test_all_apis.py             ✅ Testé (3/3 API OK)
│
├── config/
│   ├── config.yaml              ✅ Configuration principale
│   ├── profiles.yaml            ✅ Paramètres par symbole
│   └── asset_config.yaml        ✅ Configuration par type d'actif
│
├── connectors/
│   ├── finnhub_calendar.py      ✅ Calendrier économique
│   ├── alpha_vantage_news.py    ✅ News sentiment
│   └── fear_greed_index.py      ✅ Sentiment crypto
│
├── orchestrator/
│   └── orchestrator.py          📌 Système de voting multi-agents
│
├── agents/                       ✅ 9 agents actifs
│   ├── scalping_agent.py
│   ├── swing_agent.py
│   ├── technical_agent.py
│   ├── structure_agent.py
│   ├── smart_money_agent.py
│   ├── news_agent.py
│   ├── sentiment_agent.py
│   ├── fundamental_agent.py
│   └── macro_agent.py
│
├── utils/
│   ├── mt5_client.py            ✅ Fix MT5 errors (PHASE 1)
│   ├── asset_manager.py         ✅ Gestion par type d'actif (PHASE 4)
│   └── logger.py
│
└── data/
    ├── cache/                    ✅ Cache API externes
    │   ├── finnhub_calendar_cache.json
    │   ├── alpha_vantage_news_cache.json
    │   └── fear_greed_index_cache.json
    └── audit/                    📊 Logs de trading
```

---

## 🚀 COMMANDES RAPIDES

### Installation complète (Windows)

```powershell
# 1. Vérifier Python
python --version

# 2. Installer dépendances
pip install -r requirements.txt

# 3. Vérifier installation
python test_all_apis.py

# 4. Lancer système
python main.py --dry-run
```

### Installation complète (WSL/Linux)

```bash
# 1. Installer pip
sudo apt update && sudo apt install python3-pip -y

# 2. Installer dépendances
pip3 install -r requirements.txt

# 3. Vérifier installation
python3 test_all_apis.py

# 4. Lancer système
python3 main.py --dry-run
```

---

## ❓ TROUBLESHOOTING

### Problème 1 : "pip: command not found"

**Solution** :
```bash
# Windows
python -m ensurepip --upgrade

# WSL/Linux
sudo apt install python3-pip -y
```

### Problème 2 : "Permission denied"

**Solution WSL** :
```bash
# Utiliser --user pour installation locale
pip3 install --user -r requirements.txt
```

**Solution Windows** :
```powershell
# Exécuter PowerShell en administrateur
# Puis installer normalement
pip install -r requirements.txt
```

### Problème 3 : "ModuleNotFoundError: No module named 'MetaTrader5'"

**Cause** : MetaTrader5 nécessite Windows ou Wine

**Solution** :
```bash
# Sur Windows
pip install MetaTrader5

# Sur WSL (peut nécessiter Wine)
pip3 install MetaTrader5
# Note : MT5 fonctionne mieux directement sur Windows
```

### Problème 4 : "No module named '_bz2'" ou "_lzma"

**Solution Ubuntu/WSL** :
```bash
sudo apt install python3-dev libbz2-dev liblzma-dev -y
pip3 install -r requirements.txt
```

### Problème 5 : Versions Python incompatibles

**Solution** : Installer Python 3.10
```bash
# WSL/Ubuntu
sudo apt install python3.10 python3.10-venv python3.10-dev -y
python3.10 -m pip install -r requirements.txt
```

---

## 📞 APRÈS INSTALLATION - CHECKLIST

- [ ] ✅ Python 3.10+ installé (`python --version`)
- [ ] ✅ Dépendances installées (`pip list | grep pandas`)
- [ ] ✅ Fichier .env configuré (API keys présentes)
- [ ] ✅ Test API réussi (`python3 test_all_apis.py` → 3/3 OK)
- [ ] ✅ MetaTrader 5 installé sur Windows
- [ ] ✅ Compte MT5 configuré (demo ou réel)
- [ ] ✅ Telegram bot configuré (token + chat_id dans .env)

---

## 🎯 PROCHAINE ÉTAPE

Une fois **TOUTES les dépendances installées**, vous pourrez :

1. **Tester le système** :
   ```bash
   python3 main.py --dry-run
   ```

2. **Vérifier les logs** :
   ```bash
   tail -f logs/empire_agent_*.log
   ```

3. **Monitoring via Telegram** :
   - Recevoir notifications de trades
   - Daily digest à 10h00 et 19h00

4. **Passage en RÉEL** (après 1 semaine DEMO) :
   - Changer `MT5_DRY_RUN=0` dans .env
   - Réduire `risk_per_trade_pct` à 0.5%
   - Commencer avec 1-2 symboles

---

## 📚 DOCUMENTATION COMPLÉMENTAIRE

- **PHASE_5_COMPLETE.md** : Guide complet Phase 5 (API externes)
- **CHANGELOG.md** : Historique de toutes les modifications (PHASE 1-5)
- **ETAT_DU_PROJET.md** : État actuel du projet
- **docs/PHASE4_INTEGRATION.md** : Guide AssetManager
- **.env.example** : Template configuration

---

**Empire Agent IA v3 - Guide d'Installation - 2025-11-30**
