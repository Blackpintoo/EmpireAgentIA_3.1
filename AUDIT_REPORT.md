# Audit opérationnel — EmpireAgentIA 3 (12 août 2025)

**Verdict :** la base est solide (multi‑agents, orchestrateur asynchrone, MT5 client robuste, risk manager par paliers, Telegram sync/async).  
Mais **3 points bloquants** empêchent un run “propre” out‑of‑the‑box : 
1) Dashboard Streamlit — mauvais mapping timeframe → MT5.  
2) Backtest quotidien — mauvais chemin vers `config.yaml` + message Telegram corrompu.  
3) Tests — attendent une classe `TelegramClient` absente.

J’ai préparé un **correctif packagé** : **`EmpireAgentIA_3_FIXED.zip`** (inclus ci‑joint) avec des patchs minimaux, non intrusifs.

---

## Ce que j’ai corrigé (P0)
- **`dashboard/app.py`**  
  - Utilise `MT5Client.parse_timeframe()` (au lieu des constantes MT5 sur l’instance client).  
  - Ajout **XAUUSD** dans le sélecteur (diversification simple).  
  - Message clair si aucune donnée n’est renvoyée.

- **`backtest_daily_all_agents.py`**  
  - Lecture config via **`config/config.yaml`**.  
  - Résumé Telegram propre : `PnL, Sharpe, Trades` par agent.  
  - Sauvegarde JSON UTF‑8 avec `ensure_ascii=False`.

- **`utils/telegram_client.py`**  
  - Ajout d’un **wrapper `TelegramClient`** compatible avec les tests existants.  
  - Factorisation `send_telegram_message()` (timeout, logs d’erreur).

- **`requirements.txt`**  
  - Dé‑doublonnage, ajout de **`streamlit`**.

> Le zip corrigé contient uniquement ces changements. Le reste (orchestrateur, agents, risk manager, optimizer) est **inchangé**.

---

## Ce qui reste à faire (priorisé)

### P0 — Bloquants si tu veux lancer en réel
- **Installation** : `pip install -r requirements.txt` (Python 3.10–3.12 recommandé).  
- **Connexion MT5** : valider que le compte **VantageInternational-Demo** s’initialise bien sur ta machine (proxy/pare‑feu).  
- **Lancement AUTO** : `python main.py` (orchestrateur + listener Telegram).  
- **Backtest quotidien** : si tu veux l’automatiser → `python scheduler_empire.py` (20:00 Europe/Zurich).  
- **Prometheus** : port **8000** est réservé par l’orchestrateur ; vérifier qu’il n’est pas déjà occupé.

### P1 — Fiabilité & Qualité signal
- **Filtre de session** (à ajouter dans les agents ou l’orchestrateur) : ne trader que **08:00–23:00 Europe/Zurich**, éviter l’illiquidité/spread.  
- **Blackout news** : appliquer `FundamentalAgent.trading_blackout()` pour bloquer les 5–10 min **avant et après** les annonces majeures.
- **Validation Telegram** : tu as déjà `send_trade_validation_only: true` en config, mais la logique de filtre vit surtout dans `AsyncTelegramClient` (`allow_kinds`). **Garde** uniquement `trade_validation` + `status` ponctuel.

### P2 — Perf & Contrôle du risque
- **Paramètres par phase (matching ton plan 500 → 10 000)**  
  Objectif approché par jour, en croissance composée (22 j ouvrés/mois) :  
  - **Phase 1 (500 → 2 000, 2 mois ≈ 44 j)** : ~**+3.2 %/j**  
  - **Phase 2 (2 000 → 5 000, 2 mois ≈ 44 j)** : ~**+2.1 %/j**  
  - **Phase 3 (5 000 → 10 000, 1 mois ≈ 22 j)** : ~**+3.2 %/j**  
  > C’est **ambitieux et risqué**. Pour rester cohérent avec tes paliers :  
  - **Phase 1** : `risk_per_trade_pct: 1.0–1.2`, `max_daily_loss_pct: 2.5–3.0`, `max_parallel_positions: 2`  
  - **Phase 2** : `1.2–1.5`, `3.0–3.5`, `2–3`  
  - **Phase 3** : `1.5–1.8`, `3.5–4.0`, `3` (mais **filtrage** beaucoup plus strict)
- **R:R minimal 2:1 + BE sur TP1** : déjà prévu côté agents ; vérifier qu’il est **effectivement appliqué** au moment de l’envoi d’ordre dans l’orchestrateur.  
- **Daily Stop** : `RiskManager.can_open_new_trade()` l’applique déjà. **Active** le recalibrage de l’équité (compounding) chaque jour.

### P3 — Nice‑to‑have (mais utile pour 10 k/mois)
- **Diversification** : activer **XAUUSD** (déjà ajouté au dashboard) + vérifier min lot/valeur du point via `MT5Client.value_per_point()`.  
- **Optuna** : lancer `optimization/optimizer.py` par agent (50–100 trials/agent) pour auto‑ajuster `EMA/RSI/ATR/vol` etc.  
- **Journalisation** : exporter tous les trades validés/rejetés + PnL par agent au format CSV (facile à ajouter dans l’orchestrateur).

---

## Checklist de mise en route (exécutable)

1. **Config & secrets**  
   - `.env` déjà rempli ✅  
   - `config/config.yaml` : OK (pondérations MTF, votes, paliers de risque).

2. **Installation**  
   ```bash
   pip install -r requirements.txt
   ```

3. **Smoke tests**  
   ```bash
   python tests/test_mt5_connection.py   # OHLC + paper order 0.001 lot
   python tests/test_telegram_client.py  # envoi texte simple
   ```

4. **Démarrage**  
   ```bash
   python main.py                         # Orchestrateur + bot Telegram (aiogram)
   streamlit run dashboard/backtest_app.py
   ```

5. **Backtest quotidien (optionnel)**  
   ```bash
   python scheduler_empire.py
   ```

---

## Recommandations de trading (concrètes, courtes)
- **Scalping (M1/M5)** : sessions Londres & NY, éviter les 5 min qui entourent les grosses news USD.  
- **Swing (H1/H4)** : exécuter **uniquement dans le sens de la tendance D1/H4** (déjà prévu par `multi_timeframes`).  
- **Qualité > quantité** : 1–3 trades/jour suffisent si R:R ≥ 2:1.  
- **Spreads** : ignorer si spread BTCUSD > seuil YAML (`spread_points`), idem XAUUSD.  
- **Sur‑perfs** : autoriser **stacking** *uniquement* quand les agents sont unanimes (votes + score pondéré).

> ⚠️ Aucune garantie de gain. Les cibles imposent un **risque élevé**. Reste discipliné avec les stops journaliers et le contrôle de taille de position.

---

## Fichiers modifiés dans le zip corrigé
- `dashboard/app.py`  
- `backtest_daily_all_agents.py`  
- `utils/telegram_client.py`  
- `requirements.txt`

Bonne mise en route ! Si tu veux, on peut activer ensuite : filtre de session, blackout news strict, et un log CSV complet côté orchestrateur.
