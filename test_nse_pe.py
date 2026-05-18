import requests
import json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.5'
}
session = requests.Session()
session.get("https://www.nseindia.com", headers=headers, timeout=5)

r = session.get("https://www.nseindia.com/api/quote-equity?symbol=RECLTD", headers=headers, timeout=5)
try:
    data = r.json()
    print("Price Info:", data.get('priceInfo'))
    print("Security Info:", data.get('securityInfo'))
    print("Metadata:", data.get('metadata'))
    
    # Also fetch corporate actions to count dividends
    r2 = session.get("https://www.nseindia.com/api/quote-equity?symbol=RECLTD&section=corp_info", headers=headers, timeout=5)
    corp_data = r2.json()
    print("Corp Info keys:", corp_data.keys())
    print("Corp Actions:", corp_data.get('corporateActions', {}).keys() if 'corporateActions' in corp_data else corp_data.get('corporate_actions'))
except Exception as e:
    print("Error:", e)
