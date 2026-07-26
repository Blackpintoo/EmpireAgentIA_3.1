# Diagnostic — Redémarrage du 2026-05-26 19:19 & arrêt présumé du 19 mai 22:59

**Investigation** : 2026-05-26 19:26 UTC+2 (≈ 7 min après redémarrage), strictement en lecture seule.
**Sources** : `logs/empire_agent.log` (240 Mo, 2,096 M lignes), `data/performance/tracker_*.json` (19 fichiers), `data/deals_history.csv`, `data/proposals_log.csv`, `data/latest_signals.json`, `data/daily_loss_state.json`, `utils/telegram_client_async.py`.

---

## 1. Synthèse exécutive (5 lignes)

1. **Le bot Python (`orchestrator/orchestrator.py`) n'a jamais tradé entre le 2026-03-05 et le 2026-05-20** : empire_agent.log contient **4 lignes par jour** (init MT5 ponctuel à 07:10 et 23:00, probablement via `sync_history.py`) sur toute cette période. La fenêtre « jusqu'au 19 mai 22:59 » n'est pas reflétée dans les logs.
2. **Le seul événement du 19 mai à 22:59** est un deal MT5 broker (SP500 LONG fermé en gain +4.49 USD) lu par `sync_history.py` depuis `mt5.history_deals_get()` — donc d'origine **non orchestrator** (manuel ou autre processus sur le compte 11535481).
3. **Le redémarrage du 26 mai 19:19:51 est sain** : 102 cycles `[RISK]` en 7 min, **0 `direction_indeterminee`**, agents répondent (breakdowns `agents=3.0..5.0`), PositionManager actif (360 `[PM_DIAG]`), 0 `Traceback`, 0 `[MTF_FILTER]` erreur.
4. **Aucun trade encore exécuté depuis 19:19**, ce qui est nominal : tous les rejets ont une raison explicite (`rr<1.50`, `score<8.0/12.0`, `off_prime_hours`) — pas de symptôme de bug bloquant.
5. **Telegram « Unauthorized » non confirmé dans le log** (0 occurrence de 401/Unauthorized/Forbidden dans 240 Mo) ; le code (`utils/telegram_client_async.py:196`) n'intercepte que `TelegramConflictError`, donc une `TelegramUnauthorizedError` serait avalée silencieusement par un try/except amont. Si l'erreur a été vue en console, elle n'est pas tracée dans le fichier log.

---

## 2. Chronologie 19 mai 22:00 → 23:59 (selon `logs/empire_agent.log`)

| Horodatage | Source | Contenu |
|---|---|---|
| (avant 21:00) | — | Aucune entrée le 19 mai depuis 07:10:15 |
| **21:00 – 22:59** | — | **0 entrée** dans empire_agent.log |
| 23:00:10 | INFO | `[MT5] MetaTrader5 module disponible` |
| 23:00:11 | INFO | `MT5 logged in: account=11535481 server=VantageInternational-Demo` |
| (après 23:00:11) | — | Aucune autre entrée le 19 mai |

**Patterns recherchés et trouvés** dans la fenêtre 21:00-23:59 :
- `[SCORE_DIAG]` : **0**
- `[DECISION]` ou `[RISK]` : **0**
- `[EXEC]` ou `place_order` : **0**
- `Traceback`, `Exception`, `ERROR`, `CRITICAL` : **0**
- `Unauthorized`, `Telegram`, `[TG]` : **0**

**Conclusion étape 1** : Aucune trace d'un orchestrator en cours d'exécution le 19 mai. Le bot Python n'a pas généré de décisions ce soir-là. Les deux lignes à 23:00 sont des appels init MT5 ponctuels (script externe). Le deal SP500 du `deals_history.csv` (epoch `1779231584` = 2026-05-19 22:59:44 UTC) provient du compte broker mais pas de `orchestrator/orchestrator.py`.

**Donnée manquante** : sans logs entre 21:00 et 22:59 le 19 mai, je ne peux pas confirmer ni infirmer ce qui s'est passé côté broker. Si un autre processus (EA MT5, script externe, action manuelle) a placé l'ordre SP500, cela n'apparaît pas dans empire_agent.log.

---

## 3. Activité depuis le redémarrage 2026-05-26 19:19:51

### 3.1 Démarrage propre
| Horodatage | Événement |
|---|---|
| 19:19:51 | `[MT5] MetaTrader5 module disponible` |
| 19:20:03 | `[MAIN] Symboles activés : ['NAS100','SP500','AUDUSD','USDJPY','XAUUSD','BNBUSD','LTCUSD','BTCUSD','SOLUSD'] (9 symboles)` |
| 19:20:04 | Init des 9 `AssetManager` (`PHASE4`), 9 fois `[HARD_FILTERS] min_score=8.0 min_conf=5 ... min_rr=1.5 kill_switch=400.0USD` |
| 19:20:04 | Schedulers démarrés (60s par symbole), Health endpoint `:9108`, scheduler digest (06:00/10:00/14:00/18:00/21:00 Zurich) |

### 3.2 Compteurs depuis 19:19 (fenêtre observée : 7 minutes)
| Métrique | Compte | Lecture |
|---|---:|---|
| Lignes log totales pour 19:xx | 897 | activité soutenue |
| Cycles `[RISK]` | **102** | bot calcule |
| `direction_indeterminee` | **0** | agents fournissent une direction |
| `[RISK] Conditions non remplies` | 34 | rejets explicites (rr<1.5, score<min) |
| `[HARD_FILTER]` rejets (explicites) | 1 | NAS100 score 6.5 < 8.0 → REJET (19:21:18) |
| `[PM_DIAG]` (manage_open_positions) | 360 | actif, scan permanent |
| `[AGENT] timeout (10s)` macro/fundamental/news | 157 | partiel, attendu (APIs externes) |
| `[AGENT] timeout (10s)` technical/swing/structure/smc/sentiment | 171 | concernant — voir §6.2 |
| `place_order` / `[EXEC]` / `retcode` | **0** | aucun ordre envoyé |
| `[MTF_FILTER]` Erreur / `analyze_mtf_confluence` exception | **0** | la TypeError du 23 mai ne se reproduit pas |
| `Traceback`, `Exception`, `ERROR`, `CRITICAL` | **0** | aucune erreur fatale |
| `Unauthorized` / `401` / `Forbidden` (Telegram) | **0** | non tracé dans le log |

### 3.3 Échantillons représentatifs de cycles `[RISK]` (post-redémarrage)
```
19:21:16 [RISK] SP500 confluence breakdown={'agents': 4.0, 'tracker': 0.105} 
  notes=['tracker_support', 'rr_blocked:1.34<1.5', 'sentiment:WAIT(0.00)']
19:21:18 [HARD_FILTER] NAS100: score 6.5 < 8.0 → REJET
19:21:20 [RISK] USDJPY confluence breakdown={'agents': 3.0, 'tracker': 0.106}
  notes=['tracker_support', 'off_prime_hours(min_score=12.00)', 'rr_blocked:0.99<1.5']
19:21:22 [RISK] XAUUSD confluence breakdown={'agents': 5.0, 'tracker': 0.133}
  notes=['tracker_support', 'off_prime_hours(min_score=3.75)', 'rr_blocked:1.39<1.5']
19:21:21 [RISK] AUDUSD confluence breakdown={'agents': 3.0}
  notes=['off_prime_hours(min_score=3.75)', 'rr_blocked:1.39<1.5']
19:21:27 [RISK] Conditions non remplies. Raison: rr(0.40)<min_rr(1.15)
```

**Lecture** : chaque cycle aboutit à une direction calculée (LONG ou SHORT), un score numérique, un breakdown d'agents non nul et un tracker actif. Les rejets sont **causaux** (RR trop faible, hors prime hours). Aucun symptôme du bug des 20-23 mai (où `agents=0.0` systématique).

**Plafonnement de volume** observé (sain) : SP500 `lots 63.63 → 1.0`, BTCUSD `lots 0.52 → 0.1`, SOLUSD `lots 35.74 → 5.0` — `max_volume` par symbole en vigueur.

---

## 4. État du tracker de performance

### 4.1 Dates de dernière écriture des fichiers (mtime fichier)
| Symbole | mtime fichier | Dernier `last_update` interne le plus récent |
|---|---|---|
| ADAUSD | 2026-03-01 21:03 | 2026-02 environ |
| AUDUSD | 2026-03-01 21:03 | 2026-02-19 |
| BNBUSD | 2026-03-01 21:03 | 2026-02-28 (1 record M30 du 2026-03-01) |
| BTCUSD | 2026-03-01 21:05 | 2025-12-22 (~99% des records) puis 2026-01-13 |
| CL-OIL | 2026-03-01 21:03 | — |
| DJ30 | 2026-03-01 21:03 | — |
| ETHUSD | 2026-03-01 21:03 | — |
| EURUSD | 2026-03-01 21:03 | — |
| GBPUSD | 2026-03-01 21:03 | — |
| GER40 | 2026-03-01 21:03 | — |
| LTCUSD | 2026-03-01 21:03 | 2026-02-11 (la plupart) |
| NAS100 | 2026-03-01 21:03 | 2026-02-27 |
| SOLUSD | **2026-03-03 14:46** | **2026-03-03 13:46** (le plus récent — dernier trade) |
| SP500 | 2026-03-01 21:03 | 2026-02-27 |
| UK100 | 2026-03-01 21:03 | — |
| USDJPY | 2026-03-01 21:03 | 2026-02-20 |
| USOUSD | 2026-03-01 21:03 | — |
| XAGUSD | 2026-03-01 21:03 | — |
| XAUUSD | 2026-03-01 21:03 | 2026-02-20 |

### 4.2 Santé des poids (échantillons des trackers utilisés au démarrage 19:20)
| Symbole | Agent | Poids | Sain ? |
|---|---|---:|---|
| NAS100 | swing_h4 | 3.5 | ✅ |
| NAS100 | swing_h1 | 3.5 | ✅ |
| SP500 | swing_h4 | 3.5 | ✅ |
| SP500 | swing_m15 | 3.5 | ✅ |
| BTCUSD | scalping M1\|trend_up | 1.001 | ✅ |
| BTCUSD | synthetic H1 (et autres) | 0.914 | ✅ |
| AUDUSD | swing_h4 → m1 | 3.5 | ✅ |
| USDJPY | swing_h4 → m1 | 2.49 - 2.57 | ✅ |
| XAUUSD | swing_h4 → m1 | 3.5 | ✅ |
| BNBUSD | swing_h4 → m15 | 3.5 | ✅ |
| LTCUSD | swing/smc/structure | 0.77 - 1.55 | ✅ (un peu plus faibles) |
| SOLUSD | swing_h4/h1/m5 | 3.5 | ✅ |
| SOLUSD | smc_m1 | 3.26 | ✅ |

**Conclusion étape 3** : **Aucun tracker dégénéré** (pas de poids à 0, pas de valeurs aberrantes). Les fichiers ont été figés au moment du dernier trade (1-3 mars 2026) et sont restés tels quels pendant 12 semaines. Les poids `weight=3.5` sont le plafond `clip_max` et restent stables. Tous les `score_ema`, `outcome_ema`, `win_rate` sont dans des plages raisonnables.

**Effet attendu post-redémarrage** : le bot va ré-écrire ces trackers à chaque trade clôturé. Les poids vont graduellement se réajuster aux performances récentes des agents.

---

## 5. Diagnostic Telegram

### 5.1 Recherche dans `logs/empire_agent.log` (5 mois, 240 Mo)
| Pattern | Occurrences | Note |
|---|---:|---|
| `Unauthorized` | **0** | aucune trace |
| `401` | 0 (sauf dans textes non liés) | — |
| `Forbidden` (HTTP) | 3 (toutes Finnhub API, 2026-01-06) | non-Telegram |
| `Telegram` | quelques refs au code | pas d'erreur runtime sortie |
| `[TG]` | très peu d'occurrences | aucune erreur 401 |
| `TelegramConflictError` | au moins 1 catché (cf. `telegram_client_async.py:196`) | géré gracieusement |
| `bot was kicked` / `bot was blocked` | 0 | — |

### 5.2 Comportement du code Telegram
- `utils/telegram_client_async.py:4` importe `TelegramConflictError` uniquement.
- `utils/telegram_client_async.py:196` intercepte ce conflit et le log explicitement.
- **`TelegramUnauthorizedError` (401) n'a pas de handler spécifique** dans `telegram_client_async.py`. Si elle survient, elle sera soit :
  - propagée vers le caller (où des try/except enveloppants l'avaleront, ex: `orchestrator.py:3683` `logger.warning("[TG] Envoi via telegram_client échoué")`),
  - imprimée par `aiogram` sur stderr (qui peut apparaître en console mais pas dans empire_agent.log).

### 5.3 Conclusion étape 4
Si le user a vu **« Unauthorized »** au démarrage **dans la console**, cela suggère que l'erreur a transité par stderr ou par un print d'aiogram, pas par le logger central. **Impossible de dater la première occurrence sans accès à stderr/console.** Le token TELEGRAM_BOT_TOKEN dans le `.env` est probablement révoqué (action manuelle de l'utilisateur côté @BotFather, ou révocation suite à un partage du token).

**Corrélation avec l'arrêt du 19 mai 22:59** : aucune dans le log. Et de toute façon, le bot Python n'a pas tradé ce jour-là (cf. §2), donc une révocation Telegram ne peut pas être la cause d'un arrêt de trading qui n'a pas eu lieu dans le bot Python. Plus probable : le token a été révoqué entre le 5 mars (dernière vraie session active) et aujourd'hui, indépendamment du trading.

**Impact opérationnel** :
- Si auto_execute=True (cas actuel), Telegram est utilisé pour notifications uniquement → impact zéro sur le trading.
- Si l'utilisateur veut le mode validation manuelle, Telegram cassé empêcherait les boutons "Valider/Rejeter" → blocage. **Ce n'est pas le cas actuel** : `[ORCH]` du redémarrage montre une init sans `telegram_validation`.

---

## 6. Anomalies secondaires observées (post-redémarrage)

### 6.1 Timeouts d'agents résiduels
Sur 7 minutes, 340 `[AGENT] ... timeout (10s)` :
- macro / fundamental / news : 157 (attendu — APIs externes Finnhub, etc.)
- technical / swing / structure / smc / sentiment : **171** (préoccupant — ces agents font du calcul local sur les bougies)

Cela explique pourquoi `agents=3.0` à `5.0` au lieu de `7-8` théorique (7 agents). Le bot fonctionne en mode dégradé : il a juste assez d'agents pour produire une direction, mais le score composite reste insuffisant à passer les filtres (`min_score=8.0` à `12.0`).

**Hypothèse à valider** : `_AGENT_TIMEOUT = 10` (orchestrator.py:3938) est trop bas pour la charge actuelle. À comparer avec ce qu'était la prod stable (jan-fév 2026) — à examiner ultérieurement.

### 6.2 Anomalies d'historique (rappels)
- `data/trades_log.csv` figé au 2026-03-03 13:46:07 (12 semaines).
- `data/trade_outcomes.csv` figé au 2026-03-01.
- `data/deals_history.csv` : trou du 4 mars → 19 mai, puis 6 deals concentrés sur le 19 mai 22:21-22:59 UTC.
- `git rev-list --left-right --count origin/main...HEAD` = `0 16` : local en avance de 16 commits non pushés sur `origin/main`.
- 58 fichiers `git status` modifiés. **Note** : le user affirme qu'aucun fichier n'a été modifié depuis début mars (vérifié par mtime Windows). Cohérence possible : les `M` rapportés par git peuvent être dus à des line endings CRLF/LF (un warning `LF will be replaced by CRLF` a été observé sur `utils/risk_manager.py`). Sans `git diff` lu, je ne peux pas trancher.

---

## 7. Trois recommandations classées par priorité

### 🟢 ACTION IMMÉDIATE (ce soir) — observer 30 à 60 min avant tout fix
1. **Laisser tourner le bot 30-60 min** et re-vérifier les compteurs : `[EXEC]`, `place_order`, nombre de `[HARD_FILTER]`, évolution des `direction`. Le bot est en bonne santé à 19:26, il faut juste valider qu'un trade va effectivement être tenté sur les heures suivantes (notamment quand le marché US ouvre / heure de prime trading reprend).
2. **Vérifier en console** si l'erreur Telegram « Unauthorized » se répète à intervalle régulier (polling). Si oui, c'est cosmétique (notifications cassées) — le trading n'est pas affecté tant que `auto_execute=True`. Si on veut couper le bruit, désactiver Telegram dans `config/config.yaml` (section telegram.enabled=false). **Ne pas appliquer sans validation explicite.**
3. **Confirmer manuellement** que le deal SP500 du 19 mai 22:59:44 UTC sur le compte 11535481 est bien un deal volontaire de votre part (manuel ou autre EA). C'est important parce que `pm_state.json` et `data/journal/` ne le tracent pas comme un trade orchestrator.

### 🟡 ACTION COURT TERME (cette semaine)
4. **Auditer les timeouts d'agents** sur 24h : si les agents `technical/swing/structure/smc/sentiment` continuent de timeout à >50%, c'est un problème de performance (lecture lente des bougies MT5 ? CPU saturé ? blocage I/O ?). Tracer ce qui prend >10s dans `_gather_agent_signals`. Sans fix, le bot reste en mode dégradé.
5. **Décider du sort des 16 commits non pushés sur `origin/main`** : soit pusher, soit créer une branche pour audit. Garder l'état actuel non synchronisé est risqué (un `git reset --hard origin/main` accidentel détruirait 2-3 semaines de fixes critiques de février).
6. **Régénérer le token Telegram via @BotFather** si l'usage Telegram est souhaité (alerts, validations manuelles). Sinon, désactiver explicitement dans `config.yaml`.

### 🔵 ACTION DE FOND (sujet ultérieur)
7. **Audit de l'écart entre logs et trading réel** : comprendre pourquoi `deals_history.csv` montre 6 deals le 19 mai alors que `empire_agent.log` ne montre rien ce jour-là. Possibilités à investiguer :
   - Existence d'un autre script Python qui tradait sur le compte 11535481 sans passer par `orchestrator/orchestrator.py`.
   - Existence d'un Expert Advisor MT5 sur la plateforme.
   - Trades manuels via l'interface MT5.
   - Le bot Python pourrait avoir été lancé pendant ~30 min le 19 mai sans logger correctement (rotation de log, redirection stderr, autre fichier de log).

8. **Rotation des logs** : `logs/empire_agent.log` = 240 Mo, 2,1 M lignes, couvre 5 mois. Mettre en place une politique de rotation hebdomadaire ou mensuelle pour éviter de saturer le disque et accélérer les futurs greps de diagnostic.

9. **Documentation runbook** : à chaque redémarrage du bot, le user a peu de visibilité sur les premières minutes (PM_DIAG noie le log). Un endpoint `/healthz` existe sur `:9108` mais n'est pas exploité ; ajouter un dashboard simple (HTML lisant `latest_signals.json` + compteurs `[RISK]` des 10 dernières minutes) éviterait les diagnostics manuels.

---

## 8. Données critiques non collectées / limites

- **Console stderr** non lue : impossible de confirmer la première occurrence de l'erreur Telegram Unauthorized.
- **Diff `git diff HEAD`** non lu en détail : impossible de garantir que les 58 fichiers `M` n'introduisent pas de changement comportemental (le user dit qu'aucune modification n'a été faite depuis mars, mais `git diff --stat` indiquait 728 lignes en plus / 258 en moins sur 6 fichiers code — voir §6.2).
- **Identité du processus parent qui a lancé le bot à 19:19:51** : non vérifiée (Task Scheduler ? lancement manuel ? service Windows ?).
- **Le bot n'a tourné que 7 minutes** au moment de cette investigation : insuffisant pour conclure définitivement qu'il va tradé. Suivre dans la prochaine heure.

---

## 9. Verdict opérationnel

Le bot est **en marche, sain et fonctionnel** au moment de cette investigation (2026-05-26 19:26). Aucune anomalie bloquante. La prémisse « arrêt du 19 mai 22h59 » ne se vérifie pas dans les logs côté Python : le bot Python était déjà inactif depuis ~6 mars. Le deal du 19 mai vient d'ailleurs (à clarifier).

**Action attendue de l'utilisateur** : observer 30-60 minutes supplémentaires, valider l'origine du deal SP500 du 19 mai, décider du sort de Telegram.
