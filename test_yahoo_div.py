import requests
import time

headers = {'User-Agent': 'Mozilla/5.0'}
url = "https://query2.finance.yahoo.com/v8/finance/chart/RECLTD.NS?interval=1d&range=1y&events=div"
r = requests.get(url, headers=headers)
data = r.json()
print("Yahoo Dividends:", data.get('chart', {}).get('result', [{}])[0].get('events', {}).get('dividends'))

url = "https://query2.finance.yahoo.com/v8/finance/chart/PGINVIT.NS?interval=1d&range=1y&events=div"
r = requests.get(url, headers=headers)
data = r.json()
print("PGINVIT Yahoo Dividends:", data.get('chart', {}).get('result', [{}])[0].get('events', {}).get('dividends'))

