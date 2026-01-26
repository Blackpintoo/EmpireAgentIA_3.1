import pathlib, csv, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from datetime import timedelta

THIS = pathlib.Path(__file__).resolve()
ROOT = THIS.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.news_filter import is_frozen_now, TZ

def test_freeze_from_csv(tmp_path):
    # CSV temporaire avec une news High USD à maintenant
    csv_path = tmp_path / "news.csv"
    now = datetime.now(TZ)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datetime","currency","impact","title"])
        w.writerow([now.strftime("%Y-%m-%d %H:%M"), "USD", "High", "Test Event"])

    profile = {"instrument": {"currencies": ["USD"]}}
    frozen, why = is_frozen_now(
        symbol="BTCUSD", profile=profile,
        news_csv=str(csv_path),
        window_before_min=10, window_after_min=10,
        impacts=["High"],
        now=now
    )
    assert frozen and "USD/High" in why


def test_manual_freeze_window():
    profile = {"instrument": {"currencies": ["USD"]}}
    now = datetime.now(TZ)
    s_dt = (now - timedelta(minutes=1)).replace(microsecond=0)
    e_dt = (now + timedelta(minutes=1)).replace(microsecond=0)
    frozen, why = is_frozen_now(
        symbol="BTCUSD", profile=profile,
        manual_freezes=[(s_dt.isoformat(), e_dt.isoformat())],
        now=now
    )
    assert frozen and "manual_freeze" in why
