# run_daegu_saltbread.py
import json
import re
import time
from pathlib import Path
import pandas as pd

from src.config.settings import assert_env, SEARCH_LIMIT, GEOCODE_LIMIT
from src.clients.naver_search import local_search
from src.clients.naver_geo import geocode
from src.utils.quota_guard import QuotaGuard

BASE_DIR = Path(__file__).resolve().parents[1]  # saltbread_seed/
INPUT_DIR = BASE_DIR / "data" / "inputs" / "daegu"
RAW_DIR = BASE_DIR / "data" / "raw" / "daegu"
OUT_DIR = BASE_DIR / "data" / "output"
CACHE_PATH = BASE_DIR / "data" / "interim" / "geocode_cache_daegu.json"

RAW_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

PAREN_RE = re.compile(r"\([^)]*\)")  # 괄호 내용 제거용

def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}

def save_cache(cache: dict):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def read_keywords_from_admin_dongs() -> list[str]:
    path = INPUT_DIR / "admin_dongs.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    if "keyword" not in df.columns:
        raise RuntimeError("admin_dongs.csv에는 keyword 컬럼이 필요합니다.")
    return [str(x).strip() for x in df["keyword"].tolist() if str(x).strip()]

def read_keywords_from_hotspots() -> list[str]:
    path = INPUT_DIR / "hotspots.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    if "keyword" not in df.columns:
        raise RuntimeError("hotspots.csv에는 keyword 컬럼이 필요합니다.")
    return [str(x).strip() for x in df["keyword"].tolist() if str(x).strip()]

def read_keywords_from_subway() -> list[str]:
    """
    subway_stations_raw.csv (line, station_code, station_name_ko)
    - station_name_ko에서 괄호 제거
    - '역' 버전도 같이 생성
    """
    path = INPUT_DIR / "subway_stations_raw.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path)
    if "station_name_ko" not in df.columns:
        raise RuntimeError("subway_stations_raw.csv에는 station_name_ko 컬럼이 필요합니다.")

    bases = []
    for s in df["station_name_ko"].tolist():
        s = str(s).strip()
        if not s:
            continue
        base = PAREN_RE.sub("", s).strip()
        if base:
            bases.append(base)
    # 역 키워드 다양화: "반월당", "반월당역" 둘 다
    keywords = set()
    for b in bases:
        keywords.add(b)
        if not b.endswith("역"):
            keywords.add(b + "역")
    return list(keywords)

def normalize_name(s: str) -> str:
    """중복 제거 강화를 위한 이름 정규화(공백/특수문자 약간 제거)"""
    s = (s or "").strip()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[\"'’‘·•.,/]", "", s)
    return s

def build_daegu_queries() -> list[str]:
    # 템플릿(쿼리 꼬리)
    tails = ["소금빵", "소금빵 베이커리", "소금빵 카페", "소금빵 맛집"]

    # 키워드 소스들
    dongs = read_keywords_from_admin_dongs()
    hotspots = read_keywords_from_hotspots()
    stations = read_keywords_from_subway()

    # 기존 구/군 레벨도 같이(너무 적게 나오는 걸 방지)
    districts = ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군"]

    keywords = set()
    for x in dongs + hotspots + stations + districts:
        x = str(x).strip()
        if x:
            keywords.add(x)

    # 기본 쿼리 + 키워드 확장 쿼리
    queries = ["대구 소금빵"]
    for kw in sorted(keywords):
        for t in tails:
            queries.append(f"대구 {kw} {t}")

    # 혹시 너무 많아지면 상한(필요시 조절)
    # 대구는 보통 수백~천 단위라 괜찮지만, 안전장치로 4000 제한
    MAX_QUERIES = 4000
    if len(queries) > MAX_QUERIES:
        queries = queries[:MAX_QUERIES]

    return queries

def safe_search(query: str, search_guard: QuotaGuard, max_retries: int = 4):
    """
    429(Too Many Requests) 대비 백오프 재시도.
    401이면 키 문제라 재시도 의미 없음.
    """
    delay = 0.6
    for _ in range(max_retries):
        search_guard.tick()
        try:
            return local_search(query, display=5, start=1, sort="comment")
        except Exception as e:
            msg = str(e)
            if "429" in msg:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    return []

def safe_filename(s: str) -> str:
    # 특수문자 들어올때 파일 저장 깨지는거 방지
    s = re.sub(r"[^\w\s-]", "", s)  # 특수문자 제거
    s = re.sub(r"\s+", "_", s).strip("_")
    return s[:120]  # 너무 긴 파일명 방지

def main():
    start_t = time.perf_counter()
    assert_env()

    search_guard = QuotaGuard(SEARCH_LIMIT, "NAVER_SEARCH")
    geo_guard = QuotaGuard(GEOCODE_LIMIT, "NAVER_GEOCODE")

    cache = load_cache()
    queries = build_daegu_queries()

    print(f"🔎 queries: {len(queries)}")
    # 쿼리 목록 저장(재현/디버깅용)
    (RAW_DIR / "_queries.txt").write_text("\n".join(queries), encoding="utf-8")

    seen = set()  # (norm_name, road_address)
    rows = []

    for idx, q in enumerate(queries, start=1):
        try:
            items = safe_search(q, search_guard)
        except Exception as e:
            print(f"[WARN] search failed: {q} => {e}")
            continue

        if idx % 20 == 0:
            print(f"[{idx}/{len(queries)}] unique={len(seen)} rows={len(rows)} last_query='{q}'")

        # raw 저장(너무 많아질 수 있어서 50개마다 1번만 저장해도 됨)
        if idx <= 60:  # 처음 60개만 저장 (원하면 숫자 늘려도 됨)
            (RAW_DIR / f"{safe_filename(q)}.json").write_text(
                json.dumps(items, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        for it in items:
            name = (it.get("title") or "").strip()
            #<b> 대구 </b> 이런거 정제용
            name = re.sub(r"<[^>]+>", "", name).strip()
            road = (it.get("roadAddress") or "").strip()
            jibun = (it.get("address") or "").strip()
            tel = (it.get("telephone") or "").strip()
            link = (it.get("link") or "").strip()
            category_text = (it.get("category") or "").strip()
            mapx = (it.get("mapx") or "").strip()
            mapy = (it.get("mapy") or "").strip()

            if not name or not road:
                continue

            key = (normalize_name(name), road)
            if key in seen:
                continue
            seen.add(key)

            # 지오코딩 캐시
            if road in cache:
                lon, lat = cache[road]["lon"], cache[road]["lat"]
                err = None
            else:
                geo_guard.tick()
                lon, lat, err = geocode(road)
                if lon is not None and lat is not None:
                    cache[road] = {"lon": lon, "lat": lat}
                time.sleep(0.07)

            rows.append({
                "dessert_category": "saltbread",
                "region": "daegu",
                "query": q,
                "name": name,
                "road_address": road,
                "jibun_address": jibun,
                "telephone": tel,
                "external_link": link,   # 네이버 지도 링크가 아닐 수도 있어서 이름 변경
                "category_text": category_text,
                "mapx": mapx,
                "mapy": mapy,
                "longitude": lon,
                "latitude": lat,
                "geocode_error": "" if err is None else str(err)[:200],
            })

        # 검색 쿼리 간 텀(429 방지)
        time.sleep(0.2)

    save_cache(cache)

    df = pd.DataFrame(rows)
    if df.empty:
        print("❌ 수집 결과 0건. query/키워드/검색API 설정을 확인하세요.")
        return

    # 좌표 없는 건 아래로
    if "latitude" in df.columns:
        df.sort_values(by=["latitude"], na_position="last", inplace=True)

    # csv저장하기 전에 대구광역시로 시작하는거만 daegu파일에 그나머지는 다른파일에 저장
    # --- region filter: keep only Daegu, but save out-of-region too ---
    before = len(df)

    mask = (
            df["road_address"].astype(str).str.startswith("대구광역시")
            | df["jibun_address"].astype(str).str.startswith("대구광역시")
    )

    out_df = df[~mask].copy()
    df = df[mask].copy()

    after = len(df)

    if not out_df.empty:
        out_of_region_path = OUT_DIR / "daegu_saltbread_places_out_of_region.csv"
        out_df.to_csv(out_of_region_path, index=False, encoding="utf-8-sig")
        print(f"🧹 filtered out_of_region: {len(out_df)} saved: {out_of_region_path}")

    print(f"🧹 region filter kept: {after}/{before}")

    out_path = OUT_DIR / "daegu_saltbread_places.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"✅ saved: {out_path} (rows={len(df)})")
    print(f"   search calls used: {search_guard.count}/{search_guard.limit}")
    print(f"   geocode calls used: {geo_guard.count}/{geo_guard.limit}")
    elapsed = time.perf_counter() - start_t
    print(f"⏱ elapsed: {elapsed:.1f}s ({elapsed / 60:.1f} min)")

if __name__ == "__main__":
    main()
