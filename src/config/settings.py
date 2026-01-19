# src/config/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv

#.env 로드는 여기서만 관리
BASE_DIR = Path(__file__).resolve().parents[2]  # saltbread_seed/
load_dotenv(BASE_DIR / ".env")
# load_dotenv()

NAVER_MAPS_CLIENT_ID = os.getenv("NAVER_MAPS_CLIENT_ID")
NAVER_MAPS_CLIENT_SECRET = os.getenv("NAVER_MAPS_CLIENT_SECRET")

# Geocoding 엔드포인트(일반적으로 ntruss)
NAVER_GEOCODE_URL = os.getenv(
    "NAVER_GEOCODE_URL",
    "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"
)

# 네이버 검색
NAVER_SEARCH_CLIENT_ID = (os.getenv("NAVER_SEARCH_CLIENT_ID") or "").strip()
NAVER_SEARCH_CLIENT_SECRET = (os.getenv("NAVER_SEARCH_CLIENT_SECRET") or "").strip()
NAVER_LOCAL_SEARCH_URL = "https://openapi.naver.com/v1/search/local.json"


#요청량은 무료사용량 한도의 최대의 90% 까지
GEOCODE_MONTHLY_FREE = int(os.getenv("GEOCODE_MONTHLY_FREE", "3000000"))
SEARCH_DAILY_FREE = int(os.getenv("SEARCH_DAILY_FREE", "25000"))  # 네이버 검색 API 하루 호출 한도 25,000회 :contentReference[oaicite:0]{index=0}
STOP_RATIO = float(os.getenv("STOP_RATIO", "0.9"))

GEOCODE_LIMIT = int(GEOCODE_MONTHLY_FREE * STOP_RATIO)
SEARCH_LIMIT = int(SEARCH_DAILY_FREE * STOP_RATIO)

def assert_env():
    missing = []
    if not NAVER_GEOCODE_URL: missing.append("NAVER_GEOCODE_URL")
    if not NAVER_MAPS_CLIENT_ID: missing.append("NAVER_MAPS_CLIENT_ID")
    if not NAVER_MAPS_CLIENT_SECRET: missing.append("NAVER_MAPS_CLIENT_SECRET")
    if not NAVER_SEARCH_CLIENT_ID: missing.append("NAVER_SEARCH_CLIENT_ID")
    if not NAVER_SEARCH_CLIENT_SECRET: missing.append("NAVER_SEARCH_CLIENT_SECRET")

    if missing:
        raise RuntimeError(f".env 누락: {', '.join(missing)}")
