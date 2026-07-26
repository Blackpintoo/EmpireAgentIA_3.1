# PROMPT CLAUDE CODE — Fix EventGuard Deadlock (Round 7)

## Cause racine

Le bot gèle **à chaque fois** qu'un symbole passe le HARD_FILTER (PASS) parce que `execute_trade` appelle `is_trade_blocked_by_event()` → `EventGuard.should_allow_trade()` → `is_blocked()` → `refresh_events()`.

Dans `refresh_events()`, le thread acquiert `self._lock` (ligne 651), puis appelle `self._source_rate_ok()` (lignes 659, 666, 673) qui tente aussi `with self._lock:` (ligne 190).

`threading.Lock()` est **non-réentrant** : le même thread ne peut pas l'acquérir deux fois → **deadlock permanent**.

C'est ce qui cause les 3 freezes identiques aujourd'hui (07:18, 18:02, 19:53) — toujours après un HARD_FILTER PASS.

## Fix — 1 seule ligne à changer

**Fichier** : `utils/event_guard.py`
**Ligne** : 159

Chercher :
```python
        self._lock = threading.Lock()
```

Remplacer par :
```python
        self._lock = threading.RLock()  # FIX 2026-03-10 R7: RLock réentrant (refresh_events → _source_rate_ok)
```

`threading.RLock()` (Reentrant Lock) permet au **même thread** d'acquérir le lock plusieurs fois sans bloquer. C'est exactement ce qu'il faut ici : `refresh_events` acquiert le lock, puis `_source_rate_ok` (appelé depuis `refresh_events`) peut le réacquérir sans deadlock.

## Vérification

```bash
python -m py_compile utils/event_guard.py
```

## Impact attendu

- **Les freezes post-HARD_FILTER PASS disparaissent** : l'EventGuard ne deadlocke plus
- **Les trades peuvent ENFIN s'exécuter** : le chemin execute_trade → EventGuard → MT5 order_send est débloqué
- **Aucun effet de bord** : RLock est un remplacement drop-in de Lock, il ajoute seulement la capacité réentrante

## Pourquoi ce bug n'a pas été détecté avant

- Le deadlock est **silencieux** : aucune exception, aucun log d'erreur
- Il se produit seulement quand le cache est expiré (TTL 30 min) ET qu'un symbole passe le HARD_FILTER PASS
- Les Rounds 3-6 corrigeaient les deadlocks COM MT5 (corrects) mais le EventGuard deadlock se produisait **avant** tout appel MT5

## Après ce fix

Redémarrer via `START_EMPIRE.bat` et attendre qu'un symbole passe le HARD_FILTER. Le chemin complet sera enfin :
1. `_run_agents_and_decide` → score OK → HARD_FILTER PASS ✅
2. `execute_trade` → EventGuard check (plus de deadlock) ✅
3. → MT5 `order_send` (protégé par le lock hybride) ✅
4. → Trade exécuté ! 🎯
