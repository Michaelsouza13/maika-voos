import re
import logging
from typing import List, Optional

from playwright.async_api import async_playwright, TimeoutError as PwTimeout

from .base import BaseScraper
from models import SearchRequest, FlightResult

logger = logging.getLogger(__name__)


class Milhas123Scraper(BaseScraper):
    def __init__(self):
        self.name = "123milhas"

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
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            try:
                dep = params.depart_date.strftime("%Y-%m-%d")
                ret = ""
                if params.return_date:
                    ret = f"-{params.return_date.strftime('%Y-%m-%d')}"
                url = (
                    f"https://123milhas.com/busca/"
                    f"{params.origin.upper()}-{params.destination.upper()}-{dep}{ret}"
                )

                logger.info(f"123Milhas URL: {url}")
                await page.goto(url, wait_until="load", timeout=30000)
                await page.wait_for_timeout(5000)

                page_text = await page.evaluate(
                    "() => document.body?.innerText || ''"
                )

                if not page_text or "não encontrado" in page_text.lower():
                    logger.warning("123Milhas no results")
                    return []

                _, prices = await page.evaluate("""
                    () => {
                        const els = [...document.querySelectorAll('span, div, p, strong, h3')];
                        const prices = [];
                        const seen = new Set();
                        for (const el of els) {
                            const t = el.textContent.trim();
                            if (!t || seen.has(t)) continue;
                            seen.add(t);
                            if (/^R?\\$\\s?[\\d.,]+$/.test(t) || /^\\d{1,3}(?:\\.\\d{3})*,\\d{2}$/.test(t)) {
                                prices.push(t);
                            }
                        }
                        return prices.slice(0, 30);
                    }
                """)

                if not prices:
                    price_matches = re.findall(
                        r"R\$\s*[\d.]+,\d{2}", page_text
                    )
                    prices = price_matches[:30]

                logger.info(f"123Milhas prices: {len(prices)}")

                airline = self._detect_airline(
                    page_text, params.origin, params.destination
                )

                lines = [
                    l.strip()
                    for l in page_text.split("\n")
                    if l.strip()
                ]
                results = self._parse_results(lines, prices, params, airline)

            except Exception as e:
                logger.error(f"123Milhas error: {e}", exc_info=True)
            finally:
                await browser.close()

        return self._filter_results(results, params)

    def _detect_airline(
        self, text: str, origin: str, dest: str
    ) -> Optional[str]:
        airlines = [
            "LATAM", "GOL", "Azul", "Voepass", "Avianca",
            "American Airlines", "United", "Delta",
        ]
        for a in airlines:
            if a.lower() in text.lower():
                return a
        return None

    def _parse_results(
        self,
        lines,
        prices,
        params: SearchRequest,
        default_airline: Optional[str],
    ) -> List[FlightResult]:
        results = []
        text = "\n".join(lines).lower()

        for i, p in enumerate(prices[:15]):
            price = self._parse_price(p)
            if not price:
                continue

            results.append(
                FlightResult(
                    airline=default_airline or "123Milhas",
                    from_code=params.origin.upper(),
                    to_code=params.destination.upper(),
                    depart_time=str(params.depart_date),
                    return_time=str(params.return_date) if params.return_date else None,
                    stops=0,
                    duration="—",
                    price=price,
                    currency="BRL",
                    url=(
                        f"https://123milhas.com/busca/"
                        f"{params.origin.upper()}-{params.destination.upper()}"
                        f"-{params.depart_date}"
                    ),
                    source="123milhas",
                )
            )

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
