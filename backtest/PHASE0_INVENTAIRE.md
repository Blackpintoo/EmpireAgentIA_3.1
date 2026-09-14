# Phase 0 — Inventaire avant mesure de la qualité de signal par agent

| | |
|---|---|
| Date | 2026-09-14 |
| Branche / commit | `fix-exploitation` / `f170aac` |
| Terminal | VantageMarkets-Demo, compte 25832276, build 6182, `maxbars` = 100 000 |
| Mode | Lecture seule : aucun fichier de production modifié, aucun réglage terminal changé |

Aucun chiffre de performance dans ce document : la phase 0 dénombre ce qui existe, elle ne
mesure aucun edge. Les seuls nombres sont des comptages (bougies, lignes, enregistrements)
et des valeurs de configuration relevées.

## Synthèse

| Question | Réponse courte |
|---|---|
| 0.1 Moteur existant | Oui (`backtest/agent_backtest.py`, nov. 2025), **non réutilisable** : 3 agents sur 4 lèvent à l'instanciation, le 4ᵉ rend `WAIT` à chaque bougie sans erreur. |
| 0.2 Historique MT5 | **Tout est borné à ~100 000 bougies**, très probablement par le réglage `maxbars` du terminal (limite broker non démontrée) : **M5 1 à 1,6 an, M15 2,9 à 4,7 ans**. H1 : premières bougies en 2006–2018, mais **historique dense seulement depuis 2011 à 2020 selon le symbole (médiane 8,7 ans)** — avant 2018, indices et métaux n'ont qu'environ une bougie H1 par jour ; GBPUSD n'a rien de 2014 à 2017. |
| 0.3 Agents isolables | `structure` et `smc` : oui, tels quels. `swing` : oui. `technical` : oui avec horloge simulée. `scalping` : non tel quel (état de module, horloge murale, spread tick, dépendance M15). |
| 0.4 Hors périmètre | news / sentiment / fundamental : exclusion confirmée. **COT : oui**, rejouable semaine par semaine depuis 1986 — mais la requête live mélange plusieurs marchés sur 3 des 6 symboles. |
| 0.5 Ce qui bouge seul | Les deux mécanismes **n'ont aucun effet réel aujourd'hui**, chacun à cause d'un défaut de clés. Aucun ne touche les votes bruts des agents. Tous deux figeables. |

---

## 0.1 Moteur de backtest existant

### Fichiers trouvés (y compris archivés)

| Fichier | Lignes | Dernière modification | Nature | Verdict |
|---|---|---|---|---|
| `backtest/agent_backtest.py` | 291 | fichier 2025-11-30 (git : import initial 2026-01-26) | Simulateur bougie par bougie pour UN agent : SL/TP ATR, spread, slippage, commission | Non réutilisable |
| `backtest/backtest.py` | 101 | fichier 2025-08-13 | `Backtester` minimal, indicateurs précalculés par colonnes | Non réutilisable |
| `scripts/backtest_runner.py` | 524 | git 2026-01-26 | Analyse de CSV de trades **déjà produits** : PF, Sharpe, walk-forward, bootstrap | Pas un moteur de signal |
| `archive/backtest/run_{scalping,swing,technical}.py` | 12–18 | archivés 2026-07-30 | Lanceurs de `agent_backtest` | Mêmes défauts |
| `archive/workshop/backtest_all_symbols_2years.py`, `backtest_daily_all_agents.py` | 170, 70 | archivés | Lanceurs de `agent_backtest` + Telegram | Mêmes défauts |
| `tools/backtest_orch.py`, `dashboard/backtest_app.py` | 0, 1 | — | Vides | — |

### Branché sur quelle version des agents ?

Sur une **API antérieure**. Vérifié en exécutant exactement la séquence d'instanciation de
`agent_backtest.py:148-153` sur les agents actuels :

| Agent | Résultat |
|---|---|
| `SwingAgent`, `TechnicalAgent`, `ScalpingAgent` | `TypeError: missing 1 required positional argument: 'symbol'` → `run_backtest_for_agent` lève |
| `StructureAgent` | Instancié avec `symbol=None`, `self.mt5=None`. Le faux client est injecté dans `agent.mt5_client`, attribut qu'aucun agent actuel ne lit, et il n'expose pas `get_rates`. `_get_rates` rend `None` → `WAIT no_data` à chaque bougie, **0 trade, aucune erreur** |

Autres défauts qui empêchent la reprise :

- un seul TF servi (`df_by_tf` à une clé), alors que `swing`, `technical` et `scalping` lisent d'autres TF ;
- `copy_rates_range` sur 365 jours échoue en M5 (plafond calendaire du terminal, voir 0.2) ;
- exceptions des agents avalées (`sig = None`), donc un agent cassé ressemble à un agent prudent ;
- quand SL et TP tombent dans la même bougie, le TP est testé en premier (biais optimiste) ;
- mesure de P&L de trades, sans n ni intervalle de confiance, et aucune mesure de qualité de signal.

**Réutilisable** : seulement le principe d'un faux client MT5 — qui devra exposer
`get_rates(symbol, timeframe, count)` et servir, pour n'importe quel TF, les bougies closes
antérieures ou égales à l'instant simulé.

---

## 0.2 Profondeur d'historique MT5

### Méthode

1. **Piège constaté** : `copy_rates_range` renvoie `(-2, 'Terminal: Invalid params')` dès que
   l'étendue **calendaire** demandée dépasse `maxbars × durée de bougie`. Vérifié à ±5 jours
   sur XAUUSD : M5 342 j → OK, 352 j → refus ; M15 1 037 / 1 047 j ; H1 4 162 / 4 172 j.
   Une requête « depuis 2000 » échoue donc sur les 36 séries, sans rapport avec la profondeur réelle.
2. Lecture par fenêtres successives de 95 % de cette limite, en remontant jusqu'à deux fenêtres
   vides consécutives ou jusqu'au 2000-01-01. Une fenêtre vide est retentée une fois après
   1,5 s (le terminal télécharge l'historique à la demande : GER40 H1 a pris ~3 minutes).
3. **Trou** = écart > 24 h entre deux bougies consécutives, **hors fermeture de week-end**
   (début vendredi/samedi, fin dimanche/lundi, écart ≤ 4 jours). Les jours fériés sont comptés.
4. Horodatages = heure serveur broker. La dernière bougie listée est la bougie en cours, non close.

Sondage du 2026-09-14 04:58 UTC, `maxbars` = 100 000. Horodatages en heure serveur du broker ; la dernière bougie de chaque série est la bougie en cours.

| Symbole | TF | Première bougie | Dernière bougie | Bougies | Années | Trous > 1 j | Plus long trou | Plafond |
|---|---|---|---|---:|---:|---:|---|:---:|
| NAS100 | H1 | 2012-10-23 | 2026-09-14 05:00 | 51 682 | 13,89 | 32 | 2013-03-28 → 2013-04-01 (4,0 j) |  |
| NAS100 | M15 | 2022-06-17 | 2026-09-14 05:15 | 99 992 | 4,24 | 10 | 2022-12-23 → 2022-12-27 (3,1 j) | **oui** |
| NAS100 | M5 | 2025-04-15 | 2026-09-14 05:25 | 99 976 | 1,41 | 3 | 2025-04-17 → 2025-04-21 (3,0 j) | **oui** |
| SP500 | H1 | 2009-09-17 | 2026-09-14 05:00 | 53 081 | 16,99 | 41 | 2011-12-23 → 2011-12-27 (4,0 j) |  |
| SP500 | M15 | 2022-06-17 | 2026-09-14 05:15 | 99 992 | 4,24 | 10 | 2022-12-23 → 2022-12-27 (3,1 j) | **oui** |
| SP500 | M5 | 2025-04-15 | 2026-09-14 05:25 | 99 976 | 1,41 | 3 | 2025-04-17 → 2025-04-21 (3,0 j) | **oui** |
| DJ30 | H1 | 2008-10-12 | 2026-09-14 05:00 | 52 726 | 17,92 | 44 | 2010-12-23 → 2010-12-27 (4,0 j) |  |
| DJ30 | M15 | 2022-06-17 | 2026-09-14 05:15 | 99 992 | 4,24 | 10 | 2022-12-23 → 2022-12-27 (3,1 j) | **oui** |
| DJ30 | M5 | 2025-04-15 | 2026-09-14 05:25 | 99 976 | 1,41 | 3 | 2025-04-17 → 2025-04-21 (3,0 j) | **oui** |
| UK100 | H1 | 2008-10-13 | 2026-09-14 05:00 | 47 829 | 17,92 | 96 | 2008-12-24 → 2008-12-29 (5,0 j) |  |
| UK100 | M15 | 2022-05-05 | 2026-09-14 05:15 | 99 992 | 4,36 | 28 | 2022-12-23 → 2022-12-28 (4,5 j) | **oui** |
| UK100 | M5 | 2025-03-28 | 2026-09-14 05:25 | 99 976 | 1,46 | 10 | 2025-12-24 → 2025-12-29 (4,5 j) | **oui** |
| GER40 | H1 | 2008-12-30 | 2026-09-14 05:00 | 46 683 | 17,71 | 68 | 2012-12-21 → 2012-12-27 (6,0 j) |  |
| GER40 | M15 | 2021-12-29 | 2026-09-14 05:15 | 99 991 | 4,71 | 17 | 2025-12-23 → 2025-12-29 (5,1 j) | **oui** |
| GER40 | M5 | 2025-02-13 | 2026-09-14 05:25 | 99 975 | 1,58 | 6 | 2025-12-23 → 2025-12-29 (5,1 j) | **oui** |
| AUDUSD | H1 | 2008-07-22 | 2026-09-14 05:00 | 100 146 | 18,15 | 28 | 2015-12-31 → 2017-01-02 (367,2 j) | **oui** |
| AUDUSD | M15 | 2022-09-06 | 2026-09-14 05:15 | 99 991 | 4,02 | 7 | 2022-12-23 → 2022-12-27 (3,0 j) | **oui** |
| AUDUSD | M5 | 2025-05-13 | 2026-09-14 05:25 | 99 974 | 1,34 | 2 | 2025-12-24 → 2025-12-26 (1,0 j) | **oui** |
| USDJPY | H1 | 2010-07-22 | 2026-09-14 05:00 | 100 308 | 16,15 | 23 | 2017-12-22 → 2017-12-26 (3,3 j) | **oui** |
| USDJPY | M15 | 2022-09-06 | 2026-09-14 05:15 | 99 991 | 4,02 | 7 | 2022-12-23 → 2022-12-27 (3,0 j) | **oui** |
| USDJPY | M5 | 2025-05-13 | 2026-09-14 05:25 | 99 973 | 1,34 | 2 | 2025-12-24 → 2025-12-26 (1,0 j) | **oui** |
| GBPUSD | H1 | 2006-07-21 | 2026-09-14 05:00 | 100 070 | 20,15 | 26 | 2013-12-31 → 2018-01-02 (1462,2 j) | **oui** |
| GBPUSD | M15 | 2022-09-06 | 2026-09-14 05:15 | 99 990 | 4,02 | 7 | 2022-12-23 → 2022-12-27 (3,0 j) | **oui** |
| GBPUSD | M5 | 2025-05-12 | 2026-09-14 05:25 | 99 972 | 1,34 | 2 | 2025-12-24 → 2025-12-26 (1,0 j) | **oui** |
| USDCAD | H1 | 2010-07-30 | 2026-09-14 05:00 | 100 167 | 16,13 | 23 | 2017-12-22 → 2017-12-26 (3,3 j) | **oui** |
| USDCAD | M15 | 2022-09-06 | 2026-09-14 05:15 | 99 990 | 4,02 | 7 | 2022-12-23 → 2022-12-27 (3,0 j) | **oui** |
| USDCAD | M5 | 2025-05-13 | 2026-09-14 05:25 | 99 971 | 1,34 | 2 | 2025-12-24 → 2025-12-26 (1,0 j) | **oui** |
| XAUUSD | H1 | 2007-06-22 | 2026-09-14 05:00 | 53 099 | 19,23 | 46 | 2009-12-24 → 2009-12-28 (4,0 j) |  |
| XAUUSD | M15 | 2022-06-21 | 2026-09-14 05:15 | 99 990 | 4,23 | 12 | 2022-12-23 → 2022-12-27 (3,1 j) | **oui** |
| XAUUSD | M5 | 2025-04-16 | 2026-09-14 05:25 | 99 971 | 1,41 | 4 | 2025-04-17 → 2025-04-21 (3,0 j) | **oui** |
| XAGUSD | H1 | 2007-04-18 | 2026-09-14 05:00 | 53 111 | 19,41 | 43 | 2009-12-24 → 2009-12-28 (4,0 j) |  |
| XAGUSD | M15 | 2022-06-21 | 2026-09-14 05:15 | 99 990 | 4,23 | 12 | 2022-12-23 → 2022-12-27 (3,1 j) | **oui** |
| XAGUSD | M5 | 2025-04-16 | 2026-09-14 05:25 | 99 971 | 1,41 | 4 | 2025-04-17 → 2025-04-21 (3,0 j) | **oui** |
| BTCUSD | H1 | 2018-01-02 | 2026-09-14 05:00 | 63 486 | 8,70 | 7 | 2020-12-31 → 2021-01-04 (3,1 j) |  |
| BTCUSD | M15 | 2023-10-12 | 2026-09-14 05:15 | 99 990 | 2,92 | 2 | 2023-12-24 → 2023-12-26 (1,0 j) | **oui** |
| BTCUSD | M5 | 2025-09-27 | 2026-09-14 05:25 | 99 970 | 0,96 | 0 | — | **oui** |

### Densité H1 par année civile

Bougies H1 par année (2026 partielle, jusqu'au 14/09). `·` = aucune bougie.

| Symbole | ’06 | ’07 | ’08 | ’09 | ’10 | ’11 | ’12 | ’13 | ’14 | ’15 | ’16 | ’17 | ’18 | ’19 | ’20 | ’21 | ’22 | ’23 | ’24 | ’25 | ’26 | Dense depuis |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NAS100 | · | · | · | · | · | · | *49* | *259* | *295* | *312* | *310* | *271* | 4 719 | 5 901 | 5 908 | 5 923 | 5 903 | 5 893 | 5 920 | 5 882 | 4 138 | 2018 |
| SP500 | · | · | · | *239* | *651* | *407* | *295* | *259* | *259* | *259* | *258* | *257* | 4 719 | 5 902 | 5 918 | 5 923 | 5 903 | 5 893 | 5 920 | 5 882 | 4 138 | 2018 |
| DJ30 | · | · | *67* | *303* | *308* | *297* | *295* | *259* | *259* | *259* | *258* | *257* | 4 719 | 5 895 | 5 893 | 5 923 | 5 903 | 5 893 | 5 920 | 5 880 | 4 139 | 2018 |
| UK100 | · | · | *57* | *324* | *503* | *332* | *257* | *257* | *258* | *257* | *253* | *720* | *3 517* | *3 936* | 5 064 | 5 149 | 5 707 | 5 732 | 5 767 | 5 732 | 4 008 | 2020 |
| GER40 | · | · | *2* | *508* | *510* | *339* | *256* | *255* | *255* | *256* | *255* | *708* | *3 504* | 4 134 | 5 195 | 5 245 | 5 426 | 5 380 | 5 362 | 5 342 | 3 752 | 2019 |
| AUDUSD | · | · | *2 745* | 6 146 | 6 192 | · | 6 212 | 6 159 | 6 150 | 6 192 | · | 6 205 | 6 214 | 6 216 | 6 240 | 6 238 | 6 215 | 6 216 | 6 240 | 6 216 | 4 351 | 2017 |
| USDJPY | · | · | · | · | *3 106* | 6 210 | 6 212 | 6 160 | 6 154 | 6 195 | 6 230 | 6 207 | 6 214 | 6 216 | 6 240 | 6 238 | 6 215 | 6 216 | 6 240 | 6 216 | 4 351 | 2011 |
| GBPUSD | *2 742* | 6 142 | 6 162 | 6 096 | 6 200 | 6 212 | 6 212 | 6 158 | · | · | · | · | 6 215 | 6 216 | 6 240 | 6 238 | 6 215 | 6 216 | 6 240 | 6 216 | 4 351 | 2018 |
| USDCAD | · | · | · | · | *2 957* | 6 211 | 6 210 | 6 166 | 6 156 | 6 195 | 6 230 | 6 207 | 6 215 | 6 216 | 6 240 | 6 238 | 6 215 | 6 216 | 6 240 | 6 216 | 4 351 | 2011 |
| XAUUSD | · | *195* | *260* | *259* | *272* | *311* | *295* | *259* | *259* | *259* | *258* | *257* | 4 728 | 5 905 | 5 906 | 5 894 | 5 916 | 5 893 | 5 933 | 5 911 | 4 130 | 2018 |
| XAGUSD | · | *189* | *264* | *261* | *272* | *311* | *295* | *259* | *259* | *259* | *258* | *257* | 4 728 | 5 905 | 5 905 | 5 908 | 5 914 | 5 893 | 5 933 | 5 912 | 4 130 | 2018 |
| BTCUSD | · | · | · | · | · | · | · | · | · | · | · | · | *4 835* | 6 235 | 6 187 | 6 653 | 7 970 | 8 423 | 8 486 | 8 591 | 6 107 | 2019 |

### Ce que ces tableaux disent, et ne disent pas

**1. Tout est borné par ~100 000 bougies, et ce plafond vient très probablement du terminal.** Les séries dont l'historique dépasserait ce seuil s'y arrêtent toutes, entre 99 970 et 100 308 : M15 12/12, M5 12/12, H1 4/12 (AUDUSD, USDJPY, GBPUSD, USDCAD). Le M1, contrôlé sur XAUUSD, s'arrête aussi à 99 858 bougies (depuis le 2026-06-03). C'est la signature du réglage `maxbars` du terminal ; que le serveur du broker détienne davantage **n'est ni démontré ni exclu**. Seul moyen de trancher : relever « Nombre max. de barres dans le graphique » (Outils › Options › Graphiques) puis relancer le sondage. Ce réglage sert aussi le bot en production et augmente la mémoire du terminal : **décision laissée à l'utilisateur, non modifié ici.**

**2. M5 : 0,96 à 1,58 an(s)** (première bougie entre le 2025-02-13 et le 2025-09-27). **M15 : 2,92 à 4,71 ans** ; BTCUSD (2,92 ans) sous les 3 ans. Promettre 3 ans en M5 n'est pas possible en l'état.

**3. En H1, « première bougie » ne veut pas dire « historique exploitable ».** Le détecteur de trous (> 24 h) ne voit rien avant 2018 sur les indices et les métaux, et pourtant ces années ne comptent qu'environ 250 à 720 bougies H1 par an (années pleines), contre ~5 900 à partir de 2019 : de l'ordre d'une bougie par jour de cotation. Le tableau de densité ci-dessus l'établit année par année ; les valeurs en *italique* sont sous 75 % de l'année pleine médiane 2019–2025 du symbole.

**4. Paires FX : trous de plusieurs années.** GBPUSD n'a aucune bougie H1 de 2014 à 2017 (1 462 jours) ; AUDUSD aucune en 2011 ni en 2016. USDJPY et USDCAD sont continus depuis 2011.

**5. BTCUSD change de régime de cotation** : ~4 800 à 6 700 bougies H1 par an jusqu'en 2021, ~8 000 à 8 600 à partir de 2022, pour 8 760 heures dans une année — ce qui est compatible avec l'ouverture de la cotation le week-end, sans que je l'aie vérifié autrement. Les statistiques par heure ou par jour ne sont pas homogènes sur la période.

**6. Profondeur H1 réellement dense** (le symbole atteint ≥ 75 % d'une année pleine chaque année jusqu'à 2025) — USDJPY, USDCAD depuis 2011 (15,7 ans) ; AUDUSD depuis 2017 (9,7 ans) ; NAS100, SP500, DJ30, GBPUSD, XAUUSD, XAGUSD depuis 2018 (8,7 ans) ; GER40, BTCUSD depuis 2019 (7,7 ans) ; UK100 depuis 2020 (6,7 ans). **De 6,7 à 15,7 ans selon le symbole, médiane 8,7 ans.**

Détail complet des trous (dates de début et de fin) et comptages annuels conservés dans les résultats bruts du sondage, hors dépôt.

---

## 0.3 Agents techniques isolables

### Constat commun

**Aucun agent ne prend un DataFrame.** Tous exposent la même porte d'entrée,
`generate_signal(self, timeframe: Optional[str] = None) -> Dict[str, Any]`, et vont chercher
eux-mêmes leurs bougies :

- via `self.mt5.get_rates(symbol, timeframe, count)` (le `MT5Client` injecté par l'orchestrateur,
  `orchestrator.py:4890-4901`) ;
- à défaut, pour `swing`, `technical` et `scalping`, via `MetaTrader5.copy_rates_from_pos(sym, tf, 0, count)`.

Dans les deux cas `utils/mt5_client.py:601` lit depuis la **position 0**, c'est-à-dire la
bougie en cours : le live évalue en intra-bougie. Limite connue, à documenter, pas à résoudre.

L'isolation passe donc par un faux client exposant `get_rates`, **sans modifier les agents** :
le constructeur l'accepte (`mt5=`), et l'agent ne voit plus que ce qu'on lui sert.

L'orchestrateur appelle **chaque agent sur chacun des TF** `["H1", "M15", "M5"]`
(`orchestrator.py:939`, aucune surcharge par symbole sur les 12), quel que soit le TF
« natif » de l'agent. L'unité de vote est donc (agent, symbole, TF). `scalping` est désactivé
sur USDJPY.

### Tableau

| Agent | Fonction | Fichier:ligne | Bougies | Horloge murale | Autre TF | État persistant | Réseau / autre agent | Isolable |
|---|---|---|---|---|---|---|---|---|
| `swing` | `SwingAgent.generate_signal(timeframe)` → `out["signal"]` | `agents/swing.py:358` | `_get_rates` l.202, 200 bougies | `_session_ok` l.281 via `time.localtime()` — **inactif** : `session_hours` non défini sur les 12 | H4, H1 dans `_higher_timeframe_bias` l.318 : **score seulement** ; ATR H1/M30 : extras | Non | Non / non | **Oui** |
| `structure` | `StructureAgent.generate_signal(timeframe)` → `out["signal"]` | `agents/structure.py:288` (décision l.331-361) | `_get_rates` l.160, 300 bougies, **sans repli natif** | Non | Non | Non | Non / non | **Oui, tel quel** |
| `smc` | Même appel → `out["smc_signal"]`, lu par `orchestrator.py:5209` | `agents/structure.py:329`, calcul `_smc_snapshot` l.202 | Les mêmes 300 bougies | Non | Non | Non (`utils/smc_patterns.py` n'a aucun état de module) | Non / non | **Oui, tel quel** |
| `technical` | `TechnicalAgent.generate_signal(timeframe)` → `out["signal"]` | `agents/technical.py:434` | `_get_rates` l.220, 300 bougies | **`_session_ok` l.348 : `WAIT` hors 7h–22h heure locale machine** | H4, H1 dans `_higher_timeframe_bias` l.394 : score seulement | Non | Non / non | **Oui, avec horloge simulée** |
| `scalping` | `ScalpingAgent.generate_signal(timeframe)` → `out["signal"]` | `agents/scalping.py:419` | `_get_rates` l.175, 250 bougies | **`_session_ok` l.284 (7h–21h locale) et `_now()` l.66 pour le cooldown** | **M15 dans `_m15_bias` l.359 : peut BLOQUER le signal** ; M15 aussi pour le score | **Oui : `_COOLDOWN_UNTIL`, `_LAST_BAR_DONE` au niveau du module (l.37-38)** | Tick live `_spread_points` l.249 / non | **Non, tel quel** |

### Détail par agent

**`structure` et `smc`.** Fonctions pures du DataFrame. Les pivots utilisent une fenêtre
centrée (`_pivot_flags`, l.51) mais neutralisent les `w` dernières bougies : servi avec des
bougies ≤ t, l'agent ne voit rien du futur. Seule exigence : fournir les bougies dans l'ordre
chronologique, `_get_rates` triant par index et non par temps (l.180).

**`swing`.** Isolable. **Point de configuration à connaître avant de mesurer** : le repli
`enable_fallback` est **actif sur les 12 symboles**. La dataclass le déclare `False`
(« DÉSACTIVÉ », l.101), mais le constructeur retombe sur `True` quand la configuration ne le
précise pas (l.170), ce qui est le cas. Hors `session` / `no_data` / `atr_spike`, `swing` ne rend
donc jamais `WAIT` : sans configuration nette, il vote la position du prix par rapport à l'EMA 50.
Paramètres effectifs relevés : `slope_level` 0,04, RSI de tendance 50/50.

**`technical`.** Isolable en simulant l'heure. `_session_ok` lit `time.localtime()` de la
machine, soit Europe/Zurich **avec changement d'heure**. Hors 7h–22h locale, le signal est
`WAIT session`. Le faux environnement doit reproduire cette heure locale à l'instant simulé ;
c'est faisable depuis `backtest/` en substituant `time` dans l'espace de noms du module, sans
toucher au fichier.

**`scalping`.** Pas isolable tel quel, pour quatre raisons cumulées :

1. **État de module partagé.** Après tout vote directionnel, `_COOLDOWN_UNTIL[symbole]` est posé
   à `now + 300 s` (l.517). L'orchestrateur appelle `scalping` en série sur H1 puis M15 puis M5
   dans le même cycle (`orchestrator.py:5138-5155`) : **un signal H1 force `WAIT cooldown` sur
   M15 et M5 du même cycle**. Et comme 300 s dépassent la durée d'un cycle (120 s), **les deux
   cycles suivants rendent `WAIT` sur les trois TF**. `_LAST_BAR_DONE` ajoute un anti-rejeu par bougie.
2. **Horloge murale** pour la session (7h–21h locale) et pour le cooldown (`time.time()`).
3. **Spread tick live** (`_spread_points`, filtres `max_spread` 100 points et spread/ATR 0,25) :
   aucun tick historique. Les bougies MT5 portent une colonne `spread` par bougie, qui pourrait
   servir d'approximation.
4. **Dépendance M15 dans le signal lui-même** : `_m15_bias` annule un LONG si EMA13 < EMA34 en M15.

Ce qu'il faudrait pour l'isoler, sans modifier `agents/scalping.py` : un faux client servant
aussi le M15 aligné sur t et un `get_tick` alimenté par le spread de bougie ; une horloge
simulée substituée à `time` et `_now` dans le module ; et une **décision de mesure** — vider
`_COOLDOWN_UNTIL` / `_LAST_BAR_DONE` avant chaque appel (on mesure le signal brut) ou rejouer
le temps pour reproduire le cooldown (on mesure le vote tel que le live l'émet). Ce ne sont
pas les mêmes grandeurs, et le second supprime l'essentiel des votes M15/M5.

---

## 0.4 Agents hors périmètre

### Exclusion confirmée

| Agent | Sources | Reconstituable ? |
|---|---|---|
| `news` | Flux RSS (Yahoo Finance, Cointelegraph, Bitcoin Magazine, CryptoSlate, CoinJournal…) + calendrier FXStreet (`agents/news.py`) | Non : les flux RSS ne sont pas archivés |
| `sentiment` | Fear & Greed alternative.me + Google Trends + sentiment Twitter (`agents/sentiment.py`, `utils/data_sources.py`) | Non pour le composite. Nuance : le Fear & Greed **seul** a un historique public journalier (`?limit=0` : 3 144 points depuis le 2018-02-01), mais c'est un indice crypto |
| `fundamental` | Calendrier FXStreet (`agents/fundamental.py`) ; désactivé par défaut (`orchestrator.py:4953`) | Non : valeurs publiées révisées, instant de publication non reconstituable |

### COT (`utils/advanced_sentiment.py`) : **oui**

**Source** : CFTC Public Reporting Environment (API Socrata), jeu `6dca-aqww` « Legacy – Futures
Only », `https://publicreporting.cftc.gov/resource/6dca-aqww.json` — **l'endpoint même
qu'utilise le live** (`advanced_sentiment.py:437`). Gratuit, sans clé, requêtable par date.

Profondeur mesurée le 2026-09-14 (groupement par code de contrat) :

| Symbole | Contrat principal (code CFTC) | Historique continu | Semaines |
|---|---|---|---|
| XAUUSD | GOLD – COMEX (`088691`) | 1986-01-15 → 2026-09-08 | 1 933 |
| XAGUSD | SILVER – COMEX (`084691`) | 1986-01-15 → 2026-09-08 | 1 933 |
| USDJPY | JAPANESE YEN – CME (`097741`) | 1986-01-15 → 2026-09-08, renommé en 2000 | 575 + 1 359 |
| USDCAD | CANADIAN DOLLAR – CME (`090741`) | 1986-01-15 → 2026-09-08, renommé en 2000 | 575 + 1 359 |
| AUDUSD | AUSTRALIAN DOLLAR – CME (`232741`) | 1987-01-30 → 2026-09-08, renommé deux fois | 455 + 159 + 1 183 |
| GBPUSD | BRITISH POUND – CME (`096742`) | 1988-04-29 → 2026-09-08, renommé en 2022 (lacune 1993-2004 à vérifier) | 123 + 944 + 240 |

Conditions d'un rejeu honnête, **non implémentées** :

- identifier le marché par `cftc_contract_market_code`, jamais par le nom (renommages ci-dessus) ;
- dater chaque rapport à sa **publication** (vendredi) et non à sa date de positions (mardi),
  sinon trois jours de look-ahead ;
- 6 des 12 symboles seulement ont un COT (indices et BTCUSD absents du mapping live).

### Défaut du live constaté en passant — signalé, non corrigé

La requête live filtre par `market_and_exchange_names like '%…%'`, trie par date et prend
`$limit 2`, en supposant que les deux lignes sont deux semaines du même contrat. Rejouée
à l'identique le 2026-09-14 :

| Symbole | `rows[0]` (traité comme « dernier ») | `rows[1]` (traité comme « précédent ») |
|---|---|---|
| XAUUSD | **PAX GOLD PERP – Coinbase**, 2026-09-08, net −358 | GOLD – COMEX, **même semaine**, net +231 960 |
| GBPUSD | **EURO FX/BRITISH POUND XRATE**, 2026-09-08, net −23 | BRITISH POUND – CME, **même semaine**, net −58 836 |
| USDJPY | **EURO FX/JAPANESE YEN XRATE**, 2026-09-08, net +2 155 | JAPANESE YEN – CME, **même semaine**, net +10 796 |
| XAGUSD, AUDUSD, USDCAD | bon contrat, 2026-09-08 | bon contrat, 2026-09-01 |

Sur 3 des 6 symboles, le « dernier » COT est un autre marché et la « variation hebdomadaire »
compare deux contrats différents. L'ordre des lignes d'une même date n'est pas garanti par
Socrata : le résultat peut changer d'un appel à l'autre.

---

## 0.5 Ce qui bouge tout seul

### `_auto_optimize_job`

| | |
|---|---|
| Planification | `cron` **21:05 Europe/Zurich**, un job par symbole (`orchestrator.py:3512-3519`). Aucun job à 23h dans le code |
| Déclenchement effectif | Oui : `proposals/profiles_patch.yaml` réécrit le 2026-09-13 à 21:05 |
| Ce qu'il fait | (1) abandonne si une position est ouverte ; (2) lance `utils/sync_history.py`, qui ajoute les deals MT5 à `deals_history.csv` ; (3) lance `utils/param_tuner.py` ; (4) lit le patch, borne les valeurs, fusionne dans `config/overrides.yaml`, recharge |
| Ce qu'il modifierait | 4 seuils d'**orchestrateur** : `min_score_for_proposal` (borné 1,4–3,0), `atr_sl_mult`, `atr_tp_mult`, `votes_required`. **Aucun paramètre d'agent** |
| Fenêtre de données | Les 150 dernières **lignes** de `deals_history.csv` par symbole. Ces lignes mêlent entrées et sorties : les deals d'entrée (profit 0) sont comptés comme pertes. Win rate calculé : 0,21 à 0,29 (72 à 80 lignes sur 150 à profit nul), donc le palier « < 40 % » pour tous les symboles |
| **Effet réel** | **Aucun.** `param_tuner` écrit sous une clé racine `profiles:` (`param_tuner.py:38`) ; le job lit `patch_all.get(self.symbol)` à la racine (`orchestrator.py:6200`) → `None` → retour immédiat. Preuve : `overrides.yaml` inchangé depuis le 2026-08-12 06:34 et porte toujours ses 150 lignes de commentaires, que `yaml.safe_dump` aurait supprimées |
| Journalisation | Aucune ligne dans `empire_agent.log` : sorties des sous-processus non capturées, Telegram seulement en cas d'application. Seule trace : la date du fichier patch (versionné, contenu identique chaque nuit, donc invisible dans `git status`) |
| Figeable pour le backtest | Oui — sans objet pour la phase 1, qui mesure les votes bruts en amont de ces seuils |

**Risque latent, signalé et non corrigé** : si la clé était un jour réparée, les 12 symboles
recevraient `min_score_for_proposal` ≤ 3,0, soit la levée silencieuse des probations XAUUSD
(6,5) et USDJPY (7,0), et `overrides.yaml` perdrait tous ses commentaires.

`_nightly_backtest_and_optimize` (Optuna via `optimize_agent`, qui touche aux paramètres
d'agents) n'est planifié que si `optimization.enabled` : la section `optimization` est absente
de la configuration, **il ne tourne pas**. Il doit le rester pendant la campagne.

### Performance tracker

| | |
|---|---|
| Stockage | `data/performance/compte_25832276/tracker_<SYM>.json` : 6 fichiers (AUDUSD, BTCUSD, NAS100, SP500, USDJPY, XAUUSD) ; aucun pour les 6 autres symboles |
| Mécanique | EMA de décroissance 0,85 (demi-vie ≈ 4,3 enregistrements), clé (symbole, agent, TF\|régime), poids borné [0,25 ; 3,5], décroissance d'inactivité de demi-vie 14 jours appliquée à la lecture |
| Écriture | `_record_performance_stats` (`orchestrator.py:1932`), à l'exécution (l.3372) et en dry-run (l.2852) |
| **Ce qu'il apprend** | `outcome = _estimate_rr(proposal)` : le R:R **prévu**, (TP − entrée)/(entrée − SL), toujours positif. **Jamais le résultat réalisé.** Un trade exécuté compte comme gagnant quelle que soit son issue, une proposition non exécutée fait baisser le taux : le « hit rate » mesure le taux d'exécution |
| Lecture | `compute_weighted_vote` (`performance_tracker.py:279`, appelée `orchestrator.py:4064`), signaux nommés `<agent>_<tf>` (l.5795), score = ±poids du TF (1,2 / 1,0 / 0,9) |
| **Effet réel** | **Aucune repondération.** Les écritures tombent toutes dans le bucket `unknown \| M30\|default` (12 à 42 enregistrements selon le symbole) ; les lectures interrogent `technical_m5 \| M5\|default`, etc., tous à `count = 0`, poids 1,0. Le vote tracker vaut la moyenne des ±poids TF des agents directionnels |
| Injection | Pas dans le score : dans la **confluence** (`orchestrator.py:4121-4133`). Si \|vote\| ≥ 0,6 : ±0,5 × min(\|vote\|, 3)/3, soit **au plus ±0,2**, puisque \|vote\| ≤ 1,2 |
| Journalisation | Aucune trace des changements de poids : fichier réécrit en place, ligne `[TRACKER] top` absente des journaux actuels |
| Figeable pour le backtest | Oui : `PerformanceTracker(storage_path=<copie figée>)` sans appel à `record`, ou poids constants à 1,0 — équivalent exact de l'état effectif actuel. Sans objet pour la phase 1 |

### Troisième mécanisme, non listé dans la consigne

**Cooldown d'agent sur erreurs** (`orchestrator.py:5058-5068`) : 5 exceptions d'un agent le
désactivent 1 h, puis 2 h, 4 h, 8 h, avec journalisation ERROR et Telegram. Il change la
composition des votes sans validation. Sans objet en backtest si les exceptions y sont
comptées comme telles plutôt qu'avalées.

---

## Avis

1. **Faisable en H1 et en M15** pour `structure`, `smc`, `swing` et `technical` : ~8,7 ans médians de H1 dense (6,7 à 15,7), 2,9 à 4,7 ans de M15, à condition de restreindre chaque symbole à sa période dense et de simuler l'heure locale pour `technical`.
2. **Bloquant en M5** : 1 à 1,6 an ne suffit pas pour un hors-échantillon sur 12 symboles. À trancher avant la phase 1 — relever `maxbars` et refaire le sondage (décision terminal), ou sortir M5 de la mesure.
3. **Deux définitions à fixer avant de construire** : pour `scalping`, mesurer le signal brut ou le vote tel que le live l'émet après cooldown (ce ne sont pas les mêmes grandeurs) ; et, pour tous, la cible de la « qualité de signal » (horizon et unité du rendement). Rien dans 0.5 n'empêche de figer l'état.

---

## Annexe — reproductibilité

- Profondeur MT5 : script de sondage par fenêtres (lecture seule, `copy_rates_range`), résultat brut
  conservé hors dépôt ; relançable tel quel une fois `maxbars` éventuellement relevé.
- COT : requêtes Socrata `$select … min/max(report_date_as_yyyy_mm_dd), count(*) $group
  market_and_exchange_names, cftc_contract_market_code`, et rejeu exact de la requête live.
- Agents : instanciation avec `get_symbol_profile(symbole)`, comme `load_agent`
  (`orchestrator.py:4876-4905`), pour relever les paramètres effectifs.
