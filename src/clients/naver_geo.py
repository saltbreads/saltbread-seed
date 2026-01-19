# src/clients/naver_geo.py
import requests
from src.config.settings import NAVER_MAPS_CLIENT_ID, NAVER_MAPS_CLIENT_SECRET, NAVER_GEOCODE_URL

def geocode(query: str, timeout: int = 15):
    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_MAPS_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_MAPS_CLIENT_SECRET,
        "Accept": "application/json",
    }
    params = {"query": query}

    r = requests.get(NAVER_GEOCODE_URL, headers=headers, params=params, timeout=timeout)
    if r.status_code != 200:
        return None, None, {"status": r.status_code, "body": r.text[:300]}

    data = r.json()
    addresses = data.get("addresses") or []
    if not addresses:
        return None, None, {"status": "NO_RESULT", "body": str(data)[:300]}

    best = addresses[0]
    lon = float(best["x"])  # 경도
    lat = float(best["y"])  # 위도
    return lon, lat, None
