import re
import json
import logging
from typing import List, Optional
from urllib.parse import quote

from playwright.async_api import async_playwright, TimeoutError as PwTimeout

from .base import BaseScraper
from models import SearchRequest, FlightResult

logger = logging.getLogger(__name__)


class DecolarScraper(BaseScraper):
    def __init__(self):
        self.name = "decolar"

    async def search(self, params: SearchRequest) -> List[FlightResult]:
        results = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1280, "height": 900},
                extra_http_headers={
                    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )
            page = await context.new_page()

            try:
                origin = quote(params.origin.upper())
                dest = quote(params.destination.upper())
                depart = params.depart_date.isoformat()

                if params.return_date:
                    ret = params.return_date.isoformat()
                    url = (
                        f"https://www.decolar.com/shop/flights/search?"
                        f"from={origin}&to={dest}&depart={depart}&return={ret}&pax=1"
                    )
                else:
                    url = (
                        f"https://www.decolar.com/shop/flights/search?"
                        f"from={origin}&to={dest}&depart={depart}&pax=1"
                    )

                logger.info(f"Decolar URL: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)

                raw = await page.evaluate("""
                    () => {
                        const scripts = [...document.querySelectorAll('script')];
                        for (const s of scripts) {
                            const t = s.textContent || '';
                            if (t.includes('__INITIAL_STATE__') || t.includes('initialState')) {
                                return t;
                            }
                        }
                        return null;
                    }
                """)

                if raw:
                    results = self._parse_initial_state(raw, params)
                else:
                    results = await self._parse_from_dom(page, params)

            except Exception as e:
                logger.error(f"Decolar scraper error: {e}")
            finally:
                await browser.close()

        return self._filter_results(results, params)

    def _parse_initial_state(
        self, raw_js: str, params: SearchRequest
    ) -> List[FlightResult]:
        results = []
        try:
            match = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?});", raw_js, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                flights = (
                    data.get("flights", {})
                    .get("results", {})
                    .get("items", [])
                )
                for f in flights:
                    price = (
                        f.get("price", {})
                        .get("total", {})
                        .get("amount", 0)
                    )
                    if price and isinstance(price, (int, float)):
                        results.append(
                            FlightResult(
                                airline=f.get("airline", {}).get("name", "Desconhecida"),
                                from_code=params.origin.upper(),
                                to_code=params.destination.upper(),
                                depart_time=f.get("departure", {}).get("date", str(params.depart_date)),
                                return_time=str(params.return_date) if params.return_date else None,
                                stops=f.get("stops", 0),
                                duration=f.get("duration", {}).get("text", "—"),
                                price=float(price),
                                currency="BRL",
                                url=f.get("deepLink", ""),
                                source="decolar",
                                logo=f.get("airline", {}).get("logo", ""),
                            )
                        )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse Decolar initial state: {e}")
        return results

    async def _parse_from_dom(
        self, page, params: SearchRequest
    ) -> List[FlightResult]:
        try:
            await page.wait_for_selector(
                '[data-testid="result-card"], .flight-card, .cluster-item, [class*="ResultCard"]',
                timeout=20000,
            )
            await page.wait_for_timeout(2000)
        except PwTimeout:
            logger.warning("Timeout waiting for Decolar results")
            return []

        items = await page.evaluate("""
            () => {
                const selectors = [
                    '[data-testid="result-card"]',
                    '.flight-card',
                    '.cluster-item',
                    '[class*="ResultCard"]',
                ];
                for (const sel of selectors) {
                    const cards = [...document.querySelectorAll(sel)];
                    if (cards.length > 0) {
                        return cards.map(c => c.textContent);
                    }
                }
                return [];
            }
        """)

        results = []
        for text in items:
            if not text:
                continue

            text_lower = text.lower()
            price = self._extract_price(text)
            if not price:
                continue

            airline = self._extract_airline(text)
            if not airline:
                continue

            stops = 0
            if "1 escala" in text_lower or "1 parada" in text_lower:
                stops = 1
            elif "direto" in text_lower or "direto" in text_lower:
                stops = 0
            elif "2 escalas" in text_lower:
                stops = 2
            else:
                stops = 1

            duration = "—"
            dur_match = re.search(r"(\d{1,2})h(\d{0,2})", text_lower)
            if dur_match:
                h = dur_match.group(1)
                m = dur_match.group(2) or "00"
                duration = f"{h}h{m}"

            results.append(
                FlightResult(
                    airline=airline,
                    from_code=params.origin.upper(),
                    to_code=params.destination.upper(),
                    depart_time=str(params.depart_date),
                    return_time=str(params.return_date) if params.return_date else None,
                    stops=stops,
                    duration=duration,
                    price=price,
                    currency="BRL",
                    url=(
                        f"https://www.decolar.com/shop/flights/search?"
                        f"from={params.origin}&to={params.destination}"
                        f"&depart={params.depart_date}"
                    ),
                    source="decolar",
                )
            )

        return results

    def _extract_price(self, text: str) -> Optional[float]:
        patterns = [
            r"R\$\s*([\d.]+,\d{2})",
            r"(\d{1,3}(?:\.\d{3})*,\d{2})",
        ]
        for pat in patterns:
            match = re.search(pat, text)
            if match:
                val = match.group(1)
                val = val.replace(".", "").replace(",", ".")
                try:
                    return round(float(val), 2)
                except ValueError:
                    continue
        return None

    def _extract_airline(self, text: str) -> Optional[str]:
        airlines = [
            "LATAM", "GOL", "Azul", "Avianca", "TAP", "American Airlines",
            "United", "Delta", "Air France", "Iberia", "British Airways",
            "Emirates", "Qatar Airways", "Copa Airlines", "JetBlue",
        ]
        for a in airlines:
            if a.lower() in text.lower():
                return a
        return None
