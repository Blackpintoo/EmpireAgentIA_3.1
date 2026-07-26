# PROMPT CLAUDE CODE — Fix MT5 COM Freeze + Trading Windows Crypto

## Contexte
Le monitoring post-restart montre que les agents MT5 fonctionnent pendant 3-5 minutes puis le COM se gèle complètement (47 104 timeouts cumulés). Cause racine identifiée :

- 9 orchestrateurs créent chacun un `MT5Client()` mais partagent la MÊME connexion COM mono-thread
- Chaque orchestrateur exécute ses 4 agents MT5 séquentiellement (fix précédent), mais les 9 orchestrateurs tournent INDÉPENDAMMENT les uns des autres
- Avec un cycle de 60s et un stagger de 0-56s, plusieurs orchestrateurs peuvent chevaucher leurs appels MT5
- Après quelques cycles, le COM se deadlock et TOUT gèle

De plus, les trading windows crypto sont trop restrictives (LTCUSD: 3h/jour, SOLUSD: 2h/jour).

## Corrections à appliquer (6 fixes)

---

### FIX 1 — CRITIQUE : Verrou global asyncio inter-orchestrateurs pour MT5

**Fichier** : `orchestrator/orchestrator.py`

**Action A** : Ajouter un sémaphore asyncio global au niveau module (près des imports, vers ligne 635-642 où sont déjà les `_ORCH_LOCKS`) :

```python
# ================================================================
# FIX 2026-03-08: Verrou GLOBAL inter-orchestrateurs pour MT5 COM
# Le COM MT5 est mono-thread : un seul orchestrateur peut l'utiliser à la fois
# asyncio.Semaphore(1) = un seul coroutine à la fois, les autres await sans bloquer
# ================================================================
import asyncio as _aio_mod
_GLOBAL_MT5_SEMAPHORE = _aio_mod.Semaphore(1)
```

**Action B** : Modifier la section d'exécution des agents MT5 (vers lignes 4345-4393, le bloc avec le commentaire `FIX 2026-03-06: Exécution séquentielle des agents MT5`). Envelopper UNIQUEMENT l'exécution des agents MT5 dans le sémaphore global :

```python
# ================================================================
# FIX 2026-03-08: Verrou global — un seul orchestrateur accède au COM à la fois
# ================================================================
async with _GLOBAL_MT5_SEMAPHORE:
    # 1) Agents MT5 séquentiellement (évite saturation COM)
    mt5_results = []
    for name, fn in mt5_agents:
        result = await _run_with_timeout(name, fn)
        mt5_results.append(result)

# 2) Agents API en parallèle HORS du sémaphore (pas de contrainte mono-thread)
api_results = await asyncio.gather(
    *[_run_with_timeout(name, fn) for name, fn in api_agents],
    return_exceptions=True,
)
```

**Important** : Les agents API (whale, news, sentiment, fundamental, macro) doivent rester HORS du `async with _GLOBAL_MT5_SEMAPHORE` pour ne pas être bloqués pendant que d'autres orchestrateurs utilisent MT5.

---

### FIX 2 — Auto-reconnect MT5 après détection de freeze

**Fichier** : `orchestrator/orchestrator.py`

**Action** : Après l'exécution des agents MT5 (juste après la boucle séquentielle, toujours dans le `async with`), ajouter une détection de freeze et auto-reconnect :

```python
async with _GLOBAL_MT5_SEMAPHORE:
    mt5_results = []
    for name, fn in mt5_agents:
        result = await _run_with_timeout(name, fn)
        mt5_results.append(result)

    # FIX 2026-03-08: Détection freeze MT5 + auto-reconnect
    _mt5_all_failed = all(
        r is None or (isinstance(r, dict) and r.get("score") in (None, 0, 0.0))
        for r in mt5_results
    )
    if _mt5_all_failed and len(mt5_results) >= 2:
        logger.warning(f"[MT5_HEALTH] {self.symbol} — Tous les agents MT5 ont échoué, tentative reconnexion COM")
        try:
            from utils.mt5_client import MT5Client as _MC
            _MC.shutdown_if_needed()
            await asyncio.sleep(3)
            _MC.initialize_if_needed(force=True)
            logger.info(f"[MT5_HEALTH] {self.symbol} — Reconnexion MT5 réussie")
        except Exception as _re:
            logger.error(f"[MT5_HEALTH] {self.symbol} — Reconnexion échouée: {_re}")
```

**Important** : Le reconnect doit être DANS le sémaphore pour éviter que d'autres orchestrateurs n'appellent MT5 pendant le restart.

---

### FIX 3 — Augmenter l'intervalle de cycle à 120 secondes

**Fichier** : `config/config.yaml`

**Action** : Dans la section `orchestrator.timeframes`, changer l'intervalle principal :
```yaml
# AVANT :
orchestrator: 60
# APRÈS :
orchestrator: 120
```

**Fichier** : `config/overrides.yaml`

**Action** : Chercher TOUTES les entrées `orchestrator:` ou `interval_secs:` dans les sections par symbole et les changer de 60 à 120. Cela concerne au minimum :
- BTCUSD (ligne ~101) : `orchestrator: 60` → `orchestrator: 120`
- LTCUSD (ligne ~256) : `interval_secs: 60` → `interval_secs: 120`
- Tout autre symbole ayant une valeur explicite < 120

**Raisonnement** : Avec 9 symboles, un cycle de 60s et un sémaphore qui sérialise les accès MT5, chaque orchestrateur n'aurait que ~6.6s pour ses 4 agents MT5 séquentiels (60s / 9). C'est trop serré. Avec 120s, chaque orchestrateur a ~13s, ce qui est confortable avec le timeout de 45s par agent.

---

### FIX 4 — Supprimer les restrictions d'heures sur les crypto

Les crypto se tradent 24/7. Les `allowed_hours_utc` et `trading_window` sessions restrictives font perdre des opportunités.

**Fichier** : `config/overrides.yaml`

**Action pour LTCUSD** :
```yaml
# AVANT :
allowed_hours_utc: [8, 18, 22]   # Seulement 3 heures par jour !
trading_window:
  enabled: true
  sessions:
    - start: "10:00"
      end: "12:00"
    - start: "15:00"
      end: "17:00"
# APRÈS :
allowed_hours_utc: []              # Vide = toutes les heures autorisées
trading_window:
  enabled: false                   # Désactivé — crypto 24/7
```

**Action pour SOLUSD** :
```yaml
# AVANT :
allowed_hours_utc: [13, 23]       # Seulement 2 heures par jour !
# APRÈS :
allowed_hours_utc: []              # Vide = toutes les heures autorisées
```

**Action pour BTCUSD** : Vérifier s'il y a des `blocked_hours` trop restrictifs. Si `blocked_hours: [16, 17, 18, 20, 22]` existe, le réduire :
```yaml
# AVANT :
blocked_hours: [16, 17, 18, 20, 22]   # 5 heures bloquées
# APRÈS :
blocked_hours: [3, 4, 5]               # Seulement les heures mortes (3-5 UTC)
```

**Action pour BNBUSD** : Vérifier et élargir :
```yaml
# AVANT (si présent) :
blocked_hours: [0, 1, 2, 3, 4, 5, 18, 19, 20, 21, 22, 23]
# APRÈS :
blocked_hours: [3, 4, 5]               # Seulement les heures mortes
```

**Vérification** : Rechercher dans TOUT le fichier overrides.yaml les occurrences de `allowed_hours`, `blocked_hours`, et `trading_window` pour les 4 crypto (BTCUSD, LTCUSD, BNBUSD, SOLUSD) et s'assurer qu'aucune restriction excessive ne reste.

---

### FIX 5 — Corriger LTCUSD min_confluence oublié

**Fichier** : `config/overrides.yaml`

**Action** : À la ligne ~174, corriger :
```yaml
# AVANT :
min_confluence: 3.0
# APRÈS :
min_confluence: 2.0
```

---

### FIX 6 — Vérifier la gestion des allowed_hours vides dans le code Python

**Fichier** : `orchestrator/orchestrator.py`

**Action** : Chercher le code du HOUR_FILTER (qui bloque les trades hors `allowed_hours_utc`). Vérifier que quand `allowed_hours_utc` est une liste vide `[]`, le filtre laisse passer (= toutes les heures autorisées). Si le code traite `[]` comme "aucune heure autorisée" (ce qui bloquerait tout), corriger la logique :

```python
# Chercher quelque chose comme :
allowed = self.cfg.get("allowed_hours_utc", [])
if allowed and current_hour not in allowed:
    # Bloquer
    ...

# S'assurer que "if allowed" est bien présent (liste vide = pas de restriction)
# Si le code est : "if current_hour not in allowed:" sans vérifier si allowed est vide,
# alors une liste vide bloquerait TOUT. Il faut corriger en ajoutant "if allowed and ..."
```

---

## Résumé des modifications

| # | Fichier | Modification | Impact |
|---|---------|-------------|--------|
| 1 | orchestrator.py | `_GLOBAL_MT5_SEMAPHORE = asyncio.Semaphore(1)` + `async with` autour des agents MT5 | Un seul orchestrateur accède au COM à la fois → plus de freeze |
| 2 | orchestrator.py | Auto-reconnect MT5 si tous les agents échouent | Récupération automatique après un freeze |
| 3 | config.yaml + overrides.yaml | Cycle 60s → 120s | Laisse assez de temps pour 9 orchestrateurs sérialisés |
| 4 | overrides.yaml | Crypto: `allowed_hours: []`, `trading_window: false`, `blocked_hours: [3,4,5]` | LTCUSD passe de 3h/jour à 21h/jour, SOLUSD de 2h à 21h |
| 5 | overrides.yaml | LTCUSD `min_confluence: 3.0` → `2.0` | Alignement avec les autres symboles |
| 6 | orchestrator.py | Vérifier `if allowed and hour not in allowed` | Évite que `allowed_hours: []` bloque tout |

## Impact attendu
- MT5 COM ne gèlera plus grâce au sémaphore global (1 seul accès à la fois)
- Si un freeze survient malgré tout, l'auto-reconnect relance la connexion
- Les crypto peuvent trader ~21h/jour au lieu de 2-3h
- LTCUSD n'est plus bloqué par min_confluence=3.0

## Après les modifications
1. Redémarrer le bot via START_EMPIRE.bat
2. Attendre **10 minutes** (cycles de 120s maintenant)
3. Vérifier dans les logs :
   - `[MT5_HEALTH]` n'apparaît PAS (= le COM ne gèle plus)
   - Les agents MT5 répondent cycle après cycle sans interruption
   - LTCUSD et SOLUSD génèrent des signaux même hors des anciennes heures restreintes
   - Des `[HARD_FILTER] PASS` apparaissent, suivis de trades exécutés
