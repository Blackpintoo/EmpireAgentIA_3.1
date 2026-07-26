# 🚀 QUICK START - EMPIRE AGENT IA v3

**Date** : 2025-11-30
**Statut** : Prêt à installer les dépendances

---

## ⚠️ ACTION REQUISE : Installation des dépendances

Les dépendances Python ne sont pas encore installées. **Vous devez exécuter manuellement le script d'installation** car il nécessite les privilèges sudo (mot de passe administrateur).

---

## 📦 INSTALLATION EN 1 COMMANDE

Ouvrez un terminal WSL/Ubuntu et exécutez :

```bash
cd /mnt/c/EmpireAgentIA_3
./install_dependencies.sh
```

**Vous serez invité à entrer votre mot de passe sudo** pour installer :
- Python 3 pip
- Environnement virtuel Python (venv)
- Toutes les dépendances nécessaires (pandas, MetaTrader5, etc.)

### ⏱️ Durée estimée : 3-5 minutes

---

## 📋 CE QUI SERA INSTALLÉ

Le script `install_dependencies.sh` va :

1. ✅ Mettre à jour apt (`sudo apt update`)
2. ✅ Installer Python 3 pip et venv (`sudo apt install python3-pip python3-venv`)
3. ✅ Installer dépendances système (build tools)
4. ✅ Créer un environnement virtuel Python (`python3 -m venv venv`)
5. ✅ Installer tous les modules Python (`pip install -r requirements.txt`)

### Modules Python installés :
- **pandas** - Manipulation de données
- **MetaTrader5** - Connexion MT5
- **feedparser** - Flux RSS news
- **requests** - Appels API
- **python-telegram-bot** - Notifications Telegram
- **pyyaml** - Lecture fichiers YAML
- **python-dotenv** - Lecture fichier .env
- **optuna** - Optimisation hyperparamètres
- **textblob** - Analyse sentiment
- **streamlit** - Dashboard (optionnel)
- **matplotlib** - Graphiques (backtests)
- Et 6 autres modules...

---

## ✅ APRÈS L'INSTALLATION

Une fois le script terminé, vous verrez :

```
========================================================================
✅ INSTALLATION TERMINÉE AVEC SUCCÈS !
========================================================================

📋 Modules installés :
pandas           2.x.x
MetaTrader5      5.x.x
feedparser       6.x.x
...
```

### Prochaines étapes :

#### 1. Activer l'environnement virtuel

```bash
source venv/bin/activate
```

Vous verrez `(venv)` devant votre prompt :
```
(venv) vin@DESKTOP:/mnt/c/EmpireAgentIA_3$
```

#### 2. Tester les API externes

```bash
python test_all_apis.py
```

**Output attendu** :
```
📊 Résultat global : 3/3 API fonctionnelles
🎉 TOUS LES TESTS RÉUSSIS !
```

#### 3. Lancer le système en dry-run

```bash
python main.py --dry-run
```

**Output attendu** :
```
[INIT] Empire Agent IA v3 - Démarrage en mode DRY-RUN
[INIT] Agents actifs: scalping, swing, technical, structure, smart_money, news, sentiment, fundamental, macro
[INIT] Symboles: BTCUSD, EURUSD, GBPUSD, USDJPY, ...
[MT5] Connexion réussie au compte 10960352
[AGENTS] 9 agents prêts
...
```

#### 4. Monitoring des logs

```bash
# Dans un autre terminal
tail -f logs/empire_agent_*.log
```

---

## 🔄 UTILISATION QUOTIDIENNE

Chaque fois que vous ouvrez un nouveau terminal, **activez l'environnement virtuel** :

```bash
cd /mnt/c/EmpireAgentIA_3
source venv/bin/activate
python main.py --dry-run
```

Pour désactiver l'environnement virtuel :
```bash
deactivate
```

---

## ❓ TROUBLESHOOTING

### Problème 1 : "Permission denied" lors de l'exécution du script

**Solution** :
```bash
chmod +x install_dependencies.sh
./install_dependencies.sh
```

### Problème 2 : Script demande mot de passe sudo

**C'est normal !** Le script nécessite sudo pour installer des paquets système.

Entrez votre mot de passe WSL/Ubuntu (celui que vous utilisez pour `sudo`).

### Problème 3 : "E: Could not get lock /var/lib/dpkg/lock"

**Cause** : Apt est déjà en cours d'utilisation (autre installation, mise à jour)

**Solution** : Attendez 1-2 minutes que l'autre processus se termine, puis relancez.

### Problème 4 : "venv/bin/activate: No such file or directory"

**Cause** : L'installation du script a échoué

**Solution** : Relancez le script d'installation :
```bash
./install_dependencies.sh
```

Vérifiez les erreurs dans l'output.

### Problème 5 : "ModuleNotFoundError" après installation

**Cause** : Environnement virtuel pas activé

**Solution** :
```bash
source venv/bin/activate
python main.py --dry-run
```

---

## 📊 ÉTAT ACTUEL DU PROJET

| Composant | Statut | Notes |
|-----------|--------|-------|
| **Code source PHASE 1-5** | ✅ | Tous fichiers créés |
| **API keys configurées** | ✅ | .env configuré (Finnhub, Alpha Vantage) |
| **API externes testées** | ✅ | 3/3 fonctionnelles |
| **Dépendances Python** | ⏳ | **À installer (script prêt)** |
| **Test système complet** | ⏳ | Après installation dépendances |
| **Production ready** | ⏳ | Après 1 semaine tests DEMO |

---

## 🎯 CHECKLIST COMPLÈTE

### Configuration (COMPLÉTÉ ✅)
- [x] Code PHASE 1-5 implémenté
- [x] Fichier .env configuré avec API keys
- [x] API externes testées (3/3 OK)
- [x] Script installation créé

### Installation (À FAIRE ⏳)
- [ ] Exécuter `./install_dependencies.sh`
- [ ] Vérifier installation : `source venv/bin/activate`
- [ ] Tester API : `python test_all_apis.py`
- [ ] Lancer système : `python main.py --dry-run`

### Tests DEMO (Après installation)
- [ ] Vérifier 9 agents actifs
- [ ] Vérifier 16 symboles configurés
- [ ] Monitoring 1 semaine (volume trades, taux succès MT5)
- [ ] Analyser logs et performances

### Production (Après validation DEMO)
- [ ] Changer `MT5_DRY_RUN=0` dans .env
- [ ] Réduire risk à 0.5%
- [ ] Commencer avec 1-2 symboles
- [ ] Monitoring intensif

---

## 📞 COMMANDES RAPIDES - AIDE-MÉMOIRE

```bash
# 1. INSTALLATION (1 FOIS)
cd /mnt/c/EmpireAgentIA_3
./install_dependencies.sh

# 2. ACTIVATION VENV (CHAQUE SESSION)
source venv/bin/activate

# 3. TESTER API
python test_all_apis.py

# 4. LANCER SYSTÈME DEMO
python main.py --dry-run

# 5. MONITORING LOGS
tail -f logs/empire_agent_*.log

# 6. DÉSACTIVER VENV
deactivate
```

---

## 🚀 LANCEMENT RAPIDE (APRÈS INSTALLATION)

**Séquence complète en 4 commandes** :

```bash
cd /mnt/c/EmpireAgentIA_3          # Aller dans le répertoire
source venv/bin/activate            # Activer environnement Python
python test_all_apis.py             # Vérifier API (optionnel)
python main.py --dry-run            # Lancer le bot en DEMO
```

---

## 📚 DOCUMENTATION DISPONIBLE

- **QUICK_START.md** (ce fichier) - Guide de démarrage rapide
- **INSTALLATION.md** - Guide complet d'installation
- **PHASE_5_COMPLETE.md** - Guide Phase 5 (API externes)
- **CHANGELOG.md** - Historique modifications (PHASE 1-5)
- **ETAT_DU_PROJET.md** - État du projet
- **.env.example** - Template configuration
- **requirements.txt** - Liste dépendances Python

---

## 💡 RAPPEL : ENVIRONNEMENT VIRTUEL

**Pourquoi un environnement virtuel ?**

L'environnement virtuel (`venv`) **isole les dépendances Python** de votre système :
- ✅ Évite conflits avec autres projets Python
- ✅ Versions spécifiques des modules
- ✅ Installation sans droits admin (après setup initial)
- ✅ Facile à supprimer/recréer

**Important** : Toujours activer `venv` avant de lancer le bot :
```bash
source venv/bin/activate  # Vous verrez (venv) devant le prompt
```

---

## 🎉 FÉLICITATIONS !

**Vous êtes à 1 commande du lancement du système complet !**

Exécutez simplement :
```bash
./install_dependencies.sh
```

Et suivez les instructions à l'écran.

---

**Empire Agent IA v3 - Quick Start Guide - 2025-11-30**
