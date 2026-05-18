import requests
import json
import time

with open("app/data/assets.json", "r") as f:
    assets = json.load(f)

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.5'
}
session = requests.Session()
session.get("https://www.nseindia.com", headers=headers, timeout=5)

for a in assets:
    sym = a['symbol']
    try:
        r = session.get(f"https://www.nseindia.com/api/quote-equity?symbol={sym}", headers=headers, timeout=5)
        data = r.json()
        print(f"{sym}: {data['priceInfo']['lastPrice']}")
    except Exception as e:
        print(f"{sym}: FAILED - {e}")
    time.sleep(0.5)
