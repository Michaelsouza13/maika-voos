import logging
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from models import SearchRequest, SearchResponse, FlightResult
from scrapers import GoogleFlightsScraper, DecolarScraper, Milhas123Scraper
from scrapers.base import BaseScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Maika Voos API",
    description="API de busca de passagens aéreas - Google Flights + Decolar",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

scrapers: List[BaseScraper] = [
    GoogleFlightsScraper(),
    DecolarScraper(),
    Milhas123Scraper(),
]

SCRAPER_MAP = {s.name: s for s in scrapers}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scrapers": list(SCRAPER_MAP.keys()),
    }


@app.get("/api/debug")
async def debug():
    import sys, os, json
    info = {
        "python": sys.version,
        "playwright": None,
        "chromium": None,
    }
    try:
        import playwright
        info["playwright"] = playwright.__version__
    except Exception as e:
        info["playwright"] = str(e)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto("https://www.google.com/travel/flights", wait_until="domcontentloaded", timeout=20000)
            title = await page.title()
            text = await page.evaluate("() => document.body?.innerText?.substring(0, 500) || ''")
            await browser.close()
            info["chromium"] = {"google_flights_title": title, "page_preview": text[:200]}
    except Exception as e:
        info["chromium"] = f"Erro: {e}"
    return info


@app.get("/api/search", response_model=SearchResponse)
async def search(
    origin: str = Query(..., description="Origem (ex: GRU, SAO, São Paulo)"),
    destination: str = Query(..., description="Destino (ex: REC, Recife)"),
    depart_date: str = Query(..., description="Data de ida (YYYY-MM-DD)"),
    return_date: str = Query(None, description="Data de volta (YYYY-MM-DD)"),
    max_price: float = Query(None, description="Preço máximo em R$"),
    max_stops: int = Query(None, description="Máximo de escalas (0=só diretos)"),
    source: str = Query("all", description="Fonte: google_flights, decolar, all"),
):
    try:
        from datetime import date
        depart = date.fromisoformat(depart_date)
        ret = date.fromisoformat(return_date) if return_date else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Data inválida: {e}")

    params = SearchRequest(
        origin=origin,
        destination=destination,
        depart_date=depart,
        return_date=ret,
        max_price=max_price,
        max_stops=max_stops,
        source=source,
    )

    all_results: List[FlightResult] = []
    sources_used = []

    if source == "all":
        for scraper in scrapers:
            try:
                res = await scraper.search(params)
                if res:
                    all_results.extend(res)
                    sources_used.append(scraper.name)
                logger.info(f"{scraper.name}: {len(res)} resultados")
            except Exception as e:
                logger.error(f"Erro no scraper {scraper.name}: {e}")
    elif source in SCRAPER_MAP:
        try:
            res = await SCRAPER_MAP[source].search(params)
            all_results.extend(res)
            sources_used.append(source)
            logger.info(f"{source}: {len(res)} resultados")
        except Exception as e:
            logger.error(f"Erro no scraper {source}: {e}")
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Fonte inválida: {source}. Opções: {list(SCRAPER_MAP.keys()) + ['all']}",
        )

    all_results.sort(key=lambda r: r.price)

    return SearchResponse(
        results=all_results,
        source="+".join(sources_used) if sources_used else "none",
        query=params,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total=len(all_results),
    )
