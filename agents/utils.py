# agents/utils.py
from __future__ import annotations

from typing import Any, Dict

from utils.config import get_symbol_profile, load_config


def merge_agent_params(symbol: str, agent_key: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Merge default -> global config -> symbol overrides for an agent.

    Order of precedence (higher overrides lower):
    1. defaults provided by the caller
    2. config.yaml -> <agent_key>.params
    3. profiles.yaml -> profiles.<symbol>.agents.<agent_key>.params
    (overrides.yaml est lu par get_symbol_profile / load_config).
    """
    cfg = load_config() or {}
    merged: Dict[str, Any] = dict(defaults or {})

    global_params = ((cfg.get(agent_key) or {}).get("params") or {})
    merged.update(global_params)

    profile = get_symbol_profile(symbol) or {}
    agents_section = profile.get("agents") or {}
    profile_entry = agents_section.get(agent_key) or {}
    profile_params = profile_entry.get("params") if isinstance(profile_entry, dict) else {}
    if profile_params:
        merged.update(profile_params)

    return merged
