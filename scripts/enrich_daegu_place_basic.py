# scripts/enrich_daegu_place_basic.py
import json
import re
import time
from pathlib import Path

import pandas as pd
from selenium.common.exceptions import WebDriverException

from scripts.collect_daegu_place_ids import make_driver
from src.clients.selenium_naver_map import (
    open_place_by_sid,
    extract_phone,
    extract_ai_briefing,
    extract_visitor_review_keywords,
    extract_hero_image,
    extract_business_hours_raw,
    jitter_sleep,
)

from src.utils.scroll import scroll_n_times

BASE_DIR = Path(__file__).resolve().parents[1]

IN_PATH = BASE_DIR / "data" / "output" / "daegu_saltbread_places_with_sid.csv"
OUT_PATH = BASE_DIR / "data" / "output" / "daegu_saltbread_places_enriched_basic.csv"
CKPT_PATH = BASE_DIR / "data" / "interim" / "daegu_place_basic_checkpoint.csv"
FAIL_DIR = BASE_DIR / "data" / "raw" / "daegu" / "selenium_basic_fail"
FAIL_DIR.mkdir(parents=True, exist_ok=True)
CKPT_PATH.parent.mkdir(parents=True, exist_ok=True)


def safe_int_sid(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
        return int(float(v))  # 1139406200.0 케이스 대응
    except Exception:
        return None


def merge_checkpoint(df: pd.DataFrame) -> pd.DataFrame:
    if not CKPT_PATH.exists():
        return df

    ck = pd.read_csv(CKPT_PATH)
    key_cols = ["name", "road_address"]

    keep_cols = key_cols + [
        "naver_place_id",
        "basic_status",
        "phone",
        "phone_status",
        "ai_briefing_json",
        "ai_briefing_status",
        "ai_briefing_debug",
        "visitor_review_total",
        "review_kw_json",
        "review_kw_status",
        "review_kw_debug",
        "hero_img_url",
        "hero_img_status",
        "hero_img_debug",
        "hours_raw",
        "hours_status",
        "hours_debug",
    ]
    keep_cols = [c for c in keep_cols if c in ck.columns]

    df = df.merge(
        ck[keep_cols],
        on=key_cols,
        how="left",
        suffixes=("", "_ck"),
    )

    for col in [
        "naver_place_id",
        "basic_status",
        "phone",
        "phone_status",
        "ai_briefing_json",
        "ai_briefing_status",
        "ai_briefing_debug",
        "visitor_review_total",
        "review_kw_json",
        "review_kw_status",
        "review_kw_debug",
        "hero_img_url",
        "hero_img_status",
        "hero_img_debug",
        "hours_raw",
        "hours_status",
        "hours_debug",
    ]:
        if f"{col}_ck" in df.columns:
            df[col] = df[col].where(df[col].astype(str).str.strip().str.len() > 0, df[f"{col}_ck"].fillna(""))
            df.drop(columns=[f"{col}_ck"], inplace=True)

    return df


def save_checkpoint(df: pd.DataFrame):
    df.to_csv(CKPT_PATH, index=False, encoding="utf-8-sig")


def main():
    df = pd.read_csv(IN_PATH)

    # 대구만
    mask_daegu = (
        df["road_address"].astype(str).str.startswith("대구광역시")
        | df["jibun_address"].astype(str).str.startswith("대구광역시")
    )
    df = df[mask_daegu].copy()

    # 컬럼 준비
    for col in [
        "basic_status",
        "phone",
        "phone_status",
        "ai_briefing_json",
        "ai_briefing_status",
        "ai_briefing_debug",
        "visitor_review_total",
        "review_kw_json",
        "review_kw_status",
        "review_kw_debug",
        "hero_img_url",
        "hero_img_status",
        "hero_img_debug",
        "hours_raw",
        "hours_status",
        "hours_debug",
        "basic_try",
        "ai_try",

    ]:
        if col not in df.columns:
            df[col] = 0 if col in ("basic_try", "ai_try") else ""

    df = merge_checkpoint(df)

    MAX_AI_TRIES = 2

    def is_blank(x):
        return str(x or "").strip() == ""

    def to_int(x):
        try:
            return int(x)
        except Exception:
            return 0

    def need_ai_retry(row) -> bool:
        st = str(row.get("ai_briefing_status") or "").strip()
        tries = to_int(row.get("ai_try"))
        if is_blank(st):
            return True
        if st in ("AI_BRIEFING_NOT_FOUND", "AI_BRIEFING_EMPTY") and tries < MAX_AI_TRIES:
            return True
        return False

    def need_phone(row) -> bool:
        return is_blank(row.get("phone_status"))

    def need_keywords(row) -> bool:
        st = str(row.get("review_kw_status") or "").strip()
        # 아예 안 돌렸으면 다시
        if is_blank(st):
            return True
        # 섹션 자체 못찾은건(로딩/스크롤) 재시도 가치 있음
        if st == "VISITOR_REVIEW_SECTION_NOT_FOUND":
            return True
        # - 원래 없다고 치고 끝내려면 False
        # - 그래도 한 번 더 시도해보려면 True
        return False

    #테스트용 코드 부분 나중에 이부분만 False로 하면 다 실행
    DEV_FORCE_RERUN = False  # ✅ 개발 중엔 True: pending 조건 무시하고 무조건 돌림
    TEST_LIMIT = None  # ✅ 개발 중엔 10, 대량 실행 땐 None

    pending = df[
        df["naver_place_id"].notna()
        & (df["naver_place_id"].astype(str).str.strip().str.len() > 0)
        ].copy()

    if not DEV_FORCE_RERUN:
        pending = pending[
            pending["basic_status"].apply(is_blank)
            | pending.apply(need_phone, axis=1)
            | pending.apply(need_ai_retry, axis=1)
            | pending.apply(need_keywords, axis=1)
            # @TODO 펜딩조건 테스트 다끝나고 대문사진, 영업시간 추가 필요
            ].copy()


    # ✅ 테스트 10개
    if TEST_LIMIT:
        pending = pending.head(TEST_LIMIT).copy()
    print(f"DEV_FORCE_RERUN={DEV_FORCE_RERUN} TEST_LIMIT={TEST_LIMIT}")
    print(f"TEST MODE: pending limited to {len(pending)} rows")
    print(f"target rows: {len(df)} | pending basic enrich: {len(pending)}")

    if pending.empty:
        print("✅ nothing to do")
        df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
        return

    driver = None
    t0 = time.perf_counter()

    try:
        driver = make_driver(headless=False)

        done = 0
        for idx, row in pending.iterrows():
            name = str(row.get("name") or "").strip()
            sid = safe_int_sid(row.get("naver_place_id"))

            if not sid:
                df.loc[idx, "basic_status"] = "NO_SID"
                continue

            try:
                ok = open_place_by_sid(driver, sid, timeout=25)
                if not ok:
                    df.loc[idx, "basic_status"] = "OPEN_FAIL"
                else:
                    scroll_n_times(driver, n=6, pause_range=(0.75, 1.35))

                    # 0) 대표사진(대문)
                    hero_url, hero_status, hero_dbg = extract_hero_image(driver, timeout=6, debug=True)
                    df.loc[idx, "hero_img_url"] = hero_url
                    df.loc[idx, "hero_img_status"] = hero_status
                    df.loc[idx, "hero_img_debug"] = hero_dbg

                    # 1) 전화번호
                    phone = extract_phone(driver)
                    df.loc[idx, "phone"] = phone
                    df.loc[idx, "phone_status"] = "OK" if phone else "PHONE_NOT_FOUND"

                    # 2) AI 브리핑 (스크롤 포함)
                    items, ai_status, ai_dbg = extract_ai_briefing(driver, timeout=8, debug=True)
                    df.loc[idx, "ai_briefing_json"] = json.dumps(items, ensure_ascii=False)
                    df.loc[idx, "ai_briefing_status"] = ai_status
                    df.loc[idx, "ai_briefing_debug"] = ai_dbg

                    # 3) 방문자 리뷰 키워드 (상위 5개만)
                    total, kw_items, kw_status, kw_dbg = extract_visitor_review_keywords(driver, timeout=6, debug=True)
                    kw_items = kw_items[:5]

                    df.loc[idx, "visitor_review_total"] = "" if total is None else int(total)
                    df.loc[idx, "review_kw_json"] = json.dumps(kw_items, ensure_ascii=False)
                    df.loc[idx, "review_kw_status"] = kw_status
                    df.loc[idx, "review_kw_debug"] = kw_dbg

                    # 4) 영업시간
                    hours_raw, hours_status, hours_dbg = extract_business_hours_raw(driver, timeout=6, debug=True)
                    df.loc[idx, "hours_raw"] = hours_raw
                    df.loc[idx, "hours_status"] = hours_status
                    df.loc[idx, "hours_debug"] = hours_dbg

                    # ✅ 기본 페이지 OK 여부(개별 필드 실패와 분리)
                    df.loc[idx, "basic_status"] = "OK"

            except WebDriverException as e:
                df.loc[idx, "basic_status"] = f"WEBDRIVER_ERR:{type(e).__name__}"
            except Exception as e:
                df.loc[idx, "basic_status"] = f"ERR:{type(e).__name__}"

            # basic 실패면 스샷
            if df.loc[idx, "basic_status"] != "OK":
                safe_name = re.sub(r"[^0-9a-zA-Z가-힣_ -]", "_", name)[:30]
                shot = FAIL_DIR / f"{idx}_{sid}_{safe_name}.png"
                try:
                    driver.save_screenshot(str(shot))
                except Exception:
                    pass

            done += 1

            # 체크포인트
            save_checkpoint(df)

            print(
                f"[{done}/{len(pending)}] {name} sid={sid} "
                f"basic={df.loc[idx, 'basic_status']} "
                f"hero={df.loc[idx, 'hero_img_status']} "
                f"phone={df.loc[idx, 'phone_status']} "
                f"ai={df.loc[idx, 'ai_briefing_status']} "
                f"kw={df.loc[idx, 'review_kw_status']} "
                f"hours={df.loc[idx, 'hours_status']}"
            )

            jitter_sleep(2.0, 3.0)

        # 최종 저장
        df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

        elapsed = time.perf_counter() - t0
        print(f"✅ saved: {OUT_PATH}")
        print(f"✅ checkpoint: {CKPT_PATH}")
        print(f"⏱ elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()

