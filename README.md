<div align="center">

# BuildWise AI
**Geo-Based Intelligent Site Feasibility & Construction Planning**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Frontend: Vite+React](https://img.shields.io/badge/Frontend-Vite%20%2B%20React-646CFF.svg)](frontend/)
[![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](backend/)
[![APIs: Zero Paid](https://img.shields.io/badge/APIs-Zero%20Paid-success.svg)](docs/map-and-data.md)

One pin on a map yields a full civil-engineering feasibility report — MCDA land suitability, IS 1893 seismic & flood stress, CPWD cost benchmarks, Vastu orientation, and a generative architectural blueprint — in seconds.

<img src="assets/brand/BuildWise_AI_intro_Gif.gif" alt="BuildWise AI Intro" width="500" style="border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.15); max-width: 100%;" />

</div>

## Why BuildWise
- **Universal Site Assessment:** Pick any plot via interactive MapLibre click, address geosearch, or WGS84 coordinates.
- **Deterministic Civil Core:** Mathematical calculations based on CPWD benchmarks, IS 1893, and NBC 2016, with Groq/Gemini reasoning and a zero-key offline fallback.
- **Generative Blueprint Engine:** Dissection-based spatial CSP solver with an architect placement knowledge base and non-negotiable topological invariants.
- **Print-Grade PDF Dossier:** Instant server-side ReportLab vector PDF compilation with an executive scorecard, 174mm vector blueprint, and room schedule.
- **Zero Paid APIs:** Built entirely on open infrastructure — OpenFreeMap, Esri World Imagery, OpenTopoMap, USGS, Open-Meteo, and Copernicus Sentinel-2.

### Windows (One-Click Setup & Launch)
```bat
.\run_project.bat
```
*(Automatically creates `backend\venv`, installs Python requirements, installs frontend npm packages, and starts both services).*

### Manual Setup

#### Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

#### Frontend
```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

## Architecture at a Glance

```text
React 19 + MapLibre GL UI (Apple Vibrancy / Glassmorphism)
   │
   ├── ReportSheet Drawer & Interactive Blueprint SVG
   │
   └──► FastAPI Backend (/api/analyze, /api/generate-floorplan, /api/report)
           ├── Civil Calc Core (CPWD DSR, IS 1893, NBC 2016)
           ├── AI Adapters (Groq / Gemini / Ollama / Mock)
           ├── Placement Engine (Knowledge Base + Topological Invariants)
           ├── Slicing-Tree CSP Dissection Solver
           └── ReportLab Vector PDF Pipeline
```

## Documentation

| Guide | Description |
|:---|:---|
| [Getting Started](docs/getting-started.md) | Prerequisites, key-by-key `.env` guide, first analysis walkthrough, and troubleshooting. |
| [Architecture](docs/architecture.md) | Mermaid system architecture, `/api/analyze` request lifecycle, and module inventory. |
| [Frontend](docs/frontend.md) | Apple design language tokens, component catalog, ReportSheet tabs, and hybrid map modes. |
| [Backend API](docs/backend-api.md) | REST endpoint reference, JSON payloads, rate limits (30 req/min), CORS, and fallback contracts. |
| [AI Pipeline](docs/ai-pipeline.md) | Groq & Gemini adapters, JSON-mode enforcement, placement reasoner, and layout critic. |
| [Blueprint Engine](docs/blueprint-engine.md) | Spatial CSP solver, room placement knowledge base, topological invariants, and PDF drawings. |
| [Space Engine](docs/space-engine.md) | Deterministic solver architecture, L1–L15 gate, independent invariant sweep, and how to audit a certificate. |
| [Map & Data Providers](docs/map-and-data.md) | MapLibre styles, hybrid layers, OpenStreetMap/Esri/USGS attribution, and data licensing. |
| [Testing & QA](docs/testing.md) | 1,352-test backend suite, placement regression and PDF tests, plus the 9-viewport Puppeteer UI audit. |
| [Deployment](docs/deployment.md) | Production setup, server-side API key isolation, Nginx/Uvicorn configuration, and health probes. |

## Development

```bash
# Frontend lint, build, and automated viewport audit
cd frontend
npm run lint          # Fast static analysis via Oxlint
npm run build         # TypeScript type check (tsc) + Vite production bundle
npm run audit:ui      # Puppeteer DOM integrity audit across 9 viewports

# Backend test suite (1,352 tests, plus the QA gate set)
cd ../backend
python -m pytest tests/
```

## License

Released under the [MIT License](LICENSE). Copyright &copy; 2026 Rolan Lobo.

Third-party mapping, elevation, and meteorological data remain under their respective open licenses (see [docs/map-and-data.md](docs/map-and-data.md)).
