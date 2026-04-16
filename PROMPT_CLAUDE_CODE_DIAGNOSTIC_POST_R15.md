# PROMPT CLAUDE CODE — Diagnostic post-Round 15

## Contexte

Round 15 a ajouté 5 fixes ciblant la qualité des entrées et le contrôle du risque :
- R15 FIX 1 : **MOMENTUM_CHECK** — filtre momentum pré-exécution (3 bougies M5). Déjà actif, 19 trades bloqués le 23 mars.
- R15 FIX 2 : **RISK_CAP indices override** — point_val hardcodé à 1.0 pour SP500, NAS100, DJ30, GER40, UK100 (était 0.01 → risque sous-estimé ×100).
- R15 FIX 3 : **Anti-QUICK_REVERSAL** — cooldown 30 min sur un symbole après SL en < 10 min.
- R15 FIX 4 : **HARD_FILTER log** — décimales `.4f` pour diagnostiquer les arrondis float.
- R15 FIX 5 : **[DECISION] log** — traçabilité complète de chaque décision.

**Fixes précédents toujours actifs :**
- R14 ENTRY_REFRESH : R:R préservé 100%, avg $/win = $124
- R14 DIR_CHECK : 0 incohérence
- R13 HARD_FILTER : 40.8% rejet (cible 40-70%)
- R12 Outcome tracker : 56 clôtures
- Bug `regime_label` → `_regime_label` (ligne 5080) corrigé
- `counter_trend_min_score` = 6.0 dans config.yaml

**Objectif** : Vérifier que les 5 fixes R15 sont actifs et mesurer leur impact sur le hit rate et le P&L. Aucun fichier ne doit être modifié.

**Référence P&L pré-R15 (23 mars) :**
- 9 trades, 2 wins (trailing), 7 SL
- Hit rate : 22%
- Avg $/win : $124
- P&L net : -$668
- 3 QUICK_REVERSALS : -$627 (AUDUSD 7min, SP500 5min, LTCUSD 3min)
- RISK_CAP indices : inactif (point_val=0.01)

---

## PHASE 1 — Collecte des données

```bash
# 1a. Dernières 3000 lignes du log
tail -n 3000 logs/empire_agent.log

# 1b. MOMENTUM_CHECK — LE FIX CLÉ R15
grep -i "MOMENTUM_CHECK" logs/empire_agent.log

# 1c. COOLDOWN + QUICK_REVERSAL
grep -i "COOLDOWN\|QUICK_REVERSAL" logs/empire_agent.log

# 1d. RISK_CAP — override indices
grep -i "RISK_CAP" logs/empire_agent.log

# 1e. DECISION log
grep -i "\[DECISION\]" logs/empire_agent.log | tail -30

# 1f. ENTRY_REFRESH (toujours actif R14)
grep -i "ENTRY_REFRESH" logs/empire_agent.log | tail -20

# 1g. HARD_FILTER (avec décimales .4f)
grep -i "HARD_FILTER" logs/empire_agent.log | tail -20

# 1h. Outcome tracker
grep -i "\[OUTCOME\]" logs/empire_agent.log | tail -30

# 1i. Trades exécutés
grep -i "order_send\|retcode\|ticket=" logs/empire_agent.log | tail -20

# 1j. SCORE_DIAG
grep -i "SCORE_DIAG" logs/empire_agent.log | tail -20

# 1k. trade_outcomes.csv
type data\trade_outcomes.csv

# 1l. tracked_positions.json
type data\tracked_positions.json

# 1m. Kill switch
type data\daily_loss_state.json

# 1n. Erreurs / Tracebacks
grep -i "Traceback\|Error\|Exception" logs/empire_agent.log | tail -20

# 1o. Config vérification
python -c "import yaml; c=yaml.safe_load(open('config/config.yaml')); print('hard_filters:', c.get('orchestrator',{}).get('hard_filters',{}))"
```

---

## PHASE 2 — MOMENTUM_CHECK ⭐⭐⭐ PRIORITÉ #1

### 2.1 — Comptage

Compter les occurrences de chaque type :
- `momentum OK` → trades autorisés par momentum
- `momentum INVERSE ... Trade BLOQUÉ` → trades bloqués (le filtre fait son travail)
- `momentum faible ... PASS` → momentum ambigu mais passé
- `données M5 indisponibles — PASS` → fail-open (pas de données)

### 2.2 — Tableau des trades bloqués

```
┌─────────┬─────────┬──────┬──────────────┬──────────────────────────────────┐
│ Heure   │ Symbole │ Dir  │ Confirm %    │ Net move                         │
├─────────┼─────────┼──────┼──────────────┼──────────────────────────────────┤
│         │         │      │              │                                  │
└─────────┴─────────┴──────┴──────────────┴──────────────────────────────────┘
```

### 2.3 — Évaluation qualité

Pour les trades qui PASSENT le filtre momentum et sont exécutés :
- Combien finissent en TP win vs SL ?
- Le momentum filter améliore-t-il le hit rate des trades autorisés ?

Comparaison :
```
┌─────────────────┬────────┬──────────┬──────────────┐
│ Catégorie       │ Trades │ TP wins  │ Hit rate     │
├─────────────────┼────────┼──────────┼──────────────┤
│ Pré-R15 (23/03) │ 9      │ 2        │ 22%          │
│ Post-R15 auj.   │        │          │              │
└─────────────────┴────────┴──────────┴──────────────┘
```

### 2.4 — Faux positifs potentiels

Si le filtre bloque > 60% des trades, c'est trop agressif. Vérifier si des trades bloqués auraient été gagnants (en regardant le mouvement de prix après le blocage — pas toujours possible, mais noter si le prix a fini par aller dans la direction bloquée).

---

## PHASE 3 — RISK_CAP INDICES ⭐⭐ PRIORITÉ #2

### 3.1 — Override actif ?

Chercher `point_val override indices` dans les logs :
- Si présent → le fix fonctionne
- Si absent et SP500/NAS100 tradés → le fix n'est PAS actif (problème de restart ?)

### 3.2 — Cap effectif ?

Pour chaque trade SP500/NAS100 :
- `point_val override indices = 1.0` → ✅
- `risque $X > max $300 → lots réduits` → ✅ cap effectif
- Combien de lots avant/après cap ?

### 3.3 — Comparaison avec le 23 mars

Le 23 mars, SP500 utilisait point_val=0.01 → risque non capé.
Aujourd'hui, vérifier que le lot sizing est contrôlé.

---

## PHASE 4 — ANTI-QUICK_REVERSAL ⭐⭐ PRIORITÉ #3

### 4.1 — Détections

Chercher `[QUICK_REVERSAL]` :
- Combien de SL en < 10 min détectés ?
- Quels symboles ? Quelle durée ?

### 4.2 — Cooldowns activés

Chercher `[COOLDOWN]` :
- Combien de trades bloqués par cooldown ?
- Combien de minutes restantes au moment du blocage ?

### 4.3 — Impact économique

Si des trades ont été bloqués par cooldown, auraient-ils été des SL ?
(Regarder le mouvement du prix pendant la période de cooldown)

Estimation : combien de $ économisés par le cooldown aujourd'hui ?

---

## PHASE 5 — P&L — LE TEST DÉCISIF

### 5.1 — Résultats des trades via trade_outcomes.csv

Pour chaque trade clos aujourd'hui :
```
┌────────────┬─────────┬──────────┬──────────┬──────────┬────────────┬───────────┬──────────────────┐
│ Ticket     │ Symbole │ Exit     │ P&L      │ R-mult   │ Durée min  │ RR fill   │ Note             │
├────────────┼─────────┼──────────┼──────────┼──────────┼────────────┼───────────┼──────────────────┤
│            │         │          │          │          │            │           │                  │
└────────────┴─────────┴──────────┴──────────┴──────────┴────────────┴───────────┴──────────────────┘
```

### 5.2 — Métriques de comparaison

```
┌──────────────┬────────┬───────────┬────────────┬───────────┬──────────────┬────────────────┐
│ Jour         │ Trades │ TP wins   │ Avg $/win  │ P&L net   │ Hit rate     │ QR losses      │
├──────────────┼────────┼───────────┼────────────┼───────────┼──────────────┼────────────────┤
│ 16 mars      │ 12     │ 5         │ $51/win    │ -$428     │ 67%          │ ?              │
│ 17 mars      │ 13     │ 8         │ $49/win    │ -$240     │ 62%          │ ?              │
│ 23 mars R14  │ 9      │ 2         │ $124/win   │ -$668     │ 22%          │ 3 (-$627)      │
│ Auj. R15     │        │           │            │           │              │                │
└──────────────┴────────┴───────────┴────────────┴───────────┴──────────────┴────────────────┘
```

**Cibles R15 :**
- Hit rate > 35% (vs 22% le 23 mars)
- 0 QUICK_REVERSAL (vs 3 le 23 mars)
- P&L net meilleur que -$668
- Avg $/win > $100 maintenu

---

## PHASE 6 — INFRASTRUCTURE

### 6.1 — Checks standards
- Event loop : 9/9 symboles ?
- Lock COM : 0 erreurs ?
- Kill switch : déclenché ? Si oui, à quelle heure et cause ?
- Tracebacks : 0 ?
- `regime_label` error : **doit être 0** (corrigé en `_regime_label`)

### 6.2 — Checks spécifiques R15
- retcode=10016 : combien de rejets MT5 ?
- Finnhub 403 : toujours présent ? (clé API expirée — info seulement)
- Erreurs dans le momentum check (MT5 data) : combien de fail-open ?

---

## FORMAT DU RAPPORT

```
═══════════════════════════════════════════════════════════════════
RAPPORT POST-ROUND 15 — [date/heure UTC]
═══════════════════════════════════════════════════════════════════

━━━ A. MOMENTUM_CHECK ⭐⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Trades autorisés (momentum OK)    : [N]
Trades bloqués (momentum INVERSE) : [N]
Trades passés (momentum faible)   : [N]
Fail-open (données manquantes)    : [N]
Taux de blocage : [N]% (cible 15-40%)

Trades bloqués :
┌─────────┬─────────┬──────┬──────────────┬──────────────┐
│ Heure   │ Symbole │ Dir  │ Confirm %    │ Net move     │
├─────────┼─────────┼──────┼──────────────┼──────────────┤
│         │         │      │              │              │
└─────────┴─────────┴──────┴──────────────┴──────────────┘

VERDICT MOMENTUM :
- ✅ Filtre efficace / ⚠️ Trop agressif (>50% bloqué) / ❌ Inactif

━━━ B. RISK_CAP INDICES ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Override actif (point_val=1.0) : [oui/non]
Symboles avec override         : [liste]
Cap $300 déclenché pour indices: [N] fois
Lots réduits (avant → après)   : [détails]

VERDICT RISK_CAP :
- ✅ Cap effectif / ❌ Override absent

━━━ C. ANTI-QUICK_REVERSAL ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

QUICK_REVERSAL détectés (SL < 10 min) : [N]
Cooldowns activés                      : [N]
Trades bloqués par cooldown            : [N]
$ économisés estimés                   : $[X]

Comparaison :
- 23 mars : 3 QR → -$627
- Aujourd'hui : [N] QR → -$[X]

VERDICT ANTI-QR :
- ✅ Protection active / ⚠️ Partiel / ❌ Aucun cooldown déclenché

━━━ D. P&L — TEST DÉCISIF ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Trades clos aujourd'hui : [N]
TP wins   : [N] → +$[total] (avg $[X]/win)
Trailing  : [N] → +$[total]
SL losses : [N] → -$[total]
BE        : [N] → -$[total]
P&L net   : $[total]

Comparaison :
┌──────────────┬────────┬───────────┬────────────┬───────────┬────────────┐
│ Jour         │ Trades │ Avg $/win │ P&L net    │ Hit rate  │ QR losses  │
├──────────────┼────────┼───────────┼────────────┼───────────┼────────────┤
│ 23 mars R14  │ 9      │ $124      │ -$668      │ 22%       │ -$627      │
│ Auj. R15     │        │           │            │           │            │
└──────────────┴────────┴───────────┴────────────┴───────────┴────────────┘

VERDICT P&L :
- ✅ Hit rate > 35% ET P&L amélioré → R15 fonctionne
- ⚠️ Hit rate amélioré mais P&L encore négatif → progrès partiel
- ❌ Hit rate < 25% → problème non résolu (investiguer les agents)

━━━ E. ENTRY_REFRESH (contrôle R14) ━━━━━━━━━━━━━━━━━━━━━━━━━━━

Nombre de [ENTRY_REFRESH] : [N]
R:R préservé : [oui/non]
Drift moyen  : [N]% du SL

━━━ F. HARD_FILTER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PASS : [N] | REJECT : [N] | Taux : [N]% (cible 40-70%)
Scores borderline .4f : [lister les cas 3.79xx observés]

━━━ G. INFRASTRUCTURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Event loop    : [OK/KO]
Lock COM      : [OK/KO]
Kill switch   : [oui/non]
regime_label  : [0 erreurs attendu]
Tracebacks    : [N]
retcode 10016 : [N]
Finnhub 403   : [oui/non]

━━━ H. BILAN ROUND 15 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────────────────────┬───────────┬──────────────────────────────────────────┐
│ Fix                          │ Statut    │ Preuve                                   │
├──────────────────────────────┼───────────┼──────────────────────────────────────────┤
│ R15 MOMENTUM_CHECK           │ ✅/❌/⚠️  │                                          │
│ R15 RISK_CAP indices         │ ✅/❌/⚠️  │                                          │
│ R15 Anti-QUICK_REVERSAL      │ ✅/❌/⚠️  │                                          │
│ R15 HARD_FILTER .4f          │ ✅/❌/⚠️  │                                          │
│ R15 [DECISION] log           │ ✅/❌/⚠️  │                                          │
│ R14 ENTRY_REFRESH            │ ✅/❌/⚠️  │                                          │
│ R14 DIR_CHECK                │ ✅/❌/⚠️  │                                          │
│ R13 HARD_FILTER 3.8          │ ✅/❌/⚠️  │                                          │
│ R12 Outcome tracker          │ ✅/❌/⚠️  │                                          │
│ regime_label fix             │ ✅/❌/⚠️  │                                          │
└──────────────────────────────┴───────────┴──────────────────────────────────────────┘

IMPACT R15 :
- Momentum : [N] trades bloqués → hit rate des autorisés = [X]%
- RISK_CAP indices : cap effectif [oui/non]
- Anti-QR : [N] cooldowns → $[X] économisés
- Hit rate global : [X]% (vs 22% le 23 mars)
- P&L net : $[X] (vs -$668 le 23 mars)

PROBLÈMES RESTANTS :
1. ...

RECOMMANDATIONS :
1. ...
```

## RÈGLES

1. **Ne modifie AUCUN fichier.** Lecture seule.
2. **MOMENTUM_CHECK, RISK_CAP indices, et ANTI-QR sont les 3 priorités** — c'est ce qui prouve le R15.
3. **Cite les lignes de log exactes.**
4. **Si aucun [MOMENTUM_CHECK]** dans les logs → le bot n'a pas été redémarré avec R15. Signale-le.
5. **Si aucun `point_val override`** pour SP500/NAS100 → le fix RISK_CAP n'est pas actif. Signale-le.
6. **Comparer IMPÉRATIVEMENT** avec le 23 mars : hit rate 22%, P&L -$668, 3 QR -$627.
7. **Vérifier que `regime_label` n'apparaît plus** dans les erreurs (doit être 0 traceback sur ce mot).
