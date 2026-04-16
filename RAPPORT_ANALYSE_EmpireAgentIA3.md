# RAPPORT D'ANALYSE APPROFONDIE - EmpireAgentIA v3

**Date d'analyse** : 1er mars 2026
**Analyste** : Expert Trading Algorithmique (Claude Opus 4.6)
**Version du projet** : EmpireAgentIA v3 (branche main)
**Profondeur** : Analyse exhaustive de ~80 fichiers Python, 14 YAML, 4900+ lignes d'orchestrateur

---

## TABLE DES MATIERES

1. [Vue d'ensemble du systeme](#1-vue-densemble-du-systeme)
2. [Ce qui est en place et fonctionnel](#2-ce-qui-est-en-place-et-fonctionnel)
3. [Points faibles et problemes identifies](#3-points-faibles-et-problemes-identifies)
4. [Recommandations d'amelioration priorisees](#4-recommandations-damelioration-priorisees)
5. [Prompts prets a l'emploi pour Claude Code](#5-prompts-prets-a-lemploi-pour-claude-code)

---

## 1. VUE D'ENSEMBLE DU SYSTEME

### 1.1 Architecture Globale

EmpireAgentIA v3 est un **bot de trading algorithmique multi-agents** operant sur **MetaTrader 5** (broker Vantage International). Le systeme orchestre 12 agents de trading specialises (8 actifs), chacun utilisant des strategies distinctes. Un orchestrateur central de 4900+ lignes agrege les signaux par vote pondere, applique 15+ filtres de qualite en cascade, et execute les trades via MT5.

```
                    +------------------+
                    |    main.py       |
                    | (Point d'entree) |
                    +--------+---------+
                             |
                    +--------v---------+
                    |   Orchestrator    |  (4900+ lignes)
                    |  orchestrator.py  |
                    +--------+---------+
                             |
    +----+---+---+---+---+---+---+---+---+---+---+---+
    |Tech|Sca|Swi|SMC|PA |VP |Str|Sen|New|Fun|Mac|Wha|
    | M30| M1| H1|M15|M15| H1|M15| - | - | - | - |Evt|
    +--+-+--++--++--++--++--++--++--++--++--++--++--+-+
       |    |   |   |   |   |   |   |   |   |   |
    +--v----v---v---v---v---v---v---v---v---v---v--+
    |        Aggregation Vote Pondere              |
    |  (score composite + regime + dispersion)     |
    +-----+---+---+---+---+---+---+---+---+---+---+
          |   |   |   |   |   |   |   |   |   |
    +-----v---v---v---v---v---v---v---v---v---v---+
    |           15+ HARD FILTERS EN CASCADE        |
    | Score>=8 | Conf>=5 | Tracker | Session | EOD |
    | DailyLoss| KillSwitch | CircuitBreaker | MTF |
    | EventGuard | InterMarket | VolFilter | Regime|
    +---------------------+------------------------+
                          |
                 +--------v---------+
                 |   Risk Sizing     |
                 | (ATR-based SL/TP) |
                 +--------+---------+
                          |
              +-----------+-----------+
              |                       |
     +--------v---------+   +--------v---------+
     |   MT5 Execution   |   |   Telegram       |
     |  (place_order)    |   |  (notification)  |
     +--------+---------+   +------------------+
              |
     +--------v---------+
     |  Position Manager |
     | BE/Partials/Trail |
     +------------------+
```

### 1.2 Technologies et Librairies

| Composant | Technologie |
|-----------|------------|
| Langage | Python 3.12 |
| Broker API | MetaTrader5 (module Python) |
| Scheduling | APScheduler (BackgroundScheduler) |
| Telegram (envoi) | requests + python-telegram-bot |
| Telegram (callbacks) | aiogram >= 3.0 (polling) |
| Optimisation | Optuna (TPE sampler, MedianPruner) |
| Sentiment NLP | TextBlob (basique), FinBERT v2 (optionnel - non dans requirements.txt) |
| Donnees news | feedparser (RSS), requests (APIs) |
| Dashboard | Streamlit (optionnel) |
| Monitoring | prometheus_client (optionnel) |
| Config | PyYAML, python-dotenv |
| Data | pandas, SQLite (trades_db) |

### 1.3 Connexions APIs et Data Sources

| Source | Utilisation | Status |
|--------|------------|--------|
| **MetaTrader 5** | Execution, donnees OHLCV, positions, deals | Operationnel |
| **Finnhub** | Calendrier economique (FOMC, NFP, CPI...) | Configure mais econ_api.py retourne liste vide (TODO) |
| **Alpha Vantage** | Sentiment news, donnees macro | Configure |
| **Fear & Greed Index** | Sentiment crypto (alternative.me) | Operationnel |
| **RSS Feeds** | CoinDesk, CoinTelegraph, BitcoinMagazine, Yahoo, Reuters | Operationnel |
| **Investing.com** | Calendrier eco (scraping HTML) | Fragile (parsing HTML) |
| **ForexFactory** | Calendrier eco (scraping CSS) | Fragile (parsing CSS) |
| **FXStreet** | Calendrier eco (API JSON) | Instable (timeout frequents) |
| **CryptoPanic** | News crypto (API) | Configure dans data_sources.py |
| **Twitter/X** | Sentiment social | Necessite bearer_token (absent) |
| **Google Trends** | Tendances recherche | Necessite pytrends (optionnel) |

### 1.4 Portefeuille d'Actifs

**Symboles actifs** : BTCUSD, BNBUSD (SHORT only), SOLUSD, NAS100, SP500, XAUUSD, USDJPY, ETHUSD (reactivable)

**Symboles desactives** : LTCUSD (WR 0%), AUDUSD (WR 33%, -844$, 10 pertes consec), EURUSD, GBPUSD, ADAUSD, XAGUSD, UK100, USOUSD

**Symboles orphelins** (configures dans asset_config.yaml mais absents de profiles.yaml) : DJ30, GER40, CL-OIL

### 1.5 Fichiers de Configuration (14 YAML)

| Fichier | Role | Lignes |
|---------|------|--------|
| config.yaml | Configuration maitre (MT5, Telegram, agents, risk) | ~400 |
| profiles.yaml | Parametres par symbole (15 symboles) | ~600 |
| overrides.yaml | Surcharges dynamiques post-audit (FIX 2026-02-20) | ~350 |
| asset_config.yaml | Classification par type d'actif (sessions, spreads) | ~200 |
| auto_optimization.yaml | Config Optuna (hebdomadaire) | ~100 |
| macro.yaml | Calendrier macro (VIDE - 2 lignes) | 2 |
| econ_calendar.yaml | Calendrier eco (1 seul event obsolete: FOMC 2025-08-19) | ~10 |
| presets/overrides.real.yaml | Mode reel (dry_run: false) | 5 |
| presets/overrides.live.yaml | Gating live (PF>1.3, DD<12%) | ~80 |
| presets/overrides.live.small.yaml | Petit compte (identique a live!) | ~40 |
| presets/overrides.demo.yaml | Demo (gating relache) | ~60 |
| presets/overrides.weekend.yaml | Weekend crypto (risk 3x plus agressif!) | ~50 |
| presets/overrides.aggressive.yaml | Agressif (RR min 0.8 = perte mathematique!) | ~40 |
| overrides.backup.yaml | Backup avec symbole LNKUSD orphelin | ~80 |

---

## 2. CE QUI EST EN PLACE ET FONCTIONNEL

### 2.1 Orchestrateur Central (orchestrator.py - 4900+ lignes)

**Architecture interne detaillee :**

**Initialisation (lignes 645-989)**
- Charge config multi-niveaux (config.yaml > profiles.yaml > overrides.yaml > env)
- Initialise MT5, Telegram, APScheduler
- Registry global `_ORCH_REGISTRY` pour callbacks Telegram
- Locks statiques `_ORCH_LOCKS` au niveau classe

**Cooldowns configures (lignes 910-939) :**
- Apres trade : 5 min
- Apres perte : 30 min
- Apres gain : 2 min
- Apres rejet : 3 min
- Streak 3 pertes : 60 min pause
- Min entre trades : 300 sec
- Max trades/jour : 15, Max trades/heure : 5

**Cycle principal (60s) :**
1. Cooldown check → Daily guards (stop_all.flag, target_met.flag)
2. Position limits check → Daily loss checks (absolu + flottant)
3. Risk manager → Losing streak cooldown
4. Kill Switch global (400 USD) → Circuit Breaker par symbole
5. EOD restriction (18:00) et close (19:30 UTC)
6. Weekend guard (VEN 23:00 → DIM 22:05)
7. Agent signal gathering (tous les agents)
8. Direction aggregation (vote pondere + regime + dispersion)
9. Fast-track validation → Whale override
10. Confluence aggregation (tracker + macro + spread + ATR)
11. HARD FILTERS cascade (score, confluence, tracker, daily loss, session)
12. ATR-based SL/TP calculation
13. Market regime filter → Crypto bucket guard
14. Composite score → Inter-market guard → MTF confluence
15. Event guard (news blackout)
16. Volatility filter → Risk sizing → Execution MT5

**Poids dynamiques par regime (lignes 4205-4260) :**
- trending_up/down : swing x1.3, scalping x0.7
- ranging : structure x1.3, swing x0.7
- volatile : scalping x0.5, structure x1.2
- quiet : swing x0.5, scalping x0.3, structure x0.5, news x0.3

**Priorite TF (lignes 4205-4224) :**
- MN: 1.00, W1: 0.95, D1: 0.90, H4: 0.70, H1: 0.55, M30: 0.40, M15: 0.30, M5: 0.20, M1: 0.10

### 2.2 Agents de Trading - Analyse Detaillee

#### A. Technical Agent (agents/technical.py) - M30
- **Indicateurs** : EMA(50), RSI(14, seuils 32/68), MACD(12/26/9, epsilon 0.003), ADX(14, seuil 20)
- **Entree LONG** : price > EMA AND ema_slope > 0 AND macd_diff > 0.003 AND RSI < 68 AND ADX >= 20
- **Confirmation** : H4, H1 multi-timeframe bias
- **Scoring** : base 0.6 + bias(0.25) + rr_bonus(0.10) + macd_strength(0.15) → [-1, +1]
- **SL/TP** : 2.0x / 2.5x ATR avec min_dist = max(50 × point, price × 0.001)

#### B. Scalping Agent (agents/scalping.py) - M1
- **Indicateurs** : EMA(13), RSI(9, seuils 28/72), ATR(14)
- **Primary** : RSI divergence (RSI<=28 + price>=EMA + bias UP → LONG)
- **Fallback** : Trend suiveur (bias UP + price > EMA + RSI < 60 → LONG)
- **Anti-spam** : Cooldown 90s, 1 signal par bougie, spread max 35 pts
- **Detection regime** : EMA 34/89 (hardcodes, incompatibles avec EMA 13 principal)
- **SL/TP** : 1.6x / 2.0x ATR

#### C. Swing Agent (agents/swing.py) - H1
- **Dual-mode** : TREND (RSI > 55 + price > EMA → LONG) vs RANGE (RSI < 32 → LONG)
- **Regime** : Pente EMA sur 10 bougies (|slope| > 0.05 = trend, sinon range)
- **SL/TP** : 1.5x / 2.4x ATR (trend), 1.5x / 2.0x ATR (range)
- **Fallback** : Desactive par defaut (genere faux signaux)

#### D. Smart Money Agent (agents/smart_money.py) - M15
- **Concepts** : FVG (min 0.3×ATR), Equal Highs/Lows (tolerance 6pts ou 0.12%), Order Blocks (reaction > 1.5×ATR), AMD (80 bougies), Asian session sweep
- **Decision** : Pente lineaire (polyfit) > 1e-4 + pattern detect → signal
- **SL/TP dynamique** : Ajuste par vol_ratio et trend_strength. OB level comme SL alternatif

#### E. Price Action Agent (agents/price_action.py) - M15
- **Patterns** : BOS (break of structure), FBO (false breakout, prioritaire), OTE (Fibonacci 62-79%)
- **Decision** : FBO_UP → SHORT, FBO_DN → LONG, BOS_UP → LONG, OTE_match → selon direction
- **SL** : Niveau pivot (swing high/low), **TP** : price ± 2.5×ATR, RR min 1.5

#### F. Volume Profile Agent (agents/volume_profile.py) - H1
- **Indicateurs** : VWAP, POC (Point of Control), Value Area (70%), HVN/LVN
- **LONG** : price < VWAP ET price < POC, **SHORT** : price > VWAP ET price > POC
- **Confiance** : 0.5 base, 0.7 si hors VA, +0.15 si pres HVN (<0.5%)
- **SL** : LVN ± 10% VA range, **TP** : POC

#### G. Structure Agent (agents/structure.py) - M15
- **9 patterns SMC** : BOS, CHoCH, FBO, OTE, Inducement, Liquidity Sweep, Mitigation Block, Breaker Block, Equal Levels
- **Vote pondere** : BOS=2.0, CHoCH=2.0, Inducement=2.5, LiquiditySweep=2.0
- **Decision** : long_score > short_score × 1.2 ET long_score > 0
- **SL** : compute_invalidation_sl() (niveau structurel) avec fallback ATR

#### H. Sentiment Agent (agents/sentiment.py) - Crypto Only
- **Sources** : Fear&Greed 50%, Twitter 30%, Google Trends 20%
- **Logique contrarian** : Extreme Greed + aggregate > 0.4 → SHORT
- **Seuils** : upper=0.4, lower=-0.4

#### I. News Agent (agents/news.py)
- **Sources** : 7+ flux RSS, keywords bullish/bearish × source_weight
- **Phase 1** : TextBlob sentiment + keyword matching → bull-bear score
- **Phase 2** : FinBERT V2 (si disponible) → hybrid 70% FinBERT / 30% classique
- **Anti-spam** : Cache TTL 900s (configure mais NON IMPLEMENTE dans le code)

#### J. Fundamental Agent (agents/fundamental.py)
- **Sources** : FXStreet API, EconCalendarClient (retourne liste vide - TODO)
- **Logique** : Si event HIGH dans ±30min → WAIT. Si actual vs forecast > 0.3% → signal
- **Confiance fixe** : 0.55 pour TOUS les events (non adaptatif)

#### K. Macro Agent (agents/macro.py)
- **3 gardes** : Calendrier local (CSV/YAML), Spread guard, ATR spike guard (ratio > 2.0)
- **Resultat** : Booleien block/pass (pas de scoring)

#### L. Whale Agent (agents/whale_agent.py)
- **Scoring double** : Trust score (winrate/PnL/followers/age/verified) et Signal score (confidence/volume/impact/slippage)
- **Seuils** : min_trust=0.6, min_signal=0.55, vol_zscore_max=3.0
- **Status** : Connecteurs (onchain_listener, cex_tracker, social_verifier) sont des stubs

### 2.3 Gestion du Risque - 7 Couches

| Couche | Module | Seuil | Persistance |
|--------|--------|-------|-------------|
| 1. GlobalKillSwitch | risk_manager.py | -400 USD/jour | data/daily_loss_state.json |
| 2. Daily Loss % | orchestrator.py | -2% equity | En memoire |
| 3. CircuitBreaker | circuit_breaker.py | 3 pertes consec → 24h block | data/circuit_breaker_state.json |
| 4. Cooldown Streak | orchestrator.py | 3 pertes → 60 min pause | En memoire |
| 5. Crypto Bucket | orchestrator.py | 2% cap, 2 positions max | En memoire |
| 6. Max Positions | orchestrator.py | Configurable par symbole | En memoire |
| 7. Direction Lock | overrides.yaml | BNBUSD = SHORT only | Config |

### 2.4 Hard Filters - Seuils Exacts

| # | Filtre | Variable | Seuil | Ligne Orch |
|---|--------|----------|-------|------------|
| 1 | Score minimum | HARD_MIN_SCORE | >= 8.0 | ~2050 |
| 2 | Confluence minimum | HARD_MIN_CONFLUENCE | >= 5 | ~2060 |
| 3 | Tracker contradiction | TRACKER_CONTRADICTION_THRESHOLD | < 0.25 | ~2071 |
| 4 | Daily loss % | daily_limit_pct | <= -2% | ~2104 |
| 5 | Low liquidity hours | low_liquidity_hours_utc | [0-5, 18-23] UTC | ~2139 |
| 6 | Dispersion agents | _disagree_pct | > 0.45 = -1.0 score | ~4327 |
| 7 | RR minimum | min_rr | >= 1.5 | ~3344 |
| 8 | Regime counter-trend | regime + confidence | contre-tendance = score >= 10 requis | ~3402 |
| 9 | Quiet regime | quiet + confidence > 0.7 | REJECT | ~3392 |
| 10 | EOD restriction | last_entry_time_utc | 18:00 UTC | ~2954 |
| 11 | EOD close | eod_close_time_utc | 19:30 UTC | ~2966 |
| 12 | Weekend close | close_day/time | VEN 23:00 | ~1207 |
| 13 | Weekend reopen | reopen_day/time | DIM 22:05 | ~1213 |
| 14 | Crypto exempt | is_crypto hardcode | 6 symboles fixes | ~2149 |
| 15 | Whale volatility | vol_zscore max | 3.0 | ~3105 |

### 2.5 Position Manager (utils/position_manager.py)

- **Break-Even** : SL → entree apres RR 1.2 (be_rr = 1.0 hardcode comme defaut)
- **Partials** : 30% a RR 1.5, 30% a RR 2.5
- **Trailing Stop** : ATR × 1.5 a partir de RR 1.5
- **Timeout** : BTCUSD 480min (8h), BNBUSD 360min (6h)
- **EOD Close** : Ferme non-crypto avant 21h UTC
- **Lock MT5 global** : `_MT5_OPERATION_LOCK` avec delai 1.5s minimum

### 2.6 Optimisation Automatique (Optuna)

- Frequence : hebdomadaire (dimanche 02:00 UTC)
- 30 essais, TPE sampler, MedianPruner
- Objectif : Profit Factor max, contraintes DD < 15%, WR > 50%, min_trades >= 50
- Walk-forward : 70% train / 30% validation sur 180 jours
- Auto-apply si amelioration >= 5%
- Symboles inclus : GBPUSD/USDJPY (desactives dans overrides!) - incoherence

### 2.7 Reporting et Monitoring

- **Daily Digest** : 5x/jour via APScheduler (Europe/Zurich)
- **Trade Events** : Notification Telegram a chaque entree/sortie avec boutons ✅/❌
- **Logs** : proposals_log.csv, agents_snap.jsonl, trades_log.csv, equity_log.csv
- **Audit** : reports/audit_trades.jsonl
- **Trades DB** : SQLite (historique + cycles de decision)
- **Performance Tracker** : Poids adaptatifs EMA par (symbol, agent, TF, regime)
- **Health Server** : HTTP /healthz, /readyz, /metrics (port 9108)
- **Prometheus** : Gauges whale trust/signal/latency (optionnel)

---

## 3. POINTS FAIBLES ET PROBLEMES IDENTIFIES

### 3.1 BUGS CRITIQUES (8 identifies)

#### BUG-01 : Variables non definies dans le mode Dry Run
**Fichier** : `orchestrator/orchestrator.py` (lignes ~2410-2421)
**Severite** : HAUTE
**Description** : Le bloc dry_run utilise des variables (`volume`, `tp1`, `tp2`, `confluences`, `confluence_breakdown`, `decision_notes`) qui ne sont jamais declarees dans ce scope. Le f-string crashera ou produira des donnees incorrectes.

#### BUG-02 : Race conditions sur fichiers d'etat JSON
**Fichiers** : `utils/risk_manager.py`, `utils/position_manager.py`, `utils/circuit_breaker.py`
**Severite** : CRITIQUE
**Description** : Les fichiers `daily_loss_state.json`, `pm_state.json`, `circuit_breaker_state.json` sont lus/ecrits sans verrou (lock). Avec 8+ orchestrateurs paralleles (un par symbole), corruption d'etat possible.

#### BUG-03 : Tracker partage entre TOUS les symboles
**Fichier** : `orchestrator/orchestrator.py` (ligne ~970)
**Severite** : HAUTE
**Description** : `self.tracker = default_tracker()` cree UNE SEULE INSTANCE de PerformanceTracker partagee par tous les orchestrateurs. Les poids adaptatifs d'un symbole impactent les autres. Conflit multi-symbole.

#### BUG-04 : Floating P&L bloque tous les trades en cas d'erreur MT5
**Fichier** : `orchestrator/orchestrator.py` (lignes ~2858-2866)
**Severite** : MOYENNE
**Description** : Si le calcul du P&L flottant echoue (MT5 indisponible temporairement), le systeme BLOQUE PAR PRECAUTION tous les nouveaux trades. Un simple timeout MT5 = faux positif.

#### BUG-05 : Whale Trust EWMA utilisee sans verification None
**Fichier** : `orchestrator/orchestrator.py` (ligne ~4389)
**Severite** : MOYENNE
**Description** : `self._whale_trust_ewma` peut etre None mais est utilisee dans le calcul du poids dynamique. TypeError possible.

#### BUG-06 : Agent desactive = permanent jusqu'au restart
**Fichier** : `orchestrator/orchestrator.py` (lignes ~3932-3941)
**Severite** : MOYENNE
**Description** : Apres 5 erreurs consecutives, `_agent_disabled.add(agent_name)` desactive l'agent DEFINITIVEMENT. Aucun mecanisme de reactivation sans redemarrage complet.

#### BUG-07 : econ_api.py retourne toujours une liste vide
**Fichier** : `utils/econ_api.py`
**Severite** : HAUTE
**Description** : La methode `events_between()` contient un TODO et retourne `[]`. Le calendrier economique via cette API est completement NON FONCTIONNEL. Les agents fundamental et macro operent sans donnees reelles.

#### BUG-08 : advanced_sentiment.py utilise des donnees simulees (random)
**Fichier** : `utils/advanced_sentiment.py`
**Severite** : HAUTE
**Description** : `fetch_retail_sentiment()` utilise `random.randint()` au lieu de vraies donnees. COT, retail, funding rate tous "simulated". Les signaux sentiment reposent sur du BRUIT ALEATOIRE.

### 3.2 FAIBLESSES DE GESTION DU RISQUE (7 identifiees)

#### RISK-01 : R-multiple mal estime (TradeOutcomeTracker)
**Fichier** : `utils/trade_outcome_tracker.py`
**Description** : Formule `sl_distance * volume * 100` si initial_risk absent. Fermetures partielles non gerees → double-comptage du profit. R-multiple fausse → poids adaptatifs incorrects.

#### RISK-02 : CircuitBreaker ne distingue pas l'amplitude des pertes
**Fichier** : `utils/circuit_breaker.py`
**Description** : 3 pertes de 1$ = 3 pertes de 1000$, meme traitement. Pas de weighted drawdown.

#### RISK-03 : Gating "allow_no_report" dangereux
**Fichier** : `utils/gating.py`
**Description** : Permet de trader sans backtest si flag=True (actif en mode demo).

#### RISK-04 : Preset "aggressive" avec RR < 1.0
**Fichier** : `config/presets/overrides.aggressive.yaml`
**Description** : `rr_min: 0.8` = perte mathematique attendue. `min_confluence: 0` = aucune confirmation. `after_streak_min: 0` = pas de pause apres pertes consecutives.

#### RISK-05 : Weekend crypto 3x plus agressif
**Fichier** : `config/presets/overrides.weekend.yaml`
**Description** : `crypto_bucket.cap` passe de 0.02 (2%) en semaine a 0.06 (6%) le weekend. `risk_per_trade` = 1.4% BTCUSD (vs 0.5% en semaine). Profil tres risque.

#### RISK-06 : pip_value USDJPY instable
**Fichier** : `config/profiles.yaml`
**Description** : `pip_value: 0.64` depend du taux USD/JPY courant. Valeur fixe = sizing potentiellement incorrect.

#### RISK-07 : Quiet regime bloque presque tout silencieusement
**Fichier** : `orchestrator/orchestrator.py` (lignes ~4253-4260)
**Description** : En regime quiet, multiplicateurs = swing x0.5, scalping x0.3, structure x0.5, news x0.3. Combine avec score >= 10 requis pour counter-trend, quasiment aucun signal ne passe.

### 3.3 PROBLEMES DE SECURITE (4 identifies)

#### SEC-01 : Credentials MT5 et Telegram EN CLAIR dans config.yaml
**Fichier** : `config/config.yaml` (lignes 3, 15-16)
**Severite** : CRITIQUE
**Description** : Mot de passe MT5, token Telegram, et chat_id sont en clair dans le YAML commite dans git. Toute personne avec acces au repo a acces au compte de trading et au bot Telegram.

#### SEC-02 : Token Telegram visible dans logs
**Fichier** : `utils/telegram_client.py`
**Description** : L'URL API `https://api.telegram.org/bot{token}` peut etre loguee. Le logger redacte certains patterns mais pas tous.

#### SEC-03 : Pas de rate limiting sur les requetes API
**Description** : Aucun rate limiter global pour Finnhub (60 calls/min), Alpha Vantage (25/jour), ou Telegram.

#### SEC-04 : Symbole LNKUSD dans overrides.backup.yaml
**Fichier** : `config/overrides.backup.yaml`
**Description** : Symbole Chainlink (LNKUSD) configure dans le backup mais absent de TOUS les autres fichiers config. Risque d'activation accidentelle sans profil valide.

### 3.4 INEFFICACITES DE PERFORMANCE (7 identifiees)

#### PERF-01 : Rechargement dynamique des agents a chaque cycle (60s)
**Fichier** : `orchestrator/orchestrator.py` (lignes ~3838-3869)
**Description** : `importlib.import_module()` + inspection de signature a chaque cycle. ~200ms gaspillees.

#### PERF-02 : Appels MT5 synchrones non caches
**Fichiers** : `utils/mt5_client.py`, `utils/position_manager.py`
**Description** : `positions_get()`, `account_info()`, `symbol_info()` appeles a chaque cycle sans cache. ~50-200ms par appel.

#### PERF-03 : Agents executent en serie, non en parallele
**Description** : 12 agents sequentiels. Avec asyncio.gather(), temps de cycle / 4-8x.

#### PERF-04 : News + Sentiment agents bloquants (5-10s chacun)
**Fichiers** : `agents/news.py`, `agents/sentiment.py`
**Description** : Fetch RSS (7 flux), Twitter API, Google Trends, Fear&Greed = ~10-15s si synchrone.

#### PERF-05 : Event Guard web scraping bloquant
**Fichier** : `utils/event_guard.py`
**Description** : Timeout 15s par source × 3 sources = jusqu'a 45s en pire cas.

#### PERF-06 : data_sources.py cache sans limite de taille (memory leak)
**Fichier** : `utils/data_sources.py`
**Description** : Dict `_cache` croit indefiniment sans eviction. En production longue duree, consommation memoire croissante.

#### PERF-07 : Structure agent recalcule 9 patterns SMC a chaque appel
**Fichier** : `agents/structure.py`
**Description** : `detect_all_patterns()` sur 300 bougies × 9 patterns sans cache. Couteux sur M1.

### 3.5 LOGIQUE DE STRATEGIE A REVOIR (8 identifiees)

#### STRAT-01 : Scalping M1 trop bruite + EMA incompatibles
**Fichier** : `agents/scalping.py`
**Description** : RSI(9) extremement volatile sur M1. Detection regime utilise EMA 34/89 (hardcodes) incompatibles avec EMA 13 du signal principal.

#### STRAT-02 : Volume Profile dependant de tick_volume
**Fichier** : `agents/volume_profile.py`
**Description** : VWAP/POC calcules avec tick_volume (fallback). tick_volume ≠ real_volume → distorsion VWAP/POC. Value Area peut etre disjointe (non contigue).

#### STRAT-03 : Calendrier economique non fonctionnel
**Fichiers** : `utils/econ_api.py`, `config/econ_calendar.yaml`
**Description** : econ_api.py retourne `[]` (TODO). econ_calendar.yaml contient 1 seul event obsolete (FOMC 2025-08-19). Agents fundamental/macro operent a l'aveugle.

#### STRAT-04 : TextBlob NLP tres basique + cache news non implemente
**Fichier** : `agents/news.py`
**Description** : TextBlob precision ~60%. Cache TTL 900s configure mais jamais utilise dans le code → flux RSS re-fetches a chaque appel.

#### STRAT-05 : Sentiment avance utilise donnees ALEATOIRES
**Fichier** : `utils/advanced_sentiment.py`
**Description** : COT, retail, funding rate sont tous `simulated` avec `random.randint()`. Les signaux contrarians sont du bruit pur.

#### STRAT-06 : Fundamental Agent confiance fixe 0.55 pour tous les events
**Fichier** : `agents/fundamental.py`
**Description** : NFP, FOMC, CPI = meme confiance 0.55. Un NFP devrait avoir confiance > 0.8, un PMI secondaire < 0.3.

#### STRAT-07 : Price Action OTE potentiellement inverse
**Fichier** : `agents/price_action.py` (lignes ~100-112)
**Description** : Quand hi_row > lo_row (recent high = swing down), la logique retourne "SHORT" pour la zone OTE. Confusion directionnelle possible.

#### STRAT-08 : Smart Money FVG scan limite a 15 dernieres bougies
**Fichier** : `agents/smart_money.py` (lignes ~116-151)
**Description** : Le scan FVG ne teste que les 15 dernieres bougies max. Des FVG structurellement importants plus eloignes sont ignores.

### 3.6 INCOHERENCES DE CONFIGURATION (6 identifiees)

#### CONFIG-01 : Symboles orphelins (DJ30, GER40, CL-OIL)
**Fichier** : `config/asset_config.yaml`
**Description** : Ces 3 symboles sont configures dans asset_config.yaml avec sessions et parametres, mais sont ABSENTS de profiles.yaml et config.yaml.

#### CONFIG-02 : Optuna optimise des symboles desactives
**Fichier** : `config/auto_optimization.yaml`
**Description** : GBPUSD et USDJPY sont dans la liste d'optimisation mais desactives dans overrides.yaml.

#### CONFIG-03 : Symboles desactives avec 200+ lignes de config mort
**Fichier** : `config/overrides.yaml`
**Description** : LTCUSD (desactive, 205 lignes conservees), AUDUSD (desactive avec prime_hours configures).

#### CONFIG-04 : News blackout inconsistant
**Fichier** : `config/config.yaml`
**Description** : news_blackout_minutes: 30 dans volatility_filter vs 45 dans overrides EURUSD/XAUUSD.

#### CONFIG-05 : FinBERT configure mais absent de requirements.txt
**Fichier** : `requirements.txt`
**Description** : FinBERT reference dans config.yaml et advanced_sentiment_v2.py mais ni `transformers` ni `torch` dans requirements.txt.

#### CONFIG-06 : min_trades incoherent entre presets
**Description** : Demo: 50, Live: 200, Live Small: 200 (identique a Live!). Le preset "small" devrait avoir des seuils plus bas.

---

## 4. RECOMMANDATIONS D'AMELIORATION PRIORISEES

### HIGH IMPACT - Impact direct sur la rentabilite et la stabilite

| # | Recommandation | Impact | Effort | Justification |
|---|---------------|--------|--------|---------------|
| H-01 | **Securiser les credentials (migrer vers .env)** | HIGH | 2h | Credentials en clair = compromission possible du compte de trading et du bot Telegram. |
| H-02 | **Ajouter locks thread-safe sur fichiers JSON d'etat** | HIGH | 3h | Race conditions corrompent kill-switch, circuit breaker, etat positions. Kill-switch corrompu = perte protection capital. |
| H-03 | **Corriger econ_api.py (TODO → implementation reelle)** | HIGH | 4h | Calendrier eco retourne liste vide. Agents fundamental/macro sont aveugles aux evenements majeurs (FOMC, NFP, CPI). |
| H-04 | **Corriger advanced_sentiment.py (random → API reelles)** | HIGH | 6h | Donnees COT/retail/funding rate sont du bruit aleatoire (random.randint). Signaux contrarians sans fondement. |
| H-05 | **Corriger le calcul R-multiple pour fermetures partielles** | HIGH | 4h | R-multiple incorrect → poids adaptatifs fausses → mauvaise allocation capital. |
| H-06 | **Separer le PerformanceTracker par symbole** | HIGH | 3h | Instance unique partagee entre symboles → conflit de poids adaptatifs. |
| H-07 | **Cacher les instances d'agents + paralleliser via asyncio** | HIGH | 6h | Agents en serie = latence cumulative. Import a chaque cycle = 200ms gaspillees. |
| H-08 | **Ajouter cache TTL pour appels MT5** | HIGH | 3h | Reduit latence I/O de 50-200ms par appel. Cache 5-10s suffisant. |
| H-09 | **Passer calendrier eco statique → live** | HIGH | 6h | econ_calendar.yaml contient 1 event obsolete (2025-08-19). Risque de trader pendant annonces high-impact. |
| H-10 | **Migrer scalping M1 → M5** | HIGH | 3h | M1 trop bruite. EMA 34/89 hardcodes incompatibles avec EMA 13 principal. |

### MEDIUM IMPACT - Ameliorations significatives

| # | Recommandation | Impact | Effort | Justification |
|---|---------------|--------|--------|---------------|
| M-01 | **Remplacer TextBlob par FinBERT + ajouter a requirements.txt** | MEDIUM | 4h | TextBlob ~60% precision. FinBERT ~85%. Deja code (v2) mais pas installe. |
| M-02 | **Ajouter weighted drawdown au CircuitBreaker** | MEDIUM | 3h | 3 pertes de 1$ ≠ 3 pertes de 1000$. |
| M-03 | **Corriger mode dry-run (variables undefined)** | MEDIUM | 2h | Dry-run essentiel pour tests. Variables volume/tp1/tp2 non definies. |
| M-04 | **Implanter cache TTL pour news.py** | MEDIUM | 2h | Cache 900s configure mais NON IMPLEMENTE. Flux RSS re-fetches inutilement. |
| M-05 | **Externaliser 30+ valeurs hardcodees vers config** | MEDIUM | 3h | HARD_MIN_SCORE, blocked_hours, crypto symbols, kill_switch limit, etc. |
| M-06 | **Confiance adaptative pour Fundamental Agent** | MEDIUM | 2h | NFP/FOMC → 0.8, PMI → 0.4, au lieu de 0.55 fixe pour tout. |
| M-07 | **Nettoyer configs mortes (symboles desactives)** | MEDIUM | 1h | 200+ lignes de config pour LTCUSD/AUDUSD desactives. Confusion maintenance. |
| M-08 | **Desactiver preset aggressive (RR 0.8)** | MEDIUM | 0.5h | rr_min=0.8 = perte mathematique. min_confluence=0 = zero confirmation. Dangereux. |
| M-09 | **Tests unitaires composite_score + smc_patterns** | MEDIUM | 8h | Modules critiques sans tests. Zero couverture estimee (<5%). |
| M-10 | **Ajouter mecanisme reactivation agent desactive** | MEDIUM | 2h | Agent desactive apres 5 erreurs = permanent. Timer de retry (ex: 1h). |

### LOW IMPACT - Optimisations a moyen terme

| # | Recommandation | Impact | Effort | Justification |
|---|---------------|--------|--------|---------------|
| L-01 | **Implementer connecteurs whale reels (Phase 6)** | LOW | 20h | Stubs uniquement. Complexite elevee, gain incertain. |
| L-02 | **Corriger data_sources.py memory leak cache** | LOW | 1h | Cache dict sans eviction. Impact long terme en production. |
| L-03 | **Ajouter log rotation** | LOW | 1h | Logs peuvent remplir le disque. |
| L-04 | **Aligner symboles orphelins (DJ30/GER40/CL-OIL)** | LOW | 1h | Configures dans asset_config mais absents ailleurs. |
| L-05 | **Sourcer real volume crypto (Binance/Kraken)** | LOW | 8h | Volume Profile imprecis avec tick_volume. |
| L-06 | **pip_value dynamique pour USDJPY** | LOW | 2h | Valeur fixe 0.64 depend du taux courant. |

---

## 5. PROMPTS PRETS A L'EMPLOI POUR CLAUDE CODE

### PROMPT H-01 : Migration Credentials vers .env

```
Objectif : Deplacer TOUTES les credentials sensibles de config.yaml vers un fichier .env.

CONTEXTE CRITIQUE : config/config.yaml contient actuellement en clair :
- Ligne 3 : password MT5
- Ligne 15 : token Telegram (format 7969631468:AAH...)
- Ligne 16 : chat_id Telegram

Fichiers concernes :
- config/config.yaml : remplacer valeurs par ${VARIABLE_NAME}
- .env.example : ajouter tous les champs avec placeholders
- .env : creer avec les vraies valeurs (verifier que .gitignore le couvre)
- utils/config_loader.py : creer/modifier un loader qui expand ${VAR} depuis os.environ
- utils/settings.py : deja charge dotenv mais pas utilise par config.yaml
- main.py : utiliser le nouveau loader
- orchestrator/orchestrator.py : adapter les references credentials

Modifications :
1. Dans config.yaml, remplacer les valeurs sensibles par des placeholders :
   mt5:
     account: ${MT5_ACCOUNT}
     password: ${MT5_PASSWORD}
     server: ${MT5_SERVER}
   telegram:
     token: ${TELEGRAM_BOT_TOKEN}
     chat_id: ${TELEGRAM_CHAT_ID}
   external_apis:
     finnhub_key: ${FINNHUB_API_KEY}
     alpha_vantage_key: ${ALPHA_VANTAGE_API_KEY}

2. utils/config_loader.py a deja une fonction de parsing .env custom. L'etendre pour :
   a. Charger .env via python-dotenv en premier
   b. Lire config.yaml
   c. Parcourir recursivement le dict YAML et remplacer ${VAR} par os.environ[VAR]
   d. Lever une ValueError claire si une variable manque (avec le nom)

3. Mettre a jour .env.example avec documentation
4. Verifier .gitignore contient .env
5. NE PAS commiter le .env, seulement .env.example
```

### PROMPT H-02 : Thread-Safety des Fichiers d'Etat JSON

```
Objectif : Ajouter un verrou thread-safe (threading.Lock) pour tous les acces aux fichiers JSON d'etat partages entre orchestrateurs.

Fichiers concernes :
- utils/risk_manager.py : GlobalKillSwitch._save_state() et _load_state() → data/daily_loss_state.json
- utils/position_manager.py : _load_state() et _save_state() → data/pm_state.json
- utils/circuit_breaker.py : _save_state() et _load_state() → data/circuit_breaker_state.json

Pour CHAQUE fichier :
1. Ajouter un threading.Lock au niveau du module :
   _FILE_LOCK = threading.Lock()
2. Wrapper chaque acces lecture/ecriture du fichier JSON avec :
   with _FILE_LOCK:
3. Remplacer les "except Exception: pass" par :
   except (FileNotFoundError, json.JSONDecodeError, IOError) as e:
       logger.warning(f"[STATE] Erreur I/O {path}: {e}")
4. Ajouter une ecriture atomique (write to temp file, then os.replace) :
   tmp_path = path + ".tmp"
   with open(tmp_path, "w") as f: json.dump(...)
   os.replace(tmp_path, path)

Ne pas modifier la logique metier, uniquement la protection de concurrence et la robustesse I/O.
```

### PROMPT H-03 : Implementer econ_api.py

```
Objectif : Remplacer le TODO dans utils/econ_api.py par une implementation reelle du calendrier economique.

Fichier concerne : utils/econ_api.py (actuellement retourne toujours une liste vide)

Contexte : La classe EconCalendarClient.events_between() a un commentaire "implémentez une vraie source". Les agents fundamental.py et macro.py dependent de cette source.

Implementation :
1. Source principale : Finnhub Calendar API (config.yaml contient deja finnhub_key)
   - Endpoint : /calendar/economic
   - Retourne : liste d'events avec date, impact, country, actual, forecast, previous

2. Source secondaire : FXStreet API (deja utilise dans event_guard.py, copier la logique)

3. Structure de retour (deja definie dans le module) :
   [{"datetime": "2026-03-01T14:30:00Z", "currency": "USD", "impact": "HIGH",
     "title": "Non-Farm Payrolls", "actual": "200K", "forecast": "185K", "previous": "175K"}]

4. Ajouter un cache TTL de 30 minutes pour eviter les appels API excessifs

5. Ajouter un rate limiter : max 1 appel/minute pour Finnhub

6. Mettre a jour config/econ_calendar.yaml pour etre deprecie (ajouter commentaire)

7. Tester que agents/fundamental.py et agents/macro.py recoivent des events reels
```

### PROMPT H-04 : Corriger advanced_sentiment.py (donnees simulees)

```
Objectif : Remplacer les donnees simulees (random.randint) dans utils/advanced_sentiment.py par des sources de donnees reelles ou desactiver proprement le module.

Fichier concerne : utils/advanced_sentiment.py

Probleme actuel : Les fonctions fetch_retail_sentiment(), fetch_cot_data(), fetch_funding_rate() utilisent toutes random.randint() pour generer des donnees fictives. Les signaux contrarians bases sur ces donnees sont du bruit pur.

Option A (Recommandee - Implementer APIs reelles) :
1. Funding Rate : Utiliser Binance API /fapi/v1/fundingRate (gratuit, pas de cle)
   - Crypto uniquement (BTCUSDT, ETHUSDT)
   - Retourner le taux actuel normalise

2. Retail Sentiment : Utiliser IG Client Sentiment ou Myfxbook (scraping)
   - Ou desactiver si aucune source fiable

3. COT (Commitment of Traders) : Utiliser CFTC weekly data via quandl ou scraping
   - Mise a jour hebdomadaire seulement

4. Pour chaque source : ajouter cache TTL, error handling, fallback None

Option B (Si APIs non disponibles) :
1. Desactiver completement le module advanced_sentiment
2. Dans composite_score.py, redistribuer le poids sentiment (15%) vers agents (65%) et volume (20%)
3. Logger un warning au demarrage : "[SENTIMENT] Module advanced_sentiment desactive (donnees simulees)"
4. Retirer l'import dans orchestrator.py
```

### PROMPT H-05 : Correction R-Multiple pour Fermetures Partielles

```
Objectif : Corriger le calcul du R-multiple dans le TradeOutcomeTracker pour gerer les fermetures partielles et le initial_risk manquant.

Fichier concerne : utils/trade_outcome_tracker.py

Modifications :
1. Dans la methode de calcul du R-multiple (chercher "r_multiple" ou "initial_risk") :
   a. Si initial_risk est disponible (depuis le journal de trade) : R = realized_pnl / initial_risk
   b. Si initial_risk manquant mais SL connu : initial_risk = abs(entry - sl) * volume * point_value
   c. Si ni l'un ni l'autre : marquer comme "R_UNKNOWN" et NE PAS enregistrer dans PerformanceTracker

2. Pour les fermetures partielles :
   a. Tracker le volume restant apres chaque partial close
   b. Ne calculer le R-multiple final que quand volume_restant = 0
   c. Aggreger les PnL de tous les deals partiels pour un meme ticket initial
   d. Ajouter un champ "partial_deals" dans le CSV de suivi

3. Synchroniser avec position_manager.py :
   a. Quand PM fait un partial close, enregistrer le deal_ticket dans pm_state
   b. TradeOutcomeTracker lit pm_state pour detecter les partiels
   c. Eviter le double-comptage en verifiant les deal_tickets deja traites
```

### PROMPT H-06 : Separer le PerformanceTracker par Symbole

```
Objectif : Creer une instance separee de PerformanceTracker par orchestrateur (par symbole) au lieu d'une instance partagee.

Fichier concerne : orchestrator/orchestrator.py (ligne ~970)

Probleme actuel :
self.tracker = default_tracker()  # UNE SEULE INSTANCE pour TOUS les symboles

Modifications :
1. Localiser l'appel default_tracker() dans __init__ (vers ligne 970)
2. Remplacer par une creation d'instance unique par symbole :
   from utils.performance_tracker import PerformanceTracker
   self.tracker = PerformanceTracker(state_file=f"data/performance/tracker_{self.symbol}.json")

3. Modifier PerformanceTracker.__init__ dans utils/performance_tracker.py pour accepter un state_file optionnel
   - Defaut : "data/performance/performance_tracker.json" (retro-compatible)
   - Si state_file fourni : utiliser ce fichier

4. Migrer les donnees existantes :
   a. Lire l'ancien fichier unique
   b. Filtrer par symbol
   c. Ecrire dans les fichiers separes

5. Verifier que le digest et les reports lisent tous les fichiers tracker (pas seulement le global)
```

### PROMPT H-07 : Cache Agents + Parallelisation asyncio

```
Objectif : (A) Cacher les instances d'agents au lieu de les reimporter a chaque cycle, (B) Executer les agents en parallele.

Fichier concerne : orchestrator/orchestrator.py

PARTIE A - Cache (lignes ~3838-3870) :
1. Ajouter self._agent_cache: Dict[str, Any] = {} dans __init__
2. Modifier le chargement dynamique :
   def _get_or_load_agent(self, module_name, class_name, **kwargs):
       key = f"{module_name}.{class_name}"
       if key not in self._agent_cache:
           mod = importlib.import_module(f"agents.{module_name}")
           cls = getattr(mod, class_name)
           self._agent_cache[key] = cls(**kwargs)
       return self._agent_cache[key]
3. L'error monitoring (5 erreurs → desactivation) doit aussi retirer du cache
4. Ajouter methode _invalidate_agent_cache() appelee si config change

PARTIE B - Parallelisation (lignes ~3977-4165) :
1. Wrapper chaque appel agent dans asyncio.to_thread() (agents sont synchrones)
2. Utiliser asyncio.gather() avec return_exceptions=True
3. Timeout par agent : 10s (news/sentiment peuvent etre lents)
4. Si un agent timeout/echoue : logger + continuer avec les autres
5. Collecter resultats dans per_tf_signals et global_signals comme avant

Ne pas modifier la logique d'aggregation des signaux en aval.
```

### PROMPT H-08 : Cache TTL pour les Appels MT5

```
Objectif : Implementer un cache TTL pour les appels MT5 frequents.

Fichier concerne : utils/mt5_client.py

1. Ajouter une classe TTLCache thread-safe en haut du fichier :
   class TTLCache:
       def __init__(self):
           self._cache = {}
           self._lock = threading.Lock()
       def get(self, key, ttl):
           with self._lock:
               if key in self._cache:
                   val, ts = self._cache[key]
                   if time.time() - ts < ttl: return val
           return None
       def set(self, key, value):
           with self._lock:
               self._cache[key] = (value, time.time())
       def invalidate(self, prefix=""):
           with self._lock:
               if prefix:
                   self._cache = {k: v for k, v in self._cache.items() if not k.startswith(prefix)}
               else:
                   self._cache.clear()

2. Cacher les methodes :
   - positions_get() : TTL 5s
   - account_info() : TTL 10s
   - symbol_info() : TTL 60s
   - symbol_info_tick() : TTL 2s

3. Invalidation apres place_order() et close_position()

Ne PAS cacher : copy_rates_from_pos(), history_deals_get()
```

### PROMPT H-09 : Calendrier Economique Live

```
Objectif : Remplacer le calendrier statique (CSV/YAML) par un refresh automatique.

Fichiers concernes :
- utils/event_guard.py : source principale
- agents/fundamental.py : utilise le calendrier
- agents/macro.py : utilise le calendrier local
- config/econ_calendar.yaml : a deprecier (contient 1 event obsolete FOMC 2025-08-19)

Modifications :
1. Dans utils/event_guard.py :
   a. Ajouter un thread timer de refresh toutes les 2h
   b. Sources prioritaires : FXStreet API > Finnhub Calendar > Investing.com scraping
   c. Deduplication par (date, heure, evenement, devise)
   d. Persistance : data/news_calendar_live.json
   e. Fallback : dernier cache local si toutes sources echouent

2. Dans agents/fundamental.py :
   a. Remplacer lecture calendrier statique par event_guard.get_upcoming_events()

3. Dans agents/macro.py :
   a. Fallback vers event_guard si CSV local obsolete (> 7 jours)

4. Rate limiter : max 1 requete/source/30min
5. Deprecier config/econ_calendar.yaml avec commentaire
```

### PROMPT H-10 : Migration Scalping M1 → M5

```
Objectif : Migrer l'agent scalping de M1 (trop bruite) vers M5.

Fichier concerne : agents/scalping.py

Modifications :
1. Timeframe : "M1" → "M5"
2. RSI : periode 9 → 14, seuils 28/72 → 30/70
3. Cooldown : 90s → 300s
4. ATR SL/TP : 1.6/2.0 → 1.8/2.5
5. Lookback : 120 → 60 barres (M5 = 5h)
6. CORRIGER le regime detection : remplacer EMA 34/89 hardcodes (lignes 335-336)
   par les parametres de l'agent (ema_period × 2.6 et ema_period × 6.8)
7. Ajouter confirmation M15 comme bias (si M15 bearish, pas de LONG scalp)
8. Spread filter : ajouter spread_atr_ratio < 0.25

Mettre a jour aussi :
- config/config.yaml : agents.scalping.timeframe si existe
- config/profiles.yaml : timeframes scalping
```

### PROMPT M-03 : Correction Mode Dry-Run

```
Objectif : Corriger les variables non definies dans le bloc dry-run.

Fichier : orchestrator/orchestrator.py (lignes ~2408-2425)

1. Localiser "if getattr(self, 'dry_run', False):"
2. Variables non definies : volume, tp1, tp2, confluences, confluence_breakdown, decision_notes
3. Calculer TOUTES ces variables AVANT le branchement dry-run/live :
   - volume : depuis risk_sizing (lots = self.risk.compute_position_size(...))
   - tp1 : original_tp × partial_ratio_1 (ex: RR 1.5 du profile)
   - tp2 : original_tp × partial_ratio_2 (ex: RR 2.5)
   - confluences : self._last_ctx.get("confluence_breakdown", {})
   - decision_notes : self._last_ctx.get("decision_notes", "")
4. Restructurer le flux pour calcul commun puis if dry_run: / else:
5. Ajouter logging : logger.info(f"[DRY_RUN] Signal {direction} {symbol} score={score} lots={volume}")
```

### PROMPT M-05 : Externaliser Valeurs Hardcodees

```
Objectif : Deplacer 30+ valeurs hardcodees critiques de orchestrator.py vers config.yaml.

Fichier source : orchestrator/orchestrator.py
Fichier destination : config/config.yaml (nouvelle section orchestrator.hard_filters)

Valeurs a externaliser (avec lignes approximatives dans orchestrator.py) :
1. HARD_MIN_SCORE = 8.0 (ligne ~2050) → orchestrator.hard_filters.min_score
2. HARD_MIN_CONFLUENCE = 5 (ligne ~2060) → orchestrator.hard_filters.min_confluence
3. TRACKER_CONTRADICTION_THRESHOLD = 0.25 (ligne ~2071) → orchestrator.hard_filters.tracker_contradiction
4. disagree_pct seuils 0.45/0.35 (ligne ~4327) → orchestrator.hard_filters.disagree_block/penalty
5. low_liquidity_hours_utc [0-5,18-23] (ligne ~2139) → orchestrator.session.blocked_hours_utc
6. crypto symbols hardcodes {"BTCUSD","ETHUSD",...} (ligne ~2149) → orchestrator.crypto_symbols
7. min_rr 1.5 (ligne ~3344) → orchestrator.hard_filters.min_rr
8. kill_switch_limit 400 USD (ligne ~2921) → risk.kill_switch.daily_loss_usd
9. break_even be_rr 1.0 (ligne ~1058) → position_manager.default_be_rr
10. quiet regime block confidence 0.7 (ligne ~3392) → orchestrator.regime.quiet_block_confidence
11. counter-trend score requis 10.0 (ligne ~3402) → orchestrator.regime.counter_trend_min_score
12. whale volatility limit 3.0 (ligne ~3105) → whale.max_vol_zscore

Dans orchestrator.py :
- Lire depuis self.ori_cfg avec .get() et valeurs par defaut actuelles
- Logger les valeurs au demarrage pour audit
```

### PROMPT M-06 : Confiance Adaptative Agent Fundamental

```
Objectif : Remplacer la confiance fixe 0.55 par une confiance adaptative selon le type d'event.

Fichier : agents/fundamental.py (ligne ~302)

Modifications :
1. Creer un mapping impact → confiance :
   CONFIDENCE_MAP = {
       "NFP": 0.85,
       "FOMC": 0.90,
       "CPI": 0.80,
       "Interest Rate": 0.85,
       "GDP": 0.70,
       "PMI": 0.50,
       "Retail Sales": 0.55,
       "Employment": 0.65,
       "Trade Balance": 0.45,
       "default": 0.40
   }

2. Matcher le titre de l'event contre les cles du mapping (case-insensitive, keyword search)
3. Si multiple matches : prendre la confiance max
4. Utiliser cette confiance dans le signal retourne au lieu de 0.55 fixe
5. Placer le mapping dans config.yaml pour flexibilite
```

### PROMPT M-10 : Reactivation Agent Desactive (Timer Retry)

```
Objectif : Ajouter un mecanisme de reactivation automatique pour les agents desactives apres 5 erreurs.

Fichier : orchestrator/orchestrator.py (lignes ~3932-3941)

Probleme : _agent_disabled.add(agent_name) est permanent. Aucun retry possible.

Modifications :
1. Remplacer _agent_disabled (set) par _agent_disabled_until (dict: agent_name → datetime)
2. Quand un agent atteint 5 erreurs :
   _agent_disabled_until[agent_name] = datetime.utcnow() + timedelta(hours=1)
   _agent_error_counts[agent_name] = 0  # Reset compteur
3. Au debut de l'execution des agents, verifier :
   if agent_name in _agent_disabled_until:
       if datetime.utcnow() > _agent_disabled_until[agent_name]:
           del _agent_disabled_until[agent_name]
           logger.info(f"[AGENT] {agent_name} reactive apres cooldown 1h")
       else:
           continue  # Toujours en cooldown
4. Logger la reactivation et l'envoi d'une alerte Telegram
5. Si l'agent echoue a nouveau 5 fois : doubler le cooldown (2h, 4h, 8h max)
```

---

## ANNEXES

### A. Arborescence des Fichiers Cles (~80 modules Python)

```
EmpireAgentIA_3/
|-- main.py                          # Point d'entree (183 lignes)
|-- orchestrator/
|   |-- orchestrator.py              # Cerveau du systeme (4900+ lignes) ⚠️
|   |-- audit.py                     # Audit des trades
|-- agents/                          # 12 agents (8 actifs)
|   |-- technical.py                 # EMA/RSI/MACD/ADX (M30)
|   |-- scalping.py                  # EMA(13)/RSI(9) (M1) ⚠️
|   |-- swing.py                     # EMA(50)/RSI(14) (H1)
|   |-- smart_money.py               # FVG/OB/AMD (M15)
|   |-- price_action.py              # BOS/FBO/OTE (M15)
|   |-- volume_profile.py            # VWAP/POC/VA (H1)
|   |-- structure.py                 # 9 patterns SMC (M15)
|   |-- sentiment.py                 # F&G/Twitter/GT (crypto)
|   |-- news.py                      # RSS/TextBlob/FinBERT
|   |-- fundamental.py               # Calendrier eco ⚠️
|   |-- macro.py                     # Spread/ATR/calendar
|   |-- whale_agent.py               # Copy-trading (stubs)
|   |-- utils.py                     # merge_agent_params()
|-- utils/                           # 52 modules utilitaires
|   |-- risk_manager.py              # GlobalKillSwitch + sizing ⚠️ (no lock)
|   |-- position_manager.py          # BE/Partials/Trail ⚠️ (no lock)
|   |-- circuit_breaker.py           # 3 pertes → 24h block ⚠️ (no lock)
|   |-- mt5_client.py                # Client MT5 (59KB)
|   |-- composite_score.py           # Score unifie 4 sources
|   |-- performance_tracker.py       # Poids adaptatifs EMA ⚠️ (partage)
|   |-- trade_outcome_tracker.py     # R-multiple ⚠️ (calcul incorrect)
|   |-- event_guard.py               # News blackout (734 lignes)
|   |-- smc_patterns.py              # Detecteurs SMC (911 lignes)
|   |-- advanced_sentiment.py        # ⚠️ DONNEES SIMULEES (random)
|   |-- advanced_sentiment_v2.py     # FinBERT (optionnel)
|   |-- econ_api.py                  # ⚠️ TODO NON IMPLEMENTE
|   |-- data_sources.py              # News aggregation (523 lignes) ⚠️ (memory leak)
|   |-- [... 40+ autres modules]
|-- config/                          # 14 fichiers YAML
|   |-- config.yaml                  # Config maitre ⚠️ (credentials en clair)
|   |-- profiles.yaml                # 15 symboles
|   |-- overrides.yaml               # Surcharges dynamiques
|   |-- asset_config.yaml            # Par type d'actif ⚠️ (symboles orphelins)
|   |-- auto_optimization.yaml       # Optuna ⚠️ (symboles desactives inclus)
|   |-- econ_calendar.yaml           # ⚠️ 1 event obsolete
|   |-- presets/                     # 6 presets ⚠️ (aggressive RR 0.8)
|-- optimization/                    # Optuna auto-optimizer
|-- backtest/                        # Moteur backtesting
|-- reporting/                       # Daily digest
|-- dashboard/                       # Streamlit (optionnel)
|-- scripts/                         # 44 scripts utilitaires
|-- connectors/                      # APIs externes + whale stubs
```

### B. Metriques de Qualite du Code

| Metrique | Valeur | Evaluation |
|----------|--------|------------|
| Fichier le plus long | orchestrator.py (4900+ lignes) | CRITIQUE - a decomposer |
| Modules Python totaux | ~80 | Correct |
| Couverture tests | < 5% estimee | INSUFFISANTE |
| Agents de trading | 12 (8 actifs) | Correct |
| Filtres de qualite | 15+ en cascade | Robuste mais complexe |
| Sources donnees externes | 10+ | Correct mais fragiles |
| Fichiers de config | 14 YAML | Trop de fichiers, inconsistances |
| Bugs critiques identifies | 8 | A corriger en priorite |
| Faiblesses risque | 7 | A renforcer |
| Problemes securite | 4 | SEC-01 critique |
| Modules avec donnees simulees | 2 (econ_api, advanced_sentiment) | A corriger |
| Valeurs hardcodees dans orchestrateur | 30+ | A externaliser |

### C. Tableau Recapitulatif Final des Priorites

| Rang | Ref | Description | Effort | Impact |
|------|-----|-------------|--------|--------|
| 1 | H-01 | Securiser credentials (.env) | 2h | Securite CRITIQUE |
| 2 | H-02 | Thread-safety fichiers JSON | 3h | Stabilite CRITIQUE |
| 3 | H-03 | Implementer econ_api.py (TODO) | 4h | Fonctionnalite |
| 4 | H-04 | Corriger advanced_sentiment (random) | 6h | Qualite signaux |
| 5 | H-05 | Corriger R-multiple partiels | 4h | Precision poids |
| 6 | H-06 | Separer PerformanceTracker par symbole | 3h | Poids adaptatifs |
| 7 | H-07 | Cache agents + parallelisation | 6h | Performance |
| 8 | H-08 | Cache TTL appels MT5 | 3h | Performance |
| 9 | H-09 | Calendrier eco live | 6h | Couverture risque |
| 10 | H-10 | Scalping M1 → M5 | 3h | Qualite signaux |
| 11 | M-03 | Fix mode dry-run | 2h | Testabilite |
| 12 | M-05 | Externaliser 30+ hardcodes | 3h | Maintenabilite |
| 13 | M-06 | Confiance adaptative fundamental | 2h | Qualite signaux |
| 14 | M-08 | Desactiver preset aggressive | 0.5h | Securite risque |
| 15 | M-01 | FinBERT + requirements.txt | 4h | Qualite NLP |
| 16 | M-02 | Weighted drawdown CB | 3h | Gestion risque |
| 17 | M-04 | Implementer cache news.py | 2h | Performance |
| 18 | M-07 | Nettoyer configs mortes | 1h | Maintenabilite |
| 19 | M-09 | Tests unitaires | 8h | Fiabilite |
| 20 | M-10 | Reactivation agent timer | 2h | Disponibilite |

**Effort total estime : ~68 heures** pour les 20 actions prioritaires.

---

*Rapport genere le 1er mars 2026 - EmpireAgentIA v3 - Analyse exhaustive de ~80 fichiers Python et 14 YAML*
*Analyste : Claude Opus 4.6 - Expert Trading Algorithmique*
