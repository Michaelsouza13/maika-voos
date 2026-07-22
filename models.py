from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime


class SearchRequest(BaseModel):
    origin: str
    destination: str
    depart_date: date
    return_date: Optional[date] = None
    max_price: Optional[float] = None
    max_stops: Optional[int] = None
    source: str = "all"


class FlightResult(BaseModel):
    airline: str
    from_code: str
    to_code: str
    depart_time: str
    return_time: Optional[str] = None
    stops: int = 0
    duration: str
    price: float
    currency: str = "BRL"
    url: str
    source: str
    logo: Optional[str] = None


class SearchResponse(BaseModel):
    results: List[FlightResult]
    source: str
    query: SearchRequest
    timestamp: str
    total: int
