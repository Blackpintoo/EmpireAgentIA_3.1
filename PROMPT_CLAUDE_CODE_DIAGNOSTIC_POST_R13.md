# PROMPT CLAUDE CODE — Diagnostic post-Round 13

## Contexte

Round 13 a ajouté :
- R13 FIX 1 : Logs diagnostiques `[TP_TRACE]` et `[MIN_STOPS]` pour tracer le TP de bout en bout
- R13 FIX 2 : RISK_CAP — log erreur symbol_info + fallback crypto si point_val inconnu
- R13 FIX 3 : HARD_FILTER min_score 3.5 → 3.8

Le problème #1 à diagnostiquer : **les TP aberrants** (0.5-1 point de l'entry malgré les corrections RR_FIX et RR_SAFETY).

**Objectif** : Utiliser les logs `[TP_TRACE]` pour identifier exactement OÙ le TP est détruit. Aucun fichier ne doit être modifié.

---

## PHASE 1 — Collecte des données

```bash
# 1a. Dernières 3000 lignes du log
tail -n 3000 logs/empire_agent.log

# 1b. TP_TRACE — LE LOG CLÉ
grep -i "TP_TRACE" logs/empire_agent.log

# 1c. MIN_STOPS — modifications par _respect_min_stops
grep -i "MIN_STOPS" logs/empire_agent.log

# 1d. RR_SAFETY — corrections de RR
grep -i "RR_SAFETY" logs/empire_agent.log

# 1e. RR_FIX — corrections ATR dans les agents
grep -i "RR_FIX\|rr_fix" logs/empire_agent.log | tail -20

# 1f. RISK_CAP — cap de risque
grep -i "RISK_CAP" logs/empire_agent.log

# 1g. Outcome tracker
grep -i "\[OUTCOME\]" logs/empire_agent.log | tail -30

# 1h. HARD_FILTER stats
grep -i "HARD_FILTER" logs/empire_agent.log | tail -20

# 1i. Trades exécutés
grep -i "order_send\|retcode\|ticket=" logs/empire_agent.log | tail -20

# 1j. trade_outcomes.csv
type data\trade_outcomes.csv

# 1k. tracked_positions.json
type data\tracked_positions.json

# 1l. Kill switch
type data\daily_loss_state.json

# 1m. Config active
python -c "import yaml; c=yaml.safe_load(open('config/config.yaml')); print('hard_filters:', c.get('orchestrator',{}).get('hard_filters',{}))"
```

---

## PHASE 2 — Analyse TP_TRACE ⭐⭐ PRIORITÉ ABSOLUE

### 2.1 — Format attendu du log [TP_TRACE]

```
[TP_TRACE] SYMBOL ACTION: entry=X, sl=X, tp=X, lots=X, proposal_tp=X, rr_final=X
```

### 2.2 — Pour CHAQUE ligne [TP_TRACE], analyser :

1. **`rr_final`** : C'est le R:R du TP au moment de l'envoi à `place_order`.
   - Si `rr_final > 0.80` : le TP est correct AVANT place_order → problème dans `place_order` ou `_respect_min_stops`
   - Si `rr_final < 0.30` : le TP est déjà aberrant AVANT place_order → problème dans RR_SAFETY ou Composite

2. **`tp` vs `proposal_tp`** :
   - Si `tp == proposal_tp` : RR_SAFETY n'a PAS modifié le TP (soit pas déclenché, soit exception)
   - Si `tp != proposal_tp` : RR_SAFETY a corrigé le TP → la correction fonctionne

3. **Cohérence entry/sl/tp** :
   - Pour BUY : tp > entry > sl (normal)
   - Pour SELL : sl > entry > tp (normal)
   - Si tp ≈ entry (< 5 points pour indices, < 100 points pour crypto) → TP ABERRANT

### 2.3 — Tableau d'analyse

Pour chaque trade, remplir :

```
┌───────┬─────────┬──────┬──────────┬──────────┬──────────┬──────────────┬──────────┬────────────┐
│ Heure │ Symbole │ Dir  │ Entry    │ SL       │ TP trace │ Proposal TP  │ RR final │ Diagnostic │
├───────┼─────────┼──────┼──────────┼──────────┼──────────┼──────────────┼──────────┼────────────┤
│       │         │      │          │          │          │              │          │            │
└───────┴─────────┴──────┴──────────┴──────────┴──────────┴──────────────┴──────────┴────────────┘
```

Diagnostic possible pour chaque trade :
- **TP_OK** : rr_final > 0.80 et tp loin de entry
- **TP_ABERRANT_PRE_SAFETY** : rr_final < 0.30 et tp == proposal_tp (RR_SAFETY n'a pas corrigé)
- **TP_ABERRANT_POST_SAFETY** : rr_final > 0.80 mais le trade final dans MT5 a un TP proche de entry (problème dans place_order)
- **TP_ABERRANT_COMPOSITE** : tp != proposal_tp mais rr_final < 0.30 (Composite a écrasé un bon TP, RR_SAFETY a raté la correction)

---

## PHASE 3 — Analyse MIN_STOPS

### 3.1 — Lignes [MIN_STOPS]

Si des lignes `[MIN_STOPS]` existent :
- `TP modifié par _respect_min_stops: X → Y` → noter le changement
- Si Y < X : `_respect_min_stops` RÉDUIT le TP → c'est le coupable
- Si Y > X : `_respect_min_stops` POUSSE le TP plus loin → c'est normal

### 3.2 — Si aucune ligne [MIN_STOPS]
→ `_respect_min_stops` ne modifie pas le TP → le problème est AVANT place_order

---

## PHASE 4 — RR_SAFETY et RR_FIX

### 4.1 — RR_SAFETY
Compter les corrections `[RR_SAFETY]` :
- `R:R X < Y → TP corrigé` → combien de corrections ?
- `R:R TOUJOURS ABERRANT → TRADE BLOQUÉ` → combien de trades bloqués ?
- `Erreur guard` → combien d'exceptions ? (étaient silencieuses avant R12)

### 4.2 — RR_FIX
Compter les corrections `[RR_FIX]` :
- Combien de corrections ATR ?
- Sur quels symboles ?

---

## PHASE 5 — RISK_CAP

### 5.1 — Logs [RISK_CAP]
- `point_val=1.0 (défaut)` → symbol_info a échoué, point_value inconnu
- `forçage cap` → fallback crypto activé
- `risque $X > max $300 → lots réduits` → cap normal activé

---

## PHASE 6 — Outcome Tracker (vérification continue)

### 6.1 — Clôtures enregistrées ?
Compter `[OUTCOME] Trade cloture` :
- Combien aujourd'hui ?
- Tous via "méthode position=" ?

### 6.2 — trade_outcomes.csv
- Combien de nouvelles entrées depuis le dernier diagnostic ?

---

## PHASE 7 — HARD_FILTER

### 7.1 — Taux de rejet avec min_score=3.8
- PASS : [N] | REJECT : [N] | Taux : [N]%
- Cible : 40-70%

---

## PHASE 8 — Infrastructure rapide

- Event loop : 9/9 symboles ?
- Lock COM : 0 erreurs ?
- Kill switch : déclenché ?
- Tracebacks : 0 ?
- Finnhub : `[FINNHUB] désactivé pour 1h` ? (R11)
- F&G backoff : stable ? (R11)
- PM partial : limiter actif ? (R11)

---

## FORMAT DU RAPPORT

```
═══════════════════════════════════════════════════════════════════
RAPPORT POST-ROUND 13 — [date/heure UTC]
═══════════════════════════════════════════════════════════════════

━━━ A. TP_TRACE — DIAGNOSTIC TP ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━

Nombre de [TP_TRACE] : [N]
Nombre de [MIN_STOPS] : [N]

Analyse par trade :
┌───────┬─────────┬──────┬──────────┬──────────┬──────────┬──────────────┬──────────┬────────────┐
│ Heure │ Symbole │ Dir  │ Entry    │ SL       │ TP trace │ Proposal TP  │ RR final │ Diagnostic │
├───────┼─────────┼──────┼──────────┼──────────┼──────────┼──────────────┼──────────┼────────────┤
│       │         │      │          │          │          │              │          │            │
└───────┴─────────┴──────┴──────────┴──────────┴──────────┴──────────────┴──────────┴────────────┘

CONCLUSION TP :
- Le TP est aberrant AVANT / APRÈS place_order
- Le problème vient de : [RR_SAFETY / Composite / _respect_min_stops / autre]
- [détail du problème]

━━━ B. RR_SAFETY + RR_FIX ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RR_SAFETY corrections : [N] | Trades bloqués : [N] | Exceptions : [N]
RR_FIX corrections ATR : [N]

━━━ C. RISK_CAP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[RISK_CAP] activations : [N]
point_val=1.0 (défaut) : [N] fois
Forçage cap crypto     : [N] fois

━━━ D. OUTCOME TRACKER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Clôtures aujourd'hui    : [N]
trade_outcomes.csv total: [N] entrées

━━━ E. HARD_FILTER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PASS : [N] | REJECT : [N] | Taux : [N]% (cible 40-70%)

━━━ F. INFRASTRUCTURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Event loop : [OK/KO] | Lock COM : [OK/KO] | Kill switch : [oui/non]

━━━ G. BILAN ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DIAGNOSTIC TP FINAL :
Le problème des TP aberrants est causé par : [CONCLUSION]
Preuve : [lignes de log exactes]
Recommandation : [fix à appliquer]
```

## RÈGLES

1. **Ne modifie AUCUN fichier.** Lecture seule.
2. **[TP_TRACE] est la priorité absolue** — c'est le log qui va résoudre le mystère des TP.
3. **Cite les lignes de log exactes** pour chaque conclusion.
4. **Si aucun [TP_TRACE]** dans les logs → le bot n'a pas encore été redémarré avec R13. Signale-le.
5. **Si [TP_TRACE] montre rr_final > 0.80** mais les trades dans MT5 ont des TP aberrants → le problème est dans place_order et il faut investiguer _respect_min_stops en détail.
