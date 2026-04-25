import urllib.request, re, json
from collections import Counter

url = "https://ti-assistant.com/en/archive"
with urllib.request.urlopen(url, timeout=30) as resp:
    html = resp.read().decode("utf-8", errors="ignore")

m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
if m:
    print("Found __NEXT_DATA__")
    data = json.loads(m.group(1))
    print(json.dumps(data, indent=2)[:2000])
else:
    print("No __NEXT_DATA__ found")

# Look for RSC / self.__next_f payloads containing archive IDs
rsc_blocks = re.findall(r'self\.__next_f\.push\(\[.*?\]\)', html[:50000])
print(f"RSC push blocks found: {len(rsc_blocks)}")
print(rsc_blocks[:3])

# Check for any JSON-like structures with gameId
game_ids = re.findall(r'"gameId"\s*:\s*"([^"]+)"', html)
print(f"gameId fields: {game_ids[:20]}")

# Also check for /api/<id>/download patterns
api_ids = re.findall(r'/api/([A-Za-z0-9]{6})/download', html)
print(f"API download IDs: {api_ids[:20]}")
