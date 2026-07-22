from abc import ABC, abstractmethod
from typing import List, Optional

from models import SearchRequest, FlightResult


class BaseScraper(ABC):
    def __init__(self):
        self.name = "base"

    @abstractmethod
    async def search(self, params: SearchRequest) -> List[FlightResult]:
        pass

    def _filter_results(
        self, results: List[FlightResult], params: SearchRequest
    ) -> List[FlightResult]:
        filtered = []
        for r in results:
            if params.max_price and r.price > params.max_price:
                continue
            if params.max_stops is not None and r.stops > params.max_stops:
                continue
            filtered.append(r)
        return filtered
