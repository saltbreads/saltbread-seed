# scripts/collect_daegu_place_ids.py
import os
import re
import time
import random
from pathlib import Path

import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options


BASE_DIR = Path(__file__).resolve().parents[1]
IN_PATH = BASE_DIR / "data" / "output" / "daegu_saltbread_places.csv"

OUT_PATH = BASE_DIR / "data" / "output" / "daegu_saltbread_places_with_sid.csv"
CKPT_PATH = BASE_DIR / "data" / "interim" / "daegu_place_ids_checkpoint.csv"
FAIL_DIR = BASE_DIR / "data" / "raw" / "daegu" / "selenium_fail"
FAIL_DIR.mkdir(parents=True, exist_ok=True)
CKPT_PATH.parent.mkdir(parents=True, exist_ok=True)

PLACE_ID_RE = re.compile(r"/place/(\d+)")


def make_driver(headless: bool = False):
    opts = Options()
    # headless는 네이버에서 더 잘 막히는 경우가 있어 초반엔 False 추천
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=ko-KR")

    # 자동화 흔적 최소화(완벽 우회 목적이 아니라, 기본 자동화 플래그 줄이기)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)

    # navigator.webdriver false
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def open_map(driver):
    driver.get("https://map.naver.com/p/search/")
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(random.uniform(1.2, 2.0))


def get_search_input(driver):
    """
    네이버 지도는 iframe이 자주 등장/변경됨.
    가장 안정적인 방식은:
    1) iframe 목록을 순회하며 input 후보를 찾는다.
    """
    driver.switch_to.default_content()
    frames = driver.find_elements(By.TAG_NAME, "iframe")

    # iframe 안에서 검색창을 찾는 여러 selector 후보
    selectors = [
        (By.CSS_SELECTOR, "input#query"),  # 가끔 존재
        (By.CSS_SELECTOR, "input.input_search"),
        (By.CSS_SELECTOR, "input[placeholder*='검색']"),
        (By.CSS_SELECTOR, "input[type='text']"),
    ]

    # 먼저 기본 문서에서 찾아보기
    for by, sel in selectors:
        els = driver.find_elements(by, sel)
        if els:
            return els[0]

    # iframe 순회
    for fr in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(fr)
            for by, sel in selectors:
                els = driver.find_elements(by, sel)
                if els:
                    return els[0]
        except Exception:
            continue

    driver.switch_to.default_content()
    return None


def extract_place_id_from_url(url: str) -> str:
    m = PLACE_ID_RE.search(url or "")
    return m.group(1) if m else ""

def wait_until_list_or_detail(driver, timeout=18):
    """
    Enter 이후:
    - URL에 /place/{id} 생기면 -> ("DETAIL", pid)
    - iframe들 중 어딘가에 /place/ 링크가 생기면 -> ("LIST", "")
    - timeout -> ("TIMEOUT", "")
    """
    end = time.time() + timeout
    while time.time() < end:
        # 1) 자동 상세 진입(결과 1개) 먼저 체크
        pid = extract_place_id_from_url(driver.current_url)
        if pid:
            return "DETAIL", pid

        # 2) 리스트(결과 여러 개) 체크: iframe 어디든 /place/ 링크가 생기면 LIST
        driver.switch_to.default_content()
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for fr in frames:
            try:
                driver.switch_to.frame(fr)
                if driver.find_elements(By.CSS_SELECTOR, "a[href*='/place/']"):
                    driver.switch_to.default_content()
                    return "LIST", ""
            except Exception:
                pass
            finally:
                driver.switch_to.default_content()

        time.sleep(0.25)

    driver.switch_to.default_content()
    return "TIMEOUT", ""


def click_first_place_link_anywhere(driver):
    driver.switch_to.default_content()
    frames = driver.find_elements(By.TAG_NAME, "iframe")

    last_err = ""
    for fr in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(fr)

            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/place/']")
            if not links:
                continue

            target = links[0]

            # ✅ 화면 중앙으로 스크롤 (클릭 인터셉트 감소)
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
                time.sleep(0.2)
            except Exception:
                pass

            # ✅ JS click 우선 (네이버 맵은 이게 제일 잘 먹음)
            try:
                driver.execute_script("arguments[0].click();", target)
                driver.switch_to.default_content()
                return True, ""
            except Exception as e:
                last_err = f"CLICK_ERR:{type(e).__name__}"
                continue

        except Exception as e:
            last_err = f"FRAME_ERR:{type(e).__name__}"
        finally:
            driver.switch_to.default_content()

    return False, (last_err or "NO_RESULT_LINKS")




def safe_sleep():
    time.sleep(random.uniform(5.0, 7.1))



def any_place_link_exists_in_any_iframe(driver) -> bool:
    """어떤 iframe 안에서든 /place/ 링크가 하나라도 생겼는지"""
    driver.switch_to.default_content()
    frames = driver.find_elements(By.TAG_NAME, "iframe")

    for fr in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(fr)
            if driver.find_elements(By.CSS_SELECTOR, "a[href*='/place/']"):
                return True
        except Exception:
            continue
    driver.switch_to.default_content()
    return False


def wait_after_search(driver, timeout=12):
    """
    Enter 이후 상태 대기:
    - URL에 /place/{id}가 생기면 -> ("DETAIL", pid)
    - iframe 어디든 결과 링크가 생기면 -> ("LIST", "")
    - timeout -> ("TIMEOUT", "")
    """
    end = time.time() + timeout

    while time.time() < end:
        pid = extract_place_id_from_url(driver.current_url)
        if pid:
            return "DETAIL", pid

        if any_place_link_exists_in_any_iframe(driver):
            return "LIST", ""

        time.sleep(0.25)

    return "TIMEOUT", ""

def click_first_place_link(driver):
    """iframe들을 돌면서 첫 /place/ 링크를 클릭"""
    driver.switch_to.default_content()
    frames = driver.find_elements(By.TAG_NAME, "iframe")

    last_err = ""
    for fr in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(fr)

            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/place/']")
            if links:
                try:
                    # 일반 click이 막히면 JS click이 더 잘 먹는 경우가 있음
                    driver.execute_script("arguments[0].click();", links[0])
                    driver.switch_to.default_content()
                    return True, ""
                except Exception as e:
                    last_err = f"CLICK_ERR:{type(e).__name__}"
        except Exception as e:
            last_err = f"FRAME_ERR:{type(e).__name__}"

    driver.switch_to.default_content()
    return False, last_err or "NO_RESULT_LINKS"


def collect_one(driver, keyword: str):
    open_map(driver)

    inp = get_search_input(driver)
    if inp is None:
        return "", "NO_SEARCH_INPUT"

    # 입력
    inp.click()
    inp.send_keys(Keys.COMMAND, "a")  # mac
    inp.send_keys(keyword)
    inp.send_keys(Keys.ENTER)

    # ✅ 여기서 sleep 말고: (자동상세) vs (리스트) vs (타임아웃) 판별
    state, pid = wait_until_list_or_detail(driver, timeout=18)

    if state == "DETAIL":
        return pid, "SID_OK_AUTO_DETAIL"

    if state == "TIMEOUT":
        return "", "SEARCH_TIMEOUT_NO_UI"

    # ✅ LIST면 첫 결과 클릭
    ok, err = click_first_place_link_anywhere(driver)
    if not ok:
        return "", err

    # ✅ 클릭 후: URL에 /place/{id} 뜰 때까지 기다림
    try:
        WebDriverWait(driver, 12).until(lambda d: extract_place_id_from_url(d.current_url))
    except TimeoutException:
        pass

    pid = extract_place_id_from_url(driver.current_url)
    if pid:
        return pid, "SID_OK_AFTER_CLICK"

    # 보조: href에서라도 pid 찾기(기존 로직 유지)
    try:
        driver.switch_to.default_content()
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for fr in frames:
            driver.switch_to.default_content()
            driver.switch_to.frame(fr)
            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/place/']")
            if links:
                href = links[0].get_attribute("href") or ""
                pid = extract_place_id_from_url(href)
                if pid:
                    return pid, "SID_OK_HREF"
    except Exception:
        pass
    finally:
        driver.switch_to.default_content()

    return "", "SID_NOT_IN_URL"



def load_input_df():
    df = pd.read_csv(IN_PATH)
    # 대구만
    mask = (
        df["road_address"].astype(str).str.startswith("대구광역시")
        | df["jibun_address"].astype(str).str.startswith("대구광역시")
    )
    df = df[mask].copy()

    # 컬럼 준비
    if "naver_place_id" not in df.columns:
        df["naver_place_id"] = ""
    if "sid_status" not in df.columns:
        df["sid_status"] = ""
    if "sid_search_keyword" not in df.columns:
        df["sid_search_keyword"] = ""

    return df


def merge_checkpoint(df: pd.DataFrame):
    if CKPT_PATH.exists():
        ck = pd.read_csv(CKPT_PATH)
        # name+road로 조인해서 이미 처리된 것 반영
        key_cols = ["name", "road_address"]
        df = df.merge(
            ck[key_cols + ["naver_place_id", "sid_status", "sid_search_keyword"]],
            on=key_cols,
            how="left",
            suffixes=("", "_ck"),
        )
        # 체크포인트 값이 있으면 우선
        for col in ["naver_place_id", "sid_status", "sid_search_keyword"]:
            df[col] = df[col].where(df[col].astype(str).str.len() > 0, df[f"{col}_ck"].fillna(""))
            if f"{col}_ck" in df.columns:
                df.drop(columns=[f"{col}_ck"], inplace=True)
    return df


def save_checkpoint(df: pd.DataFrame):
    df.to_csv(CKPT_PATH, index=False, encoding="utf-8-sig")


def format_runtime(seconds: float) -> str:
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def main():
    t0 = time.perf_counter()

    df = load_input_df()
    df = merge_checkpoint(df)

    # 이미 sid 있는 건 스킵
    pending = df[df["naver_place_id"].astype(str).str.len() == 0].copy()

    #테스트용 상위 30개만
    # pending = pending.head(10).copy()
    print(f"target rows: {len(df)} | pending: {len(pending)}")

    if pending.empty:
        print("✅ nothing to do (all rows have sid)")
        df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
        return

    driver = None
    try:
        driver = make_driver(headless=False)

        done = 0
        loop_t0 = time.perf_counter()  # (선택) 진행률/ETA용

        for idx, row in pending.iterrows():
            name = str(row["name"]).strip()
            keyword = f"대구 {name}"  # 기본 전략: 지역 + 상호명
            # 필요하면 2차 전략으로 road 포함도 가능 (첫 버전은 단순하게)

            try:
                pid, status = collect_one(driver, keyword)
            except WebDriverException as e:
                pid, status = "", f"WEBDRIVER_ERR:{type(e).__name__}"

            # 결과 반영
            df.loc[idx, "naver_place_id"] = pid
            df.loc[idx, "sid_status"] = status
            df.loc[idx, "sid_search_keyword"] = keyword

            if not pid:
                # 실패 스샷 저장
                safe_name = re.sub(r"[^0-9a-zA-Z가-힣_ -]", "_", name)[:30]
                shot = FAIL_DIR / f"{idx}_{safe_name}.png"
                try:
                    driver.save_screenshot(str(shot))
                except Exception:
                    pass

            done += 1

            # 중간 저장 (10개마다)
            if done % 10 == 0:
                save_checkpoint(df)
                avg = (time.perf_counter() - loop_t0) / done
                remain = len(pending) - done
                eta = avg * remain

                print(f"[{done}/{len(pending)}] last={status} pid={pid} | "
                      f"avg={avg:.1f}s | ETA≈{format_runtime(eta)}")

            # 너무 빠르게 돌지 않기
            time.sleep(random.uniform(5.2, 7.5))

        # 최종 저장
        save_checkpoint(df)
        df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
        print(f"✅ saved: {OUT_PATH}")
        print(f"✅ checkpoint: {CKPT_PATH}")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        elapsed = time.perf_counter() - t0
        print(f"⏱️ total runtime: {format_runtime(elapsed)} ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()

