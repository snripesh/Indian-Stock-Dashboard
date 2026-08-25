from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "assets.json"
USERS_PATH = BASE_DIR / "data" / "users.json"
USER_ASSETS_PATH = BASE_DIR / "data" / "user_assets.json"
SECRET_KEY_PATH = BASE_DIR / "data" / "secret.key"

app = FastAPI(title="Indian Income Assets Dashboard", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 55

CONFIDENCE_ORDER = {"High": 4, "Medium-High": 3, "Medium": 2, "Low-Medium": 1}

NSE_SESSION = requests.Session()
NSE_SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.5'
})

def load_assets() -> List[Dict[str, Any]]:
    with DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, "", "N/A", "N/M"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_quote(ticker: str, force: bool = False) -> Optional[Dict[str, Any]]:
    """Fetch from NSE API first (very accurate for Indian trusts), then fallback to Yahoo."""
    if not ticker:
        return None
    now = time.time()
    cached = CACHE.get(ticker)
    if not force and cached and now - cached["cached_at"] < CACHE_TTL_SECONDS:
        return cached["data"]

    # 1. Try NSE API
    symbol = ticker.split('.')[0] # Remove .NS
    try:
        if not NSE_SESSION.cookies:
            NSE_SESSION.get("https://www.nseindia.com", timeout=5)
        
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        r = NSE_SESSION.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            p_info = data.get("priceInfo", {})
            meta = data.get("metadata", {})
            if p_info and p_info.get("lastPrice"):
                pe_ratio = meta.get("pdSymbolPe")
                if pe_ratio == "NA":
                    pe_ratio = None
                
                week_high_low = p_info.get("weekHighLow", {})
                fiftyTwoWeekLow = week_high_low.get("min")
                fiftyTwoWeekHigh = week_high_low.get("max")

                result = {
                    "price": round(float(p_info["lastPrice"]), 2),
                    "previous_close": round(float(p_info.get("previousClose", 0)), 2),
                    "day_change": round(float(p_info.get("change", 0)), 2),
                    "day_change_pct": round(float(p_info.get("pChange", 0)), 2),
                    "pe_ratio": pe_ratio,
                    "fiftyTwoWeekLow": float(fiftyTwoWeekLow) if fiftyTwoWeekLow else None,
                    "fiftyTwoWeekHigh": float(fiftyTwoWeekHigh) if fiftyTwoWeekHigh else None,
                    "market_time": data.get("metadata", {}).get("lastUpdateTime"),
                    "source": "NSE Live API",
                    "companyName": data.get("info", {}).get("companyName", symbol),
                }
                CACHE[ticker] = {"cached_at": now, "data": result}
                return result
    except Exception:
        pass

    # 2. Fallback to Yahoo v8
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=6)
        response.raise_for_status()
        result = response.json().get("chart", {}).get("result", [])
        if not result:
            return None
        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
            
        prev_close = meta.get("chartPreviousClose")
        change = None
        change_pct = None
        if price is not None and prev_close is not None:
            change = price - prev_close
            if prev_close != 0:
                change_pct = (change / prev_close) * 100

        data = {
            "price": round(float(price), 2),
            "previous_close": round(float(prev_close), 2) if prev_close is not None else None,
            "day_change": round(float(change), 2) if change is not None else None,
            "day_change_pct": round(float(change_pct), 2) if change_pct is not None else None,
            "pe_ratio": None,
            "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
            "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
            "market_time": meta.get("regularMarketTime"),
            "source": "Yahoo Finance (Fallback)",
        }
        CACHE[ticker] = {"cached_at": now, "data": data}
        return data
    except Exception:
        return None

def fetch_dividend_history(ticker: str, force: bool = False) -> Dict[str, Any]:
    if not ticker:
        return {}
    now = time.time()
    cache_key = f"div_{ticker}"
    cached = CACHE.get(cache_key)
    if not force and cached and now - cached["cached_at"] < 3600:
        return cached["data"]

    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1y&events=div"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=6)
        response.raise_for_status()
        data = response.json()
        events = data.get('chart', {}).get('result', [{}])[0].get('events', {}).get('dividends', {})
        
        divs = []
        for ts, d in events.items():
            divs.append({"amount": float(d["amount"]), "date": int(d["date"])})
        
        divs.sort(key=lambda x: x["date"], reverse=True)
        
        ttm_income = sum(d["amount"] for d in divs)
        last_dividend_amount = divs[0]["amount"] if divs else None
        
        last_dividend_date = None
        if divs:
            last_dividend_date = datetime.fromtimestamp(divs[0]["date"], timezone.utc).strftime("%Y-%m-%d")
            
        result = {
            "ttm_income": round(ttm_income, 2) if ttm_income else 0,
            "last_dividend_amount": round(last_dividend_amount, 2) if last_dividend_amount else None,
            "last_dividend_date": last_dividend_date,
            "dividend_count": len(divs)
        }
        CACHE[cache_key] = {"cached_at": now, "data": result}
        return result
    except Exception:
        return {}


def enrich_asset(asset: Dict[str, Any], live: bool = True, force: bool = False) -> Dict[str, Any]:
    out = dict(asset)
    
    if live:
        quote = fetch_quote(asset.get("ticker", ""), force=force)
        div_data = fetch_dividend_history(asset.get("ticker", ""), force=force)
    else:
        quote = None
        div_data = {}

    if quote:
        price = quote["price"]
        out["data_source"] = quote["source"]
        out["last_price_update_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out["day_change"] = quote.get("day_change")
        out["day_change_pct"] = quote.get("day_change_pct")
        
        api_pe = quote.get("pe_ratio")
        if api_pe is not None:
            out["pe_ratio"] = api_pe
        elif out.get("type") in ["InvIT", "REIT"]:
            out["pe_ratio"] = "N/M"
            
        out["fiftyTwoWeekLow"] = quote.get("fiftyTwoWeekLow")
        out["fiftyTwoWeekHigh"] = quote.get("fiftyTwoWeekHigh")
    else:
        price = safe_float(asset.get("current_price")) or 0
        out["data_source"] = "Seed data from researched report"
        out["last_price_update_utc"] = None
        out["day_change"] = None
        out["day_change_pct"] = None
        out["fiftyTwoWeekLow"] = None
        out["fiftyTwoWeekHigh"] = None

    if div_data and div_data.get("ttm_income"):
        out["ttm_income"] = div_data["ttm_income"]
        out["last_dividend_amount"] = div_data["last_dividend_amount"]
        out["last_dividend_date"] = div_data["last_dividend_date"]
        out["dividend_count"] = div_data["dividend_count"]
    else:
        out["ttm_income"] = safe_float(asset.get("ttm_income")) or 0
        asset_type = str(out.get("type", "")).lower()
        if asset_type in ["invit", "reit"]:
            out["dividend_count"] = 4  # Default to quarterly for trusts if API fails
        else:
            out["dividend_count"] = 1  # Default to annual for equities if API fails

    out["current_price"] = round(price, 2) if price else None
    ttm_income = out["ttm_income"]
    annual_yield = (ttm_income / price * 100) if price else 0
    out["annual_yield_pct"] = round(annual_yield, 2)
    out["monthly_yield_pct"] = round(annual_yield / 12, 2)
    out["clears_12pct"] = annual_yield >= 12

    # Revert to the accurate researched Buy Zone from the report, OR calculate dynamic if missing
    buy_zone_str = str(asset.get("buy_zone", ""))
    out["is_in_buy_zone"] = False

    # Only treat it as a "researched" zone if it actually matches a Low-High range.
    # Predicted/Technical placeholders (e.g. "Predicted: Under ₹123.4") saved on a
    # previously-added asset must NOT be reused as-is, otherwise the zone freezes
    # forever instead of being recalculated from the latest 52-week range.
    range_match = re.search(r'(?:Rs\.?|₹)?\s*([\d\.]+)\s*-\s*([\d\.]+)', buy_zone_str) if buy_zone_str else None

    if range_match:
        out["buy_zone"] = buy_zone_str
        low = float(range_match.group(1))
        high = float(range_match.group(2))
        if price and low <= price <= high:
            out["is_in_buy_zone"] = True
    else:
        # Predict buy zone for unresearched/searched assets
        if out.get("fiftyTwoWeekLow") and out.get("fiftyTwoWeekHigh"):
            low = out["fiftyTwoWeekLow"]
            high = out["fiftyTwoWeekHigh"]
            
            if ttm_income > 0:
                tech_target = low + (high - low) * 0.25
                asset_type = str(out.get("type", "")).lower()
                target_yield = 0.095 if asset_type in ["invit", "reit"] else 0.05
                yield_target = ttm_income / target_yield
                buy_zone_max = (tech_target + yield_target) / 2
                out["buy_zone"] = f"Predicted: Under ₹{round(buy_zone_max, 1)}"
            else:
                # Fallback to technical-only buy zone
                buy_zone_max = low + (high - low) * 0.30
                out["buy_zone"] = f"Technical: Under ₹{round(buy_zone_max, 1)}"
                
            if price and price <= buy_zone_max:
                out["is_in_buy_zone"] = True
        else:
            out["buy_zone"] = "N/A"

    return out


from pydantic import BaseModel
from fastapi import HTTPException, Request, Response
from fastapi.responses import RedirectResponse

class LoginRequest(BaseModel):
    username: str
    password: str

def load_users() -> Dict[str, str]:
    if not USERS_PATH.exists():
        return {"admin": "password"}
    with USERS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_users(users: Dict[str, str]):
    with USERS_PATH.open("w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)

def load_user_assets() -> Dict[str, List[Dict[str, Any]]]:
    if not USER_ASSETS_PATH.exists():
        return {}
    with USER_ASSETS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_user_assets(data: Dict[str, List[Dict[str, Any]]]):
    with USER_ASSETS_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_secret_key() -> bytes:
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_bytes()
    key = secrets.token_bytes(32)
    SECRET_KEY_PATH.write_bytes(key)
    return key

SECRET_KEY = get_secret_key()

def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"{salt}${digest.hex()}"

def verify_password(password: str, stored: str) -> bool:
    if "$" not in stored:
        # Legacy plaintext entry from before hashing was added.
        return hmac.compare_digest(password, stored)
    salt, _, _ = stored.partition("$")
    return hmac.compare_digest(hash_password(password, salt), stored)

def create_session_token(username: str) -> str:
    sig = hmac.new(SECRET_KEY, username.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{username}.{sig}"

def verify_session_token(token: str) -> Optional[str]:
    if not token or "." not in token:
        return None
    username, _, sig = token.rpartition(".")
    expected = hmac.new(SECRET_KEY, username.encode("utf-8"), hashlib.sha256).hexdigest()
    if username and hmac.compare_digest(sig, expected):
        return username
    return None

def get_current_user(request: Request) -> Optional[str]:
    token = request.cookies.get("auth_token")
    if not token:
        return None
    return verify_session_token(token)

@app.get("/login")
def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return FileResponse(BASE_DIR / "static" / "login.html")

@app.get("/register")
def register_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/", status_code=302)
    return FileResponse(BASE_DIR / "static" / "register.html")

@app.post("/api/login")
def api_login(credentials: LoginRequest, response: Response):
    users = load_users()
    stored = users.get(credentials.username)
    if stored and verify_password(credentials.password, stored):
        if "$" not in stored:
            # Upgrade legacy plaintext entries to a hashed password on next login.
            users[credentials.username] = hash_password(credentials.password)
            save_users(users)
        response = JSONResponse({"success": True})
        response.set_cookie(
            key="auth_token",
            value=create_session_token(credentials.username),
            httponly=True,
            samesite="lax",
            max_age=86400 * 30 # 30 days
        )
        return response
    return JSONResponse({"success": False, "error": "Invalid credentials"}, status_code=401)

@app.post("/api/register")
def api_register(credentials: LoginRequest):
    users = load_users()
    if credentials.username in users:
        return JSONResponse({"success": False, "error": "Username already exists"}, status_code=400)
    if len(credentials.password) < 4:
        return JSONResponse({"success": False, "error": "Password too short (min 4 characters)"}, status_code=400)
    if not credentials.username.isalnum():
        return JSONResponse({"success": False, "error": "Username must be alphanumeric"}, status_code=400)

    users[credentials.username] = hash_password(credentials.password)
    save_users(users)
    
    # Pre-copy default dashboard for new user
    user_assets_db = load_user_assets()
    user_assets_db[credentials.username] = load_assets()
    save_user_assets(user_assets_db)
    
    return JSONResponse({"success": True})

@app.post("/api/logout")
def api_logout():
    response = JSONResponse({"success": True})
    response.delete_cookie("auth_token")
    return response

@app.get("/")
def index(request: Request):
    if not get_current_user(request):
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse(BASE_DIR / "static" / "index.html")

@app.get("/search")
def search_page(request: Request):
    if not get_current_user(request):
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse(BASE_DIR / "static" / "search.html")

@app.get("/api/assets")
def get_assets(
    request: Request,
    live: bool = Query(True, description="Try to refresh prices from free/delayed quote source."),
    force: bool = Query(False, description="Force refresh bypassing cache."),
    type_filter: str = Query("all", description="all, equity, invit, reit"),
    confidence: str = Query("all"),
    min_yield: float = Query(0),
    sort_by: str = Query("yield", description="confidence, yield, price, change, asset"),
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_assets_db = load_user_assets()
    if user in user_assets_db:
        raw_assets = user_assets_db[user]
    else:
        raw_assets = load_assets()

    assets = [enrich_asset(a, live=live, force=force) for a in raw_assets]

    if type_filter.lower() != "all":
        assets = [a for a in assets if str(a.get("type", "")).lower() == type_filter.lower()]
    if confidence.lower() != "all":
        assets = [a for a in assets if str(a.get("confidence", "")).lower() == confidence.lower()]
    if min_yield:
        assets = [a for a in assets if a.get("annual_yield_pct", 0) >= min_yield]

    if sort_by == "yield":
        assets.sort(key=lambda x: x.get("annual_yield_pct", 0), reverse=True)
    elif sort_by == "price":
        assets.sort(key=lambda x: x.get("current_price") or 0)
    elif sort_by == "change":
        assets.sort(key=lambda x: x.get("day_change_pct") if x.get("day_change_pct") is not None else -999, reverse=True)
    elif sort_by == "asset":
        assets.sort(key=lambda x: x.get("asset", ""))
    else:
        assets.sort(key=lambda x: (CONFIDENCE_ORDER.get(x.get("confidence"), 0), x.get("annual_yield_pct", 0)), reverse=True)

    return JSONResponse({
        "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(assets),
        "assets": assets,
        "disclaimer": "Free quote data may be delayed or unavailable. Use a licensed data feed for production trading decisions. This is not financial advice.",
    })

@app.get("/api/portfolio")
def get_portfolio(
    request: Request,
    amount: float = Query(100000, description="Total investment amount, allocated equally across qualifying assets."),
    min_confidence: str = Query("all"),
    type_filter: str = Query("all", description="all, equity, invit, reit"),
    live: bool = Query(True, description="Try to refresh prices from free/delayed quote source."),
):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_assets_db = load_user_assets()
    raw_assets = user_assets_db.get(user) or load_assets()
    assets = [enrich_asset(a, live=live) for a in raw_assets]

    if type_filter.lower() != "all":
        assets = [a for a in assets if str(a.get("type", "")).lower() == type_filter.lower()]
    if min_confidence.lower() != "all":
        threshold = CONFIDENCE_ORDER.get(min_confidence, 0)
        assets = [a for a in assets if CONFIDENCE_ORDER.get(a.get("confidence"), 0) >= threshold]

    n = len(assets)
    per_asset_amount = (amount / n) if n else 0
    total_annual_income = 0.0
    holdings = []
    for a in assets:
        est_annual = per_asset_amount * (a.get("annual_yield_pct", 0) / 100)
        total_annual_income += est_annual
        holdings.append({
            "asset": a.get("asset"),
            "ticker": a.get("ticker"),
            "type": a.get("type"),
            "confidence": a.get("confidence"),
            "annual_yield_pct": a.get("annual_yield_pct"),
            "allocated_amount": round(per_asset_amount, 2),
            "estimated_annual_income": round(est_annual, 2),
        })

    return JSONResponse({
        "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_investment": amount,
        "asset_count": n,
        "estimated_annual_income": round(total_annual_income, 2),
        "estimated_monthly_income": round(total_annual_income / 12, 2),
        "blended_annual_yield_pct": round((total_annual_income / amount * 100), 2) if amount else 0,
        "holdings": holdings,
        "disclaimer": "Free quote data may be delayed or unavailable. Use a licensed data feed for production trading decisions. This is not financial advice.",
    })

class AddAssetRequest(BaseModel):
    asset: Dict[str, Any]

@app.post("/api/assets/add")
def add_asset(request: Request, payload: AddAssetRequest):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_assets_db = load_user_assets()
    if user not in user_assets_db:
        user_assets_db[user] = load_assets()
    
    new_ticker = payload.asset.get("ticker")
    if any(a.get("ticker") == new_ticker for a in user_assets_db[user]):
        return JSONResponse({"success": False, "error": "Asset already in dashboard"})
        
    user_assets_db[user].append(payload.asset)
    save_user_assets(user_assets_db)
    return JSONResponse({"success": True})

@app.delete("/api/assets/remove/{ticker:path}")
def remove_asset(request: Request, ticker: str):
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_assets_db = load_user_assets()
    if user not in user_assets_db:
        user_assets_db[user] = load_assets()
    
    original_len = len(user_assets_db[user])
    user_assets_db[user] = [a for a in user_assets_db[user] if a.get("ticker") != ticker]
    
    if len(user_assets_db[user]) < original_len:
        save_user_assets(user_assets_db)
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "Asset not found"})

@app.get("/api/search")
def search_asset(request: Request, ticker: str = Query(..., description="NSE Ticker symbol or company name")):
    if not get_current_user(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

    query = ticker.strip()
    symbol = query.upper()
    
    # Try NSE Autocomplete first
    try:
        if not NSE_SESSION.cookies:
            NSE_SESSION.get("https://www.nseindia.com", timeout=5)
            
        url = f"https://www.nseindia.com/api/search/autocomplete?q={query}"
        r = NSE_SESSION.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            symbols = data.get("symbols", [])
            if symbols:
                # Pick the first valid symbol match
                for s in symbols:
                    if s.get("result_type") == "symbol":
                        symbol = s.get("symbol", symbol).upper()
                        break
    except Exception:
        pass

    # Dummy asset dict for search
    asset_dict = {
        "asset": symbol,
        "symbol": symbol,
        "ticker": f"{symbol}.NS",
        "type": "Equity",
        "confidence": "Unresearched",
        "risk": "Unresearched"
    }
    
    enriched = enrich_asset(asset_dict, live=True, force=True)
    if enriched.get("current_price") is None:
        return JSONResponse({"error": f"Could not fetch data for {symbol}. Make sure it is a valid NSE ticker."}, status_code=404)
        
    # Replace dummy asset name if companyName was found
    if enriched.get("data_source") == "NSE Live API":
        cached = CACHE.get(f"{symbol}.NS")
        if cached and "companyName" in cached["data"]:
            enriched["asset"] = cached["data"]["companyName"]
            
    return JSONResponse({"asset": enriched})
