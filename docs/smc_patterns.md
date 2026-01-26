# Smart Money Concepts (SMC) dans Empire

Ce module complète l’agent `structure` avec des signaux orientés price action
(BOS, CHoCH, FVG, EQH/EQL, order blocks, breaker blocks, equilibrium / OTE).
Les détections sont implémentées dans `utils/smc_patterns.py` et exposées via
`StructureAgent.generate_signal` (`smc_signal`, `smc_events`, `smc_meta`).

## Activer / ajuster le poids SMC

1. Dans la configuration du symbole (`config/overrides.yaml` ou preset dédié),
   ajoute la clé `agent_weights.smc`. Par défaut, les overrides fournissent:

   ```yaml
   orchestrator:
     agent_weights:
       smc: 0.6
   ```

2. L’orchestrateur lit ce poids (`w_smc`) et comptabilise le vote SMC dans la
   direction agrégée. Augmenter la valeur donne plus d’influence aux patterns
   SMC sur la confluence globale.

3. Côté agent `structure`, la détection peut être coupée en mettant
   `agents.structure.smc_enabled: false` dans `config/profiles.yaml` si besoin.
   Des tolérances supplémentaires sont disponibles (`smc_fvg_tolerance`,
   `smc_eq_tolerance`, `smc_pivot_window`).
   Exemple d’override par symbole :

   ```yaml
   BTCUSD:
     agents:
       structure:
         smc_enabled: true
         smc_pivot_window: 3
         smc_fvg_tolerance: 0.05   # tolérance gap (5%)
         smc_eq_tolerance: 0.02    # marge pour EQH/EQL
   ```

## Tests unitaires

Le module est couvert par `tests/test_smc_patterns.py` qui génère des séries
syntétiques pour chaque heuristique. Lancer les tests:

```bash
pytest tests/test_smc_patterns.py
```

## Validation manuelle

1. Démarrer Empire en mode démo: `start-empire-demo.cmd` (ou `start-empire.bat`
   en `dry_run`).  
2. Surveiller les logs de l’agent structure (`debug.smc`), ou `market["smc_events"]`
   côté orchestrateur, pour confirmer les patterns détectés et les votes LONG/SHORT.
3. Ajuster les multipliers SL/TP si la nouvelle largeur des stops (ex: LINKUSD)
   impacte les retcodes MT5, puis relancer un test pour valider le flux complet.

## Notes

- Les heuristiques restent volontairement simples pour limiter les faux positifs
  massifs sur données bruitées. N’hésite pas à enrichir `utils/smc_patterns.py`
  avec des filtres additionnels (minimum ATR, volumes, session).  
- Les événements SMC sont sérialisés dans le `debug` agent et dans `market` afin
  de faciliter l’export vers un dashboard ou une alerte Telegram.
