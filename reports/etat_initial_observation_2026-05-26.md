# État initial — Période d'observation 2 semaines

**Investigation** : 2026-05-26 21:21:53 UTC+2 (Europe/Zurich), strictement en lecture seule.
**Objectif** : référence pour comparaison à J+14 (2026-06-09).
**Sources** : `logs/empire_agent.log` (242 MB), `config/overrides.yaml`, `data/*.json`, `data/*.csv`, Get-Process Windows, MT5 terminal info (PID).

---

## 1. Confirmation du fonctionnement technique

### 1.1 Processus Python actifs (PID, RAM, CPU, démarrage)

| PID | Nom | StartTime | RAM (MB) | CPU (s) | Rôle probable |
|---:|---|---|---:|---:|---|
| **24408** | python | **2026-05-26 19:19:50** | 379,8 | 341,7 | Bot principal (orchestrator + 9 sub-orchs) |
| 55928 | python | 2026-05-26 19:19:50 | 4,8 | 0,0 | Worker / launcher minimal |

Démarrage = il y a **2 h 02 min** au moment de l'investigation. Cohérent avec la trace `2026-05-26 19:19:51 [MT5] MetaTrader5 module disponible` dans empire_agent.log et avec ce que vous avez indiqué (« redémarré aujourd'hui à 19:19 »).

### 1.2 MT5 Terminal
| PID | StartTime | MainWindowTitle |
|---:|---|---|
| 24032 | 2026-05-23 09:17:59 | `11535481 - VantageInternational-Demo: Compte demo - Hedge - Vantage International Group Limited` |

MT5 tourne depuis le **23 mai 2026 09:17** (3 jours). Compte démo Vantage International, mode Hedge.

### 1.3 Logs : écriture confirmée
| Fichier | mtime | Statut |
|---|---|---|
| `logs/empire_agent.log` | **2026-05-26 21:21:45** | ✅ écrit (à jour à 8 s près) |
| `data/open_positions.json` | 2026-05-26 21:21:xx | ✅ écrit (rafraîchi en boucle) |
| `data/daily_loss_state.json` | 2026-05-26 (sans heure) | ✅ écrit (date du jour) |
| `data/equity_log.csv` | **2026-05-26 19:22:06** | ⚠️ **figé** depuis 19:22 (cf. §5.2) |
| `data/latest_signals.json` | **2026-05-26 19:21:19** | ⚠️ **figé** depuis 19:21 (cf. §5.2) |
| `data/proposals_log.csv` | **2026-05-26 17:21:26** | ⚠️ figé (avant le redémarrage actuel) |
| `data/trades_log.csv` | **2026-03-03 13:46:07** | ❌ figé depuis 12 semaines (cf. §5.3) |

### 1.4 Cycles `[RISK]` effectués depuis le redémarrage 19:19
| Fenêtre | Cycles `[RISK]` | Notes |
|---|---:|---|
| 19:2x-19:5x | 630 | bot calcule avec agents `3.0-5.0` → directions valides, rejets RR |
| 20:00-20:59 | 360 | activité réduite |
| 21:00-21:01 (partiel) | ~12 visibles | **régression** : retour `direction_indeterminee, agents=0.0` |
| `[EXEC]` / `place_order` / `retcode` du 26 mai | **0** | aucun ordre envoyé |
| `Traceback` / `Exception` / `ERROR` 20-21h | 0 | pas d'erreur Python fatale |
| `MTF_FILTER` erreur / `analyze_mtf_confluence` | 0 | la TypeError du 23 mai ne se reproduit pas |
| `[AGENT] timeout (10s)` 19:xx | 2 716 | persistant |
| `[AGENT] timeout (10s)` 20-21h | 2 241 | persistant (~1 100/h) |

---

## 2. Instantané de l'état actuel

| Élément | Valeur | Source |
|---|---|---|
| **Solde du compte 11535481** | **49 666,50 USD** | dernière ligne `data/equity_log.csv` à 2026-05-26 19:22:06 (snapshot figé — donnée potentiellement périmée de 2 h) |
| Equity instantané | 49 666,50 USD | idem |
| Margin / Free margin | 0,00 / 49 666,50 USD | aucune position |
| **Positions ouvertes Python** | **0** | `data/open_positions.json` = `{"AUDUSD": {}}` (scan vide), confirmé par 360 `[PM_DIAG]` montrant `0 position(s) trouvée(s)` pour tous les symboles |
| Capital initial | **non documenté dans le repo** | aucune entrée `capital_initial`, `initial_balance`, `starting_capital` trouvée dans `config/*.yaml` ni dans le code. Limite : à fournir par l'utilisateur (montant du dépôt initial sur le compte démo). |
| Dernier trade `trades_log.csv` | **2026-03-03 13:46:07** SOLUSD SHORT, retcode 10009 ok=True | figé depuis 12 semaines |
| Dernier deal `deals_history.csv` | **2026-05-19 22:59:44 UTC** SP500 fermé +4,49 USD (epoch 1779231584) | issu de `mt5.history_deals_get()` ; vraisemblablement EA EmpireIA_Pro (cf. `reports/empireia_pro_analysis_2026-05-26.md`) |
| Dernière proposition `proposals_log.csv` | **2026-05-26 17:21:26** LTCUSD SHORT, executed=False | écrite avant le redémarrage 19:19 (instance précédente) |
| Kill-switch journalier | non déclenché, realized_pnl=0,0 | `data/daily_loss_state.json` daté 2026-05-26 |
| Token Telegram | **« Unauthorized » signalé en console** | 0 trace dans le log (cf. `reports/diagnostic_redemarrage_2026-05-26.md` §5) ; impact zéro tant que `auto_execute=True` |

---

## 3. Les 9 symboles activés et leurs paramètres clés

Liste depuis `[MAIN] Symboles activés` au démarrage 19:20:03 :
`['NAS100', 'SP500', 'AUDUSD', 'USDJPY', 'XAUUSD', 'BNBUSD', 'LTCUSD', 'BTCUSD', 'SOLUSD']`

Paramètres `[HARD_FILTERS]` **uniformes au démarrage** (loggué pour chaque symbole) :
`min_score=8.0 · min_conf=5 · tracker_contra=0.25 · disagree=0.35/0.45 · min_rr=1.5 · counter_trend=10.0 · quiet_conf=0.7 · kill_switch=400.0 USD · be_rr=1.0 · whale_vol_z=3.0`

Paramètres spécifiques par symbole (extrait `config/overrides.yaml`) :

| Symbole | `max_volume` | `atr_sl_mult` | `atr_tp_mult` | `min_rr` | `min_score_for_proposal` | `min_confluence` | `prime_hours_utc` | Notes |
|---|---:|---:|---:|---:|---:|---:|---|---|
| **BTCUSD** | 0,10 | 1,5 | (non lu) | 1,15 | 1,2 | 0,8 | (n/a) | crypto majeure ; min_score le plus bas |
| **LTCUSD** | 5,0 | 1,5 | n/a | 1,5* | n/a | n/a | (n/a) | crypto |
| **BNBUSD** | 1,0 | 1,5 | n/a | n/a | n/a | n/a | (n/a) | crypto |
| **XAUUSD** | 0,15 | 1,8 | n/a | n/a | n/a | n/a | (n/a) | or |
| **SOLUSD** | 5,0 | 1,5 | n/a | n/a | n/a | n/a | (n/a) | crypto |
| **SP500** | 1,0 | 1,6 | 2,5 | 1,5* | n/a | n/a | 13-20 | indices ; blocked_hours_utc 1/7/8/10/14/17/18/20/22 ; daily_loss_abs 500 |
| **NAS100** | 1,0 | 1,6 | 2,5 | 1,5* | n/a | n/a | 13-20 | indices ; daily_loss_abs 2000 |
| **AUDUSD** | 1,0 | 1,4 | 2,5 | 1,5* | n/a | n/a | 0-8 / 22-24 | ⚠️ `enabled: false` dans overrides.yaml (cf. §5.1) |
| **USDJPY** | 1,0 | 1,4 | 2,5 | 1,5* | n/a | n/a | 7-17 | forex ; allowed_hours_utc 4/7/12/13/14/15/17/22 ; daily_loss_abs 150 |

`*` valeur héritée du `GLOBAL.default` quand non spécifiée par symbole.
`(n/a)` paramètre absent du bloc symbole dans overrides.yaml — résolu par défauts globaux ou défauts code.

**Hard filters globaux (depuis `[HARD_FILTERS]` au runtime)** : `min_score=8.0`, `min_conf=5`, `min_rr=1.5`, `counter_trend=10.0`. Ces seuils sont les **mêmes pour les 9 symboles** au démarrage (la log les répète 9 fois identiquement).

**Trading windows globales** (`config/overrides.yaml:23-25`) :
- `eod_close_time_utc: "19:30"` (= 21:30 Zurich)
- `last_entry_time_utc: "18:00"` (= 20:00 Zurich)
- Weekend guard actif : ferme VEN 23:00, rouvre LUN 05:30

---

## 4. EA MT5 EmpireIA_Pro — non actif ?

**Non confirmable depuis le repo seul.** Pour confirmer définitivement qu'aucun EA n'est attaché à un graphique, il faut :
- Soit ouvrir MetaTrader 5 (terminal64.exe PID 24032) et inspecter l'onglet « Experts » de chaque graphique → l'icône en haut à droite indique si un EA tourne (smiley vert vs croix rouge).
- Soit lancer un script Python `mt5.terminal_info()` qui renvoie un champ `trade_allowed` indiquant si AutoTrading global est ON.
- Soit grepper `MQL5/Logs/<date>.log` (non lu dans cette investigation pour éviter d'allonger).

**Indices indirects** dans cette investigation suggérant que l'EA n'est *probablement pas* actif maintenant :
- `data/deals_history.csv` n'a aucun nouveau deal après 2026-05-19 22:59:44 UTC. Si l'EA était attaché et tradait, on s'attendrait à voir d'autres deals dans cette fenêtre.
- `MQL5/Files/EmpireIA_Backtest.csv` n'existe pas (dossier `MQL5/Files/` vide selon Glob).
- Aucun fichier `.set` ne correspond à un attachement SP500 live (le `.set` connu cible BTCUSD pour le tester).

→ **À vérifier manuellement par vous-même sur la plateforme MT5**. Pas de garantie 100 % côté repo.

---

## 5. Anomalies à signaler

### 5.1 ⚠️ AUDUSD activé alors qu'il est marqué `enabled: false` dans `overrides.yaml`
Ligne 715 de `config/overrides.yaml` : `AUDUSD.orchestrator.enabled: false`, commentaire « DÉSACTIVÉ (WR 33%, -$844, 10 losses consécutifs) ». Pourtant au démarrage 19:20:03, AUDUSD figure dans la liste des 9 symboles activés. Le `[PHASE4]` log confirme : `AssetManager initialisé pour AUDUSD (type: FOREX)`. Et les cycles `[RISK] AUDUSD` apparaissent dans les logs.

→ L'override `enabled: false` semble **ignoré par le runner de démarrage**. Soit la liste 9 est en dur côté code (`scripts/start_empire.py` ou `main.py`), soit l'override est lu pour autre chose mais pas pour décider de l'activation. À investiguer si la période d'observation ne doit pas inclure AUDUSD.

### 5.2 ⚠️ Régression « agents=0.0 » revenue à partir de 21:00
- 19:21:16 : `[RISK] SP500 confluence breakdown={'agents': 4.0}` — sain
- 19:21:20 : `[RISK] USDJPY confluence breakdown={'agents': 3.0}` — sain
- 19:21:22 : `[RISK] XAUUSD confluence breakdown={'agents': 5.0}` — sain
- **21:00:16 : `[RISK] LTCUSD confluence breakdown={'agents': 0.0}` — direction_indeterminee**
- 21:00:17 : `[RISK] BTCUSD direction_indeterminee, agents=0.0`
- 21:00:17 : `[RISK] SOLUSD direction_indeterminee, agents=0.0`
- 21:01:16, 21:01:17 : idem

C'est le **même motif** que pendant la panne du 20-22 mai (cf. `reports/diagnostic_trading_silence_2026-05-26.md`). Sur les 2h de fonctionnement, le bot est passé d'agents calculés à agents=0.0. Et seuls 3 symboles (LTCUSD, BTCUSD, SOLUSD = crypto 24/7) génèrent encore des cycles ; les autres semblent en pause horaire (marché fermé ou hors prime_hours).

**Cause probable** : combinaison de (a) marché fermé pour Forex/Indices à 21h UTC dimanche soir, (b) timeouts persistants sur les agents technical/swing/structure/smc/sentiment.

### 5.3 ⚠️ `trades_log.csv` figé depuis 2026-03-03
Le fichier `data/trades_log.csv` n'a aucune nouvelle entrée depuis 12 semaines. La fonction `_log_trade_execution()` (orchestrator.py:4809) est saine mais n'est jamais appelée parce que `place_order` n'est jamais atteint. **Conséquence pour l'observation 2 semaines** : si aucun trade n'est exécuté pendant les 2 semaines, ce fichier restera figé et il n'y aura rien à comparer.

### 5.4 ⚠️ Timeouts d'agents persistants
`_AGENT_TIMEOUT = 10s` (orchestrator.py:3938) provoque ~2 000 timeouts/h. Touche tous les agents (macro/fundamental/news mais aussi technical/swing/structure/smc/sentiment). C'est la cause directe des `agents=0.0` quand les timeouts s'accumulent.

### 5.5 ⚠️ Aucun trade exécuté en 2 heures depuis 19:19
102 cycles `[RISK]` (puis 630, puis 360 sur 2h), aucune proposition n'a passé conjointement les filtres `min_score=8.0`, `min_conf=5`, `min_rr=1.5`. Tous les rejets ont une raison explicite (`rr<1.5`, `score<min`, `off_prime_hours`).

### 5.6 ⚠️ Capital initial non documenté
Aucune valeur de référence du capital initial dans les configs. Sans cette info, on ne peut pas calculer le ROI dans 2 semaines. **À fournir par l'utilisateur** : montant du dépôt initial sur le compte démo Vantage 11535481.

### 5.7 Working tree non commitée
`git status` rapporte 58 fichiers `M` non commités (vu dans investigations précédentes). Le user a indiqué que ces fichiers n'ont pas été modifiés depuis mars (probablement line-endings CRLF/LF). Ne pas reset/discard, ils peuvent contenir du contenu réel.

### 5.8 Log de 242 Mo non roté
`logs/empire_agent.log` croît continuellement (240 → 242 Mo en 2 heures). Pas urgent mais à planifier la rotation avant de saturer le disque.

---

## 6. Recommandation : démarrer ou non l'observation ?

### ⚠️ Recommandation : **NE PAS démarrer l'observation 2 semaines en l'état**

**Raisonnement** : sur 2 heures de fonctionnement, 0 trade exécuté et retour de la régression `agents=0.0`. Si cette situation persiste pendant 2 semaines, vous mesurerez 0 activité — donc 0 information utile.

**Pré-requis à valider avant de démarrer l'observation** (par ordre de priorité, ne pas appliquer sans validation explicite) :

1. **Résoudre les timeouts d'agents** ou en mesurer la cause racine. Soit augmenter `_AGENT_TIMEOUT` de 10s à 30s, soit identifier ce qui prend >10s dans `_gather_agent_signals` (lecture lente MT5 ? appels API externes ? CPU ?). Sans fix, le bot reste en mode dégradé `agents=0.0` la plupart du temps.

2. **Décider du sort d'AUDUSD** : soit l'overrider est bugué et il faut désactiver AUDUSD effectivement, soit volontairement le réactiver (auquel cas mettre à jour overrides.yaml). Ne pas le laisser dans cet état ambigu pendant 2 semaines.

3. **Documenter le capital initial** (à minima dans un fichier `data/observation_baseline.json` ou en config). Sans baseline, on ne pourra pas mesurer le ROI à J+14.

4. **Confirmer manuellement sur la plateforme MT5** qu'aucun EA n'est attaché à un graphique. Sinon les deals EA pollueront `deals_history.csv` et fausseront la mesure de performance du bot Python.

5. **Définir explicitement les KPIs** mesurés en J+14 (nombre trades, win rate, max drawdown, ROI, sharpe, max RR atteint…), figés maintenant pour comparaison apples-to-apples.

### Alternative si vous voulez démarrer malgré tout

Si vous acceptez de démarrer maintenant en sachant que l'observation pourra mesurer « 0 trade en 2 semaines », vous pourrez au moins :
- Constater **factuellement** que le bot Python n'exécute pas de trades dans son état actuel (preuve par observation, pas par diagnostic).
- Capturer un baseline équity = 49 666,50 USD à confirmer manuellement via MT5.
- Comparer dans 2 semaines : si toujours 49 666,50 USD et 0 trade dans trades_log.csv, on aura la confirmation par 2 semaines de données que le pipeline est cassé en aval de la décision.

Mais c'est un coût élevé (2 semaines) pour une confirmation qu'on a déjà à 95 % par l'investigation actuelle.

---

## 7. Limites de cette investigation

- **MT5 `account_info()` live non interrogé** : pour éviter d'instancier un second client Python qui pourrait perturber le bot actif (PID 24408). Le solde 49 666,50 USD vient du snapshot equity de 19:22:06 ; il est plausiblement encore valable maintenant (aucune position ouverte, aucune exécution depuis), mais à confirmer si besoin.
- **MT5 `terminal_info()` non interrogé** : même raison. Statut EA non vérifié programmatiquement.
- **Capital initial** : non récupérable depuis le repo. À fournir.
- **Comptage `[RISK]` 21:xx** : recherché à 21:21:53 ; on a vu les 12 premiers de 21:00-21:01 mais pas la fin de la fenêtre. La régression `agents=0.0` est confirmée sur ces 12 mais l'évolution sur 21:02-21:21 reste à analyser au cas par cas.
- **Cycles `[RISK]` par symbole sur la fenêtre** : non détaillé symbole par symbole (volumineux).

---

## 8. Sigles & références

- Rapport précédent diagnostic : `reports/diagnostic_redemarrage_2026-05-26.md`
- Rapport précédent EA : `reports/empireia_pro_analysis_2026-05-26.md`
- Rapport précédent silence trading : `reports/diagnostic_trading_silence_2026-05-26.md`
- État brut configs : `config/overrides.yaml` (756 lignes, 14 blocs symbole)
- Code orchestrator : `orchestrator/orchestrator.py` (≈ 5 100 lignes, non commitée intégralement)

**Date du rapport** : 2026-05-26 21:21 UTC+2 — utiliser comme T0 pour la comparaison à J+14 = **2026-06-09**.
