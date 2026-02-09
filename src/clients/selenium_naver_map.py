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
            # time.sleep(0.2)
            jitter_sleep(0.3,0.6)
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


def extract_hero_image(driver, timeout=6, debug=False):
    """
    return: (url:str, status:str, debug_info:str)
    status:
      - OK
      - HERO_IMG_STREETVIEW_ONLY
      - HERO_IMG_NOT_FOUND
      - HERO_IMG_PARSE_ERR:*
    """
    dbg = []
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#app-root"))
        )

        # 1) 1순위: 네가 준 대표사진 앵커 (#_autoPlayable)
        # <a id="_autoPlayable"> <img src="...">
        els = driver.find_elements(By.CSS_SELECTOR, "a#_autoPlayable img")
        if els:
            img = els[0]
            src = (img.get_attribute("src") or "").strip()
            if debug:
                dbg.append("hit=a#_autoPlayable img")
                dbg.append(f"src_len={len(src)}")
            if src:
                return src, "OK", "\n".join(dbg) if debug else ""

        # 2) 2순위: 상단 썸네일(일반적으로 place_thumb 안의 첫 img)
        # - 너무 넓게 잡으면 리뷰 이미지까지 섞일 수 있으니 "place_thumb"로 제한
        cand_imgs = driver.find_elements(By.CSS_SELECTOR, "a.place_thumb img")
        if cand_imgs:
            img = cand_imgs[0]
            src = (img.get_attribute("src") or "").strip()

            # 거리뷰 여부 판정: a 태그 내부에 '거리뷰' 뱃지(span.SHrAF) 있으면 거리뷰로 처리
            parent_a = img.find_element(By.XPATH, "./ancestor::a[1]")
            is_street = False
            try:
                if parent_a.find_elements(By.CSS_SELECTOR, "span.SHrAF"):
                    is_street = True
            except Exception:
                pass

            if debug:
                dbg.append("hit=a.place_thumb img (fallback)")
                dbg.append(f"is_street={is_street}")
                dbg.append(f"src_len={len(src)}")

            if src:
                if is_street:
                    return src, "HERO_IMG_STREETVIEW_ONLY", "\n".join(dbg) if debug else ""
                return src, "OK", "\n".join(dbg) if debug else ""

        # 3) 3순위: 거리뷰 전용 앵커(F7qGx) (대표사진 미등록 케이스가 여기로 뜨는 경우)
        street_imgs = driver.find_elements(By.CSS_SELECTOR, "a.F7qGx img")
        if street_imgs:
            src = (street_imgs[0].get_attribute("src") or "").strip()
            if debug:
                dbg.append("hit=a.F7qGx img (streetview)")
                dbg.append(f"src_len={len(src)}")
            if src:
                return src, "HERO_IMG_STREETVIEW_ONLY", "\n".join(dbg) if debug else ""

        return "", "HERO_IMG_NOT_FOUND", "\n".join(dbg) if debug else ""

    except Exception as e:
        return "", f"HERO_IMG_PARSE_ERR:{type(e).__name__}", (str(e) if debug else "")

def extract_business_hours_raw(driver, timeout=6, debug=False) -> Tuple[str, str, str]:
    """
    펼쳐보기(aria-expanded=true) 이후의 div.w9QyJ 블록 텍스트만 raw로 저장.

    return: (hours_raw:str, status:str, debug_info:str)

    status:
      - OK                : w9QyJ(요일/매일) 블록을 1개 이상 수집
      - HOURS_NOT_FOUND   : 영업시간 토글 자체를 못 찾음(없거나 렌더 안됨)
      - HOURS_NO_DETAIL   : 토글은 있는데 펼친 뒤에도 요약만 있고 상세(w9QyJ 추가) 없음
      - HOURS_EMPTY_TEXT  : w9QyJ는 찾았는데 텍스트가 비었음(이상)
      - HOURS_ERR:*       : 예외
    """
    dbg = []
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#app-root"))
        )

        # 1) 영업시간 토글(a.gKP9i.RMgN0) 찾기: "영업시간" 앵커 기준으로 가까운 vV_z_ 아래 토글을 잡는다
        anchors = driver.find_elements(
            By.XPATH,
            "//*[contains(@class,'place_blind') and normalize-space(.)='영업시간']"
        )
        if not anchors:
            return "", "HOURS_NOT_FOUND", ""

        toggle = None
        wrapper = None

        # anchor -> ancestor div 중 vV_z_를 찾고 그 안의 a.gKP9i.RMgN0를 찾는다
        for a in anchors:
            vwrap = a.find_elements(By.XPATH, "ancestor::div[contains(@class,'vV_z_')][1]")
            if vwrap:
                wrapper = vwrap[0]
                cand = wrapper.find_elements(By.CSS_SELECTOR, "a.gKP9i.RMgN0")
                if cand:
                    toggle = cand[0]
                    break

        if toggle is None:
            # fallback: 화면 내 첫 영업시간 토글을 그냥 잡기
            cand = driver.find_elements(By.CSS_SELECTOR, "div.vV_z_ a.gKP9i.RMgN0")
            if cand:
                toggle = cand[0]
                wrapper = toggle.find_element(By.XPATH, "ancestor::div[contains(@class,'vV_z_')][1]")
            else:
                return "", "HOURS_NOT_FOUND", ""

        if debug:
            dbg.append("hit=hours_toggle")

        # 2) 펼치기: aria-expanded=false면 클릭해서 true로
        aria = (toggle.get_attribute("aria-expanded") or "").strip().lower()
        if debug:
            dbg.append(f"aria_before={aria}")

        if aria != "true":
            # driver.execute_script("arguments[0].scrollIntoView({block:'center'});", toggle)
            # jitter_sleep(0.2, 0.4)
            driver.execute_script("arguments[0].click();", toggle)

            # 펼쳐짐 판정: aria-expanded true OR w9QyJ 개수가 증가(요약+상세)
            def _expanded(_):
                a2 = (toggle.get_attribute("aria-expanded") or "").strip().lower()
                if a2 == "true":
                    return True
                return False

            try:
                WebDriverWait(driver, 2).until(_expanded)
                jitter_sleep(0.5,1)
            except Exception:
                pass  # aria가 안 바뀌는 케이스도 있어서 아래 w9QyJ로 재판정

        aria2 = (toggle.get_attribute("aria-expanded") or "").strip().lower()
        if debug:
            dbg.append(f"aria_after={aria2}")

        # 3) 펼친 이후 wrapper 내부의 w9QyJ 수집
        # wrapper는 <div class="vV_z_"> ... </div>
        w_blocks = wrapper.find_elements(By.CSS_SELECTOR, "div.w9QyJ")

        # w9QyJ는 항상 최소 1개(요약)가 있고, 펼치면 추가로 더 생기는 구조가 흔함.
        # 하지만 "매일" 1줄만 있는 곳도 펼친 뒤 w9QyJ가 2개(요약+매일)인 경우가 많음.
        if debug:
            dbg.append(f"w9QyJ_count={len(w_blocks)}")

        if not w_blocks:
            return "", "HOURS_NO_DETAIL", "\n".join(dbg) if debug else ""

        def _clean_hours_text(t: str) -> str:
            t = (t or "").strip()

            # UI 텍스트 제거
            t = t.replace("접기", "").replace("펼쳐보기", "").strip()

            # 빈 줄 제거 + 각 줄 trim
            t = "\n".join([line.strip() for line in t.splitlines() if line.strip()])
            t = t.replace("\n", " ")

            return t.strip()

        # 4) w9QyJ 텍스트를 줄로 만들기
        # - 첫 w9QyJ(vI8SM)은 '영업 중/종료 + ~에 종료/시작' 요약
        # - 그 뒤 w9QyJ들은 요일/매일 상세
        lines = []
        for b in w_blocks:
            t = _clean_hours_text(b.text)
            if t:
                lines.append(t)

        if not lines:
            return "", "HOURS_EMPTY_TEXT", "\n".join(dbg) if debug else ""

        # 5) "상세만" 원하면 요약(vI8SM) 제거 옵션
        # 너가 말한 "유효한 정보는 w9QyJ"인데, 요약도 w9QyJ라 포함됨.
        # 만약 상세(요일/매일)만 저장하고 싶다면 아래 로직 켜면 됨.
        # - vI8SM 클래스를 가진 w9QyJ는 요약으로 간주하고 제외
        detailed_lines = []
        for b in w_blocks:
            cls = (b.get_attribute("class") or "")
            if "vI8SM" in cls:
                continue

            t = _clean_hours_text(b.text)
            if t:
                detailed_lines.append(t)

        # 상세가 있으면 상세만 저장, 없으면 전체(lines) 저장(최소한이라도 남기기)
        out_lines = detailed_lines if detailed_lines else lines

        if debug:
            dbg.append(f"detail_lines={len(detailed_lines)}")

        # 최종 raw: 블록 단위로 구분되게 빈줄 하나 넣어도 됨(취향)
        # hours_raw = "\n\n".join(out_lines)
        hours_raw = " | ".join(out_lines)

        # 펼쳤는데도 상세가 전혀 없고 요약 1블록뿐이면 "상세 없음"으로 치자
        # if len(out_lines) == 1 and detailed_lines == [] and len(w_blocks) == 1:
        #     return hours_raw, "HOURS_NO_DETAIL", "\n".join(dbg) if debug else ""

        if not detailed_lines:
            # 요약만 있거나(혹은 정제 후 상세가 비어버린 경우)
            return hours_raw, "HOURS_NO_DETAIL", "\n".join(dbg) if debug else ""

        return hours_raw, "OK", "\n".join(dbg) if debug else ""

    except Exception as e:
        return "", f"HOURS_ERR:{type(e).__name__}", (str(e) if debug else "")



def jitter_sleep(min_s: float = 2.0, max_s: float = 3.0):
    time.sleep(random.uniform(min_s, max_s))
