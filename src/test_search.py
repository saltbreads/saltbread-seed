from pathlib import Path
from dotenv import load_dotenv
import os, requests

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

cid = os.getenv("NAVER_SEARCH_CLIENT_ID", "").strip()
csec = os.getenv("NAVER_SEARCH_CLIENT_SECRET", "").strip()

r = requests.get(
    "https://openapi.naver.com/v1/search/local.json",
    headers={
        "X-Naver-Client-Id": cid,
        "X-Naver-Client-Secret": csec,
        "Accept": "application/json",
    },
    params={"query": "대구 소금빵", "display": 5, "start": 1, "sort": "comment"},
    timeout=15,
)

print(r.status_code)
print(r.text[:500])
