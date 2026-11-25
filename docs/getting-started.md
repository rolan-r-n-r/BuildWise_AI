# Getting Started with BuildWise AI

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)
[![Frontend: Vite + React](https://img.shields.io/badge/Frontend-Vite%20%7C%20React%2019-61DAFB.svg)](../frontend)
[![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](../backend)
[![APIs: Zero Paid](https://img.shields.io/badge/APIs-Zero%20Paid%20Dependencies-brightgreen.svg)](#zero-paid-api-guarantee)

Comprehensive onboarding guide covering prerequisites, environment configuration, first analysis execution, and troubleshooting.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation & Quick Start](#installation--quick-start)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
  - [One-Click Windows Launcher](#one-click-windows-launcher)
- [Environment Configuration](#environment-configuration)
  - [Backend Configuration (`backend/.env`)](#backend-configuration-backendenv)
  - [Frontend Configuration (`frontend/.env`)](#frontend-configuration-frontendenv)
- [First Analysis Walkthrough](#first-analysis-walkthrough)
- [Troubleshooting & FAQ](#troubleshooting--faq)
- [Next Steps](#next-steps)

---

## Prerequisites

Ensure the following tools are installed on your host system:

| Tool | Minimum Version | Recommended Version | Verification Command |
| :--- | :--- | :--- | :--- |
| **Python** | 3.11+ | 3.12 or 3.13 | `python --version` |
| **Node.js** | 18.0+ | 20.x or 22.x LTS | `node --version` |
| **npm** | 9.0+ | 10.x+ | `npm --version` |
| **Git** | 2.30+ | Latest | `git --version` |

> [!NOTE]
> No database engine (PostgreSQL, Redis, MongoDB) is required. BuildWise AI computes civil engineering algorithms, spatial CSP dissections, and PDF dossiers in-memory with deterministic caching.

---

## Installation & Quick Start

### Backend Setup

```bash
# 1. Navigate to the backend directory
cd backend

# 2. Create and activate a Python virtual environment
python -m venv .venv
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# 3. Install backend dependencies
pip install -r requirements.txt

# 4. Create your local environment file
cp .env.example .env

# 5. Start the FastAPI development server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Verify backend health at:
- Swagger Interactive Docs: `http://localhost:8000/docs`
- Health Endpoint: `http://localhost:8000/api/health`

### Frontend Setup

In a new terminal window:

```bash
# 1. Navigate to the frontend directory
cd frontend

# 2. Install Node dependencies
npm install

# 3. Create your local environment file
cp .env.example .env

# 4. Start Vite development server
npm run dev
```

Open your browser at **`http://localhost:5173`**.

### One-Click Windows Launcher

On Windows systems, you can start both services simultaneously using the root launcher:

```bat
.\run_project.bat
```

This batch script automatically performs first-time bootstrapping (creates Python venv in `backend/`, installs `requirements.txt`, installs `node_modules` in `frontend/`), frees stale ports 8000 and 5173, and launches both the FastAPI backend and Vite frontend services. On subsequent runs, it skips installation and launches immediately. You can force reinstallation at any time by running `.\run_project.bat --install`.

---

## Environment Configuration

### Backend Configuration (`backend/.env`)

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `HOST` | `127.0.0.1` | Network interface IP binding. Use `0.0.0.0` for Docker containerization. |
| `PORT` | `8000` | HTTP port on which the FastAPI application listens. |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated list of origins allowed for cross-origin browser requests. |
| `DEFAULT_AI_PROVIDER` | `mock` | Default LLM provider for narrative generation. Options: `mock`, `groq`, `gemini`, `ollama`. |
| `GROQ_API_KEY` | *(empty)* | Optional. API key for Groq Cloud. The model defaults to `openai/gpt-oss-120b`; override with `GROQ_MODEL`. |
| `GEMINI_API_KEY` | *(empty)* | Optional. API key for Google Gemini (`gemini-2.5-flash`). |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Endpoint for local self-hosted Ollama server (`llama3` or `mistral`). |

> [!TIP]
> **Zero-Key Operation:** Leaving `GROQ_API_KEY` and `GEMINI_API_KEY` empty is completely valid. The platform automatically uses the high-precision `mock` adapter which executes deterministic rule-based generation with zero latency.

### Frontend Configuration (`frontend/.env`)

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `VITE_API_URL` | `http://localhost:8000` | Base URL of the backend API service accessed by Axios/fetch calls. |

---

## First Analysis Walkthrough

1. **Launch the Web App:** Navigate to `http://localhost:5173`.
2. **Select a Construction Site:**
   - **Click on the Map:** Click anywhere on the map canvas to place the pin (e.g. Bangalore, Mumbai, or Delhi).
   - **Or Enter Coordinates:** Use the input drawer to type latitude/longitude directly (e.g., `12.9716, 77.5946`).
3. **Configure Project Scope:**
   - **Built-up Area:** Set desired square footage (e.g. 2,400 sq ft).
   - **Building Typology:** Select `residential_single`, `residential_multi`, `commercial`, or `industrial`.
   - **Storeys & Quality Grade:** Choose storeys (1–4) and specification grade (`standard`, `premium`, `luxury`).
4. **Trigger Analysis:** Click **Analyze Site Feasibility**.
   - Within 1.5–2.5 seconds, the multi-factor MCDA suitability radar, IS 1893 seismic risk, GloFAS river discharge, CPWD cost breakdown, and Vastu orientation compass render in the HUD.
5. **Generate Architectural Blueprint:**
   - Click **Generate Architectural Blueprint** in the Report Sheet.
   - The spatial dissection engine constructs an architecturally sane floor plan with verified circulation, leaf bathrooms, and zero voids.
6. **Export Dossier:** Click **Export PDF Report** to download the vector engineering dossier.

---

## Troubleshooting & FAQ

| Symptom / Error | Root Cause | Solution |
| :--- | :--- | :--- |
| `net::ERR_CONNECTION_REFUSED` at `http://localhost:8000` | Backend server is not running or failed during boot. | Check backend terminal logs. Confirm virtual environment is activated and run `uvicorn app.main:app --reload`. |
| `429 Rate limit exceeded` | Client exceeded 30 requests per 60 seconds per IP limit. | The sliding window limiter resets automatically within 60 seconds. |
| Map tiles render blank | Network block or corporate firewall on open tile CDN. | Toggle map style in the top right to `Satellite` (ESRI) or `Terrain` (OpenTopoMap) via `MapStyleSelector`. |
| PDF download returns `500 Server Error` | Missing `reportlab` font or corrupted SVG XML payload. | Run `pytest tests/reports/test_pdf_report_v9.py` in `backend/` to isolate ReportLab canvas failures. |
| TypeScript build error in frontend | Outdated dependencies or modified interfaces. | Run `npm run build` in `frontend/` to view exact compiler diagnostic errors. |

---

## Next Steps

- Explore the complete [Architecture Overview](architecture.md)
- Learn about the [Frontend Design Language](frontend.md)
- Inspect the [Backend API Reference](backend-api.md)

---

[Next: Architecture Overview →](architecture.md)

### License

Distributed under the MIT License. See [LICENSE](../LICENSE) for details.
