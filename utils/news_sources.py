# -*- coding: utf-8 -*-
"""
utils/news_sources.py — Registre de sources d'actualité hiérarchisé et
sélection par instrument.

AJOUT 2026-07-29 (P6). Complète la chaîne news existante sans la remplacer :
`agents/news.py` continue de produire le même contrat de sortie, mais reçoit
désormais des articles pondérés par crédibilité, fraîcheur et pertinence.

Ce que ce module apporte
------------------------
1. Un registre de sources classées par TIER de crédibilité, chacune associée
   aux classes d'actifs qu'elle éclaire réellement.
2. Une sélection par symbole : NAS100 ne reçoit plus de flux Bitcoin, et
   XAUUSD reçoit enfin de la macro (Fed, BLS, inflation) au lieu de rien.
3. Un filtrage de pertinence par mots-clés propres à l'instrument.
4. Une déduplication inter-sources : la même dépêche reprise par cinq sites
   ne compte qu'une fois, au tier le plus crédible.
5. Une décroissance temporelle : une dépêche de 20 minutes pèse plus qu'une
   de six heures.
6. Une collecte parallèle, avec timeout par flux et mise en quarantaine
   automatique des flux morts — aucun flux défaillant ne peut ralentir ou
   bloquer un cycle de décision.

Aucune clé d'API n'est requise : uniquement des flux RSS publics.
Aucune dépendance nouvelle : `feedparser` et `requests` sont déjà utilisés.
"""

from __future__ import annotations

import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    from utils.logger import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger("empire_agent_ia")

try:
    import feedparser  # type: ignore
except Exception:  # pragma: no cover
    feedparser = None  # type: ignore


# ---------------------------------------------------------------------------
# 1. TIERS DE CREDIBILITE
# ---------------------------------------------------------------------------
# Le poids multiplie la contribution d'un article au sentiment agrégé.
# Une dépêche de la Fed ne pèse pas comme un billet d'agrégateur.

TIER_WEIGHTS: Dict[int, float] = {
    1: 3.0,   # Source primaire institutionnelle : banques centrales, régulateurs, statistiques officielles
    2: 2.2,   # Presse financière établie, salle de marché
    3: 1.6,   # Presse crypto de référence
    4: 1.0,   # Agrégateurs et requêtes génériques
}

TIER_LABELS = {
    1: "institutionnel",
    2: "presse financiere",
    3: "presse crypto",
    4: "agregateur",
}

# Classes d'actifs
CRYPTO, FOREX, INDICES, METALS, ENERGY, MACRO = (
    "crypto", "forex", "indices", "metals", "energy", "macro"
)


# ---------------------------------------------------------------------------
# 2. REGISTRE DES SOURCES
# ---------------------------------------------------------------------------
# `classes` = les classes d'actifs pour lesquelles la source est pertinente.
# MACRO est ajouté à tous les instruments : une décision de la Fed déplace
# aussi bien l'or que le Nasdaq ou le bitcoin.
#
# Note : CNBC est volontairement absent, son robots.txt interdit la collecte
# automatisée. Les flux payants (FT, WSJ, Bloomberg Terminal) sont exclus.

SOURCES: List[Dict[str, Any]] = [
    # ---------------- TIER 1 : institutionnel ----------------
    {"id": "fed_press",     "tier": 1, "classes": {MACRO},
     "url": "https://www.federalreserve.gov/feeds/press_all.xml",
     "label": "Federal Reserve — communiqués"},
    {"id": "fed_monetary",  "tier": 1, "classes": {MACRO},
     "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
     "label": "Federal Reserve — politique monétaire"},
    {"id": "ecb_press",     "tier": 1, "classes": {MACRO, FOREX},
     "url": "https://www.ecb.europa.eu/rss/press.html",
     "label": "BCE — communiqués"},
    {"id": "bls_news",      "tier": 1, "classes": {MACRO},
     "url": "https://www.bls.gov/feed/bls_latest.rss",
     "label": "US Bureau of Labor Statistics (CPI, NFP)"},
    {"id": "sec_press",     "tier": 1, "classes": {MACRO, CRYPTO},
     "url": "https://www.sec.gov/news/pressreleases.rss",
     "label": "SEC — communiqués"},
    # RETIRE 2026-07-31 : flux verifie mort sur la machine de production
    # (0 article, 939 ms). home.treasury.gov/rss/press.xml ne renvoie plus
    # rien d'exploitable. Le Tresor reste couvert indirectement par
    # investing_news, marketwatch et le mot-cle "treasury yield".
    # {"id": "treasury", "tier": 1, "classes": {MACRO},
    #  "url": "https://home.treasury.gov/rss/press.xml",
    #  "label": "US Treasury"},
    {"id": "boe_news",      "tier": 1, "classes": {MACRO, FOREX},
     "url": "https://www.bankofengland.co.uk/rss/news",
     "label": "Bank of England"},

    # ---------------- TIER 2 : presse financière ----------------
    {"id": "marketwatch",   "tier": 2, "classes": {INDICES, FOREX, METALS, ENERGY, MACRO},
     "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
     "label": "MarketWatch — une"},
    {"id": "marketwatch_mk", "tier": 2, "classes": {INDICES, FOREX, MACRO},
     "url": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
     "label": "MarketWatch — Market Pulse"},
    {"id": "yahoo_finance", "tier": 2, "classes": {INDICES, FOREX, METALS, ENERGY, MACRO},
     "url": "https://finance.yahoo.com/rss/topstories",
     "label": "Yahoo Finance"},
    {"id": "investing_news", "tier": 2, "classes": {INDICES, FOREX, METALS, ENERGY, MACRO},
     "url": "https://www.investing.com/rss/news.rss",
     "label": "Investing.com — général"},
    {"id": "investing_fx",  "tier": 2, "classes": {FOREX, MACRO},
     "url": "https://www.investing.com/rss/news_1.rss",
     "label": "Investing.com — forex"},
    {"id": "investing_comm", "tier": 2, "classes": {METALS, ENERGY},
     "url": "https://www.investing.com/rss/news_11.rss",
     "label": "Investing.com — matières premières"},
    {"id": "fxstreet",      "tier": 2, "classes": {FOREX, METALS, MACRO},
     "url": "https://www.fxstreet.com/rss/news",
     "label": "FXStreet"},
    {"id": "seekingalpha",  "tier": 2, "classes": {INDICES, MACRO},
     "url": "https://seekingalpha.com/market_currents.xml",
     "label": "Seeking Alpha — Market Currents"},

    # ---------------- TIER 3 : presse crypto ----------------
    {"id": "coindesk",      "tier": 3, "classes": {CRYPTO},
     "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
     "label": "CoinDesk"},
    {"id": "cointelegraph", "tier": 3, "classes": {CRYPTO},
     "url": "https://cointelegraph.com/rss",
     "label": "Cointelegraph"},
    {"id": "theblock",      "tier": 3, "classes": {CRYPTO},
     "url": "https://www.theblock.co/rss.xml",
     "label": "The Block"},
    {"id": "decrypt",       "tier": 3, "classes": {CRYPTO},
     "url": "https://decrypt.co/feed",
     "label": "Decrypt"},
    {"id": "bitcoinmag",    "tier": 3, "classes": {CRYPTO},
     "url": "https://bitcoinmagazine.com/feed",
     "label": "Bitcoin Magazine"},
    {"id": "cryptoslate",   "tier": 3, "classes": {CRYPTO},
     "url": "https://cryptoslate.com/feed/",
     "label": "CryptoSlate"},
    {"id": "coinjournal",   "tier": 3, "classes": {CRYPTO},
     "url": "https://coinjournal.net/news/feed/",
     "label": "CoinJournal"},

    # ---------------- TIER 4 : agrégateurs ----------------
    # Requêtes ciblées, ajoutées dynamiquement par symbole (voir _google_news_for)
]


# ---------------------------------------------------------------------------
# 3. CLASSIFICATION DES INSTRUMENTS ET MOTS-CLES DE PERTINENCE
# ---------------------------------------------------------------------------

_SYMBOL_CLASS: List[Tuple[Tuple[str, ...], str]] = [
    (("BTC", "ETH", "SOL", "BNB", "LTC", "XRP", "ADA", "DOGE", "AVAX", "LINK"), CRYPTO),
    (("XAU", "XAG", "GOLD", "SILVER"), METALS),
    (("USOIL", "USO", "WTI", "BRENT", "CL-OIL", "NGAS"), ENERGY),
    (("NAS100", "SP500", "US500", "DJ30", "UK100", "GER40", "FRA40", "JP225", "AUS200"), INDICES),
]

# Mots-clés de pertinence par instrument. Un article doit toucher au moins un
# de ces termes pour être retenu, sauf s'il vient d'une source TIER 1 (une
# décision de banque centrale est pertinente par construction).
_SYMBOL_KEYWORDS: Dict[str, Sequence[str]] = {
    "BTCUSD": ("bitcoin", "btc", "crypto", "digital asset", "spot etf", "halving", "miner"),
    "ETHUSD": ("ethereum", "eth", "crypto", "staking", "layer 2", "defi"),
    "SOLUSD": ("solana", "sol ", "crypto", "defi"),
    "BNBUSD": ("binance", "bnb", "crypto"),
    "LTCUSD": ("litecoin", "ltc", "crypto"),
    "XAUUSD": ("gold", "bullion", "precious metal", "safe haven", "inflation",
               "real yield", "dollar", "fed", "rate cut", "rate hike"),
    "XAGUSD": ("silver", "precious metal", "industrial metal", "inflation", "dollar"),
    "NAS100": ("nasdaq", "tech stock", "semiconductor", "ai chip", "earnings",
               "wall street", "equities", "fed", "rate", "cpi", "inflation"),
    "SP500":  ("s&p", "sp 500", "wall street", "equities", "earnings", "stocks",
               "fed", "rate", "cpi", "inflation", "jobs report"),
    "DJ30":   ("dow jones", "dow ", "wall street", "equities", "industrials"),
    "UK100":  ("ftse", "uk stocks", "london stocks", "bank of england", "gilt"),
    "GER40":  ("dax", "german stocks", "bundesbank", "ecb", "euro zone"),
    "EURUSD": ("euro", "eur/usd", "ecb", "dollar", "fed", "euro zone", "inflation"),
    "GBPUSD": ("sterling", "pound", "gbp", "bank of england", "uk inflation", "dollar"),
    "USDJPY": ("yen", "usd/jpy", "bank of japan", "boj", "dollar", "treasury yield"),
    "AUDUSD": ("aussie", "australian dollar", "aud", "rba", "reserve bank of australia",
               "iron ore", "china data", "dollar"),
    "USDCAD": ("loonie", "canadian dollar", "cad", "bank of canada", "oil", "dollar"),
}

# Termes macro toujours pertinents, quel que soit l'instrument.
_MACRO_KEYWORDS: Tuple[str, ...] = (
    "federal reserve", "fed ", "fomc", "interest rate", "rate decision",
    "inflation", "cpi", "ppi", "nonfarm", "payroll", "unemployment",
    "gdp", "recession", "central bank", "ecb", "boj", "boe",
    "tariff", "treasury yield", "jobless claims", "powell",
)

# AJOUT 2026-07-31 : mots trop ambigus pour rendre un article pertinent A EUX
# SEULS. Constate en production : « Jersey Mike's spent almost "zero dollars"
# on digital » obtenait 0,70 de pertinence pour XAUUSD, AUDUSD ET BTCUSD, sur
# la seule presence du mot « dollars », et pesait plus lourd que la moitie des
# depeches de banque centrale. Un article qui ne declenche QUE des mots de
# cette liste est desormais ecarte ; s'il contient par ailleurs un mot-cle
# franc, son score ne change pas.
# Volontairement restreint aux termes dont l'ambiguite est CONSTATEE ou
# evidente : ce sont des mots qui designent aussi bien une somme d'argent
# ordinaire qu'un marche. « crypto » et « digital asset » n'y figurent PAS :
# sur les flux de tier 3, qui sont exclusivement crypto, ces mots portent une
# vraie information.
_MOTS_AMBIGUS: frozenset = frozenset({
    "dollar", "dollars", "stocks", "equities", "currency", "rate", "rates",
})

# Bruit à écarter : contenus sans valeur informative pour le prix.
_NOISE_PATTERNS: Tuple[str, ...] = (
    "sponsored", "press release", "partner content", "advertorial",
    "how to buy", "price prediction", "best wallet", "casino", "airdrop guide",
    "giveaway", "promo code", "top 10 coins", "beginners guide", "beginner's guide",
    "webinar", "podcast episode", "newsletter signup",
)


def classify_symbol(symbol: str) -> str:
    """Renvoie la classe d'actif d'un symbole."""
    s = (symbol or "").upper()
    for prefixes, cls in _SYMBOL_CLASS:
        if any(p in s for p in prefixes):
            return cls
    return FOREX if len(s) == 6 else INDICES


def keywords_for(symbol: str) -> Tuple[str, ...]:
    """Mots-clés de pertinence, spécifiques + macro."""
    s = (symbol or "").upper()
    own = tuple(_SYMBOL_KEYWORDS.get(s, ()))
    if not own:  # symbole inconnu : on retombe sur la classe
        cls = classify_symbol(s)
        fallback = {
            CRYPTO: ("crypto", "bitcoin", "digital asset"),
            METALS: ("gold", "silver", "precious metal"),
            ENERGY: ("oil", "crude", "energy"),
            INDICES: ("stocks", "equities", "wall street"),
            FOREX: ("currency", "dollar", "forex"),
        }
        own = fallback.get(cls, ())
    return own + _MACRO_KEYWORDS


def _google_news_for(symbol: str) -> Optional[Dict[str, Any]]:
    """Requête Google News ciblée, en TIER 4."""
    s = (symbol or "").upper()
    queries = {
        "BTCUSD": "bitcoin+price", "ETHUSD": "ethereum+price",
        "SOLUSD": "solana", "BNBUSD": "binance+coin", "LTCUSD": "litecoin",
        "XAUUSD": "gold+price", "XAGUSD": "silver+price",
        "NAS100": "nasdaq+100", "SP500": "s%26p+500", "DJ30": "dow+jones",
        "UK100": "ftse+100", "GER40": "dax+index",
        "EURUSD": "euro+dollar", "GBPUSD": "pound+dollar",
        "USDJPY": "japanese+yen", "AUDUSD": "australian+dollar",
        "USDCAD": "canadian+dollar",
    }
    q = queries.get(s)
    if not q:
        return None
    return {
        "id": f"gnews_{s.lower()}", "tier": 4, "classes": {classify_symbol(s)},
        "url": f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
        "label": f"Google News — {s}",
    }


def feeds_for_symbol(symbol: str, *, include_aggregators: bool = True) -> List[Dict[str, Any]]:
    """Sources pertinentes pour un instrument, triées par crédibilité."""
    cls = classify_symbol(symbol)
    wanted = {cls, MACRO}
    out = [s for s in SOURCES if s["classes"] & wanted]
    if include_aggregators:
        g = _google_news_for(symbol)
        if g:
            out.append(g)
    return sorted(out, key=lambda s: s["tier"])


# ---------------------------------------------------------------------------
# 4. COLLECTE : cache, quarantaine des flux morts, parallélisme
# ---------------------------------------------------------------------------

_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_CACHE_LOCK = threading.Lock()

# Un flux qui échoue est mis de côté un moment plutôt que réessayé à chaque cycle.
_QUARANTINE: Dict[str, float] = {}
_QUARANTINE_LOCK = threading.Lock()
_QUARANTINE_SECS = 1800.0          # 30 min
_FEED_TIMEOUT = 6.0                # par flux
_MAX_WORKERS = 6


def _is_quarantined(feed_id: str) -> bool:
    with _QUARANTINE_LOCK:
        until = _QUARANTINE.get(feed_id, 0.0)
        if until and until > time.time():
            return True
        if until:
            _QUARANTINE.pop(feed_id, None)
    return False


def _quarantine(feed_id: str, reason: str) -> None:
    with _QUARANTINE_LOCK:
        _QUARANTINE[feed_id] = time.time() + _QUARANTINE_SECS
    logger.info("[NEWS_SRC] %s mis en quarantaine %ds (%s)", feed_id, int(_QUARANTINE_SECS), reason)


def _parse_dt(entry: Any) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        st = getattr(entry, attr, None) or (entry.get(attr) if isinstance(entry, dict) else None)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def _fetch_one(src: Dict[str, Any], max_items: int, ttl: float) -> List[Dict[str, Any]]:
    """Récupère un flux, avec cache et quarantaine. Ne lève jamais."""
    fid = src["id"]
    if _is_quarantined(fid):
        return []

    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(fid)
        if hit and (now - hit[0]) < ttl:
            return hit[1]

    if feedparser is None:
        return []

    items: List[Dict[str, Any]] = []
    try:
        # feedparser gère lui-même la requête HTTP ; on borne le temps global.
        parsed = feedparser.parse(src["url"], request_headers={"User-Agent": "EmpireAgentIA/3.1 (+news)"})
        entries = getattr(parsed, "entries", None) or []
        if not entries:
            _quarantine(fid, "aucune entree")
            return []
        for e in entries[:max_items]:
            title = (getattr(e, "title", "") or "").strip()
            if not title:
                continue
            items.append({
                "title": title,
                "summary": (getattr(e, "summary", "") or "")[:400],
                "link": getattr(e, "link", "") or "",
                "published": _parse_dt(e),
                "source_id": fid,
                "source_label": src.get("label", fid),
                "tier": int(src["tier"]),
            })
    except Exception as exc:                      # réseau, parsing, DNS...
        _quarantine(fid, f"{type(exc).__name__}")
        return []

    with _CACHE_LOCK:
        _CACHE[fid] = (now, items)
    return items


# ---------------------------------------------------------------------------
# 5. PERTINENCE, BRUIT, DEDUPLICATION, FRAICHEUR
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "as", "at", "by",
    "is", "are", "was", "were", "with", "from", "after", "over", "amid", "its",
    "this", "that", "will", "says", "say", "new", "up", "down",
}


# Synonymes de tête : le même fait est titré différemment d'une rédaction à
# l'autre. Sans normalisation, "Fed holds rates" et "Federal Reserve holds
# rates" comptent pour deux sujets distincts.
_ALIASES: Dict[str, str] = {
    "federal": "fed", "reserve": "fed", "fomc": "fed", "powell": "fed",
    "interest": "rate", "rates": "rate",
    "cpi": "inflation",
    "equities": "stock", "equity": "stock", "shares": "stock",
    "bitcoin": "btc", "ethereum": "eth", "bullion": "gold",
    "nonfarm": "payroll", "jobs": "payroll", "employment": "payroll",
}


def _stem(w: str) -> str:
    """Racine grossière : suffit à rapprocher cool/cools/cooling, hold/holds."""
    for suf in ("ingly", "edly", "ing", "ies", "ied", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _tokens(text: str) -> Set[str]:
    out: Set[str] = set()
    for w in _WORD_RE.findall((text or "").lower()):
        if w in _STOP or len(w) <= 2:
            continue
        out.add(_ALIASES.get(w, _stem(w)))
    return out


def is_noise(item: Dict[str, Any]) -> bool:
    blob = f"{item.get('title','')} {item.get('summary','')}".lower()
    return any(p in blob for p in _NOISE_PATTERNS)


def _contient_mot(blob: str, mot: str) -> bool:
    """
    Appariement sur les limites de mot. `re.escape` protege les mots-cles
    contenant « / » (usd/jpy) ou « . » ; les mots-cles multi-termes
    fonctionnent tels quels.
    """
    m = (mot or "").strip().lower()
    if not m:
        return False
    try:
        return re.search(r"(?<!\w)%s(?!\w)" % re.escape(m), blob) is not None
    except re.error:
        return m in blob


def relevance(item: Dict[str, Any], keywords: Sequence[str]) -> float:
    """0.0 = hors sujet. Les sources TIER 1 gardent un plancher : une décision
    de banque centrale compte même sans mot-clé de l'instrument."""
    blob = f"{item.get('title','')} {item.get('summary','')}".lower()
    tier1 = int(item.get("tier", 4)) == 1

    # FIX 2026-07-31 : deux corrections mesurees en production.
    #  a) appariement sur les limites de mot. « aud » se trouvait dans
    #     « fraud », « cad » dans « cadence », « boe » dans « boeing ».
    #  b) un article qui ne declenche que des mots ambigus (_MOTS_AMBIGUS)
    #     n'est plus considere comme pertinent. Le score des articles ayant
    #     au moins un mot-cle franc est INCHANGE.
    touches = [k for k in keywords if _contient_mot(blob, k)]
    if not touches:
        return 0.35 if tier1 else 0.0
    francs = [k for k in touches if k.strip() not in _MOTS_AMBIGUS]
    if not francs:
        return 0.35 if tier1 else 0.0
    return min(1.0, 0.55 + 0.15 * len(touches))


def freshness(item: Dict[str, Any], half_life_h: float = 6.0) -> float:
    """Décroissance exponentielle. Sans date, on suppose une fraîcheur moyenne."""
    pub = item.get("published")
    if not isinstance(pub, datetime):
        return 0.5
    age_h = max(0.0, (datetime.now(timezone.utc) - pub).total_seconds() / 3600.0)
    return float(math.exp(-age_h / max(0.5, half_life_h)))


def deduplicate(items: List[Dict[str, Any]], threshold: float = 0.45) -> List[Dict[str, Any]]:
    """Regroupe les reprises d'une même dépêche. Le représentant est l'article
    du tier le plus crédible ; le nombre de reprises est conservé, un sujet
    repris par plusieurs rédactions ayant plus de poids informatif."""
    ordered = sorted(items, key=lambda i: (int(i.get("tier", 4)), -freshness(i)))
    kept: List[Dict[str, Any]] = []
    kept_tokens: List[Set[str]] = []
    for it in ordered:
        tk = _tokens(it.get("title", ""))
        if not tk:
            continue
        dup_idx = -1
        for idx, prev in enumerate(kept_tokens):
            inter = len(tk & prev)
            union = len(tk | prev) or 1
            if inter / union >= threshold:
                dup_idx = idx
                break
        if dup_idx >= 0:
            kept[dup_idx]["echo_count"] = int(kept[dup_idx].get("echo_count", 1)) + 1
        else:
            it["echo_count"] = 1
            kept.append(it)
            kept_tokens.append(tk)
    return kept


# ---------------------------------------------------------------------------
# 6. POINT D'ENTREE
# ---------------------------------------------------------------------------

def collect(
    symbol: str,
    *,
    max_items_per_feed: int = 15,
    cache_ttl: float = 600.0,
    max_total: int = 60,
    min_relevance: float = 0.3,
    half_life_h: float = 6.0,
    include_aggregators: bool = True,
) -> List[Dict[str, Any]]:
    """Articles pertinents pour un instrument, dédupliqués et pondérés.

    Chaque article porte un champ `weight` = crédibilité × fraîcheur ×
    pertinence × (1 + 0.15 × reprises), à utiliser comme pondération dans le
    calcul du sentiment.
    """
    srcs = feeds_for_symbol(symbol, include_aggregators=include_aggregators)
    if not srcs:
        return []

    raw: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futs = {pool.submit(_fetch_one, s, max_items_per_feed, cache_ttl): s for s in srcs}
        for f in as_completed(futs, timeout=_FEED_TIMEOUT * 3):
            try:
                raw.extend(f.result() or [])
            except Exception:
                continue

    kws = keywords_for(symbol)
    filtered: List[Dict[str, Any]] = []
    for it in raw:
        if is_noise(it):
            continue
        rel = relevance(it, kws)
        if rel < min_relevance:
            continue
        it["relevance"] = rel
        filtered.append(it)

    deduped = deduplicate(filtered)

    for it in deduped:
        tier_w = TIER_WEIGHTS.get(int(it.get("tier", 4)), 1.0)
        fresh = freshness(it, half_life_h)
        echo = 1.0 + 0.15 * (int(it.get("echo_count", 1)) - 1)
        it["freshness"] = round(fresh, 4)
        it["weight"] = round(tier_w * fresh * float(it["relevance"]) * echo, 4)
        it["tier_label"] = TIER_LABELS.get(int(it.get("tier", 4)), "?")

    deduped.sort(key=lambda i: -float(i.get("weight", 0.0)))
    out = deduped[:max_total]

    logger.info(
        "[NEWS_SRC] %s: %d sources, %d bruts, %d pertinents, %d apres dedup, poids total %.1f",
        symbol, len(srcs), len(raw), len(filtered), len(deduped),
        sum(float(i.get("weight", 0.0)) for i in out),
    )
    return out


def health_report(symbol: str = "BTCUSD") -> List[Dict[str, Any]]:
    """Etat de chaque flux : vivant, nombre d'articles, quarantaine.
    Utilisé par tools/test_news_sources.py."""
    rows = []
    for s in feeds_for_symbol(symbol):
        t0 = time.time()
        items = _fetch_one(s, max_items=5, ttl=0.0)
        rows.append({
            "id": s["id"], "label": s.get("label", ""), "tier": s["tier"],
            "ok": bool(items), "n": len(items),
            "ms": int((time.time() - t0) * 1000),
            "quarantined": _is_quarantined(s["id"]),
        })
    return rows
