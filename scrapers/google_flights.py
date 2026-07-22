import re
import logging
from typing import List, Optional

from playwright.async_api import async_playwright, TimeoutError as PwTimeout

from .base import BaseScraper
from models import SearchRequest, FlightResult

logger = logging.getLogger(__name__)


class GoogleFlightsScraper(BaseScraper):
    def __init__(self):
        self.name = "google_flights"

    async def _try_search_url(
        self, page, params: SearchRequest
    ) -> Optional[bool]:
        q = (
            f"Flights+from+{params.origin}+to+{params.destination}"
            f"+on+{params.depart_date}"
        )
        if params.return_date:
            q += f"+return+on+{params.return_date}"

        for path in ["/travel/flights/search", "/travel/flights"]:
            url = f"https://www.google.com{path}?q={q}"
            logger.info(f"Trying URL: {url}")
            await page.goto(url, wait_until="load", timeout=30000)
            await page.wait_for_timeout(4000)

            text = await page.evaluate(
                "() => document.body?.innerText?.substring(0, 300) || ''"
            )
            logger.info(f"Page preview: {text[:200]}")

            if "results" in text.lower() or "result" in text.lower():
                logger.info(f"Found results with path: {path}")
                return True

        return False

    async def _search_through_ui(
        self, page, params: SearchRequest
    ) -> bool:
        try:
            await page.goto(
                "https://www.google.com/travel/flights",
                wait_until="load",
                timeout=30000,
            )
            await page.wait_for_timeout(3000)
        except Exception as e:
            logger.error(f"Failed to load Google Flights: {e}")
            return False

        try:
            cookie_btn = page.locator("button:has-text('Aceitar')")
            if await cookie_btn.count() > 0:
                await cookie_btn.first.click()
                await page.wait_for_timeout(1500)
        except Exception:
            pass

        origin_inputs = [
            'input[aria-label*="from i"]',
            'input[aria-label*="Where from"]',
            'input[placeholder*="Where"]',
            'input[aria-label*="Origem"]',
            'input.e5F5td',
            '[aria-label*="from"] input',
            'input',
        ]

        for sel in origin_inputs:
            try:
                inp = page.locator(sel).first
                if await inp.count() > 0:
                    await inp.click()
                    await page.wait_for_timeout(500)
                    await inp.fill("")
                    await inp.type(params.origin, delay=80)
                    await page.wait_for_timeout(2000)

                    try:
                        suggestion = page.locator(
                            '[role="listbox"] [role="option"]'
                        ).first
                        if await suggestion.count() > 0:
                            await suggestion.click()
                            await page.wait_for_timeout(1000)
                            logger.info(f"Selected origin via {sel}")
                            break
                    except Exception:
                        pass

                    try:
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(1500)
                        logger.info(f"Origin entered via keyboard on {sel}")
                        break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"Origin selector {sel} failed: {e}")
                continue
        else:
            logger.warning("Could not fill origin via any selector")
            return False

        for sel in [
            'input[aria-label*="to"]',
            'input[aria-label*="Where to"]',
            'input[aria-label*="Destino"]',
            'input.e5F5td',
            '[aria-label*="to"] input',
            'input',
        ]:
            try:
                inp = page.locator(sel).first
                if await inp.count() > 0:
                    await inp.click()
                    await page.wait_for_timeout(500)
                    await inp.fill("")
                    await inp.type(params.destination, delay=80)
                    await page.wait_for_timeout(2000)

                    try:
                        suggestion = page.locator(
                            '[role="listbox"] [role="option"]'
                        ).first
                        if await suggestion.count() > 0:
                            await suggestion.click()
                            await page.wait_for_timeout(1000)
                            logger.info(f"Selected destination via {sel}")
                            break
                    except Exception:
                        pass

                    try:
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(1500)
                        logger.info(f"Dest entered via keyboard on {sel}")
                        break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"Dest selector {sel} failed: {e}")
                continue
        else:
            logger.warning("Could not fill destination")
            return False

        try:
            date_btn = page.locator(
                'button[aria-label*="Departure"], '
                '[aria-label*="data de ida"], '
                'input[aria-label*="date"]'
            ).first
            if await date_btn.count() > 0:
                await date_btn.click()
                await page.wait_for_timeout(1000)
                date_str = params.depart_date.strftime("%d/%m/%Y")
                try:
                    date_cell = page.locator(
                        f'[role="gridcell"][aria-label*="{params.depart_date.day}"]'
                    ).first
                    if await date_cell.count() > 0:
                        await date_cell.click()
                        await page.wait_for_timeout(1000)
                except Exception:
                    try:
                        await page.keyboard.type(date_str)
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(1000)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Date selection: {e}")

        try:
            search_btn = page.locator(
                'button[aria-label="Search"], '
                'button:has-text("Search"), '
                'button:has-text("Buscar"), '
                '[role="button"]:has-text("Search"), '
                'button[jsaction]'
            ).first
            if await search_btn.count() > 0:
                await search_btn.click()
                await page.wait_for_timeout(5000)
                logger.info("Clicked search button")
        except Exception as e:
            logger.warning(f"Search button: {e}")

        await page.wait_for_timeout(5000)

        return True

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
                if not await self._try_search_url(page, params):
                    logger.info("URL search failed, trying UI interaction")
                    await self._search_through_ui(page, params)

                await page.wait_for_timeout(3000)

                page_text = await page.evaluate(
                    "() => document.body?.innerText || ''"
                )

                if "not found" in page_text.lower() or len(page_text) < 100:
                    logger.warning("No results detected on page")
                    content = await page.content()
                    logger.info(f"HTML snippet: {content[:500]}")
                    return []

                all_text = await page.evaluate(
                    "() => document.body?.innerText || ''"
                )

                is_usd = bool(re.search(r"US\$", all_text))

                raw_prices = re.findall(
                    r"((?:US|R)?)\$[\s\xa0\u00a0]*([\d,.]+)",
                    all_text,
                    re.IGNORECASE,
                )
                prices = []
                for prefix, val in raw_prices[:40]:
                    parsed = self._parse_price(val)
                    if parsed and parsed >= 10:
                        currency_price = "USD" if prefix.upper() == "US" else "BRL"
                        prices.append((parsed, currency_price))

                logger.info(f"Page text length: {len(all_text)}, prices found: {len(prices)}, is_usd={is_usd}")

                lines = [
                    l.strip()
                    for l in all_text.split("\n")
                    if l.strip()
                ]

                results = self._parse_results(lines, prices, params, is_usd)
                logger.info(f"Parsed {len(results)} results")

            except Exception as e:
                logger.error(
                    f"Google Flights error: {e}", exc_info=True
                )
            finally:
                await browser.close()

        return self._filter_results(results, params)

    def _parse_results(
        self,
        lines: List[str],
        prices: List[tuple],
        params: SearchRequest,
        is_usd: bool = False,
    ) -> List[FlightResult]:
        results = []
        price_index = 0
        seen = set()

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
            "iberia": "Iberia",
            "british airways": "British Airways",
            "emirates": "Emirates",
            "qatar": "Qatar Airways",
            "avianca": "Avianca",
            "copa": "Copa Airlines",
            "jetblue": "JetBlue",
            "spirit": "Spirit Airlines",
        }

        text = "\n".join(lines).lower()

        if not re.search(
            r"(latam|gol|azul|tap|avianca|american)",
            text,
        ):
            logger.info("No airline names found in page text")
            return []

        price_values = [(v, c) for v, c in prices if v >= 10]
        if not price_values:
            return []

        block_delimiters = re.split(
            r"(?=\b(?:latam|gol|azul|tap|avianca|american|united|delta)\b)",
            text,
            flags=re.IGNORECASE,
        )

        q = f"Flights+from+{params.origin}+to+{params.destination}+on+{params.depart_date}"
        if params.return_date:
            q += f"+return+on+{params.return_date}"
        search_url = f"https://www.google.com/travel/flights/search?q={q}"

        for block in block_delimiters:
            block = block.strip()
            if len(block) < 20:
                continue

            airline = None
            for alias, name in airline_map.items():
                if alias in block:
                    airline = name
                    break

            if not airline:
                continue

            stops = 2
            if re.search(
                r"\b(direto|não para|sem escalas|direct|non.?stop)\b", block
            ):
                stops = 0
            elif re.search(r"\b(1 escala|1 parada)\b", block):
                stops = 1
            elif re.search(r"\b(2 escalas|2 paradas)\b", block):
                stops = 2

            duration = "—"
            dur_match = re.search(
                r"(\d{1,2})\s*h\s*(?:(\d{1,2})\s*min)?", block
            )
            if dur_match:
                h = dur_match.group(1)
                m = dur_match.group(2) or "00"
                duration = f"{h}h{m}"

            price_val = None
            price_ccy = "USD" if is_usd else "BRL"
            if price_index < len(price_values):
                price_val, price_ccy = price_values[price_index]
                price_index += 1

            if not price_val:
                continue

            key = (airline, price_val)
            if key in seen:
                continue
            seen.add(key)

            results.append(
                FlightResult(
                    airline=airline,
                    from_code=params.origin.upper(),
                    to_code=params.destination.upper(),
                    depart_time=str(params.depart_date),
                    return_time=str(params.return_date) if params.return_date else None,
                    stops=stops,
                    duration=duration,
                    price=price_val,
                    currency=price_ccy,
                    url=search_url,
                    source="google_flights",
                    logo=self._get_airline_logo(airline),
                )
            )

        return results

    def _parse_price(self, text: str) -> Optional[float]:
        if not text:
            return None
        text = re.sub(r"^us", "", text, flags=re.IGNORECASE)
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
            "Spirit Airlines": "spirit-airlines",
        }
        slug = slugs.get(airline, airline.lower().replace(" ", "-"))
        return f"https://www.gstatic.com/flights/airline_logos/70px/{slug}.png"
