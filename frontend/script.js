const API_BASE = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://localhost:8000"
    : "https://maika-voos-api.onrender.com";

const form = document.getElementById("searchForm");
const loading = document.getElementById("loading");
const error = document.getElementById("error");
const errorMessage = document.getElementById("errorMessage");
const results = document.getElementById("results");
const resultsList = document.getElementById("resultsList");
const resultsCount = document.getElementById("resultsCount");
const noResults = document.getElementById("noResults");
const initialState = document.getElementById("initialState");
const btnSearch = document.getElementById("btnSearch");

function setDefaultDate() {
    const today = new Date();
    const future = new Date(today);
    future.setDate(today.getDate() + 30);
    document.getElementById("departDate").value = future.toISOString().split("T")[0];
}

function show(element) {
    element.classList.add("show");
    element.classList.remove("hidden");
}

function hide(element) {
    element.classList.remove("show");
    element.classList.add("hidden");
}

function resetDisplay() {
    hide(loading);
    hide(error);
    hide(results);
    hide(noResults);
}

function formatPrice(price) {
    return "R$ " + price.toLocaleString("pt-BR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}

function stopsLabel(stops) {
    if (stops === 0) return { text: "Direto", cls: "stops-direct" };
    if (stops === 1) return { text: "1 escala", cls: "stops-1" };
    return { text: `${stops} escalas`, cls: "stops-2" };
}

function getAirlineLogoUrl(logo, airline) {
    if (logo && logo.startsWith("http")) return logo;
    const slugs = {
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
    };
    const slug = slugs[airline] || airline.toLowerCase().replace(/\s+/g, "-");
    return `https://www.gstatic.com/flights/airline_logos/70px/${slug}.png`;
}

function sourceLabel(source) {
    const labels = {
        "google_flights": "Google Flights",
        "decolar": "Decolar",
    };
    return labels[source] || source;
}

function createResultCard(flight) {
    const card = document.createElement("div");
    card.className = "result-card";

    const stop = stopsLabel(flight.stops);

    card.innerHTML = `
        <div class="result-airline">
            <img class="airline-logo" src="${getAirlineLogoUrl(flight.logo, flight.airline)}"
                 alt="${flight.airline}"
                 onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22><rect fill=%22%23667eea%22 width=%2232%22 height=%2232%22 rx=%226%22/><text x=%2216%22 y=%2222%22 text-anchor=%22middle%22 fill=%22%23fff%22 font-size=%2216%22 font-weight=%22bold%22>${
                     flight.airline.charAt(0)
                 }</text></svg>'">
            <span class="airline-name">${flight.airline}</span>
        </div>
        <div class="result-info">
            <div class="result-route">${flight.from_code} &rarr; ${flight.to_code}</div>
            <div class="result-meta">
                <span class="meta-item">&#128197; ${flight.depart_time}</span>
                ${flight.return_time ? `<span class="meta-item">&#128197; Volta: ${flight.return_time}</span>` : ""}
                <span class="meta-item">&#9200; ${flight.duration}</span>
                <span class="meta-item">
                    <span class="stops-badge ${stop.cls}">${stop.text}</span>
                </span>
            </div>
            <a href="${flight.url}" target="_blank" rel="noopener" class="result-link">
                Ver no ${sourceLabel(flight.source)} &rarr;
            </a>
        </div>
        <div class="result-price-area">
            <div class="result-price">${formatPrice(flight.price)}</div>
            <div class="result-currency">${flight.currency}</div>
            <div class="result-source">via ${sourceLabel(flight.source)}</div>
        </div>
    `;

    return card;
}

form.addEventListener("submit", async (e) => {
    e.preventDefault();
    resetDisplay();

    const origin = document.getElementById("origin").value.trim();
    const destination = document.getElementById("destination").value.trim();
    const departDate = document.getElementById("departDate").value;
    const returnDate = document.getElementById("returnDate").value;
    const maxPrice = document.getElementById("maxPrice").value;
    const maxStops = document.getElementById("maxStops").value;
    const source = document.getElementById("source").value;

    if (!origin || !destination || !departDate) {
        errorMessage.textContent = "Preencha origem, destino e data de ida.";
        show(error);
        return;
    }

    hide(initialState);
    show(loading);
    btnSearch.disabled = true;

    try {
        const params = new URLSearchParams();
        params.set("origin", origin);
        params.set("destination", destination);
        params.set("depart_date", departDate);
        if (returnDate) params.set("return_date", returnDate);
        if (maxPrice) params.set("max_price", maxPrice);
        if (maxStops !== "") params.set("max_stops", maxStops);
        params.set("source", source);

        const response = await fetch(`${API_BASE}/api/search?${params.toString()}`, {
            method: "GET",
            headers: { "Accept": "application/json" },
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Erro ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        hide(loading);

        if (!data.results || data.results.length === 0) {
            show(noResults);
            return;
        }

        resultsCount.textContent = `${data.total} passagem${data.total !== 1 ? "ns" : ""} encontrada${data.total !== 1 ? "s" : ""}`;
        resultsList.innerHTML = "";

        data.results.forEach((flight) => {
            resultsList.appendChild(createResultCard(flight));
        });

        show(results);
    } catch (err) {
        hide(loading);
        errorMessage.textContent = err.message || "Erro ao conectar com o servidor. Tente novamente.";
        show(error);
    } finally {
        btnSearch.disabled = false;
    }
});

async function loadDailyOffers() {
    try {
        const resp = await fetch("data/ofertas.json");
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.results && data.results.length > 0) {
            resultsCount.textContent = `${data.total} oferta${data.total !== 1 ? "s" : ""} do dia`;
            resultsList.innerHTML = "";
            data.results.forEach((flight) => {
                resultsList.appendChild(createResultCard(flight));
            });
            hide(initialState);
            show(results);
        }
    } catch {
        // No daily offers available
    }
}

setDefaultDate();
loadDailyOffers();
