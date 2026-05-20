# Monitoring post-Phase 2 — Validation push 8 commits locaux

**Date du rapport** : 2026-05-05 (UTC)
**Fenêtre d'analyse** : 2026-05-01 04:27 UTC → 2026-05-05 03:57 UTC (≈ 95h30)
**Note** : la consigne mentionnait « plus de 48h » ; la fenêtre réelle écoulée est ~95h, ce qui renforce la confiance des indicateurs.

---

## 1. Verdict global

**🟢 FEU VERT POUR PUSH** — les trois indicateurs sont PASS.

| Indicateur | Verdict |
|---|---|
| A — point_value par symbole tradé | **PASS** |
| B — HOUR_FILTER EXCEPTION = XAUUSD only | **PASS** |
| C — 0 exécution sur les 6 candidats shadow | **PASS** |

---

## 2. Indicateur A — Logs `[RISK_CAP]` et voie de calcul `point_val`

### Note méthodologique
Le pattern réel émis dans le log n'est pas `[RISK]` avec `via X` mais **`[RISK_CAP] {SYMBOL}: mode={mode} point_val={value}`**. La grep originale a été ajustée en conséquence. Le log est bien émis (36 occurrences sur toute la période).

### Symboles observés sur la fenêtre

| Symbole | Mode | point_val | Occurrences | Verdict |
|---|---|---|---|---|
| SP500 | `override_indices_USD` | **1.0** (était 0.01) | 4 | ✅ Conforme |
| NAS100 | `override_indices_USD` | **1.0** (était 0.01) | 6 | ✅ Conforme |
| XAUUSD | `MT5_native_tick_conversion` | **100.0** | 1 | ✅ Conforme |
| BTCUSD | `MT5_native_tick_conversion` | **0.01** | 2 | ✅ Conforme |
| AUDUSD | `MT5_native_tick_conversion` | **100000.0** | 3 | ✅ Conforme |
| LTCUSD | `MT5_native_tick_conversion` | **100.0** | 17 | ✅ Conforme (non listé dans le verdict attendu mais cohérent) |

### Symboles non observés (et pourquoi c'est normal)

`DJ30, UK100, GER40, USDCAD, GBPUSD, XAGUSD, EURUSD, USDJPY` n'apparaissent **jamais** dans `[RISK_CAP]` sur la fenêtre.

C'est cohérent avec le code : le log `[RISK_CAP]` n'est émis que **lorsqu'un trade est tenté**. Les 6 premiers sont en `auto_execute: false` (shadow mode → jamais d'exécution → jamais de log RISK_CAP). EURUSD/USDJPY n'ont simplement pas généré de signal exécutable sur la fenêtre.

### Anomalie critique recherchée
- ❌ Aucune occurrence de UK100 ou GER40 avec `mode=override_indices_USD` → **fix Commit `d727913` validé en négatif** (rien ne contredit le retrait du dict override).
- ❌ Aucune occurrence de DJ30/UK100/GER40 avec mode incorrect.

**Verdict A : ✅ PASS** — sur tous les symboles tradés, le mode et la valeur sont conformes au verdict attendu. Les 3 indices US (SP500/NAS100) utilisent bien `override_indices_USD=1.0` ; les autres utilisent `MT5_native_tick_conversion` avec des valeurs cohérentes.

---

## 3. Indicateur B — Logs `[HOUR_FILTER][EXCEPTION]`

### Décompte
- **144 occurrences totales** sur toute la fenêtre.
- **100 % sur XAUUSD**, **0 occurrence** pour tout autre symbole.

### Distribution par heure UTC

| Heure UTC | Occurrences |
|---|---|
| h7 | 47 |
| h10 | 38 |
| h11 | 31 |
| h12 | 2 |
| h13 | 6 |

Toutes ces heures appartiennent à `[7, 10, 11, 12, 13]` — strictement la blacklist globale `GLOBAL.blocked_hours_utc` que XAUUSD ré-autorise via `allowed_hours_utc` local.

### Distribution par jour
- 2026-05-01 : 78 occurrences (vendredi)
- 2026-05-04 : 66 occurrences (lundi)
- (week-end 02–03 : 0 — marchés clos, attendu)

### Anomalie critique recherchée
- ❌ Aucune occurrence pour un symbole autre que XAUUSD → **`BLACKLIST_OVERRIDE_WHITELIST = ["XAUUSD"]` correctement appliqué**.
- ❌ Aucune heure hors `[7, 10, 11, 12, 13]`.

**Verdict B : ✅ PASS** — l'exception XAUUSD nommée fonctionne exactement comme spécifié (Commit `de3d244`).

---

## 4. Indicateur C — Aucune exécution sur les 6 candidats shadow

### Lignes `trades_log.csv` filtrées sur la fenêtre

| Symbole shadow | Lignes trouvées |
|---|---|
| DJ30 | **0** |
| UK100 | **0** |
| GBPUSD | **0** |
| USDCAD | **0** |
| GER40 | **0** |
| XAGUSD | **0** |

### Symboles ayant trade sur la fenêtre (pour contexte)
LTCUSD (9), SP500 (4), NAS100 (2), BTCUSD (2), XAUUSD (1), AUDUSD (1) — **aucun** parmi les 6 candidats.

### Anomalies critiques recherchées
- ❌ Aucune ligne `ok=True` sur un candidat shadow → `auto_execute: false` respecté.
- ❌ Aucune ligne `ok=False` non plus → aucune tentative d'ordre rejetée par MT5.

**Verdict C : ✅ PASS** — la bascule shadow des 6 candidats (Commit `a10fca7`) est respectée à 100 %, aucune tentative d'envoi d'ordre.

---

## 5. Section bonus 1 — Volume de propositions shadow

Lecture `proposals_log.csv` filtré sur les 6 candidats, fenêtre 2026-05-01 04:27 → 2026-05-05.

| Symbole | # props | Score min | Score max | Score moyen | LONG | SHORT | Ratio L/S |
|---|---:|---:|---:|---:|---:|---:|---|
| UK100 | **801** | 2.50 | 11.10 | 4.29 | 648 | 153 | 4.24× LONG |
| GER40 | 763 | 2.50 | 10.10 | 5.80 | 544 | 219 | 2.48× LONG |
| DJ30 | 714 | 2.50 | 11.10 | 6.49 | 272 | 442 | 1.62× SHORT |
| GBPUSD | 665 | 2.50 | 10.10 | 5.14 | 373 | 292 | 1.28× LONG |
| USDCAD | 657 | 2.50 | 11.10 | 4.59 | 309 | 348 | 1.13× SHORT |
| XAGUSD | 637 | 2.50 | 10.10 | 4.90 | 318 | 319 | équilibré |
| **Total** | **4 237** | | | | **2 464** | **1 773** | |

### Heures dominantes (top 3 par symbole, occurrences ≥ 60 sur la fenêtre)
- **UK100** : très uniforme h08–h19, plateau ~60/h. Top : h08, h09, h10/h12/h14/h16/h17/h18/h19 (≈60).
- **GER40** : h06, h07, h13–h19 (≈59–60). Bas : h12 (17).
- **DJ30** : h07, h09, h10, h11, h12, h17 (≈60). Bas : h13 (21), h18 (28).
- **GBPUSD** : h08, h09, h10, h11, h12, h14 (≈60). Bas : h18 (27), h13 (30).
- **USDCAD** : h08, h09, h10, h11 (≈60). Bas : h18 (13), h13 (28).
- **XAGUSD** : h06, h10, h17 (≈60). Bas : h12 (16), h13 (22).

### Lecture
- **Tous les agents génèrent des signaux** sur les 6 candidats — la condition nécessaire pour la Directive 12 (analyse shadow à J+14) est remplie. Volume médian ~700 props/symbole sur ~96h = ~7/h, en cohérence avec un cycle d'analyse multi-minutes.
- **Asymétries notables à surveiller** : UK100 fortement biaisé LONG (4.24×) — cohérent avec un marché haussier ou avec un biais d'agent. DJ30 biaisé SHORT (1.62×) — divergence intéressante avec UK100/GER40.
- **Score moyen DJ30 (6.49)** est le plus élevé : signaux les plus confluents parmi les 6.

---

## 6. Section bonus 2 — Trades clos (P&L brut sur la fenêtre)

Source : `trade_outcomes.csv` filtré par `close_time` ≥ 2026-05-01T04:27.

| timestamp | symbol | dir | profit | exit | durée (min) |
|---|---|---|---:|---|---:|
| 2026-05-01T05:46:05 | SP500 | LONG | +11.44 | be | 420.1 |
| 2026-05-01T19:53:33 | SP500 | LONG | +11.84 | be | 420.2 |
| 2026-05-01T20:29:31 | XAUUSD | LONG | −116.40 | sl | 103.6 |
| 2026-05-01T21:02:52 | AUDUSD | LONG | −83.78 | sl | 172.8 |
| 2026-05-01T23:20:28 | SP500 | LONG | −24.06 | sl | 61.1 |
| 2026-05-01T23:30:13 | NAS100 | LONG | −15.10 | be | 318.5 |
| 2026-05-03T00:37:15 | BTCUSD | LONG | +50.57 | tp | 336.0 |
| 2026-05-04T13:03:42 | SP500 | LONG | −19.94 | sl | 21.7 |
| 2026-05-04T18:20:02 | NAS100 | LONG | −227.18 | sl | 9.6 |
| 2026-05-04T19:07:53 | SP500 | SHORT | +26.15 | tp | 47.95 |
| 2026-05-05T02:36:47 | BTCUSD | LONG | −79.00 | sl | 371.7 |

**P&L cumulé (≈95h)** : **−465.46 USD** sur 11 trades clos
**Hit-rate** : 4/11 = **36 %** (BE comptés en breakeven, exclus du hit)
**Pire trade** : NAS100 LONG du 2026-05-04 (−227.18, sl en 9.6 min)
**Trades ouverts non clos** (pm_state) : 3 (XAUUSD #858034226, SP500 #881715746, SP500 #894207203, tous en trail actif)

> Pas d'analyse approfondie demandée. À noter pour info : une perte rapide NAS100 −227 en <10 min mérite probablement un coup d'œil sur le SL initial. Hors scope de ce rapport.

---

## 7. Section bonus 3 — Santé technique

| Vérification | Valeur |
|---|---|
| Taille `logs/empire_agent.log` | **828 926 060 octets** (~790 MB) |
| Taille `logs/guards.log` | ~1.6 MB (44 lignes en mai) |
| Tracebacks Python sur la fenêtre 2026-05 | **0** |
| ERROR/CRITICAL sur la fenêtre 2026-05-01 → 05 | **17** (toutes API externes : `api.alternative.me/fng/`, `finnhub.io` — timeouts/SSL/502 transitoires, non bloquants) |
| Aucune erreur sur le code path trade/risk/orchestrator | ✅ |
| Activité Telegram (digest) | 181 lignes en mai, 57 envois confirmés, **0 erreur fallback en mai**. Premier digest émis à 06:00 le 01-05 avec 1 warning 404 isolé non critique. Pas de marqueur explicite `TG_PAUSE` / `circuit_telegram` trouvé dans les logs — le digest tourne nominalement. |
| Positions fantômes | `pm_state.json` = 3 positions trackées (XAUUSD, SP500×2). `open_positions.json` est un mapping vide par symbole (structure d'init, n'est pas la source de vérité runtime). **Comparaison avec MT5 réel impossible depuis cette session** (pas d'accès live MT5). À vérifier manuellement côté terminal MT5 si doute. |

### À noter
La taille du log empire_agent.log (~790 MB) approche d'un seuil où la rotation devrait être envisagée. Hors scope de ce push, mais à planifier.

---

## 8. Section bonus 4 — État Git

### `git log --oneline -12`
```
e706932 docs: ajout rapports d'analyse Phase 1 et 2 + script check_candidates_mt5
6951289 chore: ajustement profiles.yaml cohérence shadow mode BNBUSD/SOLUSD
49fbbac feat(orchestrator): blacklist horaire globale GLOBAL.blocked_hours_utc
eeb7ed9 feat(pm): consolidation Phase 1 — BE 1.5R + offset, partials 1.0R/1.8R, trailing 1.0R/0.4R
b10f728 config(bnbusd,solusd): bascule en shadow mode
a10fca7 feat(profiles): activation shadow mode des 6 candidats
de3d244 fix(orchestrator): blacklist horaire stricte avec exception XAUUSD nommée
d727913 fix(orchestrator): retrait UK100/GER40 du dict point_value override
6370cdb sync: mise à jour complète repo + données runtime 18-19 avril 2026
320cc89 sauvegarde complète R12-R18 + données runtime 16 avril 2026
0c26e84 data: mise à jour runtime 24 février 2026
90f1d62 fix(risk): corriger import mt5 manquant dans le floating P&L check
```

### `git rev-list --left-right --count origin/main...HEAD`
**`0	8`** — origin a 0 commits que local n'a pas, local a 8 commits que origin n'a pas. **Rien n'a été poussé**, conforme.

### `git status --short`
- **Working tree** : seuls fichiers modifiés sont dans `data/` runtime (deals_history, equity_log, latest_signals, loss_patterns, news_calendar_live, open_positions, performance/tracker_*, proposals_log, sentiment_cache/*, tracked_positions, trade_outcomes, trades_log, daily_loss_state, circuit_breaker_state) + `.claude/settings.local.json`.
- **Untracked** : 3 nouveaux caches sentiment apparus pendant la fenêtre (DJ30, GER40, USDCAD) — cohérent avec l'activation shadow de ces symboles.
- **Aucun fichier de code modifié** — clean.

✅ Les 8 commits locaux sont intacts, dans l'ordre attendu, et le working tree ne contient que du runtime data attendu.

---

## 9. Recommandation finale

**🟢 FEU VERT POUR PUSH des 8 commits locaux vers `origin/main`.**

Justification :
1. **Indicateur A PASS** : tous les symboles tradés utilisent le bon mode/`point_val`. SP500 et NAS100 sont bien en `override_indices_USD=1.0`. Aucun index non-US ne s'est retrouvé en override, validant le retrait UK100/GER40 du dict (Commit `d727913`).
2. **Indicateur B PASS** : 144/144 exceptions HOUR_FILTER concernent XAUUSD uniquement, sur les heures attendues. La whitelist nommée fonctionne (Commit `de3d244`).
3. **Indicateur C PASS** : 0 trade exécuté sur les 6 candidats shadow, aucune tentative rejetée par le broker. La bascule shadow (Commit `a10fca7`) est respectée à 100 %.
4. **Volume shadow sain** : 4 237 propositions générées sur les 6 candidats sur ~95h. La Directive 12 (analyse shadow à J+14) aura suffisamment de matière.
5. **Aucun crash, aucun Traceback** sur la fenêtre. Erreurs ERROR/CRITICAL toutes sur APIs externes non-critiques (FNG/Finnhub).
6. **Working tree clean côté code**, seuls fichiers runtime data modifiés (attendus).

### Points d'attention non bloquants (hors scope de ce push)
- Log `empire_agent.log` à ~790 MB → planifier une rotation.
- NAS100 LONG du 2026-05-04 a sauté le SL en <10 min pour −227 USD : à inspecter au prochain debrief, hors scope ici.
- Aucun moyen de comparer `pm_state.json` (3 positions trackées) à MT5 live depuis cette session : vérification manuelle côté terminal recommandée avant le push si doute.

### Action recommandée
Push standard `git push origin main` — aucun ajustement préalable nécessaire.

---
*Rapport généré en lecture seule. Aucun fichier de code, config ou data n'a été modifié.*
