# src/clients/naver_search.py
import re
import html
import requests
from src.config.settings import (
    NAVER_LOCAL_SEARCH_URL,
    NAVER_SEARCH_CLIENT_ID,
    NAVER_SEARCH_CLIENT_SECRET,
)

TAG_RE = re.compile(r"<[^>]+>")

def clean_title(s: str) -> str:
    if not s:
        return s
    s = html.unescape(s)
    return TAG_RE.sub("", s).strip()

def local_search(query: str, display: int = 5, start: int = 1, sort: str = "comment") -> list[dict]:
    headers = {
        "X-Naver-Client-Id": NAVER_SEARCH_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_SEARCH_CLIENT_SECRET,
        "Accept": "application/json",
    }
    params = {
        "query": query,
        "display": display,
        "start": start,
        "sort": sort,
    }
    r = requests.get(NAVER_LOCAL_SEARCH_URL, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    items = data.get("items", [])
    # title 클린
    for it in items:
        it["title"] = clean_title(it.get("title", ""))
    return items
