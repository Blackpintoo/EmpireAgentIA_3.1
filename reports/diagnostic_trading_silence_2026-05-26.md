# Diagnostic — Silence d'exécution depuis 2026-03-03

**Rédigé** : 2026-05-26 (lecture seule, aucune modification appliquée)
**Branche** : `main` @ `0c26e84` (24 février 2026)
**Source de vérité** : `data/trades_log.csv`, `data/trade_outcomes.csv`, `data/deals_history.csv`, `data/proposals_log.csv`, `logs/empire_agent.log` (240 Mo), `orchestrator/orchestrator.py`, `utils/mt5_client.py`, `utils/sync_history.py`.

---

## 1. Synthèse — 3 lignes

1. **H1 (bug d'écriture CSV) infirmée** : `_log_trade_execution()` (orchestrator.py:4809) est fonctionnelle, 0 erreur loggée en 5 mois.
2. **H2 (le bot n'exécute plus de trades) confirmée**, mais sous une forme aggravée : le bot a été **arrêté ~6 mars 2026 et redémarré le 20 mai 2026** (~75 jours d'inactivité). Depuis la reprise, **0 appel à `place_order` n'a abouti**, et depuis le 24 mai **plus aucun cycle de décision `[RISK]` n'est exécuté** — le bot ne tourne qu'en monitoring de positions (`[PM_DIAG]`).
3. **H3 (filtres trop stricts) infirmée comme cause racine** : les hard filters ne rejettent presque rien (20 occurrences en 7 jours). Le bot n'atteint plus l'étape des filtres : les agents votent `agents=0.0`, la direction est `direction_indeterminee`, le score est à `0.00` à chaque cycle.

**Cause racine probable** : depuis la reprise du 20 mai, la chaîne `cycle de décision → agrégation des votes d'agents` produit systématiquement `score_agr=0.0` et `confluence={'agents': 0.0}` malgré la production de signaux dans `latest_signals.json`. Et depuis le 24 mai à 00h, les cycles de décision eux-mêmes ne sont plus exécutés du tout — le bot scanne MT5 mais n'invoque plus les agents.

---

## 2. Chronologie des dernières activités par fichier

| Fichier | Dernière écriture | Cause apparente |
|---|---|---|
| `data/trades_log.csv` | **2026-03-03 13:46:07** (SOLUSD SHORT, ok=True, retcode=10009) | Bot arrêté ~3 jours plus tard |
| `data/trade_outcomes.csv` | **2026-03-01 07:57:12** (BNBUSD SHORT, sl) | Idem |
| `data/deals_history.csv` | **2026-05-19 22:59:44 UTC** (SP500, profit=+4.49) | `sync_history.py` réveillé périodiquement ; lit depuis MT5 |
| `data/proposals_log.csv` | **2026-05-23 07:21:24** (SOLUSD SHORT, executed=False) | Voir §6.1 — entrées **non corrélées** avec empire_agent.log |
| `data/equity_log.csv` | **2026-05-23 07:21:13** | Snapshot ponctuel |
| `data/latest_signals.json` | **2026-05-23 07:21:24** | Idem |
| `data/open_positions.json` | **2026-05-26 06:06** (au moment de l'investigation) | Bot tourne actuellement (monitoring seul) |
| `data/pm_state.json` | **2026-02-27 14:28** | Aucune position depuis cette date (XAUUSD/SP500/SP500 en BE+trail) |
| `data/daily_loss_state.json` | **2026-05-23 09:19** — `{"date":"2026-05-23","realized_pnl":0.0,"kill_switch_triggered":false}` | Pas de kill switch |
| `data/circuit_breaker_state.json` | (untracked) | Présent mais non analysé |

**Dernières lignes `trades_log.csv` (toutes ok=True, retcode=10009)** : pas d'échec, pas de symptôme d'erreur côté MT5 au moment de l'arrêt.

**Bornes activité MT5 (`deals_history.csv`)** :
- Période active 1 : 2026-02-24 → 2026-03-03 (alignée avec `trades_log.csv`)
- **Trou : 2026-03-04 → 2026-05-19** (~11 semaines sans deals broker)
- Période active 2 : **2026-05-19 22:21 → 2026-05-19 22:59** (USDJPY, SP500, NAS100 — 6 deals, dont 1 gain `+4.49` et 2 pertes par SL `-32.55` et `-309.26`)
- Aucun deal sur les cryptos après mars.

**Note sur l'écart entre `deals_history.csv` (deals jusqu'au 19 mai) et `trades_log.csv` (figé au 3 mars)** : `sync_history.py:17` lit `mt5.history_deals_get(...)` directement depuis MT5. Donc `deals_history.csv` reflète ce que le **broker** a exécuté, indépendamment du chemin Python. Les 6 deals du 19 mai sont donc soit :
- exécutés par le bot après son redémarrage du 20 mai (peu probable : les deals datent du 19 à 22h59, soit ~8h *avant* le `[MAIN] Symboles activés` du 20 mai 06:28),
- exécutés manuellement via MT5 par le compte `11535481`,
- exécutés par un autre processus EA/script.

---

## 3. Distribution temporelle de l'activité dans `logs/empire_agent.log`

### 3.1 Lignes totales par jour-clé (240 Mo, 2,096 M lignes janvier → 26 mai)

| Date | Lignes | Lecture |
|---|---:|---|
| 2026-03-04 | 87 269 | Bot tourne |
| 2026-03-05 | 174 766 | Bot tourne |
| 2026-03-06 | 4 | **Bot arrêté** — seuls les init/login MT5 (07:10, 23:00) → cohérent avec un script externe (sync_history) |
| 2026-03-10 | 4 | Idem |
| 2026-04-15 | 4 | Idem |
| 2026-05-19 | 4 | Idem (init MT5 07:10 et 23:00) |
| **2026-05-20** | **140 453** | **Redémarrage** : `[MAIN] Symboles activés : ['NAS100','SP500','AUDUSD','USDJPY','XAUUSD','BNBUSD','LTCUSD','BTCUSD','SOLUSD']` (9) |
| 2026-05-22 | 711 | Activité réduite (vendredi tardif) |
| 2026-05-23 | 47 869 | Samedi — surveillance |
| 2026-05-25 | 77 809 | Lundi — bot tourne mais **plus aucun cycle de décision** |
| 2026-05-26 | 19 881 (jusqu'à 06:06) | Idem |

### 3.2 Compteurs d'événements clés (5 mois entiers)

| Pattern | Total | Lecture |
|---|---:|---|
| `[PM_DIAG]` | 944 973 | Monitoring positions (massif) |
| `[RISK]` | (cf. 3.3) | Cycle de décision — voir distribution |
| Direction non établie / `pas d'action` | 210 702 | Cycles aboutissant à NO_ACTION |
| `[HARD_FILTER]` (incl. `[HARD_FILTERS]`) | 41 498 | Init + rejets |
| `place_order` (insensitive) | **266** (tous antérieurs au 3 mars dans les warnings retcode) | — |
| `[EXEC]` | **0** | Jamais loggué |
| `[MT5] retcode=…` (warnings) | 81 (tous en janvier 2026 : 10016, 10019, 10031) | Rien depuis février |
| `[LOG] trades_log.csv erreur` | **0** | La fonction d'écriture n'a **jamais** échoué |
| `[MT5] Market closed` + `kill_switch` | 27 | Marginal |
| `Traceback` / `CRITICAL` / `FATAL` | **0** | **Aucune erreur fatale en 5 mois** |

### 3.3 Distribution `[RISK]` par jour de la fenêtre de reprise

| Date | `[RISK]` | `direction_indeterminee` |
|---|---:|---:|
| 2026-05-20 + 21 (combinés) | 31 297 | inconnu |
| 2026-05-22 | 48 | inconnu |
| 2026-05-23 | 25 | 3 |
| 2026-05-24 | 0 | 0 |
| 2026-05-25 | 0 | 0 |
| **2026-05-26** | **0** | **0** |

**Observation critique** : Le bot a exécuté ~31k cycles de décision les 20-21 mai (jeudi-vendredi de la reprise), puis l'activité décisionnelle s'est effondrée le week-end (normal) et **n'a pas redémarré le lundi 25 mai**. Depuis le 24 mai 00h00, **0 entrée `[RISK]`** alors que le bot écrit 16 200 lignes par jour côté `[PM_DIAG]`.

### 3.4 Échantillons représentatifs des cycles `[RISK]` du 23 mai

```
2026-05-23 09:19:30 | [RISK] Conditions non remplies → pas d'action. 
   Raison: direction_indeterminee, score(0.00)<min(1.20), confluence(0.0)<min(0.8)
2026-05-23 09:19:30 | [RISK] BTCUSD confluence breakdown={'agents': 0.0} 
   notes=['sentiment:LONG(0.50)']
2026-05-23 09:19:33 | [RISK] Conditions non remplies → pas d'action. 
   Raison: direction_indeterminee, score(0.00)<min(1.30), confluence(0.0)<min(1.2)
2026-05-23 09:19:33 | [RISK] BNBUSD confluence breakdown={'agents': 0.0}
   notes=['sentiment:LONG(0.50)']
2026-05-23 09:20:28 | WARNING | [HARD_FILTER] BNBUSD: confluence 4 < 5 → REJET
```

→ Quand un cycle s'exécute, **les agents votent 0** dans le breakdown (`{'agents': 0.0}`). Le seul agent qui produit une valeur stable est `sentiment` (LONG 0.50 systématique). Et pourtant `latest_signals.json` au même horodatage contient des signaux explicites (`swing:SHORT`, `structure:LONG`, `smc:SHORT`, `news:LONG`) — il y a **un découplage entre les signaux générés par les agents et la valeur que voit l'agrégation `confluence_breakdown`**.

---

## 4. Commits potentiellement impliqués

Aucun commit n'a été créé entre 2026-02-24 et 2026-05-26 (`git log --since="2026-03-01" --until="2026-05-26"` → vide). Donc **aucune modification de code récente n'explique la régression** à elle seule. Les commits du 24 février qui touchent au scoring/orchestrator sont à conserver à l'esprit :

| Commit | Date | Effet possible |
|---|---|---|
| `0c26e84` | 2026-02-24 06:14 | data only — hors scope |
| `90f1d62` | 2026-02-24 06:13 | **fix(risk): import mt5 manquant dans floating P&L check** — ne devrait pas casser l'agrégation des agents |
| `b25e78d` | 2026-02-24 06:09 | feat scripts (rapport quotidien RR) — hors orchestrator |
| `e721bb7` | 2026-02-24 06:08 | exclut **AUDUSD et LTCUSD** de `start_empire.py` — mais ces deux symboles sont quand même listés dans `[MAIN] Symboles activés` du 2026-05-20 06:28 (`'AUDUSD','LTCUSD',...`). À vérifier : la config effective au lancement n'utilise pas `start_empire.py` mais un autre script. |
| `4cfe80b` | 2026-02-24 06:07 | feat position_manager (fermeture auto max_duration) |
| `8753f9d` | 2026-02-24 06:05 | fix position_manager — broker_symbol matching + logs diagnostic — d'où l'avalanche de `[PM_DIAG]` |
| `54d6e58` | 2026-02-24 06:04 | double vérification max_volume |
| `b184c85` | 2026-02-24 06:03 | feat orchestrator : filtre `allowed_directions` par symbole — **suspect** : pourrait expliquer `direction_indeterminee` si la config `allowed_directions` est mal renseignée ou met tous les symboles en `[]` |
| **`8fa57ba`** | 2026-02-24 06:02 | **fix(orchestrator): logger executed=True uniquement après succès de execute_trade** — change la sémantique de `executed` dans `proposals_log.csv`. Les `False` du 23 mai sont une conséquence directe de ce fix : avant ce fix, `executed=True` était écrit avant l'exécution réelle |
| `d354068` | 2026-02-24 06:02 | ajuster confluence cap et hard_min |
| `7150b5a` | 2026-02-24 06:01 | bloquer heures toxiques (overrides) |
| `9874e67` | 2026-02-24 06:01 | utiliser `score_agr` au lieu de `confidence` dans `counter_trend_filter` |
| `f7f4939` | 2026-02-20 13:16 | refonte audit-fev2026 : ajoute `utils/circuit_breaker.py`, `utils/session_filter.py`, modifs scoring composite |

**Commits les plus suspects pour le découplage agents↔confluence** : `9874e67` (changement de variable utilisée par `counter_trend_filter`) et `f7f4939` (refonte des poids + circuit breaker + session filter). Mais ces deux commits sont en prod depuis le 20 février et étaient présents lors de la période active du 24 fév → 3 mars où les exécutions fonctionnaient. Donc le code seul ne suffit pas à expliquer la régression — **il y a un changement d'état (data ou environnement) intervenu pendant la longue interruption**.

**Pas de commit `3f15b68` ni `729519c`** (référencés dans le briefing utilisateur précédent) : confirmés inexistants dans `git log --all`.

---

## 5. État actuel des fichiers de configuration critiques

### 5.1 `config/config.yaml`
- Symboles `enabled: true` pour ~20 entrées (config volumineuse, non auditée intégralement)
- `dry_run` : **absent de config.yaml** ; présent uniquement dans `config/overrides.backup.yaml` et `config/presets/overrides.aggressive.yaml` (à `false`)
- Aucun `auto_execute: false` ; tous les profils et overrides ont `auto_execute: true` (overrides.yaml lignes 32, 173, 267, 420, 498 ; profiles.yaml ×17)

### 5.2 `config/overrides.yaml`
- `auto_execute: true` partout
- `telegram_validation` : non trouvé via grep → reste à `False` par défaut (code orchestrator.py:733)

### 5.3 Kill switches
- `daily_loss_state.json` : `kill_switch_triggered: false`, `realized_pnl: 0.0`, `date: 2026-05-23` (date stale de 3 jours)
- `[HARD_FILTERS]` au démarrage 2026-05-20 06:28 : `kill_switch=400.0USD` → seuil paramétré, pas déclenché
- `circuit_breaker_state.json` : existe (untracked), non lu en détail
- Aucun pattern `KILL_SWITCH` ou `circuit_breaker_open` dans la fenêtre 20-26 mai

### 5.4 Positions ouvertes
- `pm_state.json` : 3 positions historiques (XAUUSD:858034226, SP500:881715746, SP500:894207203), toutes en `be_done: true, trail_active: true` — figé depuis 2026-02-27
- `open_positions.json` : `{"BNBUSD": {}, "SOLUSD": {}}` (rafraîchi à 06:06 ce matin, dictionnaires vides → bot scan ces symboles, 0 position effective)
- Cycles `[PM_DIAG]` confirment `0 position(s) trouvée(s)` pour tous les symboles

### 5.5 État Git
- `git rev-list --left-right --count origin/main...HEAD` → `0 16` (local en avance de 16 commits sur origin, jamais pushés)
- 58 fichiers modifiés non commités (data runtime + sentiment cache + `.claude/settings.local.json` + de nombreux `utils/*.py` et `agents/*.py` modifiés — voir §7 anomalies)
- Aucune mention de `SL_GUARD` dans le code ou les logs (ni `3f15b68`, ni `729519c` dans `git log --all`)

---

## 6. Anomalies secondaires identifiées (à investiguer si pertinent)

### 6.1 Découplage proposals_log.csv ↔ empire_agent.log
Les 3 lignes de `proposals_log.csv` datées `2026-05-23T07:20:26 → 07:21:24` (SOLUSD SHORT, BNBUSD SHORT, SOLUSD SHORT, toutes `expired=False, executed=False`) **n'ont aucune contrepartie dans empire_agent.log** : ce dernier ne contient que `[MT5] MetaTrader5 module disponible` à 00:04:04, puis silence jusqu'à 08:33:15 (PM_DIAG).

→ Il existe vraisemblablement **un second processus** (ou un script ad-hoc, ou un test) qui a écrit dans `proposals_log.csv` à 07:20-21 sans utiliser le logger central. Candidat possible : `optimize_scalping_agent.py` (modifié) ou `_orch_selftest.py` (modifié) qui pourraient appeler `_log_proposal_csv` hors du flux orchestrator. À confirmer si nécessaire.

### 6.2 Working tree massivement modifiée mais aucun commit depuis le 24 février
58 fichiers `M` incluant :
- Code applicatif : `orchestrator/orchestrator.py`, `orchestrator/orchestrator.minimal.py`, `main.py`, `agents/{fundamental,macro,scalping}.py`, `utils/{advanced_sentiment,circuit_breaker,config,config_loader,econ_api,event_guard,mt5_client,performance_tracker,position_manager,risk_manager,settings,telegram_client,telegram_client_async,trade_outcome_tracker}.py`
- Config : `config/config.yaml`, `config/econ_calendar.yaml`
- Scripts : `scripts/{audit_weekly,check_mt5_connection,performance_tracker_report,symbol_validator,test_trade}.py`, `optimize_scalping_agent.py`, `verify_empire.py`, `tg_*.py`

→ Le bot tourne potentiellement avec une **version locale jamais commitée** différente du `HEAD` (`0c26e84`). Le `git log --since="2026-03-01"` étant vide confirme qu'aucune de ces modifications n'a été commitée. Ces 58 fichiers représentent donc soit une refactorisation en cours, soit la cause directe du dysfonctionnement.

### 6.3 Tampons de logs anciens (potentiellement bruyants pour l'analyse)
- `logs/empire_agent.log` = 240 Mo (5 mois) — non rotaté ; peut impacter perf en lecture
- `logs/empire.log` = 2,4 Mo, dernier touché août 2025 (orphelin)
- Fichiers backups orchestrator : `orchestrator/orchestrator.corrupt`, `orchestrator/orchestrator.py.bak`, `orchestrator/orchestrator.py.bak_keepalive` — à investiguer si refactor en cours

### 6.4 Lien éventuel avec `e721bb7` (exclusion AUDUSD/LTCUSD)
Le commit `e721bb7` modifie `scripts/start_empire.py`. Pourtant le démarrage du 20 mai loggue **9 symboles activés** dont AUDUSD et LTCUSD — donc le bot n'a **pas** été démarré via `start_empire.py`. À vérifier quel script (`main.py` ? `scripts/test_trade.py` ? processus systemd ?) lance réellement le bot.

---

## 7. Recommandations (sans appliquer)

### 7.1 Action immédiate — collecte de données avant correctif (lecture seule, ~30 min)
1. **Diff intégral des fichiers non commitées** : `git diff orchestrator/orchestrator.py`, `git diff utils/risk_manager.py`, `git diff agents/scalping.py` etc. → identifier si la régression vient des modifications working tree non commitées (très probable).
2. **Identifier le runner actuel** : `ps -ef | grep python` (sous Windows : `Get-Process python`) pour voir le script lancé. Lire la première ligne de empire_agent.log du 2026-05-20 06:28 confirmera (déjà vu : `[MAIN] Symboles activés ...` indique `main.py` ou équivalent).
3. **Examiner pourquoi `[RISK]` a disparu depuis le 24 mai** : grep des dernières lignes utiles avant la coupure (2026-05-22 dernière entrée `[RISK]`) pour voir s'il y a un signal d'arrêt (scheduler off ? loop bloqué ? token Telegram invalide ?).
4. **Cause du `agents=0.0`** : ajouter (en non-prod) un log de chaque agent → leur sortie individuelle, et confirmer le découplage. Probablement lié à `weighted_vote=0` lorsque le tracker (`performance_tracker.json`) considère tous les agents comme non-rentables et leur applique poids 0.

### 7.2 Causes racines candidates par ordre de probabilité
1. **Working tree modifiée non commitée** : 16 fichiers utils/ et agents/ modifiés. Le bot tourne sur un mélange de code instable. Plus probable cause de l'écart `latest_signals.json` (signaux présents) ↔ `confluence breakdown={'agents': 0.0}` (votes agrégés à zéro).
2. **Performance tracker pondère tous les agents à 0** : 18 fichiers `data/performance/tracker_*.json` untracked. Si tous les agents sont sous le seuil de performance minimum suite à la longue inactivité de fév→mai, le système peut les ignorer (poids 0) lors de l'agrégation. Cohérent avec la disparition progressive de `[RISK]` après les 31k cycles initiaux.
3. **Scheduler asyncio bloqué après week-end** : aucun `[RISK]` depuis le 24 mai à 00h mais `[PM_DIAG]` continue → le main loop tourne, le PM scanne, mais la coroutine de décision est suspendue (deadlock ? exception silencieuse non rattrapée par le `logger.exception` ligne 3661 ?). À investiguer en lisant le code asyncio.

### 7.3 Ce qu'il ne faut **pas** faire sans investigation
- **Ne pas commiter** la working tree actuelle telle quelle : 16 fichiers de code sont modifiés sans description ; on ne sait pas si ces modifs sont expérimentales ou prod.
- **Ne pas redémarrer le bot brutalement** avant d'avoir compris d'où vient `agents=0.0` — sinon on reproduira le même état.
- **Ne pas activer un kill_switch ou un disable global** : aucun kill switch ne semble être en jeu actuellement.

---

## 8. Données critiques non collectées / limites de l'investigation

- Le contenu détaillé de `data/performance/tracker_*.json` (18 fichiers untracked) n'a pas été audité — pourtant probablement central pour la régression `agents=0.0`.
- Le `git diff` du working tree n'a pas été produit (volumineux ; à demander explicitement).
- `_orch_selftest.py` et `optimize_scalping_agent.py` (les deux modifiés, untracked d'origine) n'ont pas été lus — ils pourraient être les processus qui écrivent dans `proposals_log.csv` hors du logger central.
- Pas d'inspection des sentiment caches `data/sentiment_cache/*.json` (10 fichiers modifiés) — pourrait expliquer pourquoi `sentiment:LONG(0.50)` est figé.

---

## 9. Verdict opérationnel

**Le bot n'a effectué aucun trade orchestrator entre le 2026-03-03 et aujourd'hui (2026-05-26)** — soit ~12 semaines. Les 6 deals MT5 visibles dans `deals_history.csv` du 2026-05-19 22:21-22:59 sont **probablement extérieurs au bot Python** (timing antérieur au redémarrage du 2026-05-20 06:28).

Depuis sa reprise le 20 mai, le bot est **vivant mais infertile** : il monitore, scanne, log, mais ses agents convergent vers `agents=0.0` et n'aboutissent à aucune décision. Depuis le 24 mai, il ne fait même plus tourner ses cycles de décision.

**État effectif : bot en surveillance seule. Aucun risque marché côté Python, mais aucun signal exploité non plus.**

Le diagnostic est suffisant pour prioriser ; il **n'est pas suffisant** pour identifier la ligne précise qui produit `agents=0.0`. Cela nécessitera l'audit du `git diff` complet (16 fichiers code modifiés non commitées) et la lecture des `performance/tracker_*.json`.
