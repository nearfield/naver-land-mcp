"""Office/store monthly-rental research; advertisements are not measured facts."""

from __future__ import annotations

import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from naver_land import NaverLandClient, ResponseSchemaError
from articles import (
    M2_PER_PYEONG,
    PROPERTY_TYPES,
    normalize_article,
    get_article_detail,
)

# Preserve the first local extension's Python import surface.
get_studio_detail = get_article_detail


def validate_conditions(
    monthly_rent_lt, min_area_pyeong, max_area_pyeong, min_floor, deposit_max
):
    values = [monthly_rent_lt, min_area_pyeong, max_area_pyeong]
    if any(
        isinstance(v, bool)
        or not isinstance(v, (int, float))
        or not math.isfinite(v)
        or v <= 0
        for v in values
    ):
        raise ValueError("월세 상한과 면적은 유한한 양수여야 합니다.")
    if min_area_pyeong > max_area_pyeong:
        raise ValueError("최소 면적이 최대 면적보다 클 수 없습니다.")
    if isinstance(min_floor, bool) or not isinstance(min_floor, int) or min_floor < 2:
        raise ValueError("작업실 검색은 지상 2층 이상입니다.")
    if deposit_max is not None and (
        isinstance(deposit_max, bool)
        or not isinstance(deposit_max, (int, float))
        or not math.isfinite(deposit_max)
        or deposit_max < 0
    ):
        raise ValueError("보증금 상한은 0 이상의 유한한 값이어야 합니다.")


def evaluate_articles(
    articles: list[dict],
    monthly_rent_lt: float = 150,
    min_area_pyeong: float = 15,
    max_area_pyeong: float = 25,
    min_floor: int = 2,
    deposit_max: float | None = None,
    center_lat: float | None = None,
    center_lon: float | None = None,
) -> dict:
    validate_conditions(
        monthly_rent_lt, min_area_pyeong, max_area_pyeong, min_floor, deposit_max
    )
    if (center_lat is None) != (center_lon is None):
        raise ValueError("거리 정렬에는 기준 위도와 경도를 함께 입력하세요.")
    if center_lat is not None and (
        isinstance(center_lat, bool)
        or isinstance(center_lon, bool)
        or not isinstance(center_lat, (int, float))
        or not isinstance(center_lon, (int, float))
        or not (-90 <= center_lat <= 90 and -180 <= center_lon <= 180)
    ):
        raise ValueError("기준 좌표 범위를 확인하세요.")
    if len(articles) > 500:
        raise ValueError("한 번에 최대 500개 광고를 검토할 수 있습니다.")
    groups = {
        "matchingAdvertisements": [],
        "needsVerification": [],
        "excludedAdvertisements": [],
    }
    seen = set()
    duplicates = 0
    for raw in articles:
        item = normalize_article(raw)
        aid = item["articleNo"]
        if aid and aid in seen:
            duplicates += 1
            continue
        if aid:
            seen.add(aid)
        reasons, unknown = [], []
        if not aid:
            unknown.append("articleNo")
        for key, invalid, reason in [
            ("tradeType", lambda v: v != "B2", "월세 매물 아님"),
            ("propertyType", lambda v: v not in PROPERTY_TYPES, "상가·사무실 아님"),
            ("monthlyRentManwon", lambda v: v >= monthly_rent_lt, "월세 상한 이상"),
            ("floorNumber", lambda v: v < min_floor, "지상 최소 층수 미달"),
        ]:
            if item[key] is None or item[key] == "":
                unknown.append(key)
            elif invalid(item[key]):
                reasons.append(reason)
        area = item["advertisedExclusiveM2"]
        margin = item["areaUncertaintyM2"]
        lower, upper = min_area_pyeong * M2_PER_PYEONG, max_area_pyeong * M2_PER_PYEONG
        if area is None:
            unknown.append("advertisedExclusiveM2")
        elif area + margin < lower or area - margin > upper:
            reasons.append("광고상 전용면적 범위 밖")
        elif area - margin < lower or area + margin > upper:
            unknown.append("advertisedExclusiveM2Precision")
        if deposit_max is not None:
            if item["depositManwon"] is None:
                unknown.append("depositManwon")
            elif item["depositManwon"] > deposit_max:
                reasons.append("보증금 상한 초과")
        distance = None
        if (
            center_lat is not None
            and item["latitude"] is not None
            and item["longitude"] is not None
        ):
            lat, lon = item["latitude"], item["longitude"]
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                a = (
                    math.sin(math.radians(lat - center_lat) / 2) ** 2
                    + math.cos(math.radians(lat))
                    * math.cos(math.radians(center_lat))
                    * math.sin(math.radians(lon - center_lon) / 2) ** 2
                )
                distance = round(6371000 * 2 * math.asin(math.sqrt(min(1, a))))
        item.update(
            {
                "distanceMeters": distance,
                "exclusionReasons": reasons,
                "unknownFilterFields": unknown,
            }
        )
        key = (
            "excludedAdvertisements"
            if reasons
            else "needsVerification"
            if unknown
            else "matchingAdvertisements"
        )
        groups[key].append(item)

    def rank(item):
        return (
            item["distanceMeters"] is None,
            item["distanceMeters"] or 0,
            item["within10YearsPreferred"] is not True,
            item["monthlyRentManwon"] is None,
            item["monthlyRentManwon"] or 0,
        )

    for values in groups.values():
        values.sort(key=rank)
    return {
        **groups,
        "duplicateArticleIdsRemoved": duplicates,
        "sameSpaceDeduplication": "동일 광고번호만 제거. 다른 광고번호의 동일 공간 여부는 수동 대조",
        "conditions": {
            "monthlyRentLtManwon": monthly_rent_lt,
            "depositMaxManwon": deposit_max,
            "exclusivePyeong": [min_area_pyeong, max_area_pyeong],
            "minGroundFloor": min_floor,
            "parkingFilter": False,
            "elevatorFilter": False,
            "ageHardLimit": None,
        },
        "note": "광고 기준 분류입니다. 사용자 실측·비교 면적과 기존 후보 상태를 덮어쓰지 않습니다. 목록의 정수 면적은 경계에서 상세 확인이 필요합니다.",
    }


def search_studio(
    client: NaverLandClient,
    district: str = "개포동",
    monthly_rent_lt: float = 150,
    min_area_pyeong: float = 15,
    max_area_pyeong: float = 25,
    min_floor: int = 2,
    deposit_max: float | None = None,
    limit: int = 30,
    max_pages: int = 2,
    center_lat: float | None = None,
    center_lon: float | None = None,
    detail_limit: int = 5,
) -> dict:
    validate_conditions(
        monthly_rent_lt, min_area_pyeong, max_area_pyeong, min_floor, deposit_max
    )
    if (
        any(
            isinstance(v, bool) or not isinstance(v, int)
            for v in (limit, max_pages, detail_limit)
        )
        or not 1 <= limit <= 100
        or not 1 <= max_pages <= 3
        or not 0 <= detail_limit <= 10
    ):
        raise ValueError("limit은 1~100, max_pages는 1~3으로 지정하세요.")
    deadline = time.monotonic() + 35
    # Validate coordinates before any request.
    evaluate_articles(
        [],
        monthly_rent_lt,
        min_area_pyeong,
        max_area_pyeong,
        min_floor,
        deposit_max,
        center_lat,
        center_lon,
    )
    region = client.resolve_region(district)
    if not region or region.get("cortarType") != "sec":
        raise ValueError(
            "동 단위 지역을 지정하세요. 구·시 전체 검색은 지원하지 않습니다."
        )
    params = {
        "cortarNo": region["cortarNo"],
        "realEstateType": "SMS:SG",
        "tradeType": "B2",
        "priceType": "RETAIL",
        "order": "rank",
        "type": "list",
        "sameAddressGroup": "false",
        "rentPriceMin": 0,
        "rentPriceMax": monthly_rent_lt,
    }
    if deposit_max is not None:
        params["priceMax"] = deposit_max
    # Do not server-filter supply area/floor/tag fields: exclusive area is evaluated locally.
    articles, more, pages_scanned = [], False, 0
    for page in range(1, max_pages + 1):
        if time.monotonic() >= deadline:
            more = True
            break
        data = client._get("/articles", {**params, "page": page})
        pages_scanned += 1
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("articleList"), list)
            or not isinstance(data.get("isMoreData"), bool)
        ):
            raise ResponseSchemaError(
                "목록 응답 형식이 달라 검색을 중단했습니다. 매물 없음으로 처리하지 않습니다."
            )
        if any(
            not isinstance(a, dict) or not a.get("articleNo")
            for a in data["articleList"]
        ):
            raise ResponseSchemaError("목록에 매물번호 없는 항목이 있습니다.")
        articles.extend(data["articleList"])
        more = data["isMoreData"]
        if not more or len(articles) >= 500:
            break
    args = (
        monthly_rent_lt,
        min_area_pyeong,
        max_area_pyeong,
        min_floor,
        deposit_max,
        center_lat,
        center_lon,
    )
    payload = evaluate_articles(articles[:500], *args)
    # Enrich uncertain boundary areas first, then matching advertisements. Hard exclusions need no call.
    selected = payload["needsVerification"] + payload["matchingAdvertisements"]
    details = {}
    for item in selected[:detail_limit]:
        if time.monotonic() >= deadline:
            break
        aid = item["articleNo"]
        raw = client._get(f"/articles/{aid}")
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("articleDetail"), dict)
            or str(raw["articleDetail"].get("articleNo")) != aid
            or not isinstance(raw.get("articlePhotos"), list)
        ):
            raise ResponseSchemaError("상세 응답 형식 또는 매물번호가 목록과 다릅니다.")
        details[aid] = raw
    if details:
        articles = [details.get(str(a.get("articleNo")), a) for a in articles]
        payload = evaluate_articles(articles[:500], *args)
    budget_reached = time.monotonic() >= deadline
    truncated = (
        more
        or budget_reached
        or len(articles) > 500
        or any(
            len(payload[key]) > limit
            for key in (
                "matchingAdvertisements",
                "needsVerification",
                "excludedAdvertisements",
            )
        )
    )
    counts = {
        key: len(payload[key])
        for key in (
            "matchingAdvertisements",
            "needsVerification",
            "excludedAdvertisements",
        )
    }
    for key in counts:
        payload[key] = payload[key][:limit]
    return {
        **payload,
        "region": region,
        "fetchedAt": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "sourceEndpoint": "/api/articles",
        "collected": len(articles),
        "classifiedCounts": counts,
        "pagesScanned": pages_scanned,
        "detailLookups": len(details),
        "timeBudgetReached": budget_reached,
        "truncated": truncated,
        "coverageNote": "동 전체의 제한된 페이지를 조회합니다. 거리 정렬은 수집된 광고 중 좌표가 있는 항목만 적용됩니다.",
    }
