"""naver-land-mcp FastMCP 서버.

도구 11개 (기존 아파트 도구 + 작업실 조사 + 공통 상세·사진):
- get_article_detail: 모든 매물 유형의 광고 상세 조회
- get_article_photos: 모든 매물 유형의 공개 사진 URL 조회
- search_studio_spaces: 동 단위 상가·사무실 월세 광고 검색
- get_studio_article: 매물 상세·공개 사진 URL 조회
- review_studio_articles: 저장된 광고 JSON의 작업실 조건 검토
- watch_complexes: 관심 단지 매물+시세(한국부동산원+KB)+실거래가 일괄 조회
- search_apartments: 동/구/군 + 가격 범위로 매물 검색 (매매/전세/월세)
- get_complex_info: 단지 상세 정보
- get_complex_price_info: 단지 평형별 시세(한국부동산원+KB) + 실거래가
- resolve_district: 지역명 → cortarNo 조회
- list_districts: 전국 시/도 17개 목록
"""

from __future__ import annotations

import json
import os

from fastmcp import FastMCP

from config import (
    DEFAULT_PRICE_MAX,
    DEFAULT_PRICE_MIN,
    DEFAULT_SEARCH_LIMIT,
    MAX_SEARCH_LIMIT,
)
from filter import filter_and_rank
from naver_land import (
    _client,
    crawl_district,
    get_complex_detail,
    get_complex_prices,
    resolve_region,
    search_complex_by_name,
    watch_complexes_data,
)
from report import format_report
from snapshot import compare_with_previous
from studio import evaluate_articles, get_studio_detail, search_studio
from articles import get_article_detail as fetch_article_detail

mcp = FastMCP("naver-land")


@mcp.tool
def search_studio_spaces(
    district: str = "개포동", monthly_rent_lt: float = 150,
    min_area_pyeong: float = 15, max_area_pyeong: float = 25,
    min_floor: int = 2, deposit_max: float | None = None,
    limit: int = 30, max_pages: int = 2,
    center_lat: float | None = None, center_lon: float | None = None,
    detail_limit: int = 5,
) -> str:
    """동 단위 상가(SG)·사무실(SMS) 월세 광고를 작업실 조건으로 조사합니다.

    기본 월세는 150만원 '미만', 광고상 전용 15~25평, 지상 2층 이상.
    보증금 무제한. 주차·엘리베이터·연식으로 제외하지 않습니다.
    within10YearsPreferred는 연식 선호 표시이며, 음악 사용 허가가 아닙니다.
    기준 좌표를 함께 입력하면 수집된 광고를 직선거리 우선으로 정렬합니다.
    max_pages는 1~3, 각 분류의 반환 limit은 1~100. detail_limit은 0~10.
    목록에서 반올림/절삭된 경계 면적은 상세를 먼저 확인합니다. 불명확한 면적·층수는
    needsVerification으로 분리합니다. 접근 제한·응답 변경은 오류로 반환합니다.
    후보 문서나 자동화를 변경하지 않습니다. 사진은 get_studio_article로 조회하세요.
    """
    return json.dumps(search_studio(_client, district, monthly_rent_lt, min_area_pyeong,
                                   max_area_pyeong, min_floor, deposit_max, limit, max_pages,
                                   center_lat, center_lon, detail_limit), ensure_ascii=False, indent=1)


@mcp.tool
def get_article_detail(article_no: str) -> str:
    """아파트·상가·사무실 등 개별 광고의 상세·전용면적·월세·공개 사진 URL 조회.

    photoStatus가 available이면 공개 사진이 있고 not_published이면 API에 사진이
    없습니다. 응답 형식 오류를 무사진이나 삭제된 매물로 추정하지 않습니다.
    관리비 원문과 광고 확인일을 분리하며 음악 사용 허가는 확인하지 않습니다.
    """
    return json.dumps(fetch_article_detail(_client, article_no), ensure_ascii=False, indent=1)


@mcp.tool
def get_article_photos(article_no: str) -> str:
    """모든 매물 유형의 공개 사진 URL과 명시적인 사진 상태를 조회합니다.

    사진을 내려받거나 인증정보를 요구하지 않습니다. not_published는 정상 상세
    응답에 빈 사진 목록이 있는 경우만 반환합니다. 네트워크·스키마 오류는 오류입니다.
    """
    item = fetch_article_detail(_client, article_no)
    keys = ("articleNo", "propertyType", "link", "photoUrls", "photoStatus", "upstreamPhotoCount", "fetchedAt", "sourceEndpoint", "photoDownloadPerformed")
    return json.dumps({key: item[key] for key in keys}, ensure_ascii=False, indent=1)


@mcp.tool
def get_studio_article(article_no: str) -> str:
    """숫자 매물번호로 광고 상세·공개 사진 URL을 조회합니다.

    광고 면적·월세·관리비 원문·준공·주차·엘리베이터를 반환합니다.
    관리비 단위를 추정하거나 월세 총액을 확정하지 않습니다. 사진을 내려받지 않고
    사용자 비교 면적·후보 상태·광고 확인일을 자동 갱신하지 않습니다.
    """
    return json.dumps(get_studio_detail(_client, article_no), ensure_ascii=False, indent=1)


@mcp.tool
def review_studio_articles(
    articles: list[dict], monthly_rent_lt: float = 150,
    min_area_pyeong: float = 15, max_area_pyeong: float = 25,
    min_floor: int = 2, deposit_max: float | None = None,
    center_lat: float | None = None, center_lon: float | None = None,
) -> str:
    """저장된 네이버 목록/상세 JSON을 같은 작업실 조건으로 검토합니다(외부 요청 없음).

    최대 500개. matchingAdvertisements/needsVerification/excludedAdvertisements로
    나눕니다. 저장본의 최신성은 확인하지 않습니다. 동일 광고번호만 중복 제거하며,
    다른 광고번호가 같은 공간인지, 음악 작업이 허용되는지는 수동 확인이 필요합니다.
    사용자가 정한 비교 면적과 기존 후보 문서를 덮어쓰지 않습니다.
    """
    payload = evaluate_articles(articles, monthly_rent_lt, min_area_pyeong, max_area_pyeong,
                                min_floor, deposit_max, center_lat, center_lon)
    return json.dumps({**payload, "liveLookupPerformed": False}, ensure_ascii=False, indent=1)


@mcp.tool
def watch_complexes(
    complex_names: list[str],
    price_min: int = DEFAULT_PRICE_MIN,
    price_max: int = DEFAULT_PRICE_MAX,
) -> str:
    """관심 단지들의 매물 + 시세 + 실거래가를 한번에 조회합니다.

    각 단지별로 현재 매물, 평형별 시세, 최근 실거래가를 반환합니다.
    이전 스냅샷과 비교하여 신규/삭제/가격변동 매물도 함께 반환합니다.

    Args:
        complex_names: 관심 단지명 목록 (예: ["가천대역두산위브", "광교해모로"])
        price_min: 최소 가격 (만원). 기본 0 (무제한)
        price_max: 최대 가격 (만원). 기본 999999 (무제한)
    """
    data = watch_complexes_data(complex_names, price_min, price_max)

    # 이전 스냅샷 대비 변동 감지
    diff = compare_with_previous(data["all_articles"])

    # 포맷된 마크다운 리포트 생성
    report = format_report(
        data["complexes"],
        {**diff, "total_current": diff["total_current"]},
    )
    return report


@mcp.tool
def search_apartments(
    district: str,
    price_min: int = DEFAULT_PRICE_MIN,
    price_max: int = DEFAULT_PRICE_MAX,
    trade_type: str = "A1",
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> str:
    """지역 + 가격 범위로 아파트 매물을 검색합니다. 전국 + 매매/전세/월세 모두 지원.

    지역 지정 방식 (네이버 부동산 기준 동적 조회):
    - 동 단위: "관평동", "개포동", "반포동"
    - 구/군 단위: "강남구", "유성구", "성남시 분당구"
    - 시/도 단위(예: "서울시")는 범위 과대로 거부됨

    매물이 많은 지역은 매물 수가 많은 단지부터 우선 수집하며,
    limit 충족 시 조기 종료합니다. 특정 단지의 매물만 보려면
    가격 범위를 좁히거나 단지명으로 get_complex_price_info를 사용하세요.

    Args:
        district: 조회할 지역명 (동/구/군). 예: "관평동", "강남구", "성남시 분당구"
        price_min: 최소 가격 (만원). 매매=매매가, 전세=보증금, 월세=보증금 기준
        price_max: 최대 가격 (만원)
        trade_type: 거래 유형.
            A1 = 매매 (기본)
            B1 = 전세
            B2 = 월세 (응답에 rentPrice 포함)
        limit: 반환할 최대 매물 수 (기본 30, 최대 100)

    반환 JSON의 각 매물에는 tradeType, tradeTypeName, price, rentPrice 필드가 포함됩니다.
    월세의 경우 price는 보증금, rentPrice는 월세(만원/월)입니다.
    같은 물건을 여러 중개사가 올린 중복 매물은 하나로 묶여 반환됩니다.
    """
    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    raw, meta = crawl_district(district, price_min, price_max, trade_type, limit=limit)
    items = filter_and_rank(raw, price_min=price_min, price_max=price_max)
    truncated = len(items) > limit or meta["timeExceeded"] or (
        meta["complexesScanned"] < meta["complexesTotal"]
    )
    payload = {
        "district": meta.get("regionName", district),
        "returned": min(len(items), limit),
        "collected": len(items),
        "complexesScanned": meta["complexesScanned"],
        "complexesWithListings": meta["complexesTotal"],
        "truncated": truncated,
        "items": items[:limit],
        "lookupFailures": meta.get("lookupFailures", 0),
    }
    if truncated:
        payload["note"] = (
            "매물 수 상위 단지부터 수집하다 한도에 도달해 일부만 반환했습니다. "
            "가격 범위를 좁히거나 동 단위로 지역을 좁혀 다시 검색하세요."
        )
        if meta.get("lookupFailures"):
            payload["note"] = "일부 단지의 API 조회가 실패해 부분 결과입니다. 매물 부재로 확정할 수 없습니다."
    return json.dumps(payload, ensure_ascii=False, indent=1)


@mcp.tool
def get_complex_info(
    complex_id: str | None = None,
    complex_name: str | None = None,
) -> str:
    """아파트 단지 상세 정보를 조회합니다.

    Args:
        complex_id: 단지 번호 (complexNo)
        complex_name: 단지명 (예: "래미안강남")

    complex_id 또는 complex_name 중 하나는 필수입니다.
    """
    if not complex_id and complex_name:
        complex_id = search_complex_by_name(complex_name)
        if not complex_id:
            return json.dumps(
                {"error": f"단지를 찾을 수 없음: {complex_name} — 정확한 단지명 또는 complex_id로 다시 시도하세요."},
                ensure_ascii=False,
            )
    if not complex_id:
        return json.dumps(
            {"error": "complex_id 또는 complex_name을 입력하세요."},
            ensure_ascii=False,
        )
    detail = get_complex_detail(complex_id)
    return json.dumps(detail, ensure_ascii=False, indent=2)


@mcp.tool
def get_complex_price_info(
    complex_id: str | None = None,
    complex_name: str | None = None,
) -> str:
    """단지 평형별 시세(네이버) + 최근 실거래가를 조회합니다.

    평형별로 매매/전세 시세, 현재 호가 범위, 최근 실거래 내역을 반환합니다.

    Args:
        complex_id: 단지 번호 (complexNo)
        complex_name: 단지명 (예: "가천대역두산위브")

    complex_id 또는 complex_name 중 하나는 필수입니다.
    """
    if not complex_id and complex_name:
        complex_id = search_complex_by_name(complex_name)
        if not complex_id:
            return json.dumps(
                {"error": f"단지를 찾을 수 없음: {complex_name} — 정확한 단지명 또는 complex_id로 다시 시도하세요."},
                ensure_ascii=False,
            )
    if not complex_id:
        return json.dumps(
            {"error": "complex_id 또는 complex_name을 입력하세요."},
            ensure_ascii=False,
        )
    data = get_complex_prices(complex_id)
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool
def list_districts() -> str:
    """전국 시/도 17개 목록을 반환합니다.

    더 구체적인 지역(구/동)은 `search_apartments`의 district 파라미터에
    직접 입력하면 네이버 검색 API로 자동 조회됩니다.
    예: "관평동", "강남구", "성남시 분당구"
    """
    data = _client._get("/regions/list", {"cortarNo": "0000000000"})
    regions = data.get("regionList", [])
    simplified = [
        {"name": r.get("cortarName"), "cortarNo": r.get("cortarNo")}
        for r in regions
    ]
    return json.dumps(
        {"sido": simplified, "note": "구/동은 search_apartments에 직접 입력하세요."},
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool
def resolve_district(query: str) -> str:
    """지역명으로 네이버 cortarNo를 조회합니다.

    Args:
        query: 검색할 지역명 ("관평동", "강남구", "대전 유성구" 등)

    반환:
        cortarNo, cortarName, cortarType (city/dvsn/sec), 좌표
    """
    region = resolve_region(query)
    if not region:
        return json.dumps(
            {"error": f"지역을 찾을 수 없음: {query}"}, ensure_ascii=False
        )
    return json.dumps(region, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # PORT가 있으면 원격 HTTP(unified-school-mcp 등에서 프록시하기 위함),
    # 없으면 기존처럼 로컬 stdio(Claude Desktop 등 직접 연결용).
    port = os.environ.get("PORT")
    if port:
        mcp.run(
            transport="http",
            host="0.0.0.0",
            port=int(port),
            path="/mcp",
            stateless_http=True,
        )
    else:
        mcp.run()
