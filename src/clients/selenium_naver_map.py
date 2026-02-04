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

# def extract_ai_briefing(driver, timeout=8, debug=False):
#     """
#     return: (items:list[str], status:str, debug_info:str)
#     status:
#       - OK
#       - AI_BRIEFING_NOT_FOUND
#       - AI_BRIEFING_EMPTY
#       - AI_BRIEFING_PARSE_ERR:*
#     """
#     dbg = []
#     try:
#         WebDriverWait(driver, timeout).until(
#             EC.presence_of_element_located((By.CSS_SELECTOR, "#app-root"))
#         )
#         time.sleep(random.uniform(2.5,4))
#
#         # 1) 스크롤해서 AI 브리핑 섹션 렌더 유도
#         found = scroll_until_ai_briefing(driver)
#         if not found:
#             return [], "AI_BRIEFING_NOT_FOUND", "\n".join(dbg) if debug else ""
#
#         # 2) AI 브리핑 섹션 컨테이너 찾기
#         # strong 텍스트가 "AI 브리핑"인 요소를 기준으로 상위 place_section으로 올라감
#         header = driver.find_element(By.XPATH, "//*[normalize-space(.)='AI 브리핑']")
#         section = header.find_element(By.XPATH, "ancestor::div[contains(@class,'place_section')][1]")
#
#         if debug:
#             dbg.append("found_section=place_section")
#
#         # 3) 핵심 문장: ul.knTFs > li.yfzki > span.bkeel
#         spans = section.find_elements(By.CSS_SELECTOR, "ul.knTFs li.yfzki span.bkeel")
#         items = []
#         for sp in spans:
#             txt = (sp.text or "").strip()
#             if txt:
#                 items.append(txt)
#
#         if debug:
#             dbg.append(f"bkeel_count={len(items)}")
#
#         if items:
#             return items, "OK", "\n".join(dbg) if debug else ""
#
#         # 4) fallback: bkeel 클래스가 바뀌는 경우 대비 (ul.knTFs 안의 li 텍스트)
#         ul = section.find_elements(By.CSS_SELECTOR, "ul.knTFs")
#         if ul:
#             lis = ul[0].find_elements(By.CSS_SELECTOR, "li")
#             items2 = []
#             for li in lis:
#                 t = (li.text or "").strip()
#                 if t:
#                     items2.append(t)
#
#             # 너무 짧은 토큰 나열(메뉴명만 나열) 방지용: 총 글자수 기준
#             if items2 and sum(len(x) for x in items2) >= 40:
#                 if debug:
#                     dbg.append(f"fallback_li_text_count={len(items2)}")
#                 return items2, "OK", "\n".join(dbg) if debug else ""
#
#         return [], "AI_BRIEFING_EMPTY", "\n".join(dbg) if debug else ""
#
#     except Exception as e:
#         return [], f"AI_BRIEFING_PARSE_ERR:{type(e).__name__}", str(e) if debug else ""


# def extract_ai_review_lines(driver, max_items: int = 10) -> List[str]:
#     """
#     AI 리뷰(문장/불릿) 영역 UL > LI 텍스트를 리스트로 추출.
#     - DOM이 자주 바뀌니 "vLccY ul" 계열을 우선으로 잡고, li 텍스트를 수집.
#     """
#     ul = None
#
#     # 1) 네가 준 selector(깨질 수 있어서 try)
#     primary_sel = "#app-root > div > div > div:nth-child(7) > div > div.place_section.no_border._slog_visible.eLFy_ > div > div.vLccY > ul"
#     try:
#         ul = driver.find_element(By.CSS_SELECTOR, primary_sel)
#     except Exception:
#         ul = None
#
#     # 2) 백업: vLccY 아래 ul
#     if ul is None:
#         uls = driver.find_elements(By.CSS_SELECTOR, "#app-root div.vLccY ul")
#         # li가 있는 ul 우선
#         for cand in uls:
#             try:
#                 if cand.find_elements(By.CSS_SELECTOR, "li"):
#                     ul = cand
#                     break
#             except Exception:
#                 continue
#
#     # 3) 최후 백업: app-root 내부 모든 ul 중 li가 있는 것
#     if ul is None:
#         uls = driver.find_elements(By.CSS_SELECTOR, "#app-root ul")
#         for cand in uls:
#             try:
#                 if cand.find_elements(By.CSS_SELECTOR, "li"):
#                     ul = cand
#                     break
#             except Exception:
#                 continue
#
#     if ul is None:
#         return []
#
#     out: List[str] = []
#     lis = ul.find_elements(By.CSS_SELECTOR, "li")
#     for li in lis[:max_items]:
#         try:
#             sp = li.find_element(By.CSS_SELECTOR, "span")
#             t = (sp.text or "").strip()
#         except Exception:
#             t = (li.text or "").strip()
#
#         if t:
#             out.append(t)
#
#     # 중복 제거(순서 유지)
#     seen = set()
#     dedup = []
#     for t in out:
#         if t not in seen:
#             seen.add(t)
#             dedup.append(t)
#     return dedup


def jitter_sleep(min_s: float = 2.0, max_s: float = 3.0):
    time.sleep(random.uniform(min_s, max_s))
