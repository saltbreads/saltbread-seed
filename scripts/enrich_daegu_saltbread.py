# enrich_daegu_saltbread.py
import json
import random
import time
from pathlib import Path

import pandas as pd

from src.clients.naver_map_allsearch import allsearch, extract_place_candidates, choose_best_candidate
from src.clients.naver_place_detail import fetch_place_html, parse_next_data, extract_place_fields

BASE_DIR = Path(__file__).resolve().parents[1]
IN_PATH = BASE_DIR / "data" / "output" / "daegu_saltbread_places.csv"
OUT_PLACES = BASE_DIR / "data" / "output" / "daegu_saltbread_places_enriched.csv"
OUT_MENUS = BASE_DIR / "data" / "output" / "daegu_saltbread_menus.csv"
RAW_DIR = BASE_DIR / "data" / "raw" / "daegu" / "enrich"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# 대구 중심 좌표(반월당 근처). allSearch에 searchCoord로 사용 (경도;위도)
DAEGU_CENTER = "128.5949;35.8668"


def try_allsearch_strategies(name: str, road: str, search_coord: str, boundary: str):
    # 1) 이름만 (좌표/경계 적용)
    yield name, search_coord, boundary
    # 2) 지역 prefix (동명이인/타지역 방지)
    yield f"대구 {name}", search_coord, boundary
    # 3) 마지막: boundary 제거(더 넓게)
    yield f"대구 {name}", search_coord, ""


def main():
    start_t = time.perf_counter()

    df = pd.read_csv(IN_PATH)

    # --- keep only Daegu rows, save out-of-region ---
    mask = (
            df["road_address"].astype(str).str.startswith("대구광역시")
            | df["jibun_address"].astype(str).str.startswith("대구광역시")
    )

    out_df = df[~mask].copy()
    df = df[mask].copy()

    if not out_df.empty:
        out_path = BASE_DIR / "data" / "output" / "daegu_saltbread_places_enrich_out_of_region.csv"
        out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"🧹 enrich filtered out_of_region: {len(out_df)} saved: {out_path}")

    print(f"🧹 enrich target(daegu): {len(df)} rows")

    if df.empty:
        print("❌ input csv is empty")
        return

    # 너무 많으면 샘플로 먼저 돌리고 싶을 때
    df = df.head(30)

    enriched_rows = []
    menu_rows = []

    for i, row in df.iterrows():
        name = str(row.get("name") or "").strip()
        road = str(row.get("road_address") or "").strip()

        query = f"{name} {road}"
        status = "OK"
        sid = ""

        # row별 좌표를 searchCoord로 사용 (없으면 DAEGU_CENTER로 fallback)
        lon = row.get("longitude")
        lat = row.get("latitude")

        if pd.notna(lon) and pd.notna(lat):
            search_coord = f"{float(lon)};{float(lat)}"
        else:
            search_coord = DAEGU_CENTER

        # boundary: (minLon;minLat;maxLon;maxLat) 형태로 쓰는 경우가 많아서 이렇게 박스 생성
        # 0.03도 ≈ 3km대 (대구는 이 정도면 충분히 주변 후보를 모음)
        boundary = ""
        if pd.notna(lon) and pd.notna(lat):
            lon_f = float(lon)
            lat_f = float(lat)
            d = 0.03
            boundary = f"{lon_f - d};{lat_f - d};{lon_f + d};{lat_f + d}"

        try:
            best = None
            last_payload = None

            # 여러 전략으로 sid 찾기 (query 다양화)
            for q2, sc2, b2 in try_allsearch_strategies(name, road, search_coord, boundary):
                payload = allsearch(query=q2, search_coord=sc2, boundary=b2, page=1)
                last_payload = payload

                cands = extract_place_candidates(payload, limit=10)
                best = choose_best_candidate(cands, seed_name=name, seed_road=road)

                if best:
                    sid = best.sid
                    status = "OK"
                    break

            # 디버그: best가 없을 때만 저장하면 용량 줄어듦
            if best is None:
                status = "NO_SID"
                if i < 10 and last_payload is not None:
                    (RAW_DIR / f"allsearch_no_sid_{i}.json").write_text(
                        json.dumps(last_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

        except Exception as e:
            status = f"ALLSEARCH_ERR:{type(e).__name__}"


        detail = {"opening_hours_json": "", "homepage_url": "", "thumbnail_url": "", "menus": []}

        if sid:
            try:
                html = fetch_place_html(sid)
                if i < 3:  # 처음 3개만 html 저장(용량 방지)
                    (RAW_DIR / f"place_{sid}.html").write_text(html, encoding="utf-8")

                next_data = parse_next_data(html)
                if not next_data:
                    status = "NO_NEXT_DATA"
                else:
                    detail = extract_place_fields(next_data)
            except Exception as e:
                status = f"DETAIL_ERR:{type(e).__name__}"

        out_row = dict(row)
        out_row["naver_place_id"] = sid
        out_row["enrich_status"] = status
        out_row["opening_hours_json"] = detail.get("opening_hours_json", "")
        out_row["homepage_url"] = detail.get("homepage_url", "")
        out_row["thumbnail_url"] = detail.get("thumbnail_url", "")

        enriched_rows.append(out_row)

        # menus rows
        for m in detail.get("menus", []) or []:
            menu_rows.append({
                "naver_place_id": sid,
                "place_name": name,
                "road_address": road,
                "menu_name": m.get("menu_name", ""),
                "price": m.get("price", ""),
                "raw": m.get("raw", ""),
            })

        # 속도 제한(차단 방지)
        time.sleep(random.uniform(0.6, 1.1))

        if (i + 1) % 20 == 0:
            elapsed = time.perf_counter() - start_t
            ok_cnt = sum(1 for r in enriched_rows if r.get("enrich_status") == "OK")
            print(f"[{i+1}/{len(df)}] ok={ok_cnt} last_status={status} elapsed={elapsed/60:.1f}m")

    out_df = pd.DataFrame(enriched_rows)
    out_df.to_csv(OUT_PLACES, index=False, encoding="utf-8-sig")

    menus_df = pd.DataFrame(menu_rows)
    menus_df.to_csv(OUT_MENUS, index=False, encoding="utf-8-sig")

    elapsed = time.perf_counter() - start_t
    print(f"✅ saved: {OUT_PLACES}")
    print(f"✅ saved: {OUT_MENUS} (menus rows={len(menus_df)})")
    print(f"⏱ elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)")

if __name__ == "__main__":
    main()
