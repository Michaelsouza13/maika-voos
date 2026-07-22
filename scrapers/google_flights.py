import re
import logging
from typing import List, Optional
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PwTimeout

from .base import BaseScraper
from models import SearchRequest, FlightResult

logger = logging.getLogger(__name__)


class GoogleFlightsScraper(BaseScraper):
    def __init__(self):
        self.name = "google_flights"

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
                permissions=[],
            )
            page = await context.new_page()

            try:
                q = f"Flights+from+{params.origin}+to+{params.destination}+on+{params.depart_date}"
                if params.return_date:
                    q += f"+return+on+{params.return_date}"

                url = f"https://www.google.com/travel/flights?q={q}"
                logger.info(f"Navigating to: {url}")

                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(4000)

                try:
                    cookie_btn = page.locator("button:has-text('Aceitar')")
                    if await cookie_btn.count() > 0:
                        await cookie_btn.first.click()
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

                try:
                    await page.wait_for_selector(
                        'div[role="list"]', timeout=15000
                    )
                    await page.wait_for_timeout(2000)
                except PwTimeout:
                    logger.warning("Timeout waiting for results list")
                    return []

                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

                raw = await page.evaluate("""
                    () => {
                        const items = [...document.querySelectorAll('[role="list"] > [role="listitem"]')];
                        return items.map(item => item.textContent);
                    }
                """)

                prices = await page.evaluate("""
                    () => {
                        const spans = [...document.querySelectorAll('span')];
                        return spans
                            .filter(s => {
                                const t = s.textContent.trim();
                                return /^R?\\$\\s?[\\d.,]+$/.test(t) || /^\\d{1,3}(?:\\.\\d{3})*,\\d{2}$/.test(t);
                            })
                            .map(s => s.textContent.trim());
                    }
                """)

                results = self._parse_results(raw, prices, params)

            except Exception as e:
                logger.error(f"Google Flights scraper error: {e}")
            finally:
                await browser.close()

        return self._filter_results(results, params)

    def _parse_results(
        self,
        raw_texts: List[str],
        prices: List[str],
        params: SearchRequest,
    ) -> List[FlightResult]:
        results = []
        price_index = 0

        airline_map = {
            "latam": "LATAM",
            "gol": "GOL",
            "voepass": "Voepass",
            "azul": "Azul",
            "american airlines": "American Airlines",
            "united": "United",
            "delta": "Delta",
            "air france": "Air France",
            "tap": "TAP",
            "tap air portugal": "TAP",
            "iberia": "Iberia",
            "british airways": "British Airways",
            "emirates": "Emirates",
            "qatar": "Qatar Airways",
            "avianca": "Avianca",
            "copa": "Copa Airlines",
            "jetblue": "JetBlue",
            "spirit": "Spirit",
        }

        known_airlines = list(airline_map.keys()) + list(airline_map.values())

        for text in raw_texts:
            text_lower = text.lower()

            airline = None
            for alias, name in airline_map.items():
                if alias in text_lower:
                    airline = name
                    break

            if not airline:
                for name in known_airlines:
                    if name.lower() in text_lower:
                        airline = name
                        break

            if not airline:
                continue

            stops = 2
            if "não para" in text_lower or "direto" in text_lower or "direct" in text_lower:
                stops = 0
            elif "1 escala" in text_lower or "1 parada" in text_lower:
                stops = 1
            elif "2 escalas" in text_lower or "2 paradas" in text_lower:
                stops = 2

            duration = "—"
            dur_match = re.search(r"(\d{1,2})\s*h\s*(?:(\d{1,2})\s*min)?", text_lower)
            if dur_match:
                h = dur_match.group(1)
                m = dur_match.group(2) or "00"
                duration = f"{h}h{m}"

            time_match = re.findall(
                r"(\d{1,2}:\d{2})\s*(?:da\s*manhã|da\s*tarde|da\s*noite|—)?",
                text_lower,
            )

            price = None
            if price_index < len(prices):
                price_raw = prices[price_index]
                price = self._parse_price(price_raw)
                price_index += 1

            if not price:
                price_brl = re.search(
                    r"r\$\s*([\d.]+,\d{2})", text_lower
                )
                if price_brl:
                    price = self._parse_price(price_brl.group(0))

            if not price:
                continue

            result = FlightResult(
                airline=airline,
                from_code=params.origin.upper(),
                to_code=params.destination.upper(),
                depart_time=str(params.depart_date),
                return_time=str(params.return_date) if params.return_date else None,
                stops=stops,
                duration=duration,
                price=price,
                currency="BRL",
                url=f"https://www.google.com/travel/flights?q=Flights+from+{params.origin}+to+{params.destination}+on+{params.depart_date}",
                source="google_flights",
                logo=self._get_airline_logo(airline),
            )

            results.append(result)

        return results

    def _parse_price(self, text: str) -> Optional[float]:
        if not text:
            return None
        digits = re.sub(r"[^\d,.]", "", text)
        if "," in digits and "." in digits:
            if digits.rindex(",") > digits.rindex("."):
                digits = digits.replace(".", "")
                digits = digits.replace(",", ".")
            else:
                digits = digits.replace(",", "")
        elif "," in digits:
            digits = digits.replace(",", ".")
        try:
            return round(float(digits), 2)
        except ValueError:
            return None

    def _get_airline_logo(self, airline: str) -> str:
        slugs = {
            "LATAM": "latam-airlines",
            "GOL": "gol",
            "Azul": "azul",
            "Voepass": "voepass",
            "American Airlines": "american-airlines",
            "United": "united-airlines",
            "Delta": "delta-air-lines",
            "Air France": "air-france",
            "TAP": "tap-air-portugal",
            "Iberia": "iberia",
            "British Airways": "british-airways",
            "Emirates": "emirates",
            "Qatar Airways": "qatar-airways",
            "Avianca": "avianca",
            "Copa Airlines": "copa-airlines",
            "JetBlue": "jetblue",
            "Spirit": "spirit-airlines",
        }
        slug = slugs.get(airline, airline.lower().replace(" ", "-"))
        return f"https://www.gstatic.com/flights/airline_logos/70px/{slug}.png"
