# naver_map_allsearch.py
# sid 찾기 + 후보 뽑기

import json
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote

import requests

NAVER_ALLSEARCH_URL = "https://map.naver.com/p/api/search/allSearch"

TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(s: str) -> str:
    return TAG_RE.sub("", (s or "")).strip()


@dataclass
class PlaceCandidate:
    sid: str
    name: str
    road_address: str
    jibun_address: str
    category: str
    x: Optional[float] = None
    y: Optional[float] = None


def allsearch(query: str, search_coord: str, boundary: str = "", page: int = 1, timeout: int = 15) -> dict[str, Any]:
    # referer = f"https://map.naver.com/p/search/{quote(query)}?c=15.00,0,0,0,dh"
    referer = "https://map.naver.com/p/search/"
    headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": referer,
        "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "x-requested-with": "XMLHttpRequest",

    }
    params = {
        "query": query,
        # "type": "all",
        "type": "place",
        "searchCoord": search_coord,  # "경도;위도"
        "boundary": boundary,
        "page": str(page),
    }
    r = requests.get(NAVER_ALLSEARCH_URL, headers=headers, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def extract_place_candidates(payload: dict[str, Any], limit: int = 10) -> list[PlaceCandidate]:
    """
    payload 구조는 변할 수 있으니 방어적으로 접근.
    일반적으로 payload["result"]["place"]["list"] 아래에 place 후보가 있음.
    """
    result = payload.get("result") or {}
    place = result.get("place") or {}
    items = place.get("list") or []

    out: list[PlaceCandidate] = []
    for it in items[:limit]:
        sid = str(it.get("id") or it.get("sid") or "").strip()
        if not sid:
            continue
        out.append(
            PlaceCandidate(
                sid=sid,
                name=strip_tags(it.get("name") or it.get("title") or ""),
                road_address=(it.get("roadAddress") or it.get("road_address") or "").strip(),
                jibun_address=(it.get("address") or it.get("jibunAddress") or "").strip(),
                category=(it.get("category") or "").strip(),
                x=_to_float(it.get("x")),
                y=_to_float(it.get("y")),
            )
        )
    return out


def _to_float(v) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def choose_best_candidate(cands: list[PlaceCandidate], seed_name: str, seed_road: str) -> Optional[PlaceCandidate]:
    """
    간단한 점수 기반 매칭:
    - roadAddress가 완전/부분 일치하면 점수 크게
    - 이름이 포함/유사하면 점수
    """
    seed_name_n = re.sub(r"\s+", "", seed_name or "")
    seed_road_n = re.sub(r"\s+", "", seed_road or "")

    best = None
    best_score = -1

    for c in cands:
        score = 0
        c_name_n = re.sub(r"\s+", "", c.name or "")
        c_road_n = re.sub(r"\s+", "", c.road_address or "")

        # 주소 점수(가장 중요)
        if seed_road_n and c_road_n:
            if seed_road_n == c_road_n:
                score += 100
            elif seed_road_n in c_road_n or c_road_n in seed_road_n:
                score += 70

        # 이름 점수
        if seed_name_n and c_name_n:
            if seed_name_n == c_name_n:
                score += 30
            elif seed_name_n in c_name_n or c_name_n in seed_name_n:
                score += 15

        # 둘 다 어느 정도 맞으면 가산
        if score >= 70:
            score += 5

        if score > best_score:
            best_score = score
            best = c

    return best
