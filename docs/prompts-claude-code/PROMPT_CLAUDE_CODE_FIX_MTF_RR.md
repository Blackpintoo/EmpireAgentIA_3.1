# PROMPT CLAUDE CODE — Fix MTF_FILTER + R:R + Confluence + XAUUSD/USDJPY

## Contexte
Le monitoring post-restart montre que 7/9 agents répondent maintenant correctement (vs 0/9 avant). Mais 2 problèmes bloquent les trades :
1. Un bug dans l'appel `analyze_mtf_confluence()` qui crashe à chaque cycle
2. Des filtres R:R et confluence trop restrictifs qui bloquent 6/9 symboles
3. XAUUSD et USDJPY retournent score=0 (tous les agents MT5 à zéro)

## Corrections à appliquer (5 fixes)

---

### FIX 1 — CRITIQUE : Désactiver le MTF_FILTER cassé

**Fichier** : `orchestrator/orchestrator.py`
**Problème** : L'appel à `analyze_mtf_confluence()` utilise des paramètres incorrects :
```python
# APPEL ACTUEL (CASSÉ) — autour de la ligne 2199-2203 :
mtf_result = analyze_mtf_confluence(
    symbol=symbol,
    mt5_client=self.mt5,       # ← ERREUR: paramètre inexistant
    target_direction=sig        # ← ERREUR: le vrai paramètre s'appelle "direction"
)
# Il manque aussi tf_data (Dict[str, DataFrame]) qui est requis
```

La signature réelle de la fonction (dans `utils/mtf_confluence.py` ligne 346) est :
```python
def analyze_mtf_confluence(symbol, direction, tf_data, config=None)
```

**Action** : Désactiver le bloc MTF_FILTER en entier. Chercher le bloc qui contient `analyze_mtf_confluence(` dans orchestrator.py (autour lignes 2194-2225) et commenter tout le bloc OU remplacer la condition d'entrée par `if False:`. Concrètement :

```python
# AVANT :
if analyze_mtf_confluence is not None:
    try:
        adv_cfg = self.cfg.get("advanced_analysis", {})
        mtf_cfg = adv_cfg.get("mtf_confluence", {})
        if mtf_cfg.get("block_counter_trend", True):
            mtf_result = analyze_mtf_confluence(
                symbol=symbol,
                mt5_client=self.mt5,
                target_direction=sig
            )
            # ... suite du bloc ...

# APRÈS :
if False:  # FIX 2026-03-06: MTF filter désactivé — appel incompatible avec la signature de analyze_mtf_confluence()
    try:
        adv_cfg = self.cfg.get("advanced_analysis", {})
        # ... (laisser le code commenté/désactivé, ne pas supprimer)
```

**Alternative acceptable** : Ajouter `block_counter_trend: false` dans la section `advanced_analysis.mtf_confluence` de `config/config.yaml`. Mais la correction dans le Python est plus sûre car elle élimine le bug à la source.

**Vérification** : Après correction, rechercher dans tout le code d'autres appels à `analyze_mtf_confluence` pour vérifier qu'il n'y a pas d'autre appel cassé.

---

### FIX 2 — Baisser le filtre R:R minimum

**Fichier** : `config/config.yaml`
**Problème** : `min_rr_required: 1.2` et `hard_filters.min_rr: 1.2` bloquent 4 symboles sur 9 (SP500 rr=1.02, NAS100 rr=0.99, LTCUSD rr=0.96, SOLUSD rr=0.72).
**Action** :
- Changer `orchestrator.min_rr_required` de `1.2` à `0.8`
- Changer `orchestrator.hard_filters.min_rr` de `1.2` à `0.8`

**Fichier** : `orchestrator/orchestrator.py`
**Action** : Changer le fallback par défaut de `_hf_min_rr` :
```python
# AVANT (ligne ~759) :
self._hf_min_rr: float = float(_hf.get("min_rr", 1.5))
# APRÈS :
self._hf_min_rr: float = float(_hf.get("min_rr", 0.8))
```

**Fichier** : `config/overrides.yaml`
**Action** : Pour les symboles qui ont un `min_rr` explicite, baisser à 0.8 :
- BTCUSD : `min_rr: 1.15` → `min_rr: 0.8`
- LTCUSD : `min_rr: 1.2` → `min_rr: 0.8`
- BNBUSD : `min_rr: 1.20` → `min_rr: 0.8`
- Tout autre symbole ayant un `min_rr` > 0.8 → `0.8`

---

### FIX 3 — Baisser le seuil de confluence soft filter

**Fichier** : `config/overrides.yaml`
**Action** : Dans la section `GLOBAL.default`, changer :
```yaml
# AVANT :
min_confluence: 2.5
# APRÈS :
min_confluence: 2.0
```

**Fichier** : `config/config.yaml`
**Action** : Dans la section `orchestrator`, changer :
```yaml
# AVANT :
min_confluence: 3
# APRÈS :
min_confluence: 2.0
```

**Fichier** : `orchestrator/orchestrator.py`
**Action** : Changer le fallback Python :
```python
# AVANT (ligne ~748) :
self.min_confluence: float = float(self.ori_cfg.get("min_confluence", 2.5))
# APRÈS :
self.min_confluence: float = float(self.ori_cfg.get("min_confluence", 2.0))
```

Et aussi le hard filter :
```python
# AVANT (ligne ~755) :
self._hf_min_confluence: float = float(_hf.get("min_confluence", 3))
# APRÈS :
self._hf_min_confluence: float = float(_hf.get("min_confluence", 2.0))
```

---

### FIX 4 — Activer plus d'agents pour USDJPY

**Fichier** : `config/profiles.yaml`
**Problème** : USDJPY n'a que 4 agents activés (technical, swing, structure, smart_money). Avec si peu d'agents, le système de scoring par agreement/disagreement produit facilement score=0.
**Action** : Activer les agents news et sentiment pour USDJPY :
```yaml
# Dans la section USDJPY > agents :
# AVANT :
scalping: {enabled: false}  # Garder désactivé (trop risqué sur JPY)
# AJOUTER / MODIFIER :
news: {enabled: true}
sentiment: {enabled: true}
```

Cela fait passer USDJPY de 4 à 6 agents, améliorant la probabilité d'obtenir un score non-nul.

---

### FIX 5 — Diagnostiquer XAUUSD et USDJPY score=0

**Fichier** : `orchestrator/orchestrator.py`
**Action** : Ajouter du logging temporaire dans `_gather_agent_signals()` (ou la fonction qui collecte les résultats des agents) pour logger le score individuel de chaque agent AVANT l'agrégation. Chercher la fonction qui agrège les scores des agents et ajouter :

```python
# Après avoir collecté les résultats de tous les agents, ajouter :
logger.info(f"[AGENT_SCORES] {symbol} — Scores individuels: " +
    ", ".join(f"{name}={result.get('score', 'N/A')}/{result.get('direction', 'N/A')}"
              for name, result in agent_results.items()))
```

Cela permettra de voir dans les prochains logs si les agents XAUUSD/USDJPY retournent des signaux NEUTRAL, des scores nuls, ou des erreurs.

**Vérification additionnelle** : Vérifier que les symboles `XAUUSD` et `USDJPY` existent bien dans le terminal MT5 avec exactement ces noms (pas `XAUUSDm`, `GOLD`, `USDJPYm`, etc.). Dans `mt5_client.py`, chercher s'il y a un mapping ou suffix ajouté aux symboles.

---

## Résumé des modifications

| # | Fichier | Modification | Impact |
|---|---------|-------------|--------|
| 1 | orchestrator.py | Désactiver bloc MTF_FILTER (`if False:`) | Débloquer SP500 et tout trade passant les hard filters |
| 2 | config.yaml + overrides.yaml + orchestrator.py | min_rr: 1.2→0.8, fallback 1.5→0.8 | Débloquer 4 symboles (SP500, NAS100, LTCUSD, SOLUSD) |
| 3 | config.yaml + overrides.yaml + orchestrator.py | min_confluence: 2.5/3→2.0 | Débloquer NAS100 (2.11) et AUDUSD (2.14) |
| 4 | profiles.yaml | USDJPY: activer news + sentiment | Améliorer scoring USDJPY (4→6 agents) |
| 5 | orchestrator.py | Ajouter logging scores individuels | Diagnostiquer XAUUSD/USDJPY score=0 |

## Après les modifications
1. Redémarrer le bot via START_EMPIRE.bat
2. Attendre 5 minutes
3. Vérifier dans les logs :
   - Plus aucune erreur `[MTF_FILTER]`
   - Des trades passent les hard filters ET les soft filters
   - Les logs `[AGENT_SCORES]` montrent les scores individuels de XAUUSD/USDJPY
