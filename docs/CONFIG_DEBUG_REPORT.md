# EMPIRE AGENT IA v3 - COMPLETE CONFIGURATION AUDIT REPORT
**Generated:** 2026-03-05
**Working Directory:** /sessions/dreamy-modest-tesla/mnt/EmpireAgentIA_3

---

## CRITICAL FINDING: ZERO TRADES LIKELY DUE TO CONFLICTING THRESHOLDS

This report documents ALL configuration thresholds, filters, and blocking conditions. Multiple layers of filters may be preventing trade execution.

---

## TABLE OF CONTENTS
1. [Orchestrator Quality Thresholds](#orchestrator-quality-thresholds)
2. [Session/Hour Filters (BLOCKING CONDITIONS)](#sessionhour-filters)
3. [Volatility & Market Filters](#volatility--market-filters)
4. [Symbol-Specific Overrides](#symbol-specific-overrides)
5. [Risk & Position Limits](#risk--position-limits)
6. [Agent Quality Filters](#agent-quality-filters)
7. [Cooldown & Anti-Spam Filters](#cooldown--anti-spam-filters)
8. [Data Directory Files (State & Logs)](#data-directory-files)

---

## ORCHESTRATOR QUALITY THRESHOLDS

These are HARD FILTERS in `/config/config.yaml` (lines 303-312):

| Parameter | Value | Impact |
|-----------|-------|--------|
| `min_score_for_proposal` | **8.0** | ⚠️ VERY HIGH - Requires extremely strong signal |
| `min_confluence` | **5** | ⚠️ VERY HIGH - Requires 5+ agents in agreement |
| `min_rr_required` | **1.8** | HIGH - Risk:Reward must be at least 1:1.8 |
| `tracker_contradiction` | 0.25 | Max 25% contradiction allowed |
| `disagree_block_pct` | 0.45 | >45% agents disagree = BLOCK (-1.0 score) |
| `disagree_penalty_pct` | 0.35 | >35% agents disagree = -0.5 penalty |
| `counter_trend_min_score` | 10.0 | ⚠️ Trades against HTF trend need score 10.0 |
| `quiet_block_confidence` | 0.7 | Market quiet = 70% confidence to block |

### Vote & Execution Requirements
```yaml
votes_required: 2              # Minimum 2 votes to consider trade
push_only_on_master: true      # Only execute on primary timeframe
```

**STATUS:** These thresholds are EXTREMELY RESTRICTIVE and likely blocking most trades.

---

## SESSION/HOUR FILTERS (BLOCKING CONDITIONS)

### GLOBAL BLOCKED HOURS (UTC) - config.yaml line 315
```yaml
session:
  blocked_hours_utc: [0, 1, 2, 3, 4, 5, 18, 19, 20, 21, 22, 23]
```
⚠️ **CRITICAL:** 12 hours per day are blocked globally!

**Coverage by time (UTC):**
- 00:00-06:00 - Blocked (Asian low liquidity)
- 06:00-18:00 - **OPEN** (8 hours only: 6,7,8,9,10,11,12,13,14,15,16,17)
- 18:00-24:00 - Blocked (New York close + weekend prep)

### Volatility Filter Low Liquidity Hours - config.yaml line 126
```yaml
avoid_low_liquidity_hours_utc:
  [0, 1, 5, 6, 7, 9, 10, 11, 13, 14, 17, 19, 20, 21]
```
⚠️ 14 hours ALSO avoided for volatility reasons!

**Effectively Open Hours:**
- 08:00 UTC (London open)
- 12:00-16:00 UTC (peak liquidity)
- 18:00-21:00 UTC (blocked by session filter)
- **ACTUAL OVERLAP: ~4-6 hours per day**

### Symbol-Specific Hour Filters (overrides.yaml)

| Symbol | Blocked Hours (UTC) | Allowed Hours (UTC) | Notes |
|--------|-------------------|-------------------|-------|
| BTCUSD | [16,17,18,20,22] | None specified | Toxic hours |
| BNBUSD | [0,1,2,3,4,5,18,19,20,21,22,23] | None | Most hours blocked! |
| XAUUSD | [14,18] | Prime: 7-17 | London session preferred |
| ETHUSD | None specified | 7-23 UTC | Good coverage |
| EURUSD | None specified | 7-22:30 UTC | Good coverage |
| SP500 | [1,7,8,10,14,17,18,20,22] | Prime: 13-20 | US session |
| NAS100 | None specified | Prime: 13-20 UTC | US session |
| LTCUSD | Whitelist: [8,18,22] | Only 3 hours! | ⚠️ VERY RESTRICTIVE |
| SOLUSD | Whitelist: [13,23] | Only 2 hours! | ⚠️ EXTREMELY RESTRICTIVE |
| USDJPY | Whitelist: [4,7,12,13,14,15,17,22] | 8 hours | Moderate |
| GBPUSD | None specified | None specified | No special hours |
| UK100 | None specified | None specified | No special hours |
| AUDUSD | **DISABLED** (enabled: false) | N/A | Disabled in overrides.yaml:715 |

### CRITICAL DISCOVERY:
**LTCUSD and SOLUSD are WHITELISTED to only 2-3 hours per day!**

---

## VOLATILITY & MARKET FILTERS

### ATR Spike Detection (config.yaml lines 110-121)
```yaml
volatility_filter:
  enabled: true
  atr_spike_threshold: 2.0      # Block if ATR > 2x the moving average
  atr_lookback_periods: 20
  max_spread_atr_ratio: 0.3     # Spread must be < 30% of ATR
  gap_threshold_atr: 0.5        # Gap must be < 50% of ATR
  news_blackout_enabled: true
  news_blackout_minutes: 30     # ±30 min around HIGH impact events
```

**Asset-Specific Overrides:**
- Crypto: `atr_spike_threshold: 2.5` (more volatile allowed)
- Forex: `news_blackout_minutes: 45` (longer blackout)
- Commodities: `atr_spike_threshold: 1.8` (more restrictive)

### News Blackout Windows (config.yaml lines 244-251)
```yaml
event_guard:
  enabled: true
  high_window_before: 30        # Block 30 min BEFORE HIGH impact
  high_window_after: 30         # Block 30 min AFTER HIGH impact
  medium_window_before: 15      # Block 15 min BEFORE MEDIUM impact
  medium_window_after: 15       # Block 15 min AFTER MEDIUM impact
```

---

## SYMBOL-SPECIFIC OVERRIDES

### Active Trading Symbols (overrides.yaml)

#### **BTCUSD** (Crypto Major)
```yaml
min_rr: 1.15              # Low R:R requirement
votes_required: 2
min_confluence: 0.8       # Low confluence requirement
min_score_for_proposal: 1.2
max_trades_per_day: 6
max_volume: 0.10          # Limited to 0.10 lot
blocked_hours_utc: [16, 17, 18, 20, 22]
atr_sl_mult: 1.5          # Tight stop loss
position_manager:
  max_duration_minutes: 480     # 8-hour timeout
  break_even: rr=1.2
  partials: rr=1.5 (30%), rr=2.5 (30%)
```

#### **ETHUSD** (Crypto Secondary)
```yaml
min_rr: 1.20
votes_required: 2
min_confluence: 1.2
min_score_for_proposal: 1.3
max_trades_per_day: 6
max_volume: 0.06
atr_sl_mult: 1.5
position_manager:
  max_duration_minutes: 360     # 6-hour timeout
  break_even: rr=1.2
```

#### **BNBUSD** (Crypto Secondary)
```yaml
allowed_directions: ["SHORT"]   # ⚠️ LONG DISABLED!
min_rr: 1.20
votes_required: 2
min_confluence: 1.2
min_score_for_proposal: 1.3
max_trades_per_day: 6
max_volume: 1.0               # Higher volume cap
blocked_hours_utc: [0,1,2,3,4,5,18,19,20,21,22,23]  # ⚠️ MOST HOURS BLOCKED!
atr_sl_mult: 1.5
```

#### **XAUUSD** (Gold)
```yaml
min_rr: (global 1.8)
votes_required: (global 2)
max_trades_per_day: 4         # Conservative
max_volume: 0.15              # Small volume
blocked_hours_utc: [14, 18]
atr_sl_mult: 1.8
prime_hours_utc: [{start: 7, end: 17}]  # London session
position_manager:
  max_duration_minutes: 360
```

#### **EURUSD** (Forex Major)
```yaml
min_rr: 1.25
votes_required: 2
min_confluence: 1.3
min_score_for_proposal: 1.4
max_trades_per_day: 4         # Conservative
max_volume: 1.0
trading_window: 07:00-22:30 UTC
atr_sl_mult: 1.4
position_manager:
  max_duration_minutes: 360
```

#### **SP500** (Index)
```yaml
max_trades_per_day: 4
max_volume: 1.0
blocked_hours_utc: [1,7,8,10,14,17,18,20,22]  # Very restrictive!
atr_sl_mult: 1.6
prime_hours_utc: [{start: 13, end: 20}]  # US session
position_manager:
  max_duration_minutes: 240   # 4-hour timeout
```

#### **NAS100** (Nasdaq)
```yaml
max_trades_per_day: 4
max_volume: 1.0
atr_sl_mult: 1.6
prime_hours_utc: [{start: 13, end: 20}]
position_manager:
  max_duration_minutes: 240
```

#### **LTCUSD** (Crypto - DISABLED)
```yaml
enabled: false                # ⚠️ DISABLED!
allowed_hours_utc: [8, 18, 22]  # Only 3 hours if enabled
max_volume: 5.0 (if enabled)
```

#### **SOLUSD** (Crypto)
```yaml
allowed_hours_utc: [13, 23]   # ⚠️ Only 2 hours!
max_trades_per_day: 6
max_volume: 5.0
atr_sl_mult: 1.5
position_manager:
  max_duration_minutes: 360
```

#### **USDJPY** (Forex)
```yaml
allowed_hours_utc: [4,7,12,13,14,15,17,22]  # 8 hours
max_trades_per_day: 4
max_volume: 1.0
atr_sl_mult: 1.4
prime_hours_utc: [{start: 7, end: 17}]
position_manager:
  max_duration_minutes: 360
```

#### **GBPUSD** (Forex)
```yaml
max_trades_per_day: 1         # ⚠️ ONLY 1 TRADE PER DAY!
max_volume: 2.0
atr_sl_mult: 1.4
position_manager:
  max_duration_minutes: 360
```

#### **UK100** (Index)
```yaml
max_trades_per_day: 1         # ⚠️ ONLY 1 TRADE PER DAY!
max_volume: 2.0
atr_sl_mult: 1.6
```

#### **AUDUSD** (Forex)
```yaml
enabled: false                # ⚠️ DISABLED!
```

---

## RISK & POSITION LIMITS

### Global Risk Tiers (config.yaml lines 359-377)
```yaml
tiers:
  - name: phase1
    equity_min: 0
    equity_max: 5000
    risk_per_trade_pct: 0.01        # 0.5% per trade
    max_daily_loss_pct: 2.0
    max_parallel_positions: 1       # Only 1 position!

  - name: phase2
    equity_min: 5000
    equity_max: 15000
    risk_per_trade_pct: 0.015
    max_daily_loss_pct: 3.0
    max_parallel_positions: 2       # Up to 2 positions

  - name: phase3
    equity_min: 15000
    equity_max: 99999999
    risk_per_trade_pct: 0.02
    max_daily_loss_pct: 4.0
    max_parallel_positions: 2
```

### Global Position Limits (config.yaml lines 286-290)
```yaml
position_policy:
  allow_stacking: false
  max_open_per_side: 1
  max_open_total: 2             # Maximum 2 concurrent positions
  allow_opposite: false         # No hedges
```

### Daily Loss Limits
```yaml
kill_switch:
  daily_loss_usd: 400           # Stop ALL trading if lose $400 in a day
daily_loss_limit_pct: 0.02      # 2% of equity
```

### Override: Global Daily Loss (overrides.yaml line 16)
```yaml
global_daily_loss_limit: 400.0  # USD — stops ALL trading if exceeded
```

### Max Trades Per Day (Global)
```yaml
max_trades_per_day: 6
max_trades_per_hour: 3          # Maximum 3 trades per hour
```

### Crypto Bucket Cap (overrides.yaml BTCUSD)
```yaml
crypto_bucket:
  enabled: true
  cap: 0.06                     # Max 6% of capital in crypto
  min_factor: 0.20
```

---

## AGENT QUALITY FILTERS

### Weighted Agent Voting (config.yaml lines 326-336)
```yaml
weighted:
  enabled: true
  threshold: 3.0                # ⚠️ INCREASED from 1.5 to 3.0!
  weights:
    TechnicalAgent: 1.2         # Most important
    SwingAgent: 1.0
    ScalpingAgent: 0.8          # Lower weight
    StructureAgent: 1.1         # Important
    SmartMoneyAgent: 1.0        # Important
    NewsAgent: 0.8
    SentimentAgent: 0.6         # Lowest weight
```

⚠️ **Threshold of 3.0 is VERY RESTRICTIVE** - needs strong weighted signal

### Advanced Analysis Filters (config.yaml lines 146-183)

#### Volume Profile / VWAP
```yaml
volume_profile_enabled: true
volume_profile:
  lookback_bars: 100
  value_area_pct: 0.70          # 70% of volume
  num_bins: 50
```

#### Market Regime Detector
```yaml
market_regime_enabled: true
market_regime:
  adx_trend_threshold: 25.0     # Trend if ADX > 25
  adx_strong_trend: 40.0        # Strong trend if ADX > 40
  min_confidence_to_block: 0.6  # 60% confidence blocks trade
```

#### MTF Confluence (config.yaml lines 161-168)
```yaml
mtf_confluence_enabled: true
mtf_confluence:
  min_alignment_ratio: 0.7      # ⚠️ 70% of timeframes must align!
  require_higher_tf_confirm: true
  block_counter_trend: true     # Block trades vs D1/H4 trend
  full_alignment_bonus: 0.3
  higher_tf_priority: ["D1", "H4"]
```

#### Sentiment Analyzer
```yaml
sentiment_enabled: true
sentiment:
  extreme_long_threshold: 75.0  # >75% long = SHORT signal
  extreme_short_threshold: 25.0 # <25% long = LONG signal
  min_score_to_block: 0.7       # 70% confidence blocks
```

#### Inter-Market Correlation
```yaml
inter_market_enabled: true
inter_market:
  correlation_period: 20
  strong_correlation_threshold: 0.7
  divergence_threshold: 0.4
```

---

## COOLDOWN & ANTI-SPAM FILTERS

### Cooldown Periods (config.yaml lines 225-232)
```yaml
cooldown:
  enabled: true
  after_trade_min: 15           # Wait 15 min after ANY trade
  after_loss_min: 30            # Wait 30 min after LOSS
  after_win_min: 10             # Wait 10 min after WIN
  after_reject_min: 5           # Wait 5 min after REJECT
  after_streak_n: 3             # Trigger long pause after 3 losses
  after_streak_min: 120         # ⚠️ 2-hour pause after 3 consecutive losses
```

### Anti-Spam Rules (config.yaml lines 292-297)
```yaml
anti_spam:
  per_bar_only: true            # One signal per candle
  cooldown_minutes: 5           # Wait 5 min between proposals
  price_delta_bps: 5            # Price must move 5 bps minimum
  confidence_delta: 0.05        # Confidence must change 0.05
  avoid_if_open_position: true  # Don't enter if position open
```

### Symbol-Specific Cooldowns (overrides.yaml)

| Symbol | min_secs_between_trades | after_loss_min | after_win_min | after_streak_min |
|--------|----------------------|-----------------|---------------|-----------------|
| BTCUSD | 600 sec (10 min) | 60 min | 5 min | 30 min |
| BNBUSD | 600 sec | 60 min | 6 min | 30 min |
| ETHUSD | 600 sec | 60 min | 5 min | 30 min |
| XAUUSD | 600 sec | 60 min | 4 min | 30 min |
| EURUSD | 600 sec | 60 min | 6 min | 30 min |
| SP500 | 600 sec | 60 min | N/A | 30 min |
| NAS100 | 600 sec | 60 min | N/A | 30 min |
| USDJPY | 600 sec | 60 min | N/A | 30 min |
| GBPUSD | 600 sec | 60 min | N/A | 30 min |
| UK100 | 600 sec | 60 min | N/A | 30 min |

**Common Pattern:** 10 min between trades, 60 min after losses!

---

## DATA DIRECTORY FILES

### State & Control Files
| File | Size | Last Modified | Purpose |
|------|------|---------------|---------|
| `latest_signals.json` | 480 B | 2026-03-04 20:25 | Current signal (LTCUSD: LONG from swing/structure) |
| `open_positions.json` | 28 B | 2026-03-04 20:24 | Open positions (likely empty `[]`) |
| `circuit_breaker_state.json` | 701 B | 2026-03-01 07:57 | Circuit breaker status |
| `daily_loss_state.json` | 112 B | 2026-03-04 04:45 | Daily loss tracking |
| `pm_state.json` | 316 B | 2026-02-27 13:28 | Position manager state |

### Trade History
| File | Size | Last Modified | Purpose |
|------|------|---------------|---------|
| `deals_history.csv` | 480 KB | 2026-03-03 17:42 | Closed trade history |
| `trades_log.csv` | 611 KB | 2026-03-03 13:46 | Detailed trade log |
| `equity_log.csv` | 37 MB | 2026-03-04 20:24 | Equity curve history |
| `proposals_log.csv` | 14.5 MB | 2026-03-04 19:21 | All trade proposals (accepted/rejected) |

### Analysis Data
| File | Size | Purpose |
|------|------|---------|
| `agents_snap.jsonl` | 494 MB | Agent snapshots (very large!) |
| `news_calendar_live.json` | 30 KB | Live economic calendar |
| `news_calendar.csv` | 14.5 KB | Economic events |

---

## SUMMARY: WHY ZERO TRADES?

### PRIMARY BLOCKING FACTORS (In Order of Severity)

1. **Orchestrator Quality Thresholds (HARD STOPS)**
   - `min_score_for_proposal: 8.0` - Extremely high (standard: 2-3)
   - `min_confluence: 5` - Requires 5+ agents (standard: 2-3)
   - `min_rr_required: 1.8` - High R:R requirement

2. **Session Hour Filters (TIME-BASED BLOCKS)**
   - Global: Only 6-18 UTC open (12 hours blocked)
   - Volatility: Avoids 14 additional hours for liquidity
   - **Effective overlap: ~4-6 hours per day**

3. **Symbol-Specific Restrictions**
   - GBPUSD/UK100: **Only 1 trade per day**
   - LTCUSD: **Disabled** (enabled: false)
   - AUDUSD: **Disabled**
   - SOLUSD: Only 2 hours (13:00 & 23:00 UTC)
   - BNBUSD: Most hours blocked [0-5, 18-23 UTC]

4. **Multi-Timeframe Confluence (70% alignment required)**
   - Must have 70%+ of timeframes aligned
   - Must confirm vs D1/H4 trends
   - Blocks counter-trend trades

5. **Cooldown Penalties**
   - 10 minutes between trades
   - 60 minutes after loss
   - 120 minutes after 3 consecutive losses
   - **Can effectively lock trading for hours**

6. **Position Limits**
   - Phase 1: Max 1 concurrent position
   - Max 2 concurrent total
   - Only 1 position per side
   - No hedging allowed

7. **Risk-Per-Trade (Capital-Dependent)**
   - Phase 1 (< $5K): 0.5% per trade
   - With $400 daily loss limit = only 8-10 trades possible per day max

### LIKELY ROOT CAUSE

The configuration has been progressively "hardened" with increasing thresholds to prevent losses, resulting in **too many filters that conflict with each other**:

- Score threshold (8.0) requires very high quality signals
- Hour filters block most trading hours
- Multi-TF confluence (70%) is very restrictive
- Cooldowns prevent rapid recovery
- Position limits cap exposure

**Result:** No trades execute because the combined filters are mathematically impossible to satisfy simultaneously under real market conditions.

---

## RECOMMENDATIONS FOR DEBUGGING

1. **Check proposals_log.csv** - See if ANY proposals are being generated
2. **Check agents_snap.jsonl** - Verify agents are generating signals
3. **Temporarily relax ONE filter** at a time:
   - Try `min_score_for_proposal: 6.0` (down from 8.0)
   - Try `min_confluence: 3` (down from 5)
   - Try `blocked_hours_utc: []` (disable global hour filter)
4. **Verify symbol status** - Check which symbols are actually enabled
5. **Check circuit breaker** - May be triggered and blocking all trades
6. **Review daily loss state** - May have hit $400 limit and triggered kill switch

---

## FILE LOCATIONS (FOR REFERENCE)

- Main Config: `/sessions/dreamy-modest-tesla/mnt/EmpireAgentIA_3/config/config.yaml` (578 lines)
- Symbol Overrides: `/sessions/dreamy-modest-tesla/mnt/EmpireAgentIA_3/config/overrides.yaml` (764 lines)
- Asset Config: `/sessions/dreamy-modest-tesla/mnt/EmpireAgentIA_3/config/asset_config.yaml` (289 lines)
- Profiles: `/sessions/dreamy-modest-tesla/mnt/EmpireAgentIA_3/config/profiles.yaml`
- Trade Logs: `/sessions/dreamy-modest-tesla/mnt/EmpireAgentIA_3/data/`
- Proposals: `/sessions/dreamy-modest-tesla/mnt/EmpireAgentIA_3/data/proposals_log.csv`

