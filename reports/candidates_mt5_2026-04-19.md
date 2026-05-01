# Rapport vérification symboles candidats MT5

- Généré : 2026-04-19T10:54:00+00:00
- Directive : D5 (2026-04-19)
- Candidats testés : DJ30, UK100, GBPUSD, USDCAD, GER40, XAGUSD

## Résumé

| Symbole | Verdict | Broker name | Spread | Point | Filling |
|---|---|---|---|---|---|
| DJ30 | **AJUSTER** | DJ30 | 0 | 0.01 | IOC |
| UK100 | **AJUSTER** | UK100 | 0 | 0.01 | IOC |
| GBPUSD | **AJUSTER** | GBPUSD | 51 | 1e-05 | IOC |
| USDCAD | **AJUSTER** | USDCAD | 82 | 1e-05 | IOC |
| GER40 | **AJUSTER** | GER40 | 0 | 0.01 | IOC |
| XAGUSD | **AJUSTER** | XAGUSD | 0 | 0.001 | IOC |

## DJ30 — AJUSTER

- Broker name : `DJ30`
- Spécifications :
  - `spread` : 0
  - `point` : 0.01
  - `digits` : 2
  - `trade_contract_size` : 1.0
  - `volume_min` : 0.1
  - `volume_max` : 500.0
  - `volume_step` : 0.1
  - `trade_stops_level` : 50
  - `trade_freeze_level` : 0
  - `filling_modes` : IOC
  - `currency_profit` : USD
  - `currency_margin` : USD
  - `m15_bars_read` : 100
- Notes :
  - Symbole activé dans Market Watch par le script
  - Aucun tick disponible

## UK100 — AJUSTER

- Broker name : `UK100`
- Spécifications :
  - `spread` : 0
  - `point` : 0.01
  - `digits` : 2
  - `trade_contract_size` : 1.0
  - `volume_min` : 0.1
  - `volume_max` : 500.0
  - `volume_step` : 0.1
  - `trade_stops_level` : 50
  - `trade_freeze_level` : 0
  - `filling_modes` : IOC
  - `currency_profit` : GBP
  - `currency_margin` : GBP
  - `m15_bars_read` : 100
- Notes :
  - Symbole activé dans Market Watch par le script
  - Aucun tick disponible

## GBPUSD — AJUSTER

- Broker name : `GBPUSD`
- Spécifications :
  - `spread` : 51
  - `point` : 1e-05
  - `digits` : 5
  - `trade_contract_size` : 100000.0
  - `volume_min` : 0.01
  - `volume_max` : 100.0
  - `volume_step` : 0.01
  - `trade_stops_level` : 0
  - `trade_freeze_level` : 0
  - `filling_modes` : IOC
  - `currency_profit` : USD
  - `currency_margin` : GBP
  - `m15_bars_read` : 100
  - `last_tick_utc` : 2026-04-17T23:56:59+00:00
  - `tick_age_sec` : 125819
- Notes :
  - Tick vieux de 125820s (>5min)

## USDCAD — AJUSTER

- Broker name : `USDCAD`
- Spécifications :
  - `spread` : 82
  - `point` : 1e-05
  - `digits` : 5
  - `trade_contract_size` : 100000.0
  - `volume_min` : 0.01
  - `volume_max` : 100.0
  - `volume_step` : 0.01
  - `trade_stops_level` : 0
  - `trade_freeze_level` : 0
  - `filling_modes` : IOC
  - `currency_profit` : CAD
  - `currency_margin` : USD
  - `m15_bars_read` : 100
  - `last_tick_utc` : 2026-04-17T23:56:59+00:00
  - `tick_age_sec` : 125821
- Notes :
  - Tick vieux de 125821s (>5min)

## GER40 — AJUSTER

- Broker name : `GER40`
- Spécifications :
  - `spread` : 0
  - `point` : 0.01
  - `digits` : 2
  - `trade_contract_size` : 1.0
  - `volume_min` : 0.1
  - `volume_max` : 500.0
  - `volume_step` : 0.1
  - `trade_stops_level` : 50
  - `trade_freeze_level` : 0
  - `filling_modes` : IOC
  - `currency_profit` : EUR
  - `currency_margin` : EUR
  - `m15_bars_read` : 100
- Notes :
  - Symbole activé dans Market Watch par le script
  - Aucun tick disponible

## XAGUSD — AJUSTER

- Broker name : `XAGUSD`
- Spécifications :
  - `spread` : 0
  - `point` : 0.001
  - `digits` : 3
  - `trade_contract_size` : 5000.0
  - `volume_min` : 0.01
  - `volume_max` : 20.0
  - `volume_step` : 0.01
  - `trade_stops_level` : 10
  - `trade_freeze_level` : 0
  - `filling_modes` : IOC
  - `currency_profit` : USD
  - `currency_margin` : USD
  - `m15_bars_read` : 100
- Notes :
  - Symbole activé dans Market Watch par le script
  - Aucun tick disponible

## Gate directive 5

- PROMOUVOIR ≥ {DJ30, UK100, GBPUSD} requis : **KO** (promus=[])
