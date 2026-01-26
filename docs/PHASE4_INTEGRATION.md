# PHASE 4 - Intégration AssetManager dans l'Orchestrateur

## 📋 Vue d'ensemble

L'**AssetManager** est maintenant intégré dans l'orchestrateur pour appliquer automatiquement les paramètres spécifiques par type d'actif (FOREX, CRYPTOS, INDICES, COMMODITIES).

---

## ✅ Fonctionnalités intégrées

### 1. **Vérification automatique des sessions de trading**

L'orchestrateur vérifie maintenant si le trading est autorisé pour le symbole **avant chaque exécution de trade**.

**Exemple** :
- **FOREX (EURUSD)** : Trading bloqué le dimanche et en dehors des sessions principales
- **INDICES (US30)** : Trading autorisé uniquement pendant les horaires réguliers (15:30-22:00 CET)
- **CRYPTOS (BTCUSD)** : Trading 24/7 mais évite les périodes de faible liquidité

**Code dans l'orchestrateur** :
```python
# Ligne ~1632
if self.asset_manager:
    now = datetime.now(ZoneInfo("Europe/Zurich"))
    allowed, reason = self.asset_manager.is_trading_allowed(self.symbol, now)
    if not allowed:
        self._send_telegram(f"⏰ [PHASE4] Session fermée pour {self.symbol}: {reason}")
        return False
```

---

### 2. **Gestion des corrélations**

L'orchestrateur **bloque automatiquement** les trades si un symbole corrélé est déjà en position.

**Groupes de corrélation** (définis dans `asset_config.yaml`) :
- **EURUSD ↔ GBPUSD** (ne pas trader simultanément)
- **XAUUSD ↔ XAGUSD** (or et argent corrélés)
- **US30 ↔ NAS100** (indices US corrélés)

**Code dans l'orchestrateur** :
```python
# Ligne ~1647
# Récupère les positions ouvertes
open_positions = [broker_to_canon(pos.symbol) for pos in _mt5.positions_get()]

# Vérifie conflit
conflict = self.asset_manager.check_correlation_conflict(self.symbol, open_positions)
if conflict:
    self._send_telegram(f"🔗 [PHASE4] Conflit de corrélation pour {self.symbol}")
    return False
```

---

### 3. **Paramètres de risque dynamiques** (à implémenter si souhaité)

L'AssetManager peut fournir les paramètres de risque adaptés à chaque type d'actif :

```python
# Utilisation dans le RiskManager
if self.asset_manager:
    risk_pct = self.asset_manager.get_risk_per_trade(symbol)  # 1.0-1.5%
    sl_mult, tp_mult = self.asset_manager.get_atr_multipliers(symbol)  # (1.5, 2.5) pour FOREX
```

---

## 🎯 Comportement par type d'actif

### **CRYPTOS** (BTCUSD, ETHUSD, ADAUSD, SOLUSD, etc.)
- ✅ Trading 24/7
- ⚠️ Évite weekend 02:00-06:00 (faible liquidité)
- 📊 Timeframe principal : M15
- 💰 Risk : 1.2% par trade
- 📉 ATR SL: 1.8×, TP: 3.0×

### **FOREX** (EURUSD, GBPUSD, USDJPY, AUDUSD)
- ✅ Sessions : Tokyo, London, NY, Overlap
- ❌ Blackout : 23:00-01:00, Vendredi 21:00+, Dimanche
- 📊 Timeframe principal : H1
- 💰 Risk : 1.0% par trade
- 📉 ATR SL: 1.5×, TP: 2.5×

### **INDICES** (US30, NAS100, GER40)
- ✅ Horaires stricts par indice
  - **US30/NAS100** : 15:30-22:00 CET
  - **GER40** : 09:00-17:30 CET
- 📊 Timeframe principal : M15
- 💰 Risk : 1.5% par trade
- 📉 ATR SL: 2.0×, TP: 3.5×
- ⚠️ 1 seul indice à la fois

### **COMMODITIES** (XAUUSD, XAGUSD, USOIL)
- ✅ Sessions : Asian, London, NY, Overlap
- ❌ Blackout : 21:00-01:00
- 📊 Timeframe principal : M30
- 💰 Risk : 1.2% par trade
- 📉 ATR SL: 1.6×, TP: 2.8×
- ⚠️ Évite news macro ±30 min

---

## 📊 Logs et Notifications

### **Logs dans le terminal**
```
[PHASE4] AssetManager initialisé pour EURUSD (type: FOREX)
[PHASE4] Trading session OK for EURUSD: london
[PHASE4] Trading not allowed for US30: outside_trading_hours
[PHASE4] Correlation conflict for GBPUSD with ['EURUSD']
```

### **Notifications Telegram**
```
⏰ [PHASE4] Session fermée pour US30: outside_trading_hours
🔗 [PHASE4] Conflit de corrélation pour GBPUSD (positions: EURUSD)
```

---

## 🔧 Configuration

### **Fichiers impliqués**
1. `config/asset_config.yaml` - Configuration par type d'actif
2. `utils/asset_manager.py` - Gestionnaire centralisé
3. `orchestrator/orchestrator.py` - Intégration dans le flux de trading

### **Modifier les paramètres**

Pour ajuster les sessions de trading :
```yaml
# config/asset_config.yaml
FOREX:
  trading_sessions:
    blackout_periods:
      - {hours: ["23:00-01:00"], reason: "low_liquidity"}
      - {day: "sunday", hours: ["00:00-23:59"], reason: "weekend"}
```

Pour ajouter/modifier les corrélations :
```yaml
# config/asset_config.yaml
global_rules:
  correlation_groups:
    - [EURUSD, GBPUSD]
    - [XAUUSD, XAGUSD]
    - [US30, NAS100]
```

---

## 🧪 Tests

### **Test manuel**
```bash
# Tester l'AssetManager seul
python test_asset_manager.py

# Lancer l'orchestrateur en mode dry-run
python main.py --dry-run
```

### **Vérifications**
1. ✅ Sessions de trading respectées (logs `[PHASE4] Trading session OK`)
2. ✅ Corrélations détectées (notification Telegram si conflit)
3. ✅ AssetManager initialisé sans erreur

---

## ⚠️ Notes importantes

1. **Fallback sécurisé** : Si AssetManager échoue à l'initialisation, l'orchestrateur continue **sans les vérifications PHASE 4** (logs d'avertissement)

2. **Compatibilité** : Les vérifications PHASE 4 s'ajoutent aux vérifications existantes :
   - Gating qualité (backtests)
   - Trading windows (profiles.yaml)
   - News filter
   - Crypto bucket guard
   - Anti-spam gating

3. **Priorité** : Les vérifications PHASE 4 sont exécutées **après** les vérifications de base mais **avant** l'exécution réelle du trade

---

## 🚀 Prochaines améliorations possibles

1. **Intégration Risk Manager** : Utiliser `get_risk_per_trade()` et `get_atr_multipliers()` automatiquement

2. **Exposition max par type** : Limiter l'exposition globale par type d'actif (4% CRYPTOS, 3% FOREX, etc.)

3. **Priorités de signaux** : Si plusieurs signaux simultanés, privilégier selon l'ordre :
   FOREX > COMMODITIES > CRYPTOS > INDICES

4. **Dashboard** : Afficher les sessions de trading actives en temps réel

---

## 📚 Références

- `config/asset_config.yaml` - Configuration complète
- `utils/asset_manager.py` - Code source AssetManager
- `test_asset_manager.py` - Tests et exemples d'utilisation
- `CHANGELOG.md` - Historique des modifications PHASE 4
