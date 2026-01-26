# Guide d'Utilisation - EmpireAgentIA 3.1

## 🎯 Introduction

EmpireAgentIA 3.1 est un système de trading autonome qui combine l'analyse technique, l'apprentissage automatique et la gestion des risques pour trader de manière intelligente et autonome.

## 🚀 Démarrage Rapide

### 1. Installation

```bash
# Cloner le repository
git clone https://github.com/Blackpintoo/EmpireAgentIA_3.1.git
cd EmpireAgentIA_3.1

# Installer les dépendances
pip install -r requirements.txt
```

### 2. Première Utilisation - Mode Démo

Le mode démo est parfait pour comprendre le système :

```bash
# Exécuter 10 cycles de démonstration
python main.py demo 10
```

### 3. Démonstration Interactive

Pour voir toutes les fonctionnalités :

```bash
python demo.py
```

## 📊 Modes d'Utilisation

### Mode Démo

Idéal pour tester et comprendre le système sans risque :

```bash
python main.py demo [nombre_de_cycles]
```

Exemple avec 20 cycles :
```bash
python main.py demo 20
```

### Mode Continu

Lance le système en mode autonome continu :

```bash
python main.py
```

**Attention** : En mode continu, le système tournera indéfiniment. Utilisez `Ctrl+C` pour l'arrêter.

## ⚙️ Configuration

### Méthode 1 : Fichier .env

Créez un fichier `.env` à partir de l'exemple :

```bash
cp .env.example .env
```

Puis éditez `.env` :

```env
SYMBOL=BTC-USD
INTERVAL=1h
PERIOD=3mo
INITIAL_CAPITAL=10000
MAX_RISK_PER_TRADE=0.02
MAX_DAILY_LOSS=0.05
MIN_CONFIDENCE=0.6
```

### Méthode 2 : Modifier main.py

Ouvrez `main.py` et modifiez la configuration dans la fonction `main()` :

```python
config = {
    'symbol': 'ETH-USD',  # Changer le symbole
    'interval': '15m',    # Changer l'intervalle
    'initial_capital': 5000,  # Changer le capital
    # ... autres paramètres
}
```

## 🎨 Personnalisation

### Changer le Symbole Tradé

Pour trader différents actifs, modifiez `SYMBOL` :

- **Cryptomonnaies** : `BTC-USD`, `ETH-USD`, `SOL-USD`
- **Actions US** : `AAPL`, `TSLA`, `GOOGL`, `MSFT`
- **Forex** : `EURUSD=X`, `GBPUSD=X`
- **Indices** : `^GSPC` (S&P 500), `^DJI` (Dow Jones)

### Ajuster le Risque

Modifiez ces paramètres selon votre tolérance au risque :

```python
'max_risk_per_trade': 0.01,  # 1% par trade (conservateur)
'max_risk_per_trade': 0.03,  # 3% par trade (agressif)
'max_daily_loss': 0.03,      # 3% perte max par jour
```

### Changer l'Intervalle de Temps

```python
'interval': '5m',   # 5 minutes (day trading)
'interval': '15m',  # 15 minutes
'interval': '1h',   # 1 heure (swing trading)
'interval': '1d',   # 1 jour (position trading)
```

## 📈 Comprendre les Signaux

### Types de Signaux

Le système génère 3 types de signaux :

1. **BUY** : Signal d'achat (au moins 2 indicateurs positifs)
2. **SELL** : Signal de vente (au moins 2 indicateurs négatifs)
3. **HOLD** : Attendre (pas assez de confluence)

### Force du Signal

La force indique le nombre d'indicateurs confirmant le signal :
- **Force 2-3** : Signal faible
- **Force 4-5** : Signal moyen
- **Force 6+** : Signal fort

### Raisons du Signal

Le système explique toujours ses décisions :
- `RSI oversold` : RSI en survente (< 30)
- `MACD bullish cross` : Croisement haussier du MACD
- `Uptrend confirmed` : Tendance haussière confirmée
- etc.

## 🧠 Système d'Apprentissage

### Comment ça Marche ?

1. **Enregistrement** : Chaque trade est enregistré avec tous ses détails
2. **Analyse** : Le système analyse les patterns de succès/échec
3. **Entraînement** : Un modèle ML est entraîné (Random Forest)
4. **Prédiction** : Le modèle prédit la probabilité de succès
5. **Optimisation** : Les paramètres s'ajustent automatiquement

### Voir les Performances

Le système affiche régulièrement :

```
📈 Statut du système:
  Position actuelle: False
  Capital: 10150.00
  P&L Total: 150.00
  Retour: 1.50%
  Taux de réussite: 65.0%
```

### Obtenir des Recommandations

Toutes les 100 cycles (configurable), le système génère des recommandations :

```
💡 Recommandations d'optimisation:
  ✅ Excellent taux de réussite (72.5%). Maintenez cette stratégie.
  📊 Les trades réussis ont un RSI moyen de 45.2. Utilisez cette information pour optimiser l'entrée.
```

## 🛡️ Gestion des Risques

### Protection Automatique

Le système protège votre capital avec :

1. **Stop Loss** : 2x ATR en dessous du prix d'entrée
2. **Take Profit** : Basé sur les niveaux de résistance
3. **Limite de positions** : Max 3 positions simultanées
4. **Limite journalière** : Arrêt si perte > 5% par jour
5. **Protection capital** : Arrêt si capital < 50% initial

### Dimensionnement de Position

Le système calcule automatiquement la taille optimale :

```
Position size = (Capital × Max Risk) / Stop Distance
```

Exemple :
- Capital : 10 000 €
- Risque : 2%
- Stop : 100 €
→ Position : (10000 × 0.02) / 100 = 2 unités

## 📁 Fichiers Générés

Le système crée automatiquement :

### trade_history.json

Historique complet de tous les trades :

```json
[
  {
    "timestamp": "2024-01-26T10:00:00",
    "action": "BUY",
    "entry_price": 42500.00,
    "exit_price": 43200.00,
    "profit": 700.00,
    "success": true,
    "indicators": {...}
  }
]
```

### trading_model.pkl

Modèle d'apprentissage entraîné (créé après 10+ trades).

### trading.log

Logs détaillés de toutes les opérations :

```
2024-01-26 10:00:00 - INFO - Signal: BUY (Force: 4)
2024-01-26 10:00:01 - INFO - ACHAT exécuté: BTC-USD @ 42500.00
2024-01-26 11:30:00 - INFO - Take Profit atteint: 43200.00
2024-01-26 11:30:01 - INFO - Profit/Perte: 700.00 (1.65%)
```

## 🔍 Surveillance et Debug

### Logs en Temps Réel

```bash
tail -f trading.log
```

### Niveau de Log

Modifier dans `main.py` :

```python
logging.basicConfig(
    level=logging.DEBUG,  # PLUS de détails
    # level=logging.INFO,   # Niveau normal
    # level=logging.WARNING,  # MOINS de détails
)
```

## ⚠️ Bonnes Pratiques

### Avant de Commencer

1. **Testez en mode démo** : Toujours tester avec le mode démo
2. **Comprenez les risques** : Le trading comporte des risques
3. **Commencez petit** : Utilisez un petit capital initial
4. **Surveillez régulièrement** : Vérifiez les performances

### Pendant l'Utilisation

1. **Vérifiez les logs** : Consultez `trading.log` régulièrement
2. **Suivez les métriques** : Taux de réussite, P&L, etc.
3. **Adaptez la configuration** : Ajustez selon les résultats
4. **Sauvegardez l'historique** : Conservez `trade_history.json`

### Optimisation

1. **Laissez le système apprendre** : Au moins 20-30 trades
2. **Entraînez le modèle** : Le système le fait automatiquement
3. **Suivez les recommandations** : Le système suggère des améliorations
4. **Ajustez progressivement** : Changements petits et mesurés

## 🐛 Dépannage

### Problème : Pas de données de marché

```
ERROR: Impossible de récupérer les données de marché
```

**Solutions** :
- Vérifiez votre connexion internet
- Essayez un autre symbole (ex: `AAPL` au lieu de `BTC-USD`)
- Vérifiez que le symbole existe sur Yahoo Finance

### Problème : Aucun trade exécuté

**Raisons possibles** :
- Pas de signal assez fort (force < 2)
- Confiance trop faible (< MIN_CONFIDENCE)
- Risk manager bloque (pertes journalières atteintes)
- Position déjà ouverte

**Solutions** :
- Réduire `MIN_CONFIDENCE` (ex: 0.4 au lieu de 0.6)
- Vérifier le statut du risk manager
- Attendre de meilleures conditions de marché

### Problème : Trop de pertes

**Solutions** :
- Augmenter `MIN_CONFIDENCE` (ex: 0.7)
- Réduire `MAX_RISK_PER_TRADE` (ex: 0.01)
- Changer de symbole ou d'intervalle
- Laisser le système apprendre plus longtemps

## 📞 Support

Pour toute question :
1. Consultez le README.md
2. Vérifiez les logs dans `trading.log`
3. Ouvrez une issue sur GitHub

## 🎓 Ressources Supplémentaires

### Indicateurs Techniques

- **RSI** : Indicateur de momentum (survente < 30, surachat > 70)
- **MACD** : Croisements pour signaux d'achat/vente
- **Bollinger Bands** : Volatilité et points de retournement
- **ATR** : Mesure de la volatilité pour le stop loss

### Machine Learning

- **Random Forest** : Algorithme d'ensemble robuste
- **Apprentissage supervisé** : Apprend des exemples étiquetés
- **Probabilité** : Prédit la chance de succès (0-100%)

### Gestion des Risques

- **Position sizing** : Taille basée sur le risque
- **Stop loss** : Limite les pertes
- **Diversification** : Ne pas mettre tous les œufs dans le même panier
- **Money management** : Gestion stricte du capital

---

**Bon trading ! 🚀**
