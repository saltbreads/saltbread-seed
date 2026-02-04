
# src/utils/scroll.py
import time
import random
from selenium.webdriver.common.by import By

AI_SECTION_XPATH = (
    "//div[contains(@class,'place_section')][.//strong[normalize-space()='AI 브리핑']]"
)

def _get_scrollable_element_js():
    # app-root 내부에서 "scrollHeight > clientHeight"인 스크롤 컨테이너를 찾아 반환
    return """
    const root = document.querySelector('#app-root');
    if (!root) return null;

    const candidates = Array.from(root.querySelectorAll('*'));
    // root도 포함
    candidates.unshift(root);

    function isScrollable(el){
      if (!el) return false;
      const style = window.getComputedStyle(el);
      const oy = style.overflowY;
      const canScroll = (oy === 'auto' || oy === 'scroll' || oy === 'overlay');
      return canScroll && el.scrollHeight > el.clientHeight + 50;
    }

    // 가장 "큰" 스크롤 영역 우선
    const scrollables = candidates.filter(isScrollable);
    if (scrollables.length === 0) return null;

    scrollables.sort((a,b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
    return scrollables[0];
    """

def scroll_until_ai_briefing(driver, max_rounds=22, pause_range=(1.5, 2.5), force_down_rounds=3):
    """
    - entryIframe 안에서 호출된다는 가정
    - 먼저 무조건 force_down_rounds 만큼은 내려서 렌더 트리거
    - 그 다음 AI 브리핑 섹션(div.place_section ... strong 'AI 브리핑')이 실제로 보이면 True
    """
    # 0) 스크롤 컨테이너 찾기
    scroll_el = driver.execute_script(_get_scrollable_element_js())
    if not scroll_el:
        # fallback: window scroll이라도 시도
        scroll_el = None

    def do_scroll():
        if scroll_el:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollTop + Math.floor(arguments[0].clientHeight * 0.85);", scroll_el)
        else:
            driver.execute_script("window.scrollBy(0, Math.floor(window.innerHeight * 0.85));")

    def has_ai_section():
        # "AI 브리핑" 텍스트만 보지 말고 place_section 구조로 찾기
        return bool(driver.find_elements("xpath", AI_SECTION_XPATH))

    # 1) 무조건 몇 번은 내려서 렌더 트리거
    for _ in range(force_down_rounds):
        do_scroll()
        time.sleep(random.uniform(*pause_range))

    # 2) 이제 탐색
    for _ in range(max_rounds):
        if has_ai_section():
            return True
        do_scroll()
        time.sleep(random.uniform(*pause_range))

    return has_ai_section()
