# Indian Income Assets Live Dashboard MVP

A runnable MVP dashboard for 28 Indian income assets from the report. It shows current/delayed price, day change, recalculated annual yield, monthly equivalent yield, P/E ratio, last dividend/distribution amount, last dividend date, confidence, buy zone, and portfolio income estimates.

## What this MVP does

- Loads the 28 assets from `app/data/assets.json`
- Tries to refresh prices from Yahoo Finance's free/delayed quote endpoint
- Falls back to seed prices from the researched report when live quotes are unavailable
- Recalculates annual yield and monthly equivalent yield automatically
- Auto-refreshes every 60 seconds in the browser
- Provides filters by asset type, confidence, minimum yield, and sorting mode
- Includes a portfolio income calculator

## Important limitation

This MVP does **not** use a licensed real-time market data feed. Free quote data may be delayed, incomplete, or unavailable for some InvITs/REITs. For production, connect Zerodha Kite Connect, TrueData, Global Datafeeds, or another licensed NSE/BSE data provider.

## Run locally

```bash
cd indian_income_dashboard
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## API endpoints

```text
GET /api/assets
GET /api/assets?type_filter=Equity&min_yield=5&sort_by=yield
GET /api/portfolio?amount=100000&min_confidence=Medium
```

## Production upgrade path

1. Replace `fetch_yahoo_quote()` in `app/main.py` with a broker or licensed vendor quote function.
2. Store quotes in PostgreSQL or Redis for caching.
3. Add login and user portfolios.
4. Add alerts when annual yield crosses 12% or price enters buy zone.
5. Deploy backend on Render/Railway/Fly.io and frontend on Vercel or serve static files from FastAPI.
