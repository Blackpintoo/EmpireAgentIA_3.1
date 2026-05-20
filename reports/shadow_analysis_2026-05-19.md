# Rapport d'analyse rétroactive — Directive 12

**Date de génération** : 2026-05-19
**Auteur** : Claude Code (Opus 4.7) — assistance analytique
**Période d'observation** : 2026-05-01 04:16:10 UTC → 2026-05-19 23:59:59 UTC (≈ 18 jours civils)
**Borne basse** : horodatage du commit `e706932` (push Phase 1+2)
**Script source** : `scripts/analyze_shadow_propositions.py`
**Données brutes simulation** : `reports/shadow_analysis_data.json`

> ⚠️ **Avertissement méthodologique critique à lire avant interprétation des verdicts.**
> Les WR simulés sont très élevés (52 % → 94 %). La cause principale est la **corrélation
> sérielle** des propositions : 200 à 270 propositions par symbole et par jour
> (souvent une par minute durant les heures actives), avec SL/TP fréquemment
> similaires. Le simulateur ne déduplique pas les "clusters de proposition",
> chaque proposition est traitée comme un événement indépendant. Les chiffres
> ci-dessous reflètent donc la "qualité d'opportunité moyenne" sur la fenêtre
> mais **surestiment le WR opérationnel** qu'on observerait en exécutant
> réellement (où cooldown, déduplication, et conditions changeantes limitent
> drastiquement les entrées). Les verdicts ci-dessous appliquent les seuils
> bruts demandés et recommandent en contrepartie une **probation conservatrice
> obligatoire** plutôt qu'une promotion directe en production.

---

## Section 0 — Synthèse exécutive

| Symbole | Verdict | Justification courte |
|---|---|---|
| **DJ30**   | **PROMOUVOIR**         | n=4 381, WR 55.6 %, R:R eff 1.95 |
| **UK100**  | **PROMOUVOIR**         | n=4 884, WR 52.2 %, R:R eff 1.84 |
| **GBPUSD** | **PROMOUVOIR**         | n=3 892, WR 69.7 %, R:R eff 3.88 |
| **USDCAD** | **PROMOUVOIR**         | n=3 922, WR 78.9 %, R:R eff 5.75 |
| **GER40**  | **PROMOUVOIR**         | n=4 454, WR 62.1 %, R:R eff 2.35 |
| **XAGUSD** | **PROMOUVOIR**         | n=4 103, WR 61.3 %, R:R eff 2.07 |
| **BNBUSD** | **OPTIMISER**          | atr_sl_mult 1.5 → ~2.25 (multiplicateur 1.5×) |
| **SOLUSD** | **OPTIMISER**          | atr_sl_mult 1.5 → ~2.25 (multiplicateur 1.5×) |

**Action humaine immédiate requise** : aucune anomalie critique (zéro exécution
shadow, zéro position fantôme sur les 8 symboles). En revanche, point d'attention
opérationnel : `logs/empire_agent.log` atteint **1.0 GB** (objet du sujet P3 #7 du
backlog) et **LTCUSD a échoué sur 25 trades / 25 tentatives** (retcode 10016,
sujet P1 #3) — voir Section 5.

---

## Section 1 — Conditions de l'observation

### 1.1. Période et volumétrie

- **Début** : 2026-05-01T04:16:10+00:00 (commit `e706932` — push Phase 1+2)
- **Fin** : 2026-05-19T23:59:59+00:00
- **Durée** : 18 jours civils, 18 j et ~19 h calendrier
- **Propositions shadow analysées** : 28 644 (toutes valides après filtrage)
- **Propositions ignorées** : 0 (aucune NaN, prix nul ou incohérence side/SL/TP)

### 1.2. Confirmation de l'intégrité shadow mode

| Vérification | Résultat |
|---|---|
| Trades exécutés (`trades_log.csv`, `ok=True`) sur les 8 symboles shadow | **0 / 0** |
| Propositions shadow marquées `executed=True` dans `proposals_log.csv` | **0 / 28 644** |
| Deals dans `deals_history.csv` sur ces 8 symboles | **0 / 6 686** |
| Positions ouvertes (`open_positions.json`) sur ces 8 symboles | **0** (toutes les clés à `len=0`) |

**Conclusion** : `auto_execute=false` a été parfaitement respecté sur les 8
symboles pendant 18 jours. Aucune intervention humaine ou bug d'exécution
détecté.

### 1.3. Bornes de fetch MT5

| Symbole | Broker symbol | Barres M5 récupérées |
|---|---|---|
| DJ30   | DJ30   | 3 483 |
| UK100  | UK100  | 3 142 |
| GBPUSD | GBPUSD | 3 627 |
| USDCAD | USDCAD | 3 624 |
| GER40  | GER40  | 2 918 |
| XAGUSD | XAGUSD | 3 483 |
| BNBUSD | BNBUSD | 5 211 |
| SOLUSD | SOLUSD | 5 204 |

Toutes les propositions ont reçu au moins 1 barre exploitable
(`no_bars=0` pour les 8 symboles). Le cas TIMEOUT du tableau Section 2 ne
correspond donc pas à des données manquantes, mais à une absence de premier
touch dans les 6 heures suivantes (proposition trop serrée ou marché latéral).

---

## Section 2 — Analyse par symbole

> Convention simulation : barre M5, horizon 6 h (72 barres), test du **premier
> touch** SL ou TP dans l'ordre chronologique. Si SL et TP sont touchés dans
> **la même barre**, on attribue SL_HIT (convention conservatrice — pessimiste).

### 2.1 — DJ30 (indice US, hérite NAS100)

- **Volume** : 4 381 propositions (243 / jour ≈ 1 par 6 min)
- **LONG / SHORT** : 2 221 / 2 160 (équilibré, ratio 1.03)
- **R:R théorique moyen** : 1.687
- **Distribution scores** : [2,4)=763  [4,6)=1 268  [6,8)=1 305  [8,10)=843  [10,12)=202
- **Heures UTC dominantes** : 12h (366), 14h (362), 19h (350), 11h (342), 15h (340)
- **Résultats simulés** : TP_HIT=2 004  SL_HIT=1 599  TIMEOUT=778
- **WR simulé** : **55.62 %**  ·  **R:R effectif simulé** : **1.95**
- **Verdict** : ✅ **PROMOUVOIR** (WR > 45 %, R:R > 1.3, n ≫ 50)

### 2.2 — UK100 (indice UK, conversion GBP→USD native MT5)

- **Volume** : 4 884 propositions (271 / jour)
- **LONG / SHORT** : 2 879 / 2 005 (biais LONG, ratio 1.44)
- **R:R théorique moyen** : 1.762
- **Distribution scores** : [2,4)=961  [4,6)=991  [6,8)=1 186  [8,10)=1 367  [10,12)=368  [12,14)=11
- **Heures UTC dominantes** : 15h (387), 16h (370), 12h (365), 14h (363), 13h (359)
- **Résultats simulés** : TP_HIT=2 178  SL_HIT=1 997  TIMEOUT=709
- **WR simulé** : **52.17 %**  ·  **R:R effectif simulé** : **1.84**
- **Verdict** : ✅ **PROMOUVOIR** (à la limite basse du WR mais R:R compense)

### 2.3 — GBPUSD (forex, hérite EURUSD)

- **Volume** : 3 892 propositions (216 / jour)
- **LONG / SHORT** : 1 731 / 2 161 (biais SHORT, ratio 0.80)
- **R:R théorique moyen** : 1.656
- **Distribution scores** : [2,4)=1 382  [4,6)=1 612  [6,8)=737  [8,10)=150  [10,12)=11
- **Heures UTC dominantes** : 14h (336), 15h (331), 8h (320), 12h (311), 16h (311)
- **Résultats simulés** : TP_HIT=2 358  SL_HIT=1 024  TIMEOUT=510
- **WR simulé** : **69.72 %**  ·  **R:R effectif simulé** : **3.88**
- **Verdict** : ✅ **PROMOUVOIR**

### 2.4 — USDCAD (forex CAD natif, conversion broker)

- **Volume** : 3 922 propositions (218 / jour)
- **LONG / SHORT** : 2 738 / 1 184 (biais LONG fort, ratio 2.31)
- **R:R théorique moyen** : 1.645
- **Distribution scores** : [2,4)=1 017  [4,6)=1 828  [6,8)=909  [8,10)=156  [10,12)=12
- **Heures UTC dominantes** : 15h (357), 14h (352), 16h (339), 19h (304), 10h (302)
- **Résultats simulés** : TP_HIT=2 057  SL_HIT=550  TIMEOUT=1 315
- **WR simulé** : **78.90 %**  ·  **R:R effectif simulé** : **5.75**
- **Verdict** : ✅ **PROMOUVOIR** (taux de timeout élevé 33.5 % — marché latéral
  ou propositions trop optimistes ; à monitorer en probation)

### 2.5 — GER40 (DAX, conversion EUR→USD native, filling IOC)

- **Volume** : 4 454 propositions (247 / jour)
- **LONG / SHORT** : 2 391 / 2 063 (équilibré)
- **R:R théorique moyen** : 1.531
- **Distribution scores** : [2,4)=737  [4,6)=1 212  [6,8)=1 433  [8,10)=826  [10,12)=246
- **Heures UTC dominantes** : 13h (368), 15h (365), 17h (337), 14h (335), 16h (335)
- **Résultats simulés** : TP_HIT=2 328  SL_HIT=1 423  TIMEOUT=703
- **WR simulé** : **62.06 %**  ·  **R:R effectif simulé** : **2.35**
- **Verdict** : ✅ **PROMOUVOIR**

### 2.6 — XAGUSD (argent, hérite XAUUSD, ATR_SL +30 %, filling IOC)

- **Volume** : 4 103 propositions (228 / jour)
- **LONG / SHORT** : 2 460 / 1 643 (biais LONG modéré, ratio 1.50)
- **R:R théorique moyen** : 1.677
- **Distribution scores** : [2,4)=1 014  [4,6)=1 219  [6,8)=927  [8,10)=716  [10,12)=226  [12,14)=1
- **Heures UTC dominantes** : 16h (356), 14h (343), 19h (341), 15h (335), 17h (330)
- **Résultats simulés** : TP_HIT=2 196  SL_HIT=1 385  TIMEOUT=522
- **WR simulé** : **61.32 %**  ·  **R:R effectif simulé** : **2.07**
- **Verdict** : ✅ **PROMOUVOIR**

### 2.7 — BNBUSD (crypto, reclassé shadow pour optimisation ATR)

- **Volume** : 1 201 propositions (67 / jour) — beaucoup plus faible (probation
  héritée, votes_required=4, min_score 7.0)
- **LONG / SHORT** : 880 / 321 (biais LONG, ratio 2.74 — cohérent avec
  `allowed_directions: ["LONG"]`)
- **R:R théorique moyen** : 1.859
- **Distribution scores** : [6,8)=800  [8,10)=391  [10,12)=10  (les seuils de
  probation expliquent la concentration)
- **Heures UTC dominantes** : 16h (148), 11h (111), 15h (109), 7h (105), 10h (98)
  — toutes dans la `allowed_hours_utc [8..17]` ou en limites
- **Résultats simulés (paramètres actuels, atr_sl_mult = 1.5)** :
  TP_HIT=694  SL_HIT=245  TIMEOUT=262
  WR=**73.91 %**  ·  R:R eff=**4.94**

#### Tableau comparatif multiplicateurs ATR

Le multiplicateur agit sur la **distance** SL (élargissement) : `new_sl = entry ± (entry − sl) × m`. Le TP reste inchangé.

| Mult.   | TP_HIT | SL_HIT | TIMEOUT | WR sim. | R:R winners moy. | R:R eff sim. |
|---------|--------|--------|---------|---------|------------------|--------------|
| 1.0× *(actuel)* | 694 | 245 | 262 | 73.91 % | 1.744 | 4.94 |
| **1.5×** | 706 | 207 | 288 | **77.33 %** | **1.170** | **3.99** |
| 2.0×    | 757 | 123 | 321 | 86.02 % | 0.899 | 5.53 |
| 2.5×    | 777 | 75  | 349 | 91.20 % | 0.724 | 7.50 |
| 3.0×    | 785 | 48  | 368 | 94.24 % | 0.605 | 9.90 |

**Lecture** : les multiplicateurs ≥ 2.0× font passer `rr_winners_avg` sous 1.0,
ce qui dégrade l'asymétrie payoff par trade et augmente le risque catastrophique
si le WR réel sous-performe par rapport au simulé. Le multiplicateur **1.5×**
maintient un payoff positif (1.17) tout en améliorant le WR.

- **Verdict** : ⚙️ **OPTIMISER**
- **Multiplicateur recommandé** : **1.5×** (`atr_sl_mult: 1.5` → **`2.25`**)

### 2.8 — SOLUSD (crypto, reclassé shadow pour optimisation ATR)

- **Volume** : 1 812 propositions (101 / jour) — plus élevé que BNBUSD
- **LONG / SHORT** : 1 126 / 686 (biais LONG, ratio 1.64)
- **R:R théorique moyen** : 1.661
- **Distribution scores** : [6,8)=664  [8,10)=956  [10,12)=187  [12,14)=5
- **Heures UTC dominantes** : 15h (156), 19h (152), 16h (142), 14h (127), 11h (124)
- **Résultats simulés (paramètres actuels, atr_sl_mult = 1.5)** :
  TP_HIT=1 332  SL_HIT=82  TIMEOUT=398
  WR=**94.20 %**  ·  R:R eff=**26.66**

#### Tableau comparatif multiplicateurs ATR

| Mult.   | TP_HIT | SL_HIT | TIMEOUT | WR sim. | R:R winners moy. | R:R eff sim. |
|---------|--------|--------|---------|---------|------------------|--------------|
| 1.0× *(actuel)* | 1 332 | 82 | 398 | 94.20 % | 1.641 | 26.66 |
| **1.5×** | 1 347 | 40 | 425 | **97.12 %** | **1.097** | **36.93** |
| 2.0×    | 1 354 | 29 | 429 | 97.90 % | 0.823 | 38.44 |
| 2.5×    | 1 357 | 18 | 437 | 98.69 % | 0.659 | 49.68 |
| 3.0×    | 1 360 | 14 | 438 | 98.98 % | 0.549 | 53.37 |

**Lecture** : les WR sont extrêmes (94 % au baseline), signe quasi certain de
**propositions trop conservatrices** (TP très proche, SL très lâche) générées
en cascade. Le multiplicateur **1.5×** est le seul à maintenir
`rr_winners_avg > 1.0` tout en améliorant marginalement le WR.

- **Verdict** : ⚙️ **OPTIMISER**
- **Multiplicateur recommandé** : **1.5×** (`atr_sl_mult: 1.5` → **`2.25`**)

> Note finale sur la simulation BNBUSD/SOLUSD : malgré la qualité des chiffres
> bruts, l'avertissement méthodologique du haut de rapport s'applique avec
> double force ici. La distribution des scores est tronquée à droite (probation
> min_score 7.0), donc les propositions analysées sont déjà la fraction
> sélectionnée. Le passage en exécution réelle reste à faire en probation.

---

## Section 3 — Comparaison croisée

Symboles classés par WR simulé décroissant :

| Rang | Symbole | WR sim.  | R:R eff sim. | n proposals | Verdict |
|------|---------|----------|--------------|-------------|---------|
| 1 | SOLUSD | 94.20 % | 26.66 | 1 812 | OPTIMISER |
| 2 | USDCAD | 78.90 % | 5.75  | 3 922 | PROMOUVOIR |
| 3 | BNBUSD | 73.91 % | 4.94  | 1 201 | OPTIMISER |
| 4 | GBPUSD | 69.72 % | 3.88  | 3 892 | PROMOUVOIR |
| 5 | GER40  | 62.06 % | 2.35  | 4 454 | PROMOUVOIR |
| 6 | XAGUSD | 61.32 % | 2.07  | 4 103 | PROMOUVOIR |
| 7 | DJ30   | 55.62 % | 1.95  | 4 381 | PROMOUVOIR |
| 8 | UK100  | 52.17 % | 1.84  | 4 884 | PROMOUVOIR |

**Lecture comparative vs production** : les 9 symboles actuellement en
exécution réelle (NAS100, SP500, AUDUSD, USDJPY, XAUUSD, LTCUSD, BTCUSD,
BNBUSD-shadow, SOLUSD-shadow) ont accumulé un P&L de **−854.96 USD réalisés
+ −87 USD non-réalisés ≈ −942 USD** sur la même fenêtre (Section 5.1). Même
avec un discount sévère pour corrélation sérielle, les 6 candidats simulés
*paraissent* surperformer la production actuelle. Confirmer ce signal en
probation réelle reste impératif avant tout déploiement à pleine échelle.

---

## Section 4 — Recommandations actionnables

### 4.1 — Symboles à promouvoir (probation conservatrice)

Pour les 6 symboles **PROMOUVOIR** (DJ30, UK100, GBPUSD, USDCAD, GER40, XAGUSD),
recommander la configuration probatoire suivante dans `overrides.yaml`. Phase
de **probation 14 jours minimum** avant ouverture de calibrage.

| Paramètre                  | Valeur probation | Note |
|----------------------------|------------------|------|
| `orchestrator.auto_execute`| `true`           | passage en exécution réelle |
| `risk.risk_per_trade`      | `0.003` (0.3 %) | risque réduit vs `0.005` shadow |
| `orchestrator.position_limits.max_volume` | **moitié** de la valeur shadow actuelle | DJ30/UK100/GER40 : `0.25` ; GBPUSD/USDCAD/XAGUSD : `0.5` |
| `orchestrator.cooldown.max_trades_per_day` | `2` | abaissé de 3 |
| `orchestrator.cooldown.min_secs_between_trades` | `900`  | inchangé (15 min) |
| `orchestrator.cooldown.after_loss_min` | `90`  | resserré (vs 45-60) |
| `risk.daily_loss_abs` | inchangé | déjà conservateur ($100-200) |
| `risk.max_consec_losses` | `2` | resserré vs 3 |

À l'issue des 14 jours de probation, **gate de promotion à plein régime** :
- ≥ 5 trades exécutés
- WR live ≥ 40 %
- P&L cumulé ≥ −0.5 % du capital
- PF live ≥ 1.10

Si ces seuils sont tenus, relever progressivement `risk_per_trade` à 0.005
puis 0.008 (tier 1 standard) sur 14 jours supplémentaires.

### 4.2 — Symboles à optimiser (BNBUSD, SOLUSD)

Pour **les deux symboles**, conserver `auto_execute=false` jusqu'à ré-évaluation
des paramètres ATR (la décision optimisation **précède** la promotion).

**Changement recommandé dans `overrides.yaml`** :
```yaml
BNBUSD:
  orchestrator:
    atr_sl_mult: 2.25   # 1.5 × 1.5 (élargissement modéré SL)
    atr_tp_mult: 2.5    # inchangé
SOLUSD:
  orchestrator:
    atr_sl_mult: 2.25   # 1.5 × 1.5 (élargissement modéré SL)
    atr_tp_mult: 2.5    # inchangé
```

**Justification** : le multiplicateur `1.5×` est le seul niveau d'élargissement
qui maintient `rr_winners_avg > 1.0` (1.17 sur BNBUSD ; 1.10 sur SOLUSD).
Au-delà (2.0× et plus), le payoff par trade gagnant chute sous 1.0R et
expose à une dérive catastrophique si le WR réel est inférieur au simulé.

**Phase post-changement** : 14 jours supplémentaires en shadow avec
`atr_sl_mult=2.25` pour confirmer que la simulation s'aligne sur le nouveau
contexte, **puis** réévaluation pour promotion selon la grille 4.1.

### 4.3 — Aucun verdict CONTINUER OBSERVATION

Aucun symbole n'atteint le profil "moins de 50 propositions" ni
"à la limite des seuils sans signal clair". Tous les comptes sont ≥ 1 200
propositions et chaque WR est ≥ 52 %.

### 4.4 — Aucun verdict RETIRER

Aucun symbole ne tombe sous WR 40 % ou R:R < 1.0 simulé. Donc aucun retrait
de `enabled_symbols` n'est recommandé. Pour autant, la sortie en probation
réelle doit valider ces chiffres : un retour en shadow ou un retrait sera
décidé au cas par cas si la promotion échoue (gate 4.1).

---

## Section 5 — Données complémentaires

### 5.1 — État du bot sur la fenêtre 2026-05-01 → 2026-05-19

| Indicateur | Valeur |
|---|---|
| Equity début | 50 914.16 USD |
| Equity fin | 49 971.27 USD |
| **Delta equity** | **−942.89 USD** |
| P&L réalisé (`deals_history.csv`) | **−854.96 USD** |
| Trades OK (9 symboles actifs) | 75 |
| Trades FAIL | 25 (tous LTCUSD, voir 5.2) |

P&L réalisé par symbole sur la fenêtre :

| Symbole | P&L (USD) | Deals |
|---|---:|---:|
| NAS100 | **+212.92** | 40 |
| SP500  | +2.21       | 55 |
| BTCUSD | −16.18      | 12 |
| AUDUSD | −56.26      | 10 |
| USDJPY | −68.67      | 14 |
| XAUUSD | **−928.98** | 18 |
| LTCUSD | 0 (aucun deal — tous échecs MT5) | 0 |

XAUUSD concentre 100 % de la perte nette de la fenêtre. NAS100 reste le seul
contributeur positif net significatif. SP500 est revenu à l'équilibre. Ces
chiffres recoupent le constat Phase 1+2 (régression `avg_win` post-recalibrage
PM, sujet backlog P1 #2).

### 5.2 — Santé technique

| Indicateur | État | Action |
|---|---|---|
| `logs/empire_agent.log` | **1 036 MB** (1.0 GB) | sujet **P3 #7** — rotation devient prioritaire |
| `logs/empire.log` | 2.3 MB | OK |
| `logs/guards.log` | 1.6 MB | OK |
| Position fantôme | aucune (`tracked_positions.json` vide ; toutes les entrées de `open_positions.json` vides sauf 1 ticket NAS100 actif) | OK |
| Circuit breaker actif | XAUUSD a enregistré 1 perte le 2026-05-14 ; aucune blocage en cours | surveillance |
| Daily loss state 2026-05-19 | `realized_pnl=0.0`, kill switch non déclenché | OK |
| Taux d'échec MT5 global | 25 / 100 = **25 %** | dégradé, dû à LTCUSD |
| Taux d'échec MT5 hors LTCUSD | 0 / 75 = **0 %** | OK |
| Échecs LTCUSD | **25 / 25 (100 %)** dont **20 retcode 10016** | sujet **P1 #3** — bug critique non-résolu |

### 5.3 — Sujets P1 du backlog Phase 3 actionnables maintenant

- **#2 (Régression `avg_win` post-Phase 1)** : la fenêtre 18 j fournit 75 trades
  exécutés. Combinés aux ~25 trades initiaux post-Phase 1 (J0–J5), on atteint
  **n ≈ 100 trades**, le seuil prévu par le backlog pour reconfirmer la
  régression du couple partial 1.0R / 1.8R vs runners. Donnée XAUUSD −929 USD
  sur 18 deals fait pencher la balance, mais nécessite extraction R-multiple
  par trade pour conclure.
- **#3 (Retcode 10016 cryptos)** : **confirmé en production** — LTCUSD a
  généré 20 retcode 10016 sur 20 tentatives MT5 dans la fenêtre. Bug
  intégralement reproduit, prêt pour fix immédiat (relever distance min SL
  via `atr_sl_mult` ou `trade_stops_level_safety_margin`).
- **#4 (Optimisation ATR BNBUSD/SOLUSD)** : **traité par ce rapport** —
  voir Section 4.2.

---

## Section 6 — Plan d'action proposé pour la Phase 3

Découpage en directives implémentables, priorisées par effet attendu sur P&L et risque.

### Directive 13 — Fix retcode 10016 cryptos *(P1 backlog #3)*

- **Prérequis** : aucun (bug déjà reproduit en production).
- **Périmètre** : LTCUSD, BNBUSD, SOLUSD (cryptos sujettes à `trade_stops_level`).
- **Modification** : `config/overrides.yaml` — relever `atr_sl_mult` à `2.25`
  pour LTCUSD (équivalent à BNBUSD/SOLUSD section 4.2), **ou** introduire un
  `trade_stops_level_safety_margin` dans `risk/position_sizing.py` qui ajoute
  un buffer relatif à la distance min broker.
- **Effort** : 1 à 2 h. Test : 1 trade LTCUSD réussi (retcode 10009 ou 10018).
- **Blocage potentiel** : si LTCUSD reste perdant après le fix (probation
  R18 0 % HR), candidate au retrait pur et simple.

### Directive 14 — Probation passage en exécution réelle des 6 candidats shadow

- **Prérequis** : Directive 12 validée par l'utilisateur (ce rapport).
- **Périmètre** : DJ30, UK100, GBPUSD, USDCAD, GER40, XAGUSD.
- **Modifications** : `config/overrides.yaml` — bascule `auto_execute=true`
  + paramètres section 4.1. Mise à jour cohérente de `profiles.yaml`
  (commentaires).
- **Effort** : 1 h édition + 14 jours d'observation.
- **Blocage potentiel** : si plusieurs candidats échouent leur gate de
  promotion à J+14, ré-évaluation simultanée et possiblement bascule shadow.

### Directive 15 — Optimisation ATR BNBUSD/SOLUSD *(P1 backlog #4)*

- **Prérequis** : aucun (peut tourner en parallèle de D14).
- **Périmètre** : BNBUSD, SOLUSD.
- **Modification** : `config/overrides.yaml` — `atr_sl_mult: 1.5 → 2.25`
  (les deux symboles). Maintien `auto_execute=false` 14 j supplémentaires.
- **Effort** : 30 min édition + 14 jours shadow + ré-évaluation script
  Directive 12.
- **Blocage potentiel** : aucun. Mesure réversible immédiate.

### Directive 16 — Investigation régression `avg_win` *(P1 backlog #2)*

- **Prérequis** : exécution d'un script d'extraction R-multiple par trade
  sur les 75 trades de la fenêtre + ~25 trades antérieurs (à coder).
- **Périmètre** : analyse pure, pas de modification code.
- **Modification** : `scripts/r_multiple_analysis.py` (nouveau) qui lit
  `deals_history.csv` + reconstitue R-multiple via `proposals_log.csv` /
  `trades_log.csv` matching par ticket et timestamp.
- **Effort** : 4 à 6 h script + analyse.
- **Décision attendue** : maintenir ou bouger les partials 1.0R/1.8R vers
  1.2R/2.0R (ou réduire `close_frac` à 0.15).
- **Blocage potentiel** : matching trade ↔ proposition pas trivial si
  plusieurs propositions concurrentes au même ticket.

### Directive 17 — Cleanup opportuniste *(P3 backlog #7, #8, #9, #11)*

- **Périmètre** : cleanup non-urgents mais devenus nécessaires.
  - `#7` Rotation `empire_agent.log` (1 GB atteint) — `RotatingFileHandler`.
  - `#8` Harmonisation `[RISK]` vs `[RISK_CAP]` dans logs orchestrator.
  - `#9` Mise à jour header `ORCHESTRATOR VERSION` (R19 → R20).
  - `#11` `.gitignore` : ajout `.claude/settings.local.json`.
- **Effort** : 2 à 3 h cumulé.
- **Blocage potentiel** : aucun. Idéal pour un sprint cleanup unique.

### Priorisation suggérée

| Ordre | Directive | Justification |
|---|---|---|
| 1 | D13 (fix 10016) | bug bloquant LTCUSD, gain immédiat |
| 2 | D15 (ATR BNBUSD/SOLUSD) | mesure préparatoire à promotion future |
| 3 | D14 (promotion 6 candidats) | levier majeur d'augmentation du couvert |
| 4 | D16 (régression avg_win) | mesure analytique, décision déclenche refonte PM |
| 5 | D17 (cleanup) | hygiène technique, à grouper en sprint maintenance |

**Zones de code potentiellement impactées** :
- `config/overrides.yaml` (D13, D14, D15)
- `config/profiles.yaml` (D14, cohérence commentaires)
- `risk/position_sizing.py` (D13 si on opte pour `safety_margin`)
- `agents/orchestrator.py` (D17 #8, #9)
- `utils/logging_setup.py` ou point d'entrée logging (D17 #7)
- nouveau : `scripts/r_multiple_analysis.py` (D16)
- `.gitignore` (D17 #11)

Aucune modification de cœur de l'orchestrator ou du position manager n'est
nécessaire en Phase 3 *à ce stade* — toutes les actions sont au niveau
configuration ou outillage analytique.

---

## Annexe — Hypothèses et limitations à documenter

1. **Convention SL+TP simultanés** : si SL et TP sont touchés dans la même
   barre M5, le simulateur attribue `SL_HIT` (convention pessimiste). En réalité
   le broker arbitre via le path intra-barre, qui n'est pas observable en M5.
2. **Horizon 6 h** : retenu comme une approximation de la durée de vie typique
   d'une position avant intervention du PM (BE, partial, trailing). Trader
   en H4+ donnerait des chiffres différents.
3. **Pas de prise en compte du slippage** ni des coûts de spread/commission.
   L'exécution réelle abaisse mécaniquement le WR et le R:R effectif. À titre
   indicatif, une dégradation de 5 à 10 points de WR est plausible.
4. **Corrélation sérielle** : 1 proposition par 6 min en moyenne. Les
   simulations sont effectivement le résultat d'**opportunités empilées**,
   pas d'événements indépendants. Une déduplication par `cluster_id`
   (1 proposition par fenêtre de 5 min, par exemple) corrigerait probablement
   le WR à un niveau plus réaliste (40-50 % au lieu de 60-90 %). À envisager
   pour la prochaine itération de la Directive 12.
5. **Pas d'effet du Position Manager** : le simulateur ne modélise ni BE,
   ni partial, ni trailing. Le résultat est SL/TP brut. Un PM correctement
   calibré devrait améliorer le WR observé en production (BE protège des
   reversals) mais réduit le R:R moyen (partials coupent les runners).

---

**Fin du rapport.** Document à relire avant tout commit ou modification de configuration.
