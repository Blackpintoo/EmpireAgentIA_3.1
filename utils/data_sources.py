from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import feedparser
import requests
from textblob import TextBlob

from utils.logger import logger

__all__ = [
    "http_get",
    "http_get_json",
    "fetch_rss_feed",
    "fetch_coindesk",
    "fetch_cryptopanic",
    "fetch_reuters",
    "fetch_twitter_sentiment",
    "fetch_google_trends",
    "fetch_fxstreet_calendar",
    "aggregate_news",
]


_DEFAULT_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    "Connection": "close",
}

_SESSION = requests.Session()
_CACHE: Dict[str, Tuple[float, Any]] = {}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _safe_json(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except Exception:
            return str(value)
    return str(value)

def _make_cache_key(prefix: str, *parts: Any) -> str:
    chunks = [_safe_json(p) for p in parts]
    return f"{prefix}:" + "|".join(chunks)

def _cache_get(key: str, ttl: float) -> Optional[Any]:
    now_ts = time.time()
    cached = _CACHE.get(key)
    if not cached:
        return None
    ts, value = cached
    if (now_ts - ts) <= ttl:
        return value
    _CACHE.pop(key, None)
    return None

def _cache_set(key: str, value: Any) -> None:
    _CACHE[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def http_get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = 10.0,
    retries: int = 1,
    backoff: float = 0.5,
    session: Optional[requests.Session] = None,
    silent_errors: bool = False,
) -> Optional[requests.Response]:
    """Simple GET helper with retries and default headers."""

    sess = session or _SESSION
    merged_headers = dict(_DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    last_exc: Optional[Exception] = None
    attempts = max(1, retries + 1)
    for attempt in range(attempts):
        try:
            resp = sess.get(url, params=params, headers=merged_headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            logger.debug(
                f"[HTTP] GET {url} failed (attempt {attempt + 1}/{attempts}): {exc}"
            )
            if attempt < attempts - 1:
                time.sleep(backoff * (attempt + 1))

    if last_exc and not silent_errors:
        # Ne pas spammer les warnings pour les APIs non critiques (comme FXStreet)
        if "fxstreet" not in url.lower():
            logger.warning(f"[HTTP] GET {url} failed after {attempts} attempt(s): {last_exc}")
        else:
            logger.debug(f"[HTTP] GET {url} failed after {attempts} attempt(s): {last_exc}")
    return None

def http_get_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = 10.0,
    retries: int = 1,
    backoff: float = 0.5,
    session: Optional[requests.Session] = None,
) -> Optional[Any]:
    """GET helper that returns parsed JSON, or None."""

    resp = http_get(
        url,
        params=params,
        headers=headers,
        timeout=timeout,
        retries=retries,
        backoff=backoff,
        session=session,
    )
    if not resp:
        return None
    try:
        return resp.json()
    except ValueError as exc:
        logger.warning(f"[HTTP] Invalid JSON from {url}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _infer_source_from_url(url: str) -> str:
    url_lower = (url or "").lower()
    if "coindesk" in url_lower:
        return "coindesk"
    if "cointelegraph" in url_lower:
        return "cointelegraph"
    if "reuters" in url_lower:
        return "reuters"
    if "cryptopanic" in url_lower:
        return "cryptopanic"
    if "twitter" in url_lower:
        return "twitter"
    if "google" in url_lower:
        return "google"
    return "other"

def _to_datetime(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    if isinstance(value, time.struct_time):
        return dt.datetime.fromtimestamp(calendar.timegm(value), tz=dt.timezone.utc)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S"):
                try:
                    return dt.datetime.strptime(value, fmt).replace(tzinfo=dt.timezone.utc)
                except ValueError:
                    continue
    return None

def _normalise_entry(
    *,
    source: str,
    title: str,
    link: str,
    published: Any,
    summary: Optional[str] = None,
    raw: Optional[Any] = None,
) -> Dict[str, Any]:
    published_dt = _to_datetime(published)
    return {
        "source": source,
        "title": (title or "").strip(),
        "link": link or "",
        "summary": (summary or "").strip(),
        "published": published,
        "published_dt": published_dt,
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# RSS helpers
# ---------------------------------------------------------------------------

def fetch_rss_feed(
    url: str,
    *,
    max_items: int = 20,
    ttl: float = 600.0,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    cache_key = _make_cache_key("rss", url, max_items)
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    try:
        parsed = feedparser.parse(url, request_headers=headers or _DEFAULT_HEADERS)
    except Exception as exc:
        logger.warning(f"[RSS] Failed to parse {url}: {exc}")
        return []

    entries: List[Dict[str, Any]] = []
    source = _infer_source_from_url(url)
    for entry in parsed.entries[:max_items]:
        entries.append(
            _normalise_entry(
                source=source,
                title=getattr(entry, "title", ""),
                link=getattr(entry, "link", ""),
                published=getattr(entry, "published", getattr(entry, "updated", None)),
                summary=getattr(entry, "summary", ""),
                raw=entry,
            )
        )

    _cache_set(cache_key, entries)
    return entries


def fetch_coindesk(*, limit: int = 20, ttl: float = 600.0) -> List[Dict[str, Any]]:
    url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
    return fetch_rss_feed(url, max_items=limit, ttl=ttl)


def fetch_reuters(*, limit: int = 20, ttl: float = 600.0) -> List[Dict[str, Any]]:
    url = "https://feeds.reuters.com/reuters/cryptoNews"
    return fetch_rss_feed(url, max_items=limit, ttl=ttl)


def fetch_cryptopanic(
    *,
    token: Optional[str],
    currencies: Optional[Sequence[str]] = None,
    regions: Optional[Sequence[str]] = None,
    filter_by: Optional[str] = None,
    kind: str = "news",
    limit: int = 50,
    ttl: float = 300.0,
) -> List[Dict[str, Any]]:
    if not token:
        logger.debug("[NEWS] CryptoPanic token missing -> skip")
        return []

    base_url = "https://cryptopanic.com/api/v1/posts/"
    params: Dict[str, Any] = {
        "auth_token": token,
        "kind": kind,
        "limit": max(1, min(limit, 100)),
    }
    if currencies:
        params["currencies"] = ",".join(sorted(set(currencies)))
    if regions:
        params["regions"] = ",".join(sorted(set(regions)))
    if filter_by:
        params["filter"] = filter_by

    cache_key = _make_cache_key("cryptopanic", params)
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    data = http_get_json(base_url, params=params, timeout=8, retries=1)
    if not data or "results" not in data:
        return []

    entries: List[Dict[str, Any]] = []
    for post in data.get("results", [])[:limit]:
        entries.append(
            _normalise_entry(
                source="cryptopanic",
                title=post.get("title", ""),
                link=post.get("url", ""),
                published=post.get("published_at"),
                summary=post.get("body", ""),
                raw=post,
            )
        )

    _cache_set(cache_key, entries)
    return entries


# ---------------------------------------------------------------------------
# Sentiment data sources
# ---------------------------------------------------------------------------

def fetch_twitter_sentiment(
    query: str,
    *,
    bearer_token: Optional[str] = None,
    max_results: int = 50,
    timeout: float = 10.0,
) -> Optional[Dict[str, Any]]:
    token = bearer_token or os.getenv("TWITTER_BEARER_TOKEN")
    if not token:
        logger.debug("[SENT] No Twitter token provided -> skip")
        return None

    params = {
        "query": query,
        "max_results": max(10, min(max_results, 100)),
        "tweet.fields": "created_at,lang",
    }
    headers = {"Authorization": f"Bearer {token}"}
    resp = http_get(
        "https://api.twitter.com/2/tweets/search/recent",
        params=params,
        headers=headers,
        timeout=timeout,
        retries=1,
    )
    if not resp:
        return None

    try:
        payload = resp.json()
    except ValueError as exc:
        logger.warning(f"[SENT] Twitter invalid JSON: {exc}")
        return None

    tweets = payload.get("data", [])
    if not tweets:
        return {"score": 0.0, "samples": 0, "timestamp": dt.datetime.now(dt.timezone.utc), "raw": payload}

    score_total = 0.0
    count = 0
    for tweet in tweets:
        text = tweet.get("text", "")
        if not text:
            continue
        try:
            sent = TextBlob(text).sentiment.polarity
        except Exception:
            sent = 0.0
        score_total += sent
        count += 1

    avg = score_total / count if count else 0.0
    return {
        "score": avg,
        "samples": count,
        "timestamp": dt.datetime.now(dt.timezone.utc),
        "raw": payload,
    }


def fetch_google_trends(
    keyword: str,
    *,
    timeframe: str = "now 4-H",
    geo: str = "US",
) -> Optional[Dict[str, Any]]:
    try:
        from pytrends.request import TrendReq  # type: ignore
    except Exception as exc:
        logger.debug(f"[SENT] pytrends unavailable -> skip Google Trends ({exc})")
        return None

    try:
        client = TrendReq(hl="en-US", tz=0)
        client.build_payload([keyword], timeframe=timeframe, geo=geo)
        df = client.interest_over_time()
    except Exception as exc:
        logger.warning(f"[SENT] Google Trends request failed: {exc}")
        return None

    if df is None or df.empty:
        return None

    latest = df.iloc[-1]
    timestamp = latest.name.to_pydatetime()
    value = float(latest.get(keyword, 0.0))
    normalized = value / 100.0 if value else 0.0
    return {"score": normalized, "value": value, "timestamp": timestamp}


# ---------------------------------------------------------------------------
# FXStreet calendar
# ---------------------------------------------------------------------------

# Cache pour éviter de spammer les logs sur API non disponible
_FXSTREET_LAST_ERROR_TIME: float = 0.0
_FXSTREET_ERROR_COOLDOWN: float = 300.0  # 5 minutes entre les logs d'erreur

def fetch_fxstreet_calendar(
    *,
    start: Optional[dt.datetime] = None,
    end: Optional[dt.datetime] = None,
    importance: Optional[Sequence[str]] = None,
    base_url: str = "https://calendar-api.fxstreet.com/events",
    ttl: float = 300.0,
) -> List[Dict[str, Any]]:
    global _FXSTREET_LAST_ERROR_TIME

    start_dt = start or dt.datetime.now(dt.timezone.utc)
    end_dt = end or (start_dt + dt.timedelta(hours=12))

    params: Dict[str, Any] = {
        "from": start_dt.isoformat(),
        "to": end_dt.isoformat(),
    }
    if importance:
        params["importance"] = ",".join(sorted({imp.lower() for imp in importance}))

    cache_key = _make_cache_key("fxstreet", base_url, params)
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    # Cache les erreurs pour éviter de spammer les logs
    error_cache_key = f"fxstreet_error_{base_url}"
    if _cache_get(error_cache_key, _FXSTREET_ERROR_COOLDOWN) is not None:
        return []  # API en erreur, skip silencieusement

    data = http_get_json(base_url, params=params, timeout=10, retries=1)
    if not data:
        # Cache l'erreur pour éviter de répéter
        _cache_set(error_cache_key, True)
        now = time.time()
        if now - _FXSTREET_LAST_ERROR_TIME > _FXSTREET_ERROR_COOLDOWN:
            logger.debug("[FUND] FXStreet calendar API indisponible - calendrier économique désactivé temporairement")
            _FXSTREET_LAST_ERROR_TIME = now
        return []

    events = data if isinstance(data, list) else data.get("events", [])
    if not isinstance(events, list):
        logger.debug("[FUND] FXStreet payload not list -> skip")
        return []

    _cache_set(cache_key, events)
    return events


# ---------------------------------------------------------------------------
# News aggregation
# ---------------------------------------------------------------------------

def aggregate_news(symbol: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []

    rss_urls = params.get("news_feeds", [])
    max_per = int(params.get("max_per_feed", 20))
    ttl = float(params.get("cache_ttl", 900.0))

    for url in rss_urls:
        sources.extend(fetch_rss_feed(url, max_items=max_per, ttl=ttl))

    if params.get("enable_coindesk", True):
        sources.extend(fetch_coindesk(limit=max_per, ttl=ttl))

    if params.get("enable_reuters", True):
        sources.extend(fetch_reuters(limit=max_per, ttl=ttl))

    if params.get("enable_cryptopanic", False):
        token = params.get("cryptopanic_token") or os.getenv("CRYPTOPANIC_TOKEN")
        if token:
            currencies = params.get("cryptopanic_currencies") or [symbol[:3]]
            sources.extend(
                fetch_cryptopanic(
                    token=token,
                    currencies=currencies,
                    regions=params.get("cryptopanic_regions"),
                    filter_by=params.get("cryptopanic_filter"),
                    kind=params.get("cryptopanic_kind", "news"),
                    limit=params.get("cryptopanic_limit", max_per),
                    ttl=params.get("cryptopanic_ttl", 300.0),
                )
            )

    # Deduplicate by title/link pair and sort by recency
    seen: Dict[str, Dict[str, Any]] = {}
    for item in sources:
        key = (item.get("title") or "").lower() or item.get("link", "")
        if not key:
            key = str(len(seen))
        if key not in seen:
            seen[key] = item
        else:
            existing = seen[key]
            if (existing.get("published_dt") or dt.datetime.min.replace(tzinfo=dt.timezone.utc)) < (
                item.get("published_dt") or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
            ):
                seen[key] = item

    deduped = list(seen.values())
    deduped.sort(
        key=lambda entry: entry.get("published_dt") or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        reverse=True,
    )
    return deduped
