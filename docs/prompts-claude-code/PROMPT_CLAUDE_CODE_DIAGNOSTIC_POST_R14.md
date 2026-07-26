# PROMPT CLAUDE CODE — Diagnostic post-Round 14

## Contexte

Round 14 a ajouté le fix le plus impactant de la série R3-R14 :
- R14 FIX 1 : **ENTRY_REFRESH** — recalcule SL/TP sur le prix actuel avant place_order, en préservant les distances. Résout le problème d'entry stale identifié par les logs [TP_TRACE] du R13.
- R14 FIX 1b : **DIR_CHECK** — bloque les trades avec SL/TP incohérents directionnellement (protège contre le cas SP500#1 du 17 mars).
- R14 FIX 2 : **RISK_CAP fallback indices** — utilise contract_size × point quand tick_size/tick_value = 0 (SP500, NAS100).

**Objectif** : Vérifier que le R:R est préservé au fill et que le P&L est transformé. Aucun fichier ne doit être modifié.

---

## PHASE 1 — Collecte des données

```bash
# 1a. Dernières 3000 lignes du log
tail -n 3000 logs/empire_agent.log

# 1b. ENTRY_REFRESH — LE LOG CLÉ R14
grep -i "ENTRY_REFRESH" logs/empire_agent.log

# 1c. DIR_CHECK — trades bloqués pour incohérence
grep -i "DIR_CHECK" logs/empire_agent.log

# 1d. TP_TRACE — valeurs AVANT recalcul
grep -i "TP_TRACE" logs/empire_agent.log

# 1e. MIN_STOPS — modifications par _respect_min_stops
grep -i "MIN_STOPS" logs/empire_agent.log

# 1f. RR_SAFETY + RR_FIX
grep -i "RR_SAFETY\|RR_FIX" logs/empire_agent.log | tail -20

# 1g. RISK_CAP — cap de risque + fallback indices
grep -i "RISK_CAP" logs/empire_agent.log

# 1h. Outcome tracker
grep -i "\[OUTCOME\]" logs/empire_agent.log | tail -30

# 1i. HARD_FILTER
grep -i "HARD_FILTER" logs/empire_agent.log | tail -20

# 1j. Trades exécutés
grep -i "order_send\|retcode\|ticket=" logs/empire_agent.log | tail -20

# 1k. trade_outcomes.csv
type data\trade_outcomes.csv

# 1l. tracked_positions.json
type data\tracked_positions.json

# 1m. Kill switch
type data\daily_loss_state.json

# 1n. Config
python -c "import yaml; c=yaml.safe_load(open('config/config.yaml')); print('hard_filters:', c.get('orchestrator',{}).get('hard_filters',{}))"
```

---

## PHASE 2 — ENTRY_REFRESH ⭐⭐ PRIORITÉ ABSOLUE

### 2.1 — Format attendu du log [ENTRY_REFRESH]

```
[ENTRY_REFRESH] SYMBOL ACTION: prix drifté de X pts (Y% du SL). Entry A→B | SL C→D | TP E→F | R:R préservé Z
```

### 2.2 — Pour CHAQUE ligne [ENTRY_REFRESH], analyser :

1. **Drift en pts** : magnitude du mouvement de prix entre l'analyse et l'exécution
2. **Drift en % du SL** : si > 50%, le marché a bougé significativement
3. **R:R préservé** : doit être identique au R:R original (celui des agents)
4. **Direction correcte** :
   - BUY : SL < entry < TP
   - SELL : TP < entry < SL

### 2.3 — Comparaison AVANT/APRÈS ENTRY_REFRESH

Pour chaque trade, combiner [TP_TRACE] (AVANT) et [ENTRY_REFRESH] (APRÈS) :

```
┌───────┬─────────┬──────┬──────────────────────────┬──────────────────────────┬──────────┬──────────────┐
│ Heure │ Symbole │ Dir  │ AVANT (TP_TRACE)         │ APRÈS (ENTRY_REFRESH)    │ Drift    │ RR préservé? │
│       │         │      │ entry / sl / tp / rr      │ entry / sl / tp          │          │              │
├───────┼─────────┼──────┼──────────────────────────┼──────────────────────────┼──────────┼──────────────┤
│       │         │      │                          │                          │          │              │
└───────┴─────────┴──────┴──────────────────────────┴──────────────────────────┴──────────┴──────────────┘
```

### 2.4 — Cas où ENTRY_REFRESH ne se déclenche PAS

Si un trade a un [TP_TRACE] mais pas de [ENTRY_REFRESH] :
- Le drift était < 10% du SL → pas de recalcul (normal)
- Vérifier dans le [TP_TRACE] que `rr_final` est correct malgré tout

---

## PHASE 3 — DIR_CHECK

### 3.1 — Trades bloqués
Chercher `[DIR_CHECK]` :
- Si présent → un trade incohérent a été bloqué. Combien ?
- Si absent → tous les trades étaient cohérents directionnellement (OK)

---

## PHASE 4 — P&L — LE TEST DÉCISIF

### 4.1 — Résultats des trades via trade_outcomes.csv

Pour chaque trade clos aujourd'hui :
```
┌────────────┬─────────┬──────┬──────────┬──────────┬────────────┬───────────┬───────┐
│ Ticket     │ Symbole │ Exit │ P&L      │ R-mult   │ Durée min  │ RR fill   │ Note  │
├────────────┼─────────┼──────┼──────────┼──────────┼────────────┼───────────┼───────┤
│            │         │      │          │          │            │           │       │
└────────────┴─────────┴──────┴──────────┴──────────┴────────────┴───────────┴───────┘
```

### 4.2 — Métriques de comparaison

Comparer avec les jours précédents :

```
┌──────────┬────────┬───────────┬────────────┬───────────┬──────────────┐
│ Jour     │ Trades │ TP wins   │ Avg $/win  │ P&L net   │ Hit rate     │
├──────────┼────────┼───────────┼────────────┼───────────┼──────────────┤
│ 16 mars  │ 8      │ 5         │ $51/win    │ -$428     │ 63%          │
│ 17 mars  │ 13     │ 8         │ $49/win    │ -$240     │ 62%          │
│ Auj R14  │ ?      │ ?         │ ?/win      │ ?         │ ?            │
└──────────┴────────┴───────────┴────────────┴───────────┴──────────────┘
```

**Cible R14** : Avg $/win > $100 (au lieu de ~$49)

---

## PHASE 5 — RISK_CAP + fallback indices

### 5.1 — Logs [RISK_CAP]
- `point_val fallback via contract_size` → fallback actif pour SP500/NAS100
- `point_val=1.0 (défaut)` → fallback N'A PAS fonctionné (vérifier pourquoi)
- `risque $X > max $300 → lots réduits` → cap activé normalement

---

## PHASE 6 — Outcome Tracker (contrôle continu)

### 6.1 — Clôtures enregistrées
- `[OUTCOME] Trade cloture` : combien aujourd'hui ?
- `trade_outcomes.csv` : combien d'entrées total ?

### 6.2 — Réconciliation (si restart)
- `[OUTCOME] Réconciliation` : clôtures récupérées au démarrage ?

---

## PHASE 7 — HARD_FILTER

### 7.1 — Taux de rejet avec min_score=3.8
- PASS : [N] | REJECT : [N] | Taux : [N]%
- Cible : 40-70%

---

## PHASE 8 — Infrastructure

- Event loop : 9/9 symboles ?
- Lock COM : 0 erreurs ?
- Kill switch : déclenché ? Si oui, à quelle heure et cause ?
- Tracebacks : 0 ?

---

## FORMAT DU RAPPORT

```
═══════════════════════════════════════════════════════════════════
RAPPORT POST-ROUND 14 — [date/heure UTC]
═══════════════════════════════════════════════════════════════════

━━━ A. ENTRY_REFRESH ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Nombre de [ENTRY_REFRESH] : [N]
Nombre de [DIR_CHECK] bloqués : [N]

Analyse par trade :
┌───────┬─────────┬──────┬────────────┬────────────┬──────────┬──────────────┐
│ Heure │ Symbole │ Dir  │ Drift pts  │ Drift %SL  │ RR avant │ RR préservé  │
├───────┼─────────┼──────┼────────────┼────────────┼──────────┼──────────────┤
│       │         │      │            │            │          │              │
└───────┴─────────┴──────┴────────────┴────────────┴──────────┴──────────────┘

VERDICT ENTRY_REFRESH :
- ✅ Fonctionne parfaitement / ⚠️ Partiel / ❌ Ne fonctionne pas
- R:R est préservé au fill : oui/non
- Cas bloqués par DIR_CHECK : [N]

━━━ B. P&L — TEST DÉCISIF ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Trades clos aujourd'hui : [N]
TP wins  : [N] → $[total] (avg $[X]/win)
SL loss  : [N] → -$[total]
BE       : [N] → -$[total]
P&L net  : $[total]

Comparaison :
┌──────────┬────────┬───────────┬────────────┬───────────┐
│ Jour     │ Trades │ Avg $/win │ P&L net    │ Hit rate  │
├──────────┼────────┼───────────┼────────────┼───────────┤
│ 17 mars  │ 13     │ $49/win   │ -$240      │ 62%       │
│ Auj R14  │        │           │            │           │
└──────────┴────────┴───────────┴────────────┴───────────┘

VERDICT P&L :
- ✅ Avg $/win > $100 → ENTRY_REFRESH transforme le P&L
- ⚠️ Avg $/win $50-$100 → Amélioration partielle
- ❌ Avg $/win < $50 → ENTRY_REFRESH n'a pas d'effet (investiguer)

━━━ C. RISK_CAP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Fallback indices (contract_size) : actif/inactif
point_val=1.0 (défaut)          : [N] fois
Cap activé                      : [N] fois

━━━ D. OUTCOME TRACKER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Clôtures aujourd'hui     : [N]
trade_outcomes.csv total : [N] entrées

━━━ E. HARD_FILTER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PASS : [N] | REJECT : [N] | Taux : [N]% (cible 40-70%)

━━━ F. INFRASTRUCTURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Event loop : [OK/KO] | Lock COM : [OK/KO] | Kill switch : [oui/non]

━━━ G. BILAN ROUND 14 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────────────────┬───────────┬──────────────────────────────┐
│ Fix                      │ Statut    │ Preuve                       │
├──────────────────────────┼───────────┼──────────────────────────────┤
│ R14 ENTRY_REFRESH        │ ✅/❌/⚠️  │                              │
│ R14 DIR_CHECK            │ ✅/❌/⚠️  │                              │
│ R14 RISK_CAP fallback    │ ✅/❌/⚠️  │                              │
│ R13 HARD_FILTER 3.8      │ ✅/❌/⚠️  │                              │
│ R12 Outcome tracker      │ ✅/❌/⚠️  │                              │
└──────────────────────────┴───────────┴──────────────────────────────┘

IMPACT P&L :
- Avg $/win AVANT R14 : ~$49
- Avg $/win APRÈS R14 : $[X]
- Amélioration : [X]%
- Manque à gagner récupéré : $[X] estimé

PROBLÈMES RESTANTS :
1. ...

RECOMMANDATIONS :
1. ...
```

## RÈGLES

1. **Ne modifie AUCUN fichier.** Lecture seule.
2. **[ENTRY_REFRESH] et P&L sont les 2 priorités** — c'est ce qui prouve le fix R14.
3. **Cite les lignes de log exactes.**
4. **Si aucun [ENTRY_REFRESH]** dans les logs → le bot n'a pas été redémarré avec R14. Signale-le.
5. **Comparer IMPÉRATIVEMENT** le avg $/win avec les jours précédents (~$49).
