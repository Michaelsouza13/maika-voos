import re
import os
import logging
from typing import List, Optional

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
                    "--disable-gpu",
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
            )
            page = await context.new_page()

            try:
                q = (
                    f"Flights+from+{params.origin}+to+{params.destination}"
                    f"+on+{params.depart_date}"
                )
                if params.return_date:
                    q += f"+return+on+{params.return_date}"

                url = f"https://www.google.com/travel/flights?q={q}"
                logger.info(f"Navigating to: {url}")

                await page.goto(url, wait_until="load", timeout=45000)
                await page.wait_for_timeout(5000)

                try:
                    cookie_btn = page.locator("button:has-text('Aceitar')")
                    if await cookie_btn.count() > 0:
                        await cookie_btn.first.click()
                        await page.wait_for_timeout(1500)
                except Exception:
                    pass

                selectors = [
                    'div[role="list"]',
                    'ol[role="list"]',
                    '[data-flights-result]',
                    'ol.Rk10dc',
                    'div.Rk10dc',
                    '[class*="result"]',
                    '[jsname]',
                ]

                found_selector = None
                for sel in selectors:
                    try:
                        await page.wait_for_selector(sel, timeout=4000)
                        found_selector = sel
                        logger.info(f"Found container: {sel}")
                        break
                    except PwTimeout:
                        continue

                if not found_selector:
                    logger.warning("No result container found. Debugging...")
                    title = await page.title()
                    logger.info(f"Page title: {title}")
                    content_preview = await page.evaluate(
                        "() => document.body?.innerText?.substring(0, 2000) || 'no body'"
                    )
                    logger.info(f"Page text preview: {content_preview}")
                    try:
                        await page.screenshot(
                            path="/tmp/gf_debug.png", full_page=True
                        )
                        logger.info("Screenshot saved to /tmp/gf_debug.png")
                    except Exception as e:
                        logger.error(f"Screenshot failed: {e}")
                    return []

                await page.wait_for_timeout(3000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

                raw, prices, structured = await page.evaluate("""
                    () => {
                        const items = [];

                        const containers = [
                            ...document.querySelectorAll('[role="list"] > [role="listitem"]'),
                            ...document.querySelectorAll('ol[role="list"] > li'),
                            ...document.querySelectorAll('[jsname]'),
                        ];

                        const seen = new Set();
                        for (const el of containers) {
                            const text = el.textContent.trim();
                            if (text && text.length > 20 && !seen.has(text)) {
                                seen.add(text);
                                items.push(text);
                            }
                        }

                        if (items.length === 0) {
                            document.querySelectorAll('*').forEach(el => {
                                const text = el.textContent.trim();
                                if (text.length > 30 && /R\\$/.test(text)) {
                                    if (!seen.has(text)) {
                                        seen.add(text);
                                        items.push(text);
                                    }
                                }
                            });
                        }

                        const allSpans = [...document.querySelectorAll('span, div, button')];
                        const prices = allSpans
                            .filter(s => {
                                const t = s.textContent.trim();
                                return /^R?\\$\\s?[\\d.,]+$/.test(t) || /^\\d{1,3}(?:\\.\\d{3})*,\\d{2}$/.test(t);
                            })
                            .map(s => s.textContent.trim())
                            .slice(0, 20);

                        const structured = [];
                        for (const item of items) {
                            const lines = item.split('\\n').map(l => l.trim()).filter(Boolean);
                            const airline = lines.find(l =>
                                /latam|gol|azul|tap|american|united|delta|avianca/i.test(l)
                            ) || '';
                            const priceMatch = item.match(/R\\$\\s*([\\d.]+,\\d{2})/);
                            const price = priceMatch ? priceMatch[0] : '';
                            const stopsMatch = item.match(/(direto|não\\s*para|\\d+\\s*escala)/i);
                            const stops = stopsMatch ? stopsMatch[0] : '';
                            structured.push({ airline, price, stops, text: item });
                        }

                        return { raw: items, prices, structured };
                    }
                """)

                logger.info(f"Raw items: {len(raw)}, Prices: {len(prices)}, Structured: {len(structured)}")

                results = self._parse_results(raw, prices, params)
                logger.info(f"Parsed {len(results)} results")

            except Exception as e:
                logger.error(f"Google Flights scraper error: {e}", exc_info=True)
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
            "azul": "Azul",
            "voepass": "Voepass",
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
            if re.search(
                r"\b(direto|não para|sem escalas|direct|non.?stop)\b",
                text_lower,
            ):
                stops = 0
            elif re.search(r"\b(1 escala|1 parada)\b", text_lower):
                stops = 1
            elif re.search(r"\b(2 escalas|2 paradas)\b", text_lower):
                stops = 2

            duration = "—"
            dur_match = re.search(r"(\d{1,2})\s*h\s*(?:(\d{1,2})\s*min)?", text_lower)
            if dur_match:
                h = dur_match.group(1)
                m = dur_match.group(2) or "00"
                duration = f"{h}h{m}"

            price = None
            if price_index < len(prices):
                price = self._parse_price(prices[price_index])
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
