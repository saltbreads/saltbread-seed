import os
from dotenv import load_dotenv

load_dotenv()

print("URL:", bool(os.getenv("NAVER_GEOCODE_URL")))
print("SEARCH_ID:", bool(os.getenv("NAVER_SEARCH_CLIENT_ID")))
print("SEARCH_SECRET:", bool(os.getenv("NAVER_SEARCH_CLIENT_SECRET")))
print("MAPS_ID:", bool(os.getenv("NAVER_MAPS_CLIENT_ID")))
print("MAPS_SECRET:", bool(os.getenv("NAVER_MAPS_CLIENT_SECRET")))
