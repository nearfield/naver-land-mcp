"""Property-agnostic advertisement normalization and public photo metadata."""

from __future__ import annotations

import math
import re
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from naver_land import NaverLandClient, ResponseSchemaError

M2_PER_PYEONG = 3.305785
PROPERTY_TYPES = {"SMS": "사무실", "SG": "상가"}


def number(value, *, allow_negative=False):
    """만원/㎡ 필드만 파싱; 단위가 불명확한 문자열은 추정하지 않는다."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    pattern = r"-?\d+(?:\.\d+)?" if allow_negative else r"\d+(?:\.\d+)?"
    if not re.fullmatch(pattern, text):
        match = re.fullmatch(r"(\d+)\s*억(?:\s*(\d+))?", text)
        if not match:
            return None
        result = float(match[1]) * 10000 + float(match[2] or 0)
        return result if math.isfinite(result) else None
    result = float(text)
    return result if math.isfinite(result) else None


def first(data, *keys):
    for key in keys:
        if data.get(key) not in (None, ""):
            return data[key]
    return None


def floor_number(value):
    # 고/중/저층은 실제 층수를 확인할 수 없다. 지하·옥탑도 자동 통과시키지 않는다.
    token = str("" if value is None else value).split("/")[0].strip()
    if re.fullmatch(r"(?:B|지하)\s*\d+", token, re.I):
        return -int(re.search(r"\d+", token)[0])
    match = re.fullmatch(r"(-?\d+)(?:층)?", token)
    return int(match[1]) if match else None


def photo_url(value):
    value = str(value or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = "https://landthumb-phinf.pstatic.net" + value
    try:
        parts = urlsplit(value)
        if any(ch.isspace() or ord(ch) < 32 for ch in value):
            return None
        if parts.port not in (None, 443):
            return None
        return (
            value
            if parts.scheme == "https" and parts.hostname and not parts.username
            else None
        )
    except ValueError:
        return None


def block(raw: dict, name: str) -> dict:
    value = raw.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ResponseSchemaError(f"{name} 응답 형식이 JSON 객체가 아닙니다.")
    return value


def normalize_article(raw: dict, article_no: str | None = None) -> dict:
    """목록/상세의 명시된 필드만 읽는다. 관리비 단위는 임의 변환하지 않는다."""
    if not isinstance(raw, dict):
        raise ValueError("매물은 JSON 객체여야 합니다.")
    detail = block(raw, "articleDetail") or raw
    addition = block(raw, "articleAddition")
    price = block(raw, "articlePrice")
    space = block(raw, "articleSpace")
    facility = block(raw, "articleFacility")
    floors = block(raw, "articleFloor")
    aid = str(first(detail, "articleNo") or raw.get("articleNo") or article_no or "")
    exclusive = number(first(space, "exclusiveSpace") if space else detail.get("area2"))
    if exclusive is not None and exclusive <= 0:
        exclusive = None
    floor = (
        first(addition, "floorInfo")
        or first(detail, "floorInfo")
        or first(floors, "correspondingFloorCount")
    )
    trade = first(detail, "tradeTypeCode", "tradeType")
    rent = number(
        first(price, "rentPrice", "rentPrc")
        if price
        else first(detail, "rentPrc") or first(addition, "rentPrc")
    )
    deposit = number(
        first(price, "warrantPrice", "dealOrWarrantPrc")
        if price
        else first(detail, "dealOrWarrantPrc") or first(addition, "dealOrWarrantPrc")
    )
    approval = first(facility, "buildingUseAprvYmd") or first(
        detail, "buildingUseAprvYmd"
    )
    age = None
    try:
        approved = datetime.strptime(str(approval).replace("-", ""), "%Y%m%d").date()
        today = datetime.now(ZoneInfo("Asia/Seoul")).date()
        if approved <= today:
            age = (today - approved).days / 365.2425
    except (TypeError, ValueError):
        pass
    photos = []
    photo_rows = raw.get("articlePhotos")
    if photo_rows is not None and not isinstance(photo_rows, list):
        raise ResponseSchemaError("articlePhotos 응답 형식이 목록이 아닙니다.")
    for photo in photo_rows or []:
        if isinstance(photo, dict):
            url = photo_url(photo.get("imageSrc"))
            if url and url not in photos:
                photos.append(url)
    # Unknown units and VAT/utility scope must stay explicit.
    management_raw = {
        key: raw[key] for key in ("administrationCostInfo",) if key in raw
    }
    if "monthlyManagementCost" in detail:
        management_raw["monthlyManagementCost"] = detail["monthlyManagementCost"]
    # List area2 is rounded/truncated (observed 114 vs detail exclusiveSpace 114.75).
    uncertainty = (
        1.0 if exclusive is not None and not space and exclusive.is_integer() else 0.0
    )
    return {
        "articleNo": aid,
        "link": f"https://fin.land.naver.com/articles/{aid}" if aid else None,
        "name": first(detail, "articleName"),
        "propertyType": first(
            detail, "realestateTypeCode", "realEstateTypeCode", "realEstateType"
        )
        or first(addition, "realEstateTypeCode"),
        "tradeType": trade,
        "address": first(detail, "exposureAddress", "cortarAddress"),
        "latitude": number(detail.get("latitude"), allow_negative=True),
        "longitude": number(detail.get("longitude"), allow_negative=True),
        "depositManwon": deposit,
        "monthlyRentManwon": rent,
        "advertisedExclusiveM2": exclusive,
        "advertisedExclusivePyeong": round(exclusive / M2_PER_PYEONG, 4)
        if exclusive
        else None,
        "areaBasis": "네이버 광고상 전용면적; 실측·사용자 비교면적과 별개",
        "areaPrecision": "detail_advertised" if space else "list_display",
        "areaUncertaintyM2": uncertainty,
        "floorLabel": floor,
        "floorNumber": floor_number(floor),
        "approvalDateAdvertised": approval,
        "ageYearsAdvertised": round(age, 1) if age is not None else None,
        "within10YearsPreferred": age <= 10 if age is not None else None,
        "parkingAdvertised": first(detail, "parkingPossibleYN"),
        "elevatorAdvertised": first(facility, "elevatorCount", "elevatorYN"),
        "elevatorBuildingRegisterCount": first(
            block(raw, "articleBuildingRegister"), "totalElvtCnt"
        ),
        "managementFeeRaw": management_raw,
        "costScope": "월세만 필터링. 관리비·부가세·공과금·권리금 및 총액은 별도 확인",
        "description": first(
            detail,
            "detailDescription",
            "articleFeatureDescription",
            "articleFeatureDesc",
        ),
        "advertisementConfirmedDate": first(
            detail, "articleConfirmYMD", "articleConfirmYmd"
        )
        or first(addition, "articleConfirmYmd"),
        "photoUrls": photos,
        "photoStatus": "unknown"
        if photo_rows is None
        else "not_published"
        if not photo_rows
        else "available"
        if photos
        else "unusable",
        "upstreamPhotoCount": len(photo_rows) if photo_rows is not None else None,
        "musicUsePermission": "미확인: 임대인·관리규약·공사 허가 별도 확인",
    }


def get_article_detail(client: NaverLandClient, article_no: str) -> dict:
    if not re.fullmatch(r"\d{5,15}", article_no):
        raise ValueError("숫자 매물번호를 입력하세요.")
    data = client._get(f"/articles/{article_no}")
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("articleDetail"), dict)
        or not data["articleDetail"]
        or not isinstance(data.get("articlePhotos"), list)
    ):
        raise ResponseSchemaError(
            "상세 응답 형식이 달라 중단했습니다. 삭제·무사진 매물로 추정하지 않습니다."
        )
    if str(data["articleDetail"].get("articleNo")) != article_no:
        raise ResponseSchemaError("상세 응답에 요청한 매물번호가 명시되지 않았습니다.")
    item = normalize_article(data, article_no)
    return {
        **item,
        "fetchedAt": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "sourceEndpoint": f"/api/articles/{article_no}",
        "photoDownloadPerformed": False,
    }
