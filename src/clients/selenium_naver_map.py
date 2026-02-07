# src/clients/selenium_naver_map.py
import re
import time
import random
from typing import List, Tuple, Dict, Any, Optional
import json

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from src.utils.scroll import scroll_until_ai_briefing

PHONE_RE = re.compile(r"(0\d{1,3}-\d{3,4}-\d{4})")
INT_RE = re.compile(r"(\d+)")



def switch_to_entry_iframe(driver, timeout: int = 15) -> bool:
    """
    entryIframe로 진입. 이름이 바뀌는 경우를 대비해 iframe 순회 fallback 포함.
    """
    driver.switch_to.default_content()
    WebDriverWait(driver, timeout).until(EC.presence_of_all_elements_located((By.TAG_NAME, "iframe")))

    # 1) name으로 먼저
    try:
        driver.switch_to.frame("entryIframe")
        return True
    except Exception:
        pass

    # 2) iframe 순회하며 #app-root 있는 프레임 찾기
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    for fr in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(fr)
            if driver.find_elements(By.CSS_SELECTOR, "#app-root"):
                return True
        except Exception:
            continue

    driver.switch_to.default_content()
    return False


def open_place_by_sid(driver, sid: int, timeout: int = 20) -> bool:
    """
    https://map.naver.com/p/smart-around/place/{sid} 로 진입 후 entryIframe + #app-root 대기
    """
    url = f"https://map.naver.com/p/smart-around/place/{sid}"
    driver.get(url)

    # 페이지 로딩 기본 대기
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    jitter_sleep(2.0, 3.0)
    # entry iframe
    if not switch_to_entry_iframe(driver, timeout=timeout):
        return False

    # app-root 렌더
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#app-root")))
    return True


def extract_phone(driver) -> str:
    """
    <span class="xlx7Q">053-611-5003</span> 형태에서 번호만 추출.
    """
    # 1) 가장 안정적인: span.xlx7Q
    try:
        el = driver.find_element(By.CSS_SELECTOR, "span.xlx7Q")
        txt = (el.text or "").strip()
        m = PHONE_RE.search(txt)
        if m:
            return m.group(1)
    except Exception:
        pass

    # 2) tel: 링크가 있을 때
    try:
        a = driver.find_element(By.CSS_SELECTOR, "a[href^='tel:']")
        href = a.get_attribute("href") or ""
        if href.startswith("tel:"):
            return href.replace("tel:", "").strip()
    except Exception:
        pass

    # 3) 최후: body 텍스트에서 패턴 검색
    try:
        body = driver.find_element(By.TAG_NAME, "body").text
        m = PHONE_RE.search(body)
        return m.group(1) if m else ""
    except Exception:
        return ""

AI_SECTION_XPATH = "//div[contains(@class,'place_section')][.//strong[normalize-space()='AI 브리핑']]"


def extract_ai_briefing(driver, timeout=8, debug=False):
    dbg = []
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#app-root"))
        )

        found = scroll_until_ai_briefing(driver)
        if not found:
            return [], "AI_BRIEFING_NOT_FOUND", ""

        # ✅ 섹션을 직접 찾기 (텍스트 노드 말고 place_section)
        section = driver.find_element(By.XPATH, AI_SECTION_XPATH)

        # 섹션으로 뷰포트 이동(추가 안정화)
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", section)
            time.sleep(0.2)
        except Exception:
            pass

        # 렌더 기다림: knTFs가 뜰 때까지 짧게 대기
        try:
            WebDriverWait(driver, 3).until(
                lambda d: section.find_elements(By.CSS_SELECTOR, "ul.knTFs li")
            )
        except Exception:
            pass

        spans = section.find_elements(By.CSS_SELECTOR, "ul.knTFs li span.bkeel")
        items = [ (sp.text or "").strip() for sp in spans if (sp.text or "").strip() ]

        if debug:
            dbg.append(f"bkeel_count={len(items)}")

        if items:
            return items, "OK", "\n".join(dbg) if debug else ""

        # fallback: li 텍스트
        lis = section.find_elements(By.CSS_SELECTOR, "ul.knTFs li")
        items2 = [ (li.text or "").strip() for li in lis if (li.text or "").strip() ]
        if items2 and sum(len(x) for x in items2) >= 40:
            return items2, "OK", "\n".join(dbg) if debug else ""

        return [], "AI_BRIEFING_EMPTY", "\n".join(dbg) if debug else ""

    except Exception as e:
        return [], f"AI_BRIEFING_PARSE_ERR:{type(e).__name__}", str(e) if debug else ""


def extract_visitor_review_keywords(driver, timeout=6, debug=False):
    """
    return: (total:int|None, items:list[dict], status:str, debug_info:str)
    items: [{"keyword": "음식이 맛있어요", "count": 116}, ...]
    """
    dbg = []
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#app-root"))
        )

        # ✅ 1) "방문자 리뷰" 섹션을 header_title 기준으로 정확히 찾기
        sections = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'place_section_header_title')][contains(normalize-space(.),'방문자 리뷰')]/ancestor::div[contains(@class,'place_section')][1]"
        )
        if not sections:
            return None, [], "VISITOR_REVIEW_SECTION_NOT_FOUND", "\n".join(dbg) if debug else ""

        section = sections[0]

        # ✅ 2) total count는 '방문자 리뷰' 타이틀 안의 em만 파싱
        total = None
        try:
            em = section.find_element(
                By.XPATH,
                ".//div[contains(@class,'place_section_header_title')][contains(normalize-space(.),'방문자 리뷰')]//em[contains(@class,'place_section_count')]"
            )
            t = (em.text or "").strip()
            m = INT_RE.search(t)
            if m:
                total = int(m.group(1))
        except Exception:
            pass

        # 3) 키워드 리스트 찾기
        # <ul class="K4J9r"> <li class="MHaAm"> ... <span class="sP19k">"음식이 맛있어요"</span> <span class="CUoLy">116</span>
        ul = section.find_elements(By.CSS_SELECTOR, "ul.K4J9r")
        if not ul:
            # 섹션은 있는데 키워드 영역이 없음 (리뷰 적거나 미노출)
            return total, [], "VISITOR_REVIEW_KEYWORDS_NOT_FOUND", "\n".join(dbg) if debug else ""

        lis = ul[0].find_elements(By.CSS_SELECTOR, "li.MHaAm")
        if not lis:
            return total, [], "VISITOR_REVIEW_KEYWORDS_NOT_FOUND", "\n".join(dbg) if debug else ""

        items: List[Dict] = []
        for li in lis:
            try:
                kw = li.find_element(By.CSS_SELECTOR, "span.sP19k").text.strip()
                kw = kw.strip('"')  # 따옴표 제거

                cnt_text = li.find_element(By.CSS_SELECTOR, "span.CUoLy").text.strip()
                m = INT_RE.search(cnt_text)
                cnt = int(m.group(1)) if m else None

                if kw and cnt is not None:
                    items.append({"keyword": kw, "count": cnt})
            except Exception:
                continue

        if items:
            if debug:
                dbg.append(f"keyword_count={len(items)} total={total}")
            return total, items, "OK", "\n".join(dbg) if debug else ""

        return total, [], "VISITOR_REVIEW_KEYWORDS_NOT_FOUND", "\n".join(dbg) if debug else ""

    except Exception as e:
        return None, [], f"VISITOR_REVIEW_PARSE_ERR:{type(e).__name__}", str(e) if debug else ""



def jitter_sleep(min_s: float = 2.0, max_s: float = 3.0):
    time.sleep(random.uniform(min_s, max_s))
