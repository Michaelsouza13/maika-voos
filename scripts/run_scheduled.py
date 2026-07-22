"""Script para GitHub Actions - busca agendada de passagens"""
import asyncio
import json
import os
import sys
from datetime import date, timedelta, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import SearchRequest
from scrapers import GoogleFlightsScraper, DecolarScraper

ORIGIN = os.getenv("ORIGIN", "GRU")
DESTINATION = os.getenv("DESTINATION", "")
DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", "7"))

POPULAR_ROUTES = [
    ("GRU", "REC"),
    ("GRU", "SSA"),
    ("GRU", "FOR"),
    ("GRU", "CGH"),
    ("GRU", "BSB"),
    ("GRU", "POA"),
    ("GRU", "CNF"),
    ("GRU", "CWB"),
    ("GRU", "FLN"),
    ("GRU", "GIG"),
    ("GRU", "NAT"),
    ("GRU", "MIA"),
    ("GRU", "LIS"),
    ("GRU", "MCO"),
    ("GRU", "JFK"),
]


async def main():
    scraper_gf = GoogleFlightsScraper()
    scraper_dec = DecolarScraper()
    all_results = []

    routes = []
    if DESTINATION:
        routes.append((ORIGIN, DESTINATION.upper()))
    else:
        routes = POPULAR_ROUTES

    depart_date = date.today() + timedelta(days=DAYS_AHEAD)
    return_date = depart_date + timedelta(days=7)

    for origin, dest in routes:
        print(f"Buscando {origin} -> {dest} em {depart_date}...")

        params = SearchRequest(
            origin=origin,
            destination=dest,
            depart_date=depart_date,
            return_date=return_date,
        )

        for scraper in [scraper_gf, scraper_dec]:
            try:
                results = await scraper.search(params)
                for r in results:
                    all_results.append(r.model_dump())
                print(f"  {scraper.name}: {len(results)} resultados")
            except Exception as e:
                print(f"  Erro no {scraper.name}: {e}")

        await asyncio.sleep(2)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(all_results),
        "routes_searched": len(routes),
        "results": all_results,
    }

    out_dir = os.path.join(
        os.path.dirname(__file__), "..", "frontend", "data"
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ofertas.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nTotal de {len(all_results)} ofertas salvas em {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
