import re
import urllib.request
req = urllib.request.Request('https://www.google.com/finance/quote/INDIGRID:NSE', headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8')
print("Match:", re.findall(r'class="YMlKec fxKbKc">([^<]+)</div>', html))
