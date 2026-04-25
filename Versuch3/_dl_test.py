import urllib.request, json

# Quick test: can we download a game from the hardcoded list?
test_ids = ["46LL3J", "DX6sb4", "v4T6CR"]
for gid in test_ids:
    url = f"https://ti-assistant.com/api/{gid}/download"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read()
            print(f"{gid}: status={resp.status}  bytes={len(body)}")
    except Exception as e:
        print(f"{gid}: ERROR {e}")
