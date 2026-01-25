# pcmap.place.naver.com에서 상세 추출 (A폴백 포함)

import json
import re
from typing import Any, Optional

import requests

NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application\/json">(.+?)<\/script>')

def fetch_place_html(sid: str, timeout: int = 15) -> str:
    url = f"https://pcmap.place.naver.com/place/{sid}"
    headers = {
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "accept-language": "ko-KR,ko;q=0.9",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text

def parse_next_data(html: str) -> Optional[dict[str, Any]]:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    return json.loads(m.group(1))

def deep_find(obj: Any, keys: set[str], found: list[tuple[str, Any]], path: str = ""):
    """
    JSON 구조가 바뀌어도 최대한 버틸 수 있게,
    관심 키(openingHours, businessHours, menus, images, homepage 등)를 재귀 탐색.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            if k in keys:
                found.append((p, v))
            deep_find(v, keys, found, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            deep_find(v, keys, found, f"{path}[{i}]")

def extract_place_fields(next_data: dict[str, Any]) -> dict[str, Any]:
    """
    1차 버전: 구조가 달라도 '찾아서 담기' 방식으로.
    - opening_hours: 문자열/리스트/딕셔너리 형태 가능 -> raw json으로 저장
    - homepage_url: 발견되는 첫 URL
    - thumbnail_url: 발견되는 첫 이미지 URL
    - menus: name/price 후보를 최대한 추출
    """
    keys = {
        "businessHours", "openingHours", "openHours", "hours",
        "homePage", "homepage", "url",
        "images", "image", "thumbnail", "photo", "photos",
        "menus", "menu", "menuList",
    }
    found: list[tuple[str, Any]] = []
    deep_find(next_data, keys, found)

    opening_hours = None
    homepage_url = None
    thumbnail_url = None
    menus: list[dict[str, Any]] = []

    # 1) opening hours 후보
    for p, v in found:
        if any(k in p.lower() for k in ["businesshours", "openinghours", "openhours", ".hours"]):
            opening_hours = v
            break

    # 2) 홈페이지 URL 후보
    for p, v in found:
        if "home" in p.lower() or "homepage" in p.lower() or p.lower().endswith(".url"):
            if isinstance(v, str) and v.startswith("http"):
                homepage_url = v
                break

    # 3) 대표 이미지 후보
    thumbnail_url = _extract_first_image_url(found)

    # 4) 메뉴 후보
    menus = _extract_menus(found)

    return {
        "opening_hours_json": json.dumps(opening_hours, ensure_ascii=False) if opening_hours is not None else "",
        "homepage_url": homepage_url or "",
        "thumbnail_url": thumbnail_url or "",
        "menus": menus,
        "debug_hits": [(p, type(v).__name__) for p, v in found[:25]],  # 디버깅용(필요하면 저장)
    }

def _extract_first_image_url(found: list[tuple[str, Any]]) -> Optional[str]:
    for p, v in found:
        if any(k in p.lower() for k in ["thumbnail", "photo", "photos", "images", "image"]):
            # 다양한 구조 대응
            if isinstance(v, str) and v.startswith("http"):
                return v
            if isinstance(v, dict):
                for kk in ["url", "src", "thumbUrl", "thumbnailUrl"]:
                    vv = v.get(kk)
                    if isinstance(vv, str) and vv.startswith("http"):
                        return vv
            if isinstance(v, list) and v:
                first = v[0]
                if isinstance(first, str) and first.startswith("http"):
                    return first
                if isinstance(first, dict):
                    for kk in ["url", "src", "thumbUrl", "thumbnailUrl"]:
                        vv = first.get(kk)
                        if isinstance(vv, str) and vv.startswith("http"):
                            return vv
    return None

def _extract_menus(found: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add_menu(name: str, price: Optional[str], raw: Any):
        name = (name or "").strip()
        if not name:
            return
        out.append({"menu_name": name, "price": (price or "").strip(), "raw": json.dumps(raw, ensure_ascii=False)[:500]})

    for p, v in found:
        if "menu" not in p.lower():
            continue

        # case A: 리스트[dict{name, price}]
        if isinstance(v, list):
            for it in v[:50]:
                if isinstance(it, dict):
                    name = it.get("name") or it.get("menuName") or it.get("title")
                    price = it.get("price") or it.get("priceText") or it.get("cost")
                    if isinstance(price, (int, float)):
                        price = str(price)
                    add_menu(str(name or ""), str(price or ""), it)
        # case B: dict 안에 list가 들어있는 구조
        if isinstance(v, dict):
            for kk in ["list", "menus", "menuList", "items"]:
                vv = v.get(kk)
                if isinstance(vv, list):
                    for it in vv[:50]:
                        if isinstance(it, dict):
                            name = it.get("name") or it.get("menuName") or it.get("title")
                            price = it.get("price") or it.get("priceText") or it.get("cost")
                            if isinstance(price, (int, float)):
                                price = str(price)
                            add_menu(str(name or ""), str(price or ""), it)

    # 중복 제거(이름+가격)
    dedup = {}
    for m in out:
        k = (m["menu_name"], m["price"])
        dedup[k] = m
    return list(dedup.values())
