import urllib.request, json

# Try known API endpoints
endpoints = [
    "https://ti-assistant.com/api/archive",
    "https://ti-assistant.com/api/games",
    "https://ti-assistant.com/api/archive?limit=30",
]
for url in endpoints:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            print(f"URL: {url}  status={resp.status}  len={len(body)}")
            print(body[:300])
    except Exception as e:
        print(f"URL: {url}  ERROR: {e}")
