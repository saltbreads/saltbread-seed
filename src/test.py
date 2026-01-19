# test.py
import os, requests
from dotenv import load_dotenv
load_dotenv()

url = os.getenv("NAVER_GEOCODE_URL")
cid = os.getenv("NAVER_MAPS_CLIENT_ID")
csec = os.getenv("NAVER_MAPS_CLIENT_SECRET")

r = requests.get(
    url,
    headers={
        "X-NCP-APIGW-API-KEY-ID": cid,
        "X-NCP-APIGW-API-KEY": csec,
        "Accept": "application/json",
    },
    params={"query": "대구광역시 중구 동성로2길 5"},
    timeout=15,
)

print(r.status_code)
print(r.text[:300])

