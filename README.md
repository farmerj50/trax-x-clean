# TRAX-X

TRAX-X is a React + Flask trading dashboard with stock scans, AI-ranked picks, live stock monitoring, options tooling, and premarket intelligence views.

## Stack

- Frontend: React (`src/`)
- Backend: Flask + Socket.IO (`backend/`)
- Market data: Polygon
- Additional data: Alpha Vantage

## Environment

Use two env files locally:

- Root `.env`: frontend-safe values only.
- `backend/.env`: backend secrets and server-only feature flags.

Root `.env`:

```env
REACT_APP_API_BASE=http://localhost:5000
REACT_APP_SOCKET_BASE=ws://localhost:5000
REACT_APP_POLYGON_API_KEY=your_polygon_key
```

`backend/.env`:

```env
POLYGON_API_KEY=your_polygon_key
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_key
```

Optional backend env vars for `backend/.env`:

```env
ENABLE_MARKET_SIGNALS=true
ENABLE_OPTIONS_FLOW_SIGNALS=false
MARKET_SIGNALS_BIG_PRINT_THRESHOLD=10000000
MARKET_SIGNALS_SUBSCRIBE=
INTRINIO_API_KEY=
ENABLE_TRADING=false
TRADING_MODE=paper
TRADING_STARTING_CASH=100000
TRADING_PAPER_AUTO_FILL=true
TRADING_PROVIDER=paper
ALPACA_BROKER_ENV=sandbox
ALPACA_BROKER_API_BASE=https://broker-api.sandbox.alpaca.markets
ALPACA_BROKER_API_KEY=
ALPACA_BROKER_API_SECRET=
ALPACA_BROKER_ENABLED=false
ALPACA_BROKER_ACCOUNT_ID=
ALPACA_BROKER_ALLOW_ORDERS=false
```

The backend prefers `backend/.env` and falls back to the repo-root `.env` for older local setups.

Optional frontend runtime env vars:

```env
REACT_APP_API_BASE=http://localhost:5000
REACT_APP_SOCKET_BASE=ws://localhost:5000
```

## Install

Frontend:

```powershell
npm install
```

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..
```

## Run Locally

Start backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python app.py
```

Start frontend in another terminal:

```powershell
npm start
```

Frontend default:

- `http://localhost:3000`

Backend default:

- `http://localhost:5000`

Health check:

- `http://localhost:5000/health`

## Common Commands

Frontend test:

```powershell
npm test -- --watchAll=false --runInBand
```

Frontend production build:

```powershell
npm run build
```

## Notes

- `backend/config.py` is the source of truth for backend paths and required API keys.
- Market scanners and AI picks depend on live upstream market data and can be slow locally.
- The React app proxies API requests to the backend on port `5000`.
- The trading layer is paper-only in this codebase. Live broker execution is intentionally not wired in.
- Alpaca Broker sandbox account discovery is read-only through `/api/trading/alpaca/accounts`.
- Order routing uses `ALPACA_BROKER_ACCOUNT_ID` when set; otherwise it uses the selected Alpaca account saved through `/api/trading/alpaca/selected-account`.
- Alpaca order submission remains locked unless `ALPACA_BROKER_ALLOW_ORDERS=true`; use `/api/trading/orders/preview` or the Trading page preview before submitting.
