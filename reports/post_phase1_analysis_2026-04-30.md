# Analyse post-Phase-1 EmpireAgentIA 3.1

- **Période d'analyse** : 2026-04-19 07:02 UTC (commit du tag `pre-phase-2026-04-19`) → 2026-04-30 23:59 UTC
- **Durée** : 11 jours civils, 11 jours de trading observés
- **Baseline référence** : 2026-01-21 → 2026-04-19 07:02 UTC (324 trades)
- **Mode** : analyse en lecture seule, aucune modification de code/config, aucun commit

---

## ⚠️ ACTION HUMAINE REQUISE — Trois écarts critiques entre l'attendu et l'observé

> Ces points sont remontés en tête de rapport conformément au cadrage. Aucune correction n'a été tentée.

### CRITIQUE 1 — Phase 2 (profils shadow) jamais appliquée
Vous indiquez dans la consigne que la Phase 2 a été appliquée (« candidats DJ30/UK100/GBPUSD/USDCAD/GER40/XAGUSD en shadow, BNBUSD/SOLUSD basculés en shadow »). **Les fichiers de configuration contredisent cette hypothèse :**

| Élément attendu en Phase 2 | État réel constaté |
|---|---|
| 6 candidats ajoutés à `profiles.yaml:enabled_symbols` | **Non**. La liste contient toujours `[NAS100, SP500, AUDUSD, USDJPY, XAUUSD, BNBUSD, LTCUSD, BTCUSD, SOLUSD]` (9 symboles, identique au pré-Phase-1) |
| Section `DJ30` dans `overrides.yaml` | **Absente** |
| Section `USDCAD` dans `overrides.yaml` | **Absente** |
| Section `GER40` dans `overrides.yaml` | **Absente** |
| Section `XAGUSD` dans `overrides.yaml` | **Absente** |
| Sections `UK100`, `GBPUSD` dans `overrides.yaml` | Présentes (déjà avant Phase 1) mais symboles non actifs |
| `BNBUSD.orchestrator.auto_execute` | **`True`** (devait être `False`) |
| `SOLUSD.orchestrator.auto_execute` | Non défini explicitement (hérite, comportement à vérifier) |

**Conséquence observable** : 0 proposition générée sur DJ30, UK100, GBPUSD, USDCAD, GER40, XAGUSD pendant la période. **5 trades exécutés sur BNBUSD et 6 sur SOLUSD** (PnL cumulé -269 USD pour ces 11 trades). Ces deux symboles étaient censés être en shadow mais sont restés en exécution réelle.

Implication : la Phase 2 telle que décrite n'a jamais été exécutée. Ma livraison du 19 avril s'est arrêtée à Phase 1 + Directive 5 (par votre instruction « Attends mon retour après livraison du script et de la Phase 1 »). Aucune action n'a été reprise depuis. Les chiffres de cette analyse reflètent **uniquement l'effet de la Phase 1**.

### CRITIQUE 2 — Blacklist horaire contournée par les whitelists locales pré-existantes
La logique implémentée pour la Directive 4 est `effective_blocked = (global ∪ local_blocked) − local_allowed`. Cette règle « priorité locale > blacklist globale » a été pensée pour l'exception XAUUSD documentée dans le brief, mais elle s'applique en fait à **tous les symboles** qui ont un `allowed_hours_utc` pré-existant.

Conséquence observée sur 11 jours :

| Symbole | `allowed_hours_utc` local | Heures globalement blacklistées qui restent autorisées |
|---|---|---|
| USDJPY | [8,9,10,11,12,13,14,15] | h10, h11, h12, h13, h14 |
| BNBUSD | [8,9,10,11,12,13,14,15,16,17] | h10, h11, h12, h13, h14 |
| SOLUSD | [8,9,10,11,12,13,14,15,16,17] | h10, h11, h12, h13, h14 |
| AUDUSD | [8,9,10,11,12,13,14,15,16,17] | h10, h11, h12, h13, h14 |
| LTCUSD | [8,9,10,11,12,13,14,15,16,17] | h10, h11, h12, h13, h14 |
| XAUUSD (exception voulue) | [7,8,9,10,11,12,13,15,16,17] | h7, h10, h11, h12, h13 |

Vérifié dans `data/trades_log.csv` post-tag : **5 ordres exécutés OK pendant des heures globalement blacklistées hors XAUUSD** (3 BNBUSD, 1 SOLUSD, 1 USDJPY). Tous tombent sous le `allowed_hours_utc` local, donc la logique fait ce qu'elle dit faire — mais l'effet contredit l'intention « blacklist globale stricte ».

À clarifier : la priorité locale doit-elle s'appliquer uniquement au cas exceptionnel XAUUSD, ou à tous les symboles ? La logique actuelle est la deuxième interprétation.

### CRITIQUE 3 — Échantillon trop petit pour conclure statistiquement
51 trades sur 11 jours = en dessous du seuil de 100 trades minimum pour distinguer signal du bruit. Les comparaisons baseline/post sont indicatives mais **aucune conclusion forte ne peut être tirée à ce stade**. Recommandation : maintenir la configuration en place 2-3 semaines supplémentaires avant toute décision majeure.

---

## SECTION 1 — Synthèse exécutive

**P&L -441,59 USD sur 51 trades clôturés en 11 jours, WR 43,1 %, R-multiple moyen -0,12. Verdict : régression matérielle vs baseline (-441 vs +748 baseline) — mais échantillon trop petit (51 trades) pour conclure structurellement, et 11 trades sur les 51 sont concentrés sur BNBUSD/SOLUSD/AUDUSD/LTCUSD qui auraient dû être désactivés ou en shadow.**

---

## SECTION 2 — Comparaison avant/après Phase 1

| Métrique | Baseline (21/01 → 19/04) | Post-Phase-1 (19/04 → 30/04) | Delta |
|---|---:|---:|---:|
| Nombre de trades clôturés | 324 | 51 | -273 |
| Winrate | 43,5 % | 43,1 % | -0,4 pt |
| Avg win | +116,85 USD | +75,55 USD | -41,30 USD |
| Avg loss | -90,91 USD | -72,54 USD | +18,37 USD |
| Payoff (avgW/\|avgL\|) | 1,285 | 1,041 | -0,244 |
| Profit factor | 1,048 | 0,790 | -0,258 |
| P&L total | +748,41 USD | -441,59 USD | -1 190 USD |
| Jours de trading | 35 | 11 | — |
| P&L par jour | +21,38 USD | -40,14 USD | -61,52 USD |
| Drawdown maximum | -4 242,82 USD | -1 019,21 USD | n/a (échelle ≠) |

Notes :
- Le baseline indiqué dans la consigne (« +748 CHF, WR 43,5 %, R:R 1,36 ») est cohérent avec mon calcul à l'unité près sur le P&L et le WR. Le R:R 1,36 du brief correspond probablement au calcul `avg_R-multiple` ; le payoff money 1,285 que je calcule ici diverge légèrement.
- Avg win baseline 116,85 USD vs post 75,55 USD : la baisse de 35 % du gain moyen est le principal contributeur à la régression. Hypothèse à explorer : les nouveaux partials à 1,0R/1,8R encaissent plus tôt et coupent les runners.

---

## SECTION 3 — Validation des Directives 1 à 4

### D1 — Break-Even repoussé à 1,5R + offset positif

| Source | n trades 'be' | R-multiple médian | R-multiple moyen |
|---|---:|---:|---:|
| Baseline | 44 | +0,000 | -0,010 |
| Post-Phase-1 | 11 | **+0,035** | **+0,032** |

**Effet attendu confirmé.** Le R-multiple médian sur les sorties BE passe de 0,000R à +0,035R. L'offset positif fait son travail : les trades qui touchaient un BE pur ferment maintenant avec un micro-gain. Sur 11 trades en BE en 11 jours, l'effet est faible en valeur absolue (+0,38 USD cumulés) mais conforme à la spec.

Ratio BE / total : **21,6 %** post-phase contre **13,6 %** baseline. Le BE se déclenche **plus souvent** alors qu'il était censé se déclencher plus tard (1,5R vs 1,2R baseline). À surveiller — possible effet de la combinaison BE + partials qui modifie la dynamique.

### D2 — Partials recalibrés sur 1,0R/1,8R

| Source | n (TP+Trailing winners) | R P25 | R médian | R P75 | R max |
|---|---:|---:|---:|---:|---:|
| Baseline | 118 | 0,55 | 0,99 | 1,56 | 2,52 |
| Post-Phase-1 | 16 | 0,48 | **1,26** | 1,49 | 2,49 |

La distribution s'est resserrée vers 1,0R-1,8R comme prévu (P75 stable autour de 1,5R, médiane qui remonte de 0,99 à 1,26). Les runners >2R restent rares (max identique 2,5R). L'échantillon n=16 est faible mais cohérent avec la cible.

Limite : on ne dispose pas du log granulaire des partials pour mesurer ce que chaque jambe a rapporté individuellement. L'analyse repose sur le R-multiple final du trade.

### D3 — Trailing actif dès 1,0R

Ratios des sorties par exit_type :

| Exit type | Baseline | Post-Phase-1 |
|---|---:|---:|
| sl | 47,8 % | 47,1 % |
| be | 13,6 % | 21,6 % |
| tp | 22,5 % | 19,6 % |
| trailing | 13,9 % | 11,8 % |
| manual | 2,2 % | 0 % |

**Effet attendu non observé.** Le ratio `trailing` est en baisse (13,9 % → 11,8 %), pas en hausse. Le `be` augmente significativement (+8 pts). Hypothèse : le BE à 1,5R se déclenche avant que le trailing à 1,0R puisse capturer la suite, parce qu'à 1,5R le trade touche soit le 2e partial (1,8R) puis sort en TP, soit revient et ferme en BE (avec offset). Le trailing n'a une fenêtre étroite que entre les deux partials. À investiguer.

### D4 — Blacklist horaire globale [3,4,7,10,11,12,13,14] UTC

**Logique active** : confirmé par 661 occurrences de `[HOUR_FILTER][BLACKLIST]` dans la queue du log empire_agent.log, avec mention explicite de `blocked=[3, 4, 5, 7, 10, 11, 12, 13, 14]` (union global + local).

**Violations observées dans `trades_log.csv` (entrées exécutées OK)** :

| Date entrée | Symbole | Heure UTC | Cause |
|---|---|---:|---|
| 2026-04-21 11:42 | BNBUSD | 11 | allowed_hours_utc local couvre h11 |
| 2026-04-21 14:48 | BNBUSD | 14 | allowed_hours_utc local couvre h14 |
| 2026-04-24 12:12 | BNBUSD | 12 | allowed_hours_utc local couvre h12 |
| 2026-04-24 12:20 | SOLUSD | 12 | allowed_hours_utc local couvre h12 |
| 2026-04-28 10:50 | USDJPY | 10 | allowed_hours_utc local couvre h10 |

Ces 5 violations ne sont **pas** des bugs de la logique : elles sont la conséquence directe de la règle « allowed_hours_utc local soustrait du blacklist effectif ». Voir CRITIQUE 2 ci-dessus pour la décision à prendre.

Aucune violation sur XAUUSD (l'exception voulue) ni sur des symboles sans `allowed_hours_utc` local (BTCUSD, SP500, NAS100). Pour ceux-là, la blacklist est strictement appliquée.

---

## SECTION 4 — Observation des candidats shadow mode

**Périmètre attendu vs observé :**

| Symbole | Statut attendu | n propositions | n exécutions réelles | Statut observé |
|---|---|---:|---:|---|
| DJ30 | shadow | 0 | 0 | non configuré |
| UK100 | shadow | 0 | 0 | non activé (pas dans enabled_symbols) |
| GBPUSD | shadow | 0 | 0 | non activé (pas dans enabled_symbols) |
| USDCAD | shadow | 0 | 0 | non configuré |
| GER40 | shadow | 0 | 0 | non configuré |
| XAGUSD | shadow | 0 | 0 | non configuré |
| BNBUSD | shadow | 673 | **5** | exécution réelle, pas en shadow |
| SOLUSD | shadow | 740 | **6** | exécution réelle, pas en shadow |

### BNBUSD — propositions post-tag (n=673)

- LONG : 102 (15 %), SHORT : 571 (85 %) — biais SHORT massif
- Score : range [7,00 ; 10,03], médiane 7,83
- Heures dominantes UTC : h15 (86), h6 (83), h7 (80), h16 (77), h19 (73)
- R:R théorique moyen : 1,82
- **Exécutions** : 5 (auto_execute resté à `True`). Voir CRITIQUE 1.

### SOLUSD — propositions post-tag (n=740)

- LONG : 223 (30 %), SHORT : 517 (70 %) — biais SHORT
- Score : range [7,10 ; 12,70], médiane 7,70
- Heures dominantes UTC : h7 (102), h6 (94), h14 (70), h15 (64), h10 (62)
- R:R théorique moyen : 1,67
- **Exécutions** : 6. Voir CRITIQUE 1.

### Simulation rétroactive SL/TP/timeout

**Non effectuée.** Cette analyse nécessite la récupération via MT5 des barres OHLC M5 sur les 6 heures suivant chaque proposition (1 413 propositions × 72 barres = 100 k requêtes broker). Cela correspond exactement à la Directive 12 du brief original, qui doit faire l'objet d'un script dédié (`scripts/analyze_shadow_propositions.py`) lancé manuellement après une période d'observation. À ce stade, la simulation n'a pas été lancée.

---

## SECTION 5 — Performance par symbole en production

Les 6 symboles « production » au sens du brief Phase 1 :

| Symbole | n | W | L | WR | PF | P&L | avg R | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| USDJPY | 5 | 3 | 2 | 60,0 % | 2,16 | +99,97 | +0,49 | OK |
| XAUUSD | 4 | 2 | 2 | 50,0 % | 1,16 | +53,10 | +0,08 | OK |
| BTCUSD | 4 | 2 | 2 | 50,0 % | 0,83 | -16,73 | -0,21 | échantillon trop petit |
| SP500 | 14 | 7 | 7 | 50,0 % | 0,72 | -29,72 | -0,01 | **R:R<1 sur n≥10** |
| NAS100 | 10 | 6 | 4 | 60,0 % | 0,92 | -72,82 | +0,11 | **R:R<1 sur n≥10** |
| EURUSD | 0 | — | — | — | — | — | — | non actif (pas dans enabled_symbols) |

Symboles non-prod encore tradés :

| Symbole | n | WR | PF | P&L | Note |
|---|---:|---:|---:|---:|---|
| AUDUSD | 4 | 25,0 % | 0,20 | -206,18 | hors design Phase 1 |
| SOLUSD | 5 | 0,0 % | 0,00 | -164,66 | devait être en shadow |
| BNBUSD | 5 | 20,0 % | 0,37 | -104,55 | devait être en shadow |
| LTCUSD | 0 | — | — | — | aucun trade clôturé sur la période |

**Symboles avec R:R < 1,0 et n ≥ 10** : SP500 (PF 0,72) et NAS100 (PF 0,92). Sur 11 jours c'est dans le bruit, mais à surveiller : NAS100 et SP500 étaient les piliers profitables du baseline (PF 2,53 et 1,40), et ils sont neutres voire légèrement négatifs depuis Phase 1. Hypothèse à explorer : les nouveaux partials 1,0R/1,8R + trailing 1,0R coupent les runners qui faisaient la profitabilité historique de NAS100. À mesurer sur un échantillon plus large avant action.

---

## SECTION 6 — Analyse horaire post-blacklist

Distribution P&L par heure d'entrée UTC, post-tag :

| Heure UTC | n | P&L (USD) | Statut blacklist |
|---:|---:|---:|---|
| 9 | 1 | +78,06 | hors blacklist |
| 11 | 7 | -21,26 | blacklist (mais trades autorisés via allowed local) |
| 12 | 5 | +318,15 | blacklist (mais trades autorisés) |
| 13 | 1 | +16,26 | blacklist |
| 14 | 1 | -41,60 | blacklist |
| 15 | 4 | -238,04 | hors blacklist |
| 17 | 1 | -52,30 | hors blacklist |
| 18 | 14 | **-467,07** | hors blacklist |
| 19 | 9 | -14,42 | hors blacklist |
| 20 | 4 | +199,54 | hors blacklist |
| 22 | 4 | -218,91 | hors blacklist |

Observations :
- **h12 +318 et h20 +199** : profitables, cohérent avec le baseline (h20 et h22 étaient les piliers).
- **h18 -467 sur 14 trades** : c'est l'heure la plus active et elle est négative. C'est aussi l'heure que le baseline indiquait comme un pilier. **Inversion à investiguer** sur un échantillon plus grand. Si elle se confirme sur 50+ trades, candidat pour ajout à la blacklist.
- **h22 -218 sur 4 trades** : à surveiller — le baseline disait que c'était un pilier ; ici c'est négatif. Échantillon trop petit (4 trades) pour conclure.
- **h11 et h12 (blacklist contournée) +297 cumulé** : ironique — les heures « toxiques » ont été profitables sur l'échantillon. Contredit l'hypothèse de la blacklist. Mais 12 trades, c'est très peu.

---

## SECTION 7 — Analyse directionnelle

| Direction | n | WR | avgW | avgL | Payoff | P&L |
|---|---:|---:|---:|---:|---:|---:|
| LONG (post) | 42 | 45,2 % | +77,27 | -68,69 | 1,12 | -111,76 |
| SHORT (post) | 9 | 33,3 % | +64,67 | -87,31 | 0,74 | -329,83 |

Comparaison au baseline donné dans la consigne (LONG WR 47,5 % R:R 0,94 P&L -1 416 / SHORT WR 37,3 % R:R 2,24 P&L +2 164) :

- **LONG** : WR stable (47,5 → 45,2 %), P&L plus mesuré sur la période (-111 vs -1 416 ramené à 11 jours).
- **SHORT** : régression marquée. Le baseline avait un payoff SHORT de 2,24 (R:R historique des SHORT très favorable). Post-Phase-1, le SHORT est à 0,74 et concentré sur 9 trades dont la plupart sur cryptos toxiques (SOLUSD, BNBUSD).

Le biais SHORT identifié comme facteur de profitabilité dans le baseline ne s'est pas reproduit, mais avec n=9 c'est mécaniquement non significatif.

---

## SECTION 8 — Santé technique

### Taux d'échec MT5

| Source | Total tentatives | OK | KO | Taux d'échec |
|---|---:|---:|---:|---:|
| Baseline (réf. brief : 42 % global) | — | — | — | 42 % |
| Post-Phase-1 | 89 | 54 | 35 | **39,3 %** |

Quasi-stable. Pas d'amélioration significative — la Directive 9 (mapping filling_type par symbole) n'a pas été déployée, donc rien ne devait changer.

### Retcodes dominants post-tag

| Retcode | Description | Occurrences |
|---:|---|---:|
| 10016 | Invalid stops (SL/TP trop proches du minimum broker) | 32 |
| (vide) | divers | 3 |

**32 échecs sur 35 sont des retcode 10016 « stops invalides »**, exclusivement sur cryptos :

| Symbole | Échecs 10016 | Total échecs |
|---|---:|---:|
| LTCUSD | 12 | 15 |
| SOLUSD | 14 | 14 |
| BNBUSD | 6 | 6 |

Le `trade_stops_level` broker pour ces cryptos doit être plus restrictif que ce que les agents proposent. À traiter via Directive 9 (Phase 3) — relever la distance min SL pour les cryptos.

### Positions fantômes

| Source | Positions trackées |
|---|---:|
| `pm_state.json` | 3 tickets |
| `tracked_positions.json` | 3 positions |
| `open_positions.json` (snapshot MT5) | 3 positions actives (NAS100×1, XAUUSD×1, SP500×1) |

Les 3 sources concordent. **Aucune position fantôme détectée.**

### Erreurs / exceptions queue de log

Sur 5 MB de queue de `logs/empire_agent.log` (fichier total 0,76 GB) :
- **0 exception Python non gérée** détectée (Traceback, Exception, CRITICAL).
- 2 erreurs réseau récurrentes : `api.alternative.me` (Fear & Greed sentiment) en backoff 30 min — non bloquant.
- 661 lignes `HOUR_FILTER` (filtre horaire fonctionnel).
- 468 mentions `BLACKLIST` (logique active).

### Croissance des fichiers de log

`logs/empire_agent.log` = **0,76 GB** après 11 jours de fonctionnement. À ce rythme, ~2 GB/mois. Pas de fuite mémoire détectable depuis ce que je peux observer, mais la rotation des logs n'est pas configurée. Candidat à signaler en MOYENNE.

---

## SECTION 9 — Recommandations priorisées

### CRITIQUE (sous 24 h)

1. **Décider du sort de la Phase 2.** Trois options : (a) la livrer maintenant comme initialement prévu (BNBUSD/SOLUSD en shadow + 6 candidats ajoutés), (b) la repousser et garder la config actuelle, (c) la simplifier (par exemple : juste désactiver `auto_execute` sur BNBUSD/SOLUSD sans ajouter les 6 candidats). **Sujet identifié dans le brief original** mais l'exécution n'a jamais été lancée.

2. **Trancher la sémantique de la blacklist horaire.** Soit la blacklist globale est stricte et `allowed_hours_utc` ne peut pas la contourner sauf exception XAUUSD nommément (modifier la logique `orchestrator.py` pour limiter l'override aux symboles d'une liste explicite), soit la priorité locale s'applique à tous (statu quo, à documenter dans `overrides.yaml`). **Sujet nouveau** non identifié dans le brief original.

### HAUTE (sous une semaine)

3. **Investiguer la régression `trailing`** (13,9 % → 11,8 %) qui ne suit pas l'effet attendu de la Directive 3. Hypothèse à vérifier : interaction BE 1,5R / 2e partial 1,8R / trailing 1,0R qui laisse une fenêtre trop étroite au trailing. Action : extraire les trades sortis en BE+offset et vérifier combien auraient été éligibles au trailing si le BE avait été à 1,8R ou 2,0R.

4. **Investiguer la perte sur h18** (-467 sur 14 trades) qui contredit le baseline. Si confirmée sur 30+ trades, h18 devient candidate pour la blacklist. **Sujet nouveau**.

5. **Implémenter la Directive 9 (mapping filling_type par symbole) ou le contournement équivalent pour cryptos**. Le retcode 10016 représente 91 % des échecs MT5 de la période et reste à 39 %. La directive 9 visait surtout filling, mais le retcode 10016 vise les stops. À reformuler en Phase 3 : relever `trade_stops_level_safety_margin` pour LTCUSD/SOLUSD/BNBUSD, ou adapter `atr_sl_mult` pour ces symboles. **Sujet identifié dans le brief, à reformuler**.

6. **Diagnostiquer la baisse d'avg_win** (-35 %) et son impact sur le payoff (-19 %). C'est le facteur unique le plus important de la régression P&L. Très probablement lié aux nouveaux partials qui encaissent à 1,0R + 1,8R = trades coupés avant les runners 2R+. Si confirmé, envisager de différer le 1er partial à 1,2R ou de réduire `close_frac` à 0,15.

### MOYENNE (à planifier)

7. Implémenter la rotation des logs `empire_agent.log` (logrotate, RotatingFileHandler, ou cron mensuel). À ~2 GB/mois c'est gérable mais ça finira par poser problème.

8. **Lancer la Directive 12** (script `analyze_shadow_propositions.py`) avec récupération OHLC M5 + simulation SL/TP, dès que les 6 candidats auront 14+ jours de propositions logguées. Aujourd'hui ils ont 0 jour parce que non actifs.

9. Implémenter la Directive 13 (analyse biais directionnel hebdomadaire) et la Directive 14 (analyse échecs MT5 par retcode). Ces deux scripts manquent et auraient permis ce diagnostic plus rapidement.

10. **Maintenir la configuration actuelle 2-3 semaines de plus** avant toute optimisation Optuna ou ajout de feature. Avec 51 trades l'échantillon est trop petit pour distinguer signal et bruit. Le critère de validation Phase 1 du brief était 200 trades en démo — on est à 25 % du chemin.

---

**Fin du rapport. Aucune action prise. Aucun fichier de configuration ou de code modifié. Aucun commit créé.**
