# src/main.py
from src.config.settings import assert_env
from src.clients.naver_geo import geocode
from src.pipelines.export_csv import save_places_csv

def run_demo_geocode_to_csv():
    assert_env()

    # 테스트용 샘플 주소 3개 (원하는 걸로 바꿔도 됨)
    samples = [
        {"name": "샘플1", "road_address": "대구광역시 중구 동성로2길 5"},
        {"name": "샘플2", "road_address": "서울특별시 중구 세종대로 110"},
        {"name": "샘플3", "road_address": "부산광역시 해운대구 우동 1418-2"},
    ]

    rows = []
    for s in samples:
        lon, lat, err = geocode(s["road_address"])
        rows.append({
            "dessert_category": "saltbread",
            "name": s["name"],
            "road_address": s["road_address"],
            "longitude": lon,
            "latitude": lat,
            "geocode_error": None if err is None else str(err)[:200],
        })

    out = save_places_csv(rows, "data/output/demo_places.csv")
    print(f"✅ saved: {out}")

if __name__ == "__main__":
    run_demo_geocode_to_csv()
