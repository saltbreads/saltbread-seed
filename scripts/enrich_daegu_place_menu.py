# scripts/enrich_daegu_place_menu.py
import json
import re
import time
from pathlib import Path

import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException
from scripts.collect_daegu_place_ids import make_driver
from src.utils.scroll import scroll_n_times
from src.clients.selenium_naver_map import (
    open_place_by_sid,
    extract_menu_all,
    jitter_sleep,
)

# ====== PATHS ======
ROOT = Path(__file__).resolve().parents[1]
IN_PATH = ROOT / "data" / "output" / "daegu_saltbread_places_enriched_basic.csv"
OUT_PATH = ROOT / "data" / "output" / "daegu_saltbread_places_enriched_menu.csv"
CKPT_PATH = ROOT / "data" / "interim" / "daegu_place_menu_checkpoint.csv"
FAIL_DIR = ROOT / "data" / "fail_screens_menu"
FAIL_DIR.mkdir(parents=True, exist_ok=True)


def merge_checkpoint(df: pd.DataFrame) -> pd.DataFrame:
    if not CKPT_PATH.exists():
        return df
    ck = pd.read_csv(CKPT_PATH)
    if "naver_place_id" not in ck.columns:
        return df

    # 같은 sid면 ckpt 값을 우선
    key = "naver_place_id"
    df = df.copy()
    df[key] = df[key].astype(str)

    ck = ck.copy()
    ck[key] = ck[key].astype(str)

    # ck에 있는 컬럼만 덮어쓰기
    overwrite_cols = [c for c in ck.columns if c != key]
    df = df.merge(ck[[key] + overwrite_cols], on=key, how="left", suffixes=("", "_ck"))

    for c in overwrite_cols:
        c_ck = f"{c}_ck"
        if c_ck in df.columns:
            df[c] = df[c_ck].where(df[c_ck].notna(), df[c])
            df.drop(columns=[c_ck], inplace=True)

    return df


def save_checkpoint(df: pd.DataFrame):
    # 메뉴 관련 컬럼만 저장해도 되지만, 편하게 전부 저장해도 OK
    df.to_csv(CKPT_PATH, index=False, encoding="utf-8-sig")


def safe_int_sid(x):
    try:
        if pd.isna(x):
            return 0
        s = str(x).strip()
        if not s:
            return 0
        # "1139406200.0" 같은 케이스 대응
        return int(float(s))
    except Exception:
        return 0


def is_blank(x):
    return str(x or "").strip() == ""


def main():
    df = pd.read_csv(IN_PATH)

    # sid 없으면 제외
    df = df[df["naver_place_id"].notna()].copy()
    df["naver_place_id"] = df["naver_place_id"].astype(str)

    # 메뉴 전용 컬럼 준비(없으면 생성)
    menu_cols = [
        "menu_status",
        "menu_debug",
        "menu_count",
        "menu_items_json",
        "menu_img_top5_json",
        "menu_try",
    ]
    for col in menu_cols:
        if col not in df.columns:
            df[col] = 0 if col in ("menu_count", "menu_try") else ""

    df = merge_checkpoint(df)

    DEV_FORCE_RERUN = False   # 개발 중 True
    TEST_LIMIT = None          # 개발 중 10, 대량 실행 None

    pending = df.copy()
    if not DEV_FORCE_RERUN:
        pending = pending[pending["menu_status"].apply(is_blank)].copy()

    if TEST_LIMIT:
        pending = pending.head(TEST_LIMIT).copy()

    print(f"DEV_FORCE_RERUN={DEV_FORCE_RERUN} TEST_LIMIT={TEST_LIMIT}")
    print(f"target rows: {len(df)} | pending menu enrich: {len(pending)}")

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
                df.loc[idx, "menu_status"] = "NO_SID"
                continue

            # try count
            try_n = int(df.loc[idx, "menu_try"] or 0)
            df.loc[idx, "menu_try"] = try_n + 1

            try:
                ok = open_place_by_sid(driver, sid, timeout=25)
                if not ok:
                    df.loc[idx, "menu_status"] = "OPEN_FAIL"
                else:
                    # 메뉴는 섹션이 아래에 있을 수 있어 스크롤 약간
                    scroll_n_times(driver, n=4, pause_range=(0.65, 1.15))

                    items, top5, st, dbg = extract_menu_all(driver, timeout=8, debug=True)

                    df.loc[idx, "menu_status"] = st
                    df.loc[idx, "menu_debug"] = dbg
                    df.loc[idx, "menu_count"] = len(items)
                    df.loc[idx, "menu_items_json"] = json.dumps(items, ensure_ascii=False)
                    df.loc[idx, "menu_img_top5_json"] = json.dumps(top5, ensure_ascii=False)

            except WebDriverException as e:
                df.loc[idx, "menu_status"] = f"WEBDRIVER_ERR:{type(e).__name__}"
            except Exception as e:
                df.loc[idx, "menu_status"] = f"ERR:{type(e).__name__}"

            # 실패 스샷
            if str(df.loc[idx, "menu_status"]) not in ("OK", "MENU_TAB_ABSENT", "MENU_EMPTY"):
                safe_name = re.sub(r"[^0-9a-zA-Z가-힣_ -]", "_", name)[:30]
                shot = FAIL_DIR / f"{idx}_{sid}_{safe_name}.png"
                try:
                    driver.save_screenshot(str(shot))
                except Exception:
                    pass

            done += 1
            save_checkpoint(df)

            print(
                f"[{done}/{len(pending)}] {name} sid={sid} "
                f"menu={df.loc[idx, 'menu_status']} "
                f"count={df.loc[idx, 'menu_count']}"
            )

            jitter_sleep(1.8, 2.6)

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


# # scripts/enrich_daegu_place_menu.py
#
# import json
# import re
# import time
# import pandas as pd
# from pathlib import Path
# from selenium.common.exceptions import WebDriverException
#
# from src.clients.selenium_naver_map import (
#     open_place_by_sid,
#     jitter_sleep,
#     extract_menu_all,
# )
# from scripts.collect_daegu_place_ids import make_driver
# from src.utils.scroll import scroll_n_times
#
# BASE_DIR = Path(__file__).resolve().parents[1]
# IN_PATH = BASE_DIR / "data" / "output" / "daegu_saltbread_places_enriched_basic.csv"
# OUT_PATH = BASE_DIR / "data" / "output" / "daegu_saltbread_places_enriched_menu.csv"
# FAIL_DIR = BASE_DIR / "data" / "fail"
# FAIL_DIR.mkdir(parents=True, exist_ok=True)
#
# def safe_int_sid(x):
#     try:
#         if x is None:
#             return 0
#         s = str(x).strip()
#         if s.endswith(".0"):
#             s = s[:-2]
#         return int(float(s))
#     except Exception:
#         return 0
#
# def main():
#     df = pd.read_csv(IN_PATH)
#
#     pending = df[df["naver_place_id"].notna()].copy()
#     pending["sid"] = pending["naver_place_id"].apply(safe_int_sid)
#     pending = pending[pending["sid"] > 0].copy()
#
#     # 테스트 옵션
#     DEV_FORCE_RERUN = True
#     TEST_LIMIT = 10
#
#     if TEST_LIMIT:
#         pending = pending.head(TEST_LIMIT).copy()
#
#     # 결과는 별도 테이블(롱 포맷)로 쌓기
#     rows = []
#
#     driver = None
#     t0 = time.perf_counter()
#     try:
#         driver = make_driver(headless=False)
#
#         for i, row in pending.iterrows():
#             name = str(row.get("name") or "").strip()
#             sid = int(row["sid"])
#
#             status = ""
#             dbg = ""
#             try:
#                 ok = open_place_by_sid(driver, sid, timeout=25)
#                 if not ok:
#                     status = "OPEN_FAIL"
#                     rows.append({
#                         "sid": sid,
#                         "place_name": name,
#                         "menu_status": status,
#                         "menu_debug": "",
#                         "menu_items_json": "[]",
#                         "menu_img_top5_json": "[]",
#                         "menu_count": 0,
#                     })
#                     continue
#
#                 scroll_n_times(driver, n=4, pause_range=(0.7, 1.2))
#
#                 items, top5_imgs, status, dbg = extract_menu_all(driver, timeout=6, debug=True)
#
#                 rows.append({
#                     "sid": sid,
#                     "place_name": name,
#                     "menu_status": status,
#                     "menu_debug": dbg,
#                     "menu_items_json": json.dumps(items, ensure_ascii=False),
#                     "menu_img_top5_json": json.dumps(top5_imgs, ensure_ascii=False),
#                     "menu_count": len(items),
#                 })
#
#             except WebDriverException as e:
#                 status = f"WEBDRIVER_ERR:{type(e).__name__}"
#                 rows.append({
#                     "sid": sid,
#                     "place_name": name,
#                     "menu_status": status,
#                     "menu_debug": str(e)[:200],
#                     "menu_items_json": "[]",
#                     "menu_img_top5_json": "[]",
#                     "menu_count": 0,
#                 })
#             except Exception as e:
#                 status = f"ERR:{type(e).__name__}"
#                 rows.append({
#                     "sid": sid,
#                     "place_name": name,
#                     "menu_status": status,
#                     "menu_debug": str(e)[:200],
#                     "menu_items_json": "[]",
#                     "menu_img_top5_json": "[]",
#                     "menu_count": 0,
#                 })
#
#             # 실패 스샷
#             if status not in ("OK",):
#                 safe_name = re.sub(r"[^0-9a-zA-Z가-힣_ -]", "_", name)[:30]
#                 shot = FAIL_DIR / f"menu_{sid}_{safe_name}.png"
#                 try:
#                     driver.save_screenshot(str(shot))
#                 except Exception:
#                     pass
#
#             print(f"[menu] {name} sid={sid} status={status} count={rows[-1]['menu_count']}")
#             jitter_sleep(1.8, 2.6)
#
#         out = pd.DataFrame(rows)
#         out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
#         elapsed = time.perf_counter() - t0
#         print(f"✅ saved menu: {OUT_PATH}")
#         print(f"⏱ elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)")
#
#     finally:
#         if driver:
#             try:
#                 driver.quit()
#             except Exception:
#                 pass
#
# if __name__ == "__main__":
#     main()
