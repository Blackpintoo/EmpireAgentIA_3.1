# EmpireAgentIA 3.1 - Système de Trading Autonome

## 🚀 Description

EmpireAgentIA 3.1 est un système de trading autonome intelligent qui :

- 📊 **Analyse constamment les graphiques** avec de multiples indicateurs techniques (RSI, MACD, Bollinger Bands, etc.)
- 🤖 **Apprend de ses erreurs et succès** grâce à un système d'apprentissage automatique (Machine Learning)
- 🎯 **S'optimise automatiquement** en analysant ses performances passées
- ⚡ **Trade de manière autonome** en prenant des décisions basées sur l'analyse technique et l'apprentissage
- 🛡️ **Gère les risques** avec un système de risk management intégré

## 🏗️ Architecture du Système

Le système est composé de plusieurs modules spécialisés :

1. **ChartAnalyzer** (`src/chart_analyzer.py`)
   - Calcule les indicateurs techniques (SMA, EMA, MACD, RSI, Bollinger Bands, etc.)
   - Analyse les signaux d'achat/vente
   - Détermine les tendances du marché

2. **LearningSystem** (`src/learning_system.py`)
   - Enregistre tous les trades (succès et échecs)
   - Entraîne un modèle de machine learning (Random Forest)
   - Prédit la probabilité de succès des trades
   - Génère des recommandations d'optimisation

3. **RiskManager** (`src/risk_manager.py`)
   - Contrôle l'exposition au risque
   - Calcule la taille optimale des positions
   - Limite les pertes journalières
   - Protège le capital

4. **TradingEngine** (`src/trading_engine.py`)
   - Coordonne tous les modules
   - Prend les décisions de trading
   - Gère les positions (entrée, sortie, stop loss, take profit)

5. **MarketDataFetcher** (`src/market_data.py`)
   - Récupère les données de marché en temps réel
   - Utilise yfinance pour accéder aux données

## 📋 Prérequis

- Python 3.8 ou supérieur
- pip (gestionnaire de paquets Python)

## 🔧 Installation

1. **Cloner le repository**
   ```bash
   git clone https://github.com/Blackpintoo/EmpireAgentIA_3.1.git
   cd EmpireAgentIA_3.1
   ```

2. **Installer les dépendances**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configurer le système (optionnel)**
   ```bash
   cp .env.example .env
   # Modifier .env selon vos besoins
   ```

## 🎮 Utilisation

### Mode Démo (recommandé pour débuter)

Le mode démo exécute un nombre limité de cycles pour tester le système :

```bash
python main.py demo 10
```

Cela exécutera 10 cycles d'analyse et de trading en mode démo.

### Mode Continu

Pour lancer le système en mode continu (attention : utilise des données réelles) :

```bash
python main.py
```

Le système va :
1. Analyser le marché toutes les 60 secondes (configurable)
2. Prendre des décisions de trading autonomes
3. S'optimiser automatiquement tous les 100 cycles
4. Enregistrer tous les trades pour l'apprentissage

### Arrêt du système

Pour arrêter le système en mode continu, appuyez sur `Ctrl+C`. Le système affichera un rapport final de performance.

## ⚙️ Configuration

Vous pouvez configurer le système en modifiant le fichier `.env` ou directement dans `main.py` :

| Paramètre | Description | Valeur par défaut |
|-----------|-------------|-------------------|
| `SYMBOL` | Symbole à trader (BTC-USD, ETH-USD, AAPL, etc.) | BTC-USD |
| `INTERVAL` | Intervalle de temps (1m, 5m, 15m, 1h, 1d) | 1h |
| `PERIOD` | Période historique (1d, 5d, 1mo, 3mo, 1y) | 3mo |
| `INITIAL_CAPITAL` | Capital initial | 10000 |
| `MAX_RISK_PER_TRADE` | Risque max par trade (2% = 0.02) | 0.02 |
| `MAX_DAILY_LOSS` | Perte max journalière (5% = 0.05) | 0.05 |
| `MIN_CONFIDENCE` | Confiance min pour trader (60% = 0.6) | 0.6 |
| `CHECK_INTERVAL` | Intervalle entre vérifications (secondes) | 60 |

## 📊 Indicateurs Techniques Utilisés

Le système utilise une combinaison d'indicateurs techniques pour l'analyse :

- **Moyennes Mobiles** : SMA (20, 50), EMA (12, 26)
- **MACD** : Moving Average Convergence Divergence
- **RSI** : Relative Strength Index (14 périodes)
- **Stochastic Oscillator** : %K et %D
- **Bollinger Bands** : Bandes de Bollinger avec largeur
- **ATR** : Average True Range (volatilité)
- **OBV** : On Balance Volume
- **Analyse de tendance** : Basée sur les moyennes mobiles

## 🧠 Système d'Apprentissage

Le système apprend continuellement de ses trades :

1. **Enregistrement** : Chaque trade est enregistré avec tous ses détails
2. **Analyse** : Les trades réussis et ratés sont analysés
3. **Entraînement** : Un modèle Random Forest est entraîné sur l'historique
4. **Prédiction** : Le modèle prédit la probabilité de succès des futurs trades
5. **Optimisation** : Le système s'adapte en fonction des performances

### Métriques Suivies

- Taux de réussite (win rate)
- Profit/perte total
- Profit/perte moyen par trade
- Performance récente (derniers 10 trades)
- Meilleur et pire trade

## 🛡️ Gestion des Risques

Le système intègre un risk manager sophistiqué :

- **Limite de positions** : Maximum 3 positions simultanées
- **Stop Loss automatique** : Basé sur l'ATR (2x ATR)
- **Take Profit** : Calculé selon support/résistance
- **Dimensionnement de position** : Calculé selon le risque max
- **Protection du capital** : Arrêt si capital < 50% du capital initial
- **Limite journalière** : Arrêt si perte journalière > 5%

## 📁 Structure des Fichiers

```
EmpireAgentIA_3.1/
├── src/
│   ├── __init__.py
│   ├── chart_analyzer.py      # Analyse technique
│   ├── learning_system.py     # Apprentissage ML
│   ├── risk_manager.py        # Gestion des risques
│   ├── trading_engine.py      # Moteur principal
│   └── market_data.py         # Récupération données
├── main.py                    # Application principale
├── requirements.txt           # Dépendances Python
├── .env.example              # Exemple de configuration
├── .gitignore                # Fichiers à ignorer
└── README.md                 # Documentation

Fichiers générés automatiquement :
├── trade_history.json        # Historique des trades
├── trading_model.pkl         # Modèle ML entraîné
└── trading.log              # Logs du système
```

## 📈 Exemple de Sortie

```
================================================================================
EmpireAgentIA 3.1 - Système de Trading Autonome
================================================================================
Symbole: BTC-USD
Intervalle: 1h
Mode: DEMO
================================================================================
🚀 Démarrage du système de trading autonome...

================================================================================
Cycle #1 - 2024-01-26 10:00:00
================================================================================
Calcul des indicateurs techniques...
Indicateurs calculés pour 2160 périodes
Signal: BUY (Force: 3)
Raisons: RSI oversold, MACD bullish cross, Uptrend confirmed
Probabilité de succès prédite: 72.5%
ACHAT exécuté: BTC-USD @ 42500.00
  Taille: 0.0471
  Stop Loss: 41200.00
  Take Profit: 44500.00
✅ Trade exécuté!

📈 Statut du système:
  Position actuelle: True
  Capital: 10000.00
  P&L Total: 0.00
  Retour: 0.00%
  Taux de réussite: 0.0%

⏳ Attente de 60 secondes...
```

## 🔍 Logs et Monitoring

Le système génère des logs détaillés dans `trading.log` :
- Toutes les décisions de trading
- Calculs d'indicateurs
- Résultats des trades
- Erreurs et avertissements
- Recommandations d'optimisation

## ⚠️ Avertissements

1. **Mode Démo** : Toujours tester en mode démo avant d'utiliser avec de l'argent réel
2. **Risques** : Le trading comporte des risques de perte en capital
3. **Responsabilité** : L'utilisateur est seul responsable de ses décisions de trading
4. **Données** : Le système utilise des données historiques qui ne garantissent pas les performances futures

## 🤝 Contribution

Les contributions sont les bienvenues ! N'hésitez pas à :
- Signaler des bugs
- Proposer des améliorations
- Ajouter de nouvelles fonctionnalités

## 📄 Licence

Ce projet est fourni "tel quel" sans garantie d'aucune sorte.

## 📞 Support

Pour toute question ou problème, ouvrez une issue sur GitHub.

---

**Développé avec ❤️ pour le trading intelligent et autonome** 
