# utils/econ_api.py
from datetime import datetime
from typing import List
from agents.fundamental import Event

class EconCalendarClient:
    def __init__(self, provider="dummy", **kwargs):
        self.provider = provider
        self.kwargs = kwargs

    def events_between(self, start: datetime, end: datetime) -> List[Event]:
        # TODO: implémentez une vraie source (ex: service interne / proxy)
        # Retour de secours : aucune news
        return []
