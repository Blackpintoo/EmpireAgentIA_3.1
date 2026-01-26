# Performance Tracker Integration

The orchestrator now records real agent votes through `utils/performance_tracker.PerformanceTracker`.

## Quick Overview

* `_build_tracker_signals()` converts per-agent, per-timeframe outputs into tracker inputs.
* Every proposal keeps `weighted_vote`, the enriched `signals`, `tracker_vote`, `rr`, and `regime`.
* `_record_performance_stats()` logs each signal as a `PerformancePoint` (dry-run and live execution).
* A `[TRACKER] top …` log shows the most influential bucket after each update.

## Configuration knobs

* `orchestrator.multi_timeframes.tfs` / `tf_weights` weight agent signals.
* `orchestrator.auto_execute_threshold` controls when the tracker outcome is considered “executed”.
* Tracker data persists to `data/performance/performance_tracker.json` (keep for dashboards or audits).

## Sample test

````
python -m compileall orchestrator/orchestrator.py
python scripts/audit_weekly.py
````

Typical logs:

````
[ORCH] BTCUSD vote=0.600 (signals=4)
[TRACKER] top BTCUSD/scalping bucket=M1|trend_up weight=2.10 count=12
````

## Notes

* Cache the minimal version in `orchestrator/orchestrator.minimal.py` if you want to compare behaviours.
* The tracker doesn’t crash the orchestrator: failures fall back to raw signals.
* You can inspect/update the JSON manually if you want to reset weights (`data/performance/performance_tracker.json`).
