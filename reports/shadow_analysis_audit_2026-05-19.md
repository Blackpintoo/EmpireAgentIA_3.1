# Addendum — Audit méthodologique du rapport shadow_analysis_2026-05-19

**Date** : 2026-05-19
**Origine** : Directive 14 (audit du rapport `reports/shadow_analysis_2026-05-19.md`)
**Script d'audit** : `scripts/audit_shadow_analysis.py` (nouveau, distinct de
`analyze_shadow_propositions.py` qui n'a pas été modifié)
**Données brutes** : `reports/shadow_audit_data.json`
**Tag de sauvegarde** : `pre-phase3-2026-05-19` (HEAD)

---

## TL;DR — Verdicts révisés

| Symbole | Verdict initial | Verdict révisé      | Raison principale |
|---------|-----------------|----------------------|--------------------|
| DJ30    | PROMOUVOIR      | **PROMOUVOIR**       | dedup ΔWR = −6.19 pp, ΔRR = −23.5 % (sous seuils) |
| UK100   | PROMOUVOIR      | **PROMOUVOIR**       | dedup ΔWR = −6.71 pp, ΔRR = −27.6 % (sous seuils, marge tendue) |
| GBPUSD  | PROMOUVOIR      | **CONTINUER OBS.**   | dedup ΔWR = −14.29 pp, ΔRR = −47.7 % (ALERTE WR + RR) |
| USDCAD  | PROMOUVOIR      | **CONTINUER OBS.**   | dedup ΔWR = −17.18 pp, ΔRR = −58.3 % (ALERTE WR + RR) |
| GER40   | PROMOUVOIR      | **PROMOUVOIR**       | dedup ΔWR = −6.71 pp, ΔRR = −23.5 % (sous seuils) |
| XAGUSD  | PROMOUVOIR      | **CONTINUER OBS.**   | dedup ΔWR = −11.32 pp, ΔRR = −38.9 % (ALERTE WR + RR) |
| BNBUSD  | OPTIMISER       | **CONTINUER OBS.**   | dedup ΔRR = −36.0 % (ALERTE RR) |
| SOLUSD  | OPTIMISER       | **CONTINUER OBS.**   | dedup ΔRR = −57.4 % (ALERTE RR) |

**3 symboles conservent PROMOUVOIR (DJ30, UK100, GER40)**, **5 basculent en
CONTINUER OBSERVATION**. La Phase 3 Directive 14 doit être recalibrée : la
probation initiale ne peut couvrir que 3 candidats, pas 6.

---

## Q1 — Périmètre temporel vs commit `d727913`

**Question** : la fenêtre exclut-elle les propositions UK100 / GER40 émises
avant le commit `d727913` (fix point_value, 30 avril) ?

**Méthode** : lecture étendue de `proposals_log.csv` du 2026-04-28 (commit-2j)
au 2026-05-19, comptage strict des propositions UK100 et GER40 avec
`ts < 2026-04-30T19:43:44+00:00` (heure UTC du commit `d727913`).

**Résultat** :

| Symbole | Propositions pré-commit (J−2 → commit) | Première proposition observée |
|---------|----------------------------------------:|--------------------------------|
| UK100   | **0**                                   | 2026-05-01T06:02:12 UTC        |
| GER40   | **0**                                   | 2026-05-01T06:01:36 UTC        |

**Conclusion** : la fenêtre d'analyse `[2026-05-01T04:16:10 UTC ; 2026-05-19T23:59:59 UTC]`
est **postérieure au commit `d727913` de 8h33** (commit à 2026-04-30T19:43:44 UTC).
Toutes les propositions UK100 et GER40 du pool initial sont post-fix. **Aucun
delta à appliquer**, aucune ré-exécution nécessaire. Le rapport initial est
intact sur ce point.

---

## Q2 — Position du log `proposals_log` vs `hard_filters`

**Question** : les propositions sont-elles loguées en amont ou en aval des
`hard_filters` (`min_score`, `min_confluence`, `tracker_contradiction`,
`min_rr`, `short_score_penalty`, blacklist horaires) ?

### Lecture du code

Deux chemins coexistent dans `orchestrator/orchestrator.py` :

| Chemin                     | Conditions                                                  | Log proposal | Position vs hard_filters |
|----------------------------|-------------------------------------------------------------|---------------|---------------------------|
| **`auto_execute=true`**    | Symboles en production (NAS100, SP500, …)                   | Ligne **4397**, après l'attempt `execute_trade(direction)`. `executed=True/False` selon résultat MT5. | **AVAL** (les hard_filters internes à `execute_trade` ont déjà tourné) |
| **`auto_execute=false`** *(shadow)* ou `use_telegram_validation=true` | DJ30, UK100, GBPUSD, USDCAD, GER40, XAGUSD, BNBUSD, SOLUSD | Ligne **1909** via `_send_validation_proposal`, AVANT toute exécution. `executed=False` constant. | **AMONT** (les hard_filters de `execute_trade` ne sont jamais évalués) |

**Conclusion structurelle** : les propositions des 8 symboles shadow loguées
dans `proposals_log.csv` sont la **sortie brute** du pipeline de décision,
hors hard_filters globaux. C'est exactement le biais redouté par la Directive 14.

### Ré-simulation après application manuelle des hard_filters

Filtres appliqués (extraits de `config/config.yaml` et `orchestrator.py`) :
- `min_score = 3.8`
- `min_confluence = 2.5`
- `min_rr = 1.0`
- `short_score_penalty = +1.5` (donc `min_score_short = 5.3`)
- `GLOBAL.blocked_hours_utc = [3, 4, 7, 10, 11, 12, 13, 14]` (rejet pour non-crypto)

| Symbole | Input | Gardés | % gardé | Rejets (rang)              | WR filtré | RR_eff filtré | WR initial | RR_eff initial |
|---------|------:|-------:|--------:|-----------------------------|----------:|--------------:|-----------:|---------------:|
| DJ30    | 4 428 | 1 502  | 33.9 %  | hour 1 194 / score 780 / conf 618 / short 334 | 66.14 %   | 3.13          | 55.62 %    | 1.95           |
| UK100   | 4 948 | 1 912  | 38.6 %  | hour 1 409 / score 977 / conf 410 / short 240 | 62.97 %   | 2.93          | 52.17 %    | 1.84           |
| GBPUSD  | 3 931 | 758    | 19.3 %  | score 1 392 / short 694 / hour 627 / conf 460 | 87.76 %   | 13.08         | 69.72 %    | 3.88           |
| USDCAD  | 3 938 | 1 150  | 29.2 %  | score 1 031 / hour 819 / conf 562 / short 376 | 94.43 %   | 26.38         | 78.90 %    | 5.75           |
| GER40   | 4 497 | 1 625  | 36.1 %  | hour 1 170 / score 780 / conf 655 / short 267 | 77.76 %   | 5.08          | 62.06 %    | 2.35           |
| XAGUSD  | 4 145 | 1 395  | 33.7 %  | score 1 030 / hour 1 016 / conf 353 / short 351 | 71.85 %   | 3.25          | 61.32 %    | 2.07           |
| BNBUSD  | 1 201 | 1 201  | 100 %   | (aucun — déjà filtré par `min_score=7.0` upstream) | 73.91 % | 4.94 | 73.91 % | 4.94 |
| SOLUSD  | 1 815 | 1 812  | 99.8 %  | conf 3                       | 94.19 %   | 26.59         | 94.20 %    | 26.66          |

**Lecture** : les hard_filters rejettent 60-80 % des propositions non-crypto.
Les propositions **restantes ont un WR encore plus élevé** que le pool brut
(les filtres font leur travail : ils éliminent les signaux faibles dont la
performance projetée était basse). Pour les cryptos (BNBUSD/SOLUSD), les filtres
en amont du log (`min_score_for_proposal=7.0`, `votes_required=4`) couvrent
déjà les seuils hard_filters globaux ; les chiffres sont identiques à l'initial.

**Conclusion Q2** : la qualité des propositions shadow analysées **sous-estime**
la qualité projetée en production. Les verdicts du rapport initial ne sont
PAS faussés par excès d'optimisme dû à ce biais — au contraire, la projection
production serait *encore* plus favorable. Mais cette observation n'invalide
pas le risque méthodologique principal (corrélation sérielle, Q4).

---

## Q3 — Distribution du R:R théorique par symbole

**Question** : le R:R effectif simulé de 5.75 sur USDCAD est-il un artefact ou
vient-il de propositions naturellement très optimistes en TP ?

### Distribution (avant simulation, sur le pool intégral)

| Symbole | n     | min   | p25   | médiane | p75   | max    | moyenne |
|---------|------:|------:|------:|--------:|------:|-------:|--------:|
| DJ30    | 4 428 | 1.000 | 1.314 | 1.563   | 2.000 | 4.159  | 1.689   |
| UK100   | 4 948 | 1.000 | 1.562 | 1.563   | 2.000 | 11.424 | 1.763   |
| GBPUSD  | 3 931 | 1.000 | 1.196 | 1.786   | 1.786 | 3.226  | 1.652   |
| USDCAD  | 3 938 | 1.000 | 1.110 | **1.786** | 1.786 | 2.500  | 1.643 |
| GER40   | 4 497 | 1.000 | 1.302 | 1.302   | 2.000 | 5.554  | 1.534   |
| XAGUSD  | 4 145 | 1.000 | 1.202 | 1.202   | 2.000 | 17.368 | 1.689   |
| BNBUSD  | 1 201 | 1.029 | 1.667 | 1.667   | 2.000 | 2.500  | 1.859   |
| SOLUSD  | 1 815 | 1.002 | 1.667 | 1.667   | 1.667 | 2.500  | 1.661   |

### Analyse spécifique USDCAD

- R:R théorique médian = **1.786** (proposition standard, pas optimiste).
- R:R théorique max = **2.500** (plafond mode probation/shadow).
- 50 % des propositions ont R:R entre 1.110 et 1.786 → distribution serrée
  autour de 1.6-1.8.

**Conclusion Q3** : les propositions USDCAD ne sont **pas anormalement optimistes
en TP**. Leur R:R théorique est dans la norme du portefeuille (médiane 1.5-1.8
sur tous les symboles). Le R:R effectif simulé de 5.75 vient **mécaniquement
de la formule** `(rr_winners_avg × WR) / (1 − WR)` appliquée à un WR de 78.9 % :

```
rr_eff = 1.538 × 0.789 / 0.211 = 5.75
```

C'est une amplification correcte mathématiquement, mais elle **amplifie aussi
le bruit** sur le WR. Si le WR réel chute de 10 points (passe à 68 %), `rr_eff`
chute à `1.538 × 0.68 / 0.32 = 3.27` (−43 %). C'est la sensibilité du levier
non-linéaire à l'erreur sur WR qui rend le verdict initial fragile. La Q4
mesure précisément cette fragilité par dedup.

---

## Q4 — Test de robustesse par déduplication temporelle 60 min

**Question** : si on ne garde qu'une proposition par symbole et par direction
par fenêtre de 60 min, le WR / R:R simulés changent-ils significativement ?

### Méthode

- Tri chronologique de chaque pool symbole.
- Pour chaque direction (LONG / SHORT) indépendamment, on garde la première
  proposition d'une fenêtre 60 min ; toutes les suivantes dans la même fenêtre
  sont éliminées.
- Re-simulation MT5 M5 sur le sous-ensemble dédupliqué (même horizon 6h, même
  convention SL+TP).

### Résultats

| Symbole | n init | n dedup | WR dedup | RR_eff dedup | ΔWR (pp)     | ΔRR (%)       | Alerte ? |
|---------|-------:|--------:|---------:|-------------:|-------------:|--------------:|:---------|
| DJ30    | 4 428  | 209     | 49.43 %  | 1.49         | **−6.19**    | **−23.5 %**   | ❌ NON   |
| UK100   | 4 948  | 203     | 45.45 %  | 1.33         | **−6.71**    | **−27.6 %**   | ❌ NON   |
| GBPUSD  | 3 931  | 206     | 55.43 %  | 2.03         | **−14.29** ⚠️ | **−47.7 %** ⚠️ | ✅ OUI  |
| USDCAD  | 3 938  | 209     | 61.72 %  | 2.40         | **−17.18** ⚠️ | **−58.3 %** ⚠️ | ✅ OUI  |
| GER40   | 4 497  | 201     | 55.36 %  | 1.80         | **−6.71**    | **−23.5 %**   | ❌ NON   |
| XAGUSD  | 4 145  | 199     | 50.00 %  | 1.27         | **−11.32** ⚠️ | **−38.9 %** ⚠️ | ✅ OUI  |
| BNBUSD  | 1 201  | 95      | 65.28 %  | 3.16         | −8.63        | **−36.0 %** ⚠️ | ✅ OUI  |
| SOLUSD  | 1 815  | 143     | 87.38 %  | 11.36        | −6.82        | **−57.4 %** ⚠️ | ✅ OUI  |

> **Critère d'alerte** (per Directive 14) : ΔWR > 10 pp **OU** ΔRR > 30 % en
> valeur relative ⇒ marquer en CONTINUER OBSERVATION.

### Lecture

- Les 8 symboles voient leur **n effective tomber d'un facteur 10-25x** après
  dedup (les pools sont essentiellement des clusters de re-émission).
- **3 symboles passent le test** (DJ30, UK100, GER40) avec un WR encore au-dessus
  de 45 % et un R:R effectif au-dessus de 1.3. UK100 est à la marge stricte
  (45.45 % WR ; 1.33 R:R) — à monitorer particulièrement en probation.
- **5 symboles échouent** (GBPUSD, USDCAD, XAGUSD, BNBUSD, SOLUSD) : la
  corrélation sérielle gonflait artificiellement les chiffres initiaux. Le
  signal n'est pas absent — il est **insuffisamment indépendant** sur 18 j.

### Conclusion Q4

Les verdicts initiaux PROMOUVOIR / OPTIMISER pour ces 5 symboles ne sont
**pas soutenus par la simulation robuste**. Délai supplémentaire d'observation
requis avant toute promotion en exécution réelle.

---

## Verdict révisé par symbole et plan d'observation

### Maintenus PROMOUVOIR (3 symboles)

| Symbole | Conditions de promotion en probation                                              |
|---------|-----------------------------------------------------------------------------------|
| DJ30    | `risk_per_trade=0.003`, `max_volume=0.25`, `max_trades_per_day=2`, 14 j probation |
| UK100   | mêmes que DJ30, **monitorer particulièrement** (WR dedup 45.5 % à la limite)      |
| GER40   | mêmes que DJ30                                                                    |

### Basculés CONTINUER OBSERVATION (5 symboles)

| Symbole | Délai d'observation suppl. | Métrique à attendre                                |
|---------|----------------------------|-----------------------------------------------------|
| GBPUSD  | **+21 j** (3 semaines)     | WR dedup stable ≥ 50 % sur 2 fenêtres indépendantes |
| USDCAD  | **+21 j**                  | idem + investigation du timeout 33 % (Section 2.4 rapport initial) |
| XAGUSD  | **+14 j**                  | WR dedup ≥ 45 % et R:R dedup ≥ 1.3 stables          |
| BNBUSD  | **+14 j**                  | WR dedup ≥ 45 % et R:R dedup ≥ 1.4 (critère OPTIMISER initial) |
| SOLUSD  | **+14 j**                  | idem BNBUSD ; valider que la dilution post-dedup ne tombe pas sous 1.4 RR |

**Critère commun de gating après observation supplémentaire** : ré-exécution
du script `audit_shadow_analysis.py` avec la nouvelle fenêtre élargie. Si le
ΔWR / ΔRR post-dedup reste dans les seuils tolérés, promotion en probation
selon la grille Section 4.1 du rapport initial. Sinon, considérer le retrait
de `enabled_symbols` (verdict RETIRER).

### Plus aucun OPTIMISER pour BNBUSD/SOLUSD

L'optimisation ATR (multiplicateurs 1.5×-3.0×) n'a de sens que si la base
post-dedup confirme un signal exploitable. Comme la Q4 montre que BNBUSD
et SOLUSD ne passent pas le test de robustesse, le sujet ATR (Directive 15
prévue) est **suspendu** jusqu'à ce que CONTINUER OBSERVATION se résolve
par un signal stable.

---

## Impact sur le plan d'action Phase 3

### Recalibrage du plan présenté dans le rapport initial Section 6

| Directive | État | Changement |
|-----------|------|------------|
| **D13** (fix retcode 10016 cryptos) | **inchangé** | bug réel, indépendant de l'audit |
| **D14** (promotion 6 candidats) | **réduite à 3** | ne couvre que DJ30, UK100, GER40 |
| **D15** (optimisation ATR BNBUSD/SOLUSD) | **suspendue** | conditionnée au déblocage CONTINUER OBSERVATION |
| **D16** (régression avg_win, sujet #2) | **inchangé** | analyse autonome, indépendante de l'audit |
| **D17** (cleanup P3) | **inchangé** | indépendant |

### Nouvelle directive proposée

| Directive | Description |
|-----------|-------------|
| **D18** (nouveau) | Réévaluation à J+14 / J+21 des 5 symboles CONTINUER OBSERVATION. Ré-exécuter `audit_shadow_analysis.py`. Critères de décision : promouvoir si dedup stable, retirer si dégradation, prolonger une fois max si zone grise. |

---

## Limites de l'audit (à connaître pour interprétation)

1. **Dedup 60 min unique** — un autre choix (30 min, 120 min) donnerait des
   résultats différents. 60 min est un proxy raisonnable pour "événements de
   marché indépendants" en intraday, pas une vérité absolue.
2. **Pas de hard_filters complets** — `tracker_contradiction` n'est pas
   reproduit (tracker_vote absent du log) ; momentum check non simulé ;
   ASIA_BLOCK supposé désactivé pour cohérence (non-vu dans overrides actif).
   Approximation conservatrice : un filtre supplémentaire éliminerait
   davantage de propositions et accentuerait le signal.
3. **Pas de prise en compte du Position Manager** — BE/partials/trailing
   modifieraient les WR observés en production. Effet indéterminé sur les
   verdicts post-dedup.
4. **Pas de slippage / spread / commissions** — l'exécution réelle réduit
   mécaniquement WR et RR_eff de quelques points. Effet à intégrer dans la
   marge de sécurité des gates de promotion.

---

## Avertissement final

Cet addendum **ne remplace pas** le rapport initial — il en affine les
verdicts par application d'un critère de robustesse explicite, à la demande
de la Directive 14. Le rapport initial reste lisible comme document de
référence pour le contexte, les volumétries, les distributions de scores
et la santé technique (Section 5). Les **verdicts révisés** ci-dessus sont
ceux qui doivent guider la Phase 3.

---

**Fin de l'addendum D14. Aucune modification de code applicatif ou de
configuration. Aucun commit. Prêt pour relecture.**
