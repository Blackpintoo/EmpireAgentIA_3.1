# -*- coding: utf-8 -*-
"""
utils/pertinence_sentiment.py — SentimentAgent ne peut voter que sur la crypto.

AJOUT 2026-08-16.

L'etat de depart
----------------
`config/profiles.yaml` declare `sentiment: {enabled: true}` sur XAUUSD, EURUSD,
USDJPY, USOUSD, et l'omet (donc actif par defaut) sur GBPUSD, AUDUSD, NAS100,
SP500, UK100, XAGUSD, DJ30, USDCAD, GER40. Sur les 12 symboles actifs, la
configuration annonce donc un agent sentiment partout.

Mais `agents/sentiment.py` refuse au point d'entree :

    def generate_signal(self, bar=None):
        if not _is_crypto(self.symbol):
            return {"signal": None, "trend": "disabled", "reason": "non_crypto"}

L'orchestrateur chargeait donc l'agent, l'appelait une fois en global puis une
fois par timeframe, recevait `signal: None` a chaque fois, et n'inscrivait
rien. Un agent declare actif, structurellement incapable de voter, sur 11
symboles sur 12.

Le cout machine est faible — la garde renvoie immediatement, sans reseau. Ce
qui se corrige ici, c'est la VERACITE de la configuration : rien, ni dans les
profils ni dans les journaux de demarrage, ne laissait deviner que ce vote
etait impossible.

Pourquoi en code et pas dans le YAML
------------------------------------
Poser `enabled: false` sur les 11 symboles aurait marche le jour meme, puis
aurait derive : un symbole ajoute plus tard sans la cle retombe sur le defaut
`enabled: true`, et le trou se rouvre en silence. Le predicat vit deja dans
`agents/sentiment.py` ; on l'interroge, on ne le recopie pas.

L'echappatoire
--------------
`sentiment.non_crypto: true` dans le profil force l'appel malgre tout. Le jour
ou l'agent recevra de vraies sources hors crypto, une cle suffit. On ne se sert
volontairement PAS de `enabled` pour ca : `enabled: true` est deja pose sur des
symboles non crypto, s'en servir comme derogation annulerait le correctif.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def sentiment_pertinent(symbol: str,
                        agents_cfg: Optional[Dict[str, Any]] = None
                        ) -> Tuple[bool, str]:
    """
    Renvoie (pertinent, motif).

    En cas de doute — predicat introuvable, configuration illisible — on
    renvoie True. Le comportement d'avant ce correctif est ainsi preserve :
    un garde d'observabilite ne doit pas pouvoir supprimer un vote par
    accident.
    """
    try:
        cfg = (agents_cfg or {}).get("sentiment")
        if isinstance(cfg, dict) and cfg.get("non_crypto") is True:
            return True, "derogation non_crypto posee dans le profil"
    except Exception:
        pass

    try:
        from agents.sentiment import _is_crypto
    except Exception as exc:
        return True, "predicat crypto indisponible (%s) — on laisse passer" % exc

    try:
        if _is_crypto(symbol):
            return True, "symbole crypto"
        return False, "non_crypto"
    except Exception as exc:
        return True, "predicat crypto en echec (%s) — on laisse passer" % exc
