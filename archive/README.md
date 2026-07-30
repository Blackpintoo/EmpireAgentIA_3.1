# archive/ — modules retirés du chemin d'exécution

**Créé le 30 juillet 2026 (P6).** Rien n'a été supprimé.

Ces 19 modules ne sont atteints par aucun point d'entrée du bot
(`main.py`, `scheduler_empire.py`, `scripts/start_empire.py`) et ne sont
référencés nulle part ailleurs dans le dépôt — ni par un import, ni par un
`importlib`, ni par une chaîne de caractères, ni par un `.bat`, ni par un
fichier de configuration, ni par un test.

La vérification est reproductible :

```
python tools/modules_orphelins.py
```

Le script fait deux passes indépendantes : accessibilité depuis les points
d'entrée (analyse AST, sans rien exécuter), puis recherche de références sur
tout le dépôt. Un module n'est archivé que s'il échoue aux deux.

## Ce qui a été déplacé

| Module | Ce que c'était |
|---|---|
| `backtest/run_scalping.py` | lanceurs de backtest par stratégie |
| `backtest/run_swing.py` | idem |
| `backtest/run_technical.py` | idem |
| `connectors/alpha_vantage_client.py` | connecteur Alpha Vantage |
| `connectors/alpha_vantage_news.py` | news Alpha Vantage — remplacé par `utils/news_sources.py` |
| `connectors/fear_greed_index.py` | indice Fear & Greed |
| `connectors/finnhub_calendar.py` | calendrier Finnhub |
| `optimization/optimize_and_update_config.py` | optimisation de config |
| `optimization/optuna_agent.py` | recherche d'hyperparamètres Optuna |
| `orchestrator/orchestrator.minimal.py` | orchestrateur minimal (non importable : le `.` du nom en fait un module inatteignable) |
| `utils/_e2e_ttl_test.py` | script de test manuel du TTL |
| `utils/analyze_trades.py` | analyse de trades hors ligne |
| `utils/data_fetchers.py` | récupération de données |
| `utils/error_codes.py` | table de codes d'erreur |
| `utils/risk_sizing.py` | dimensionnement — remplacé par `utils/risk_manager.py` |
| `utils/settings.py` | réglages — remplacé par `utils/config.py` |
| `utils/smc_visualizer.py` | visualisation des patterns SMC |
| `utils/tg_callback_worker.py` | **voir la note ci-dessous** |
| `utils/trades_db.py` | persistance des trades en base |

## Note sur `utils/tg_callback_worker.py`

Ce module est une boucle de polling des callbacks Telegram
(`orch|<SYMBOL>|VALIDATE|<LONG\|SHORT>`), prévue pour tourner dans un thread
daemon. **Elle n'est démarrée nulle part.** C'est une seconde implémentation,
plus ancienne, de l'écoute des boutons de validation ; celle qui tourne
réellement vit dans `orchestrator/orchestrator.py` et exige
`telegram_validation: true` sur le symbole.

Elle est archivée parce qu'elle est effectivement morte, pas parce qu'elle
serait sans intérêt : si un jour tu veux une écoute des callbacks indépendante
de l'orchestrateur, le point de départ est ici.

## Restaurer un module

```
git mv archive/utils/settings.py utils/settings.py
```

Ou, sans git :

```
move archive\utils\settings.py utils\settings.py
```
