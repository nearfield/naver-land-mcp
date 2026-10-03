"""네이버 부동산 내부 API 호출 모듈.

JWT Bearer 토큰이 필요하며, 메인 페이지 HTML에서 추출한다.
요청마다 requests.Session을 유지해 쿠키/토큰을 재사용한다.
"""

from __future__ import annotations

import re
import time
import threading
from typing import Any, Optional

import requests

from config import (
    API_BASE,
    BROWSER_HEADERS,
    CRAWL_TIME_BUDGET_SEC,
    DEFAULT_MAX_COMPLEXES,
    MAIN_PAGE_URL,
    REQUEST_DELAY_SEC,
    REQUEST_TIMEOUT_SEC,
    USER_AGENT,
)

_JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")


class AccessRestrictedError(RuntimeError):
    """접근 제한은 빈 매물 목록으로 처리하거나 자동 재시도하지 않는다."""


class ResponseSchemaError(RuntimeError):
    """Expected upstream contract changed; never silently treat it as zero results."""


def check_access(response) -> None:
    if response.status_code in (401, 403, 429) or 300 <= response.status_code < 400:
        raise AccessRestrictedError(f"네이버 접근 제한/리다이렉트(HTTP {response.status_code}). 자동 재시도를 중단합니다.")
    if "text/html" in response.headers.get("Content-Type", "") and any(
        token in response.text.lower() for token in ("captcha", "서비스 이용이 제한", "비정상적인 접근")
    ):
        raise AccessRestrictedError("네이버 접근 제한/CAPTCHA 응답. 자동 재시도를 중단합니다.")


class NaverLandClient:
    """네이버 부동산 API 클라이언트. 세션/토큰 생명주기 관리."""

    def __init__(self) -> None:
        self._session: Optional[requests.Session] = None
        self._jwt: Optional[str] = None
        self._request_lock = threading.RLock()
        self._last_request = 0.0
        self._access_restricted = False

    def _pause(self) -> None:
        time.sleep(max(0, 1.0 - (time.monotonic() - self._last_request)))
        self._last_request = time.monotonic()

    def _ensure_session(self) -> None:
        """Session + JWT 확보. 최초 호출 시 메인 페이지에서 토큰 추출."""
        if self._session is not None and self._jwt is not None:
            return
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9",
        })
        self._pause()
        r = sess.get(MAIN_PAGE_URL, timeout=REQUEST_TIMEOUT_SEC, allow_redirects=False)
        check_access(r)
        r.raise_for_status()
        tokens = _JWT_PATTERN.findall(r.text)
        if not tokens:
            raise RuntimeError("네이버 부동산 메인페이지에서 JWT 토큰을 찾지 못했습니다.")
        self._session = sess
        self._jwt = tokens[0]

    def _headers(self) -> dict:
        assert self._jwt is not None
        return {
            **BROWSER_HEADERS,
            "Authorization": f"Bearer {self._jwt}",
        }

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """요청 간 1초. 접근 제한은 같은 서버 실행에서 추가 호출도 중단한다."""
        with self._request_lock:
            if self._access_restricted:
                raise AccessRestrictedError("앞선 네이버 접근 제한으로 추가 요청을 중단했습니다. 수동 확인 후 서버를 다시 실행하세요.")
            try:
                self._ensure_session()
                assert self._session is not None
                self._pause()
                resp = self._session.get(
                    f"{API_BASE}{path}",
                    params=params,
                    headers=self._headers(),
                    timeout=REQUEST_TIMEOUT_SEC,
                    allow_redirects=False,
                )
                check_access(resp)
                resp.raise_for_status()
                try:
                    data = resp.json()
                except ValueError:
                    raise ResponseSchemaError(f"{path} JSON 응답 형식 오류.") from None
                if not isinstance(data, dict):
                    raise ResponseSchemaError(f"{path} 응답이 JSON 객체가 아닙니다.")
                # 네이버 API는 200이어도 error 필드를 반환할 수 있음
                if isinstance(data, dict) and data.get("error"):
                    err = data["error"]
                    code = str(err.get("code", "")) if isinstance(err, dict) else ""
                    if code.upper() in {"401", "403", "429", "CAPTCHA", "TOO_MANY_REQUESTS", "ACCESS_DENIED"}:
                        raise AccessRestrictedError("네이버 API 접근 제한 응답. 자동 재시도를 중단합니다.")
                    raise RuntimeError(
                        f"API 오류 응답 (path={path}); 결과를 매물 없음으로 처리하지 않습니다."
                    )
                return data
            except AccessRestrictedError:
                self._access_restricted = True
                raise
            except requests.RequestException as e:
                raise RuntimeError(f"{path} 요청 실패 ({type(e).__name__}). 자동 재시도하지 않습니다.") from None
            except ValueError:
                raise ResponseSchemaError(f"{path} JSON 응답 형식 오류. 매물 없음으로 처리하지 않습니다.") from None

    def close(self) -> None:
        """Release the session without persisting credentials or clearing a denial."""
        with self._request_lock:
            if self._session is not None:
                self._session.close()
            self._session = None
            self._jwt = None

    # ---- 공개 API ----

    def get_dong_list(self, cortar_no: str) -> list[dict]:
        """구/시 cortarNo → 하위 동 목록."""
        data = self._get("/regions/list", {"cortarNo": cortar_no})
        return data.get("regionList", [])

    def get_complexes(self, dong_code: str) -> list[dict]:
        """동 cortarNo → 아파트 단지 목록."""
        data = self._get(
            "/regions/complexes",
            {"cortarNo": dong_code, "realEstateType": "APT", "order": ""},
        )
        if not isinstance(data.get("complexList"), list):
            raise ResponseSchemaError("아파트 단지 목록 응답 형식이 달라 검색을 중단했습니다.")
        return data["complexList"]

    def get_articles(
        self,
        complex_no: str,
        trade_type: str = "A1",
        price_min: Optional[int] = None,
        price_max: Optional[int] = None,
        max_pages: int = 20,
        same_address_group: bool = False,
    ) -> list[dict]:
        """단지 번호 → 매물 목록 (페이지 수집).

        price_min/price_max(만원)를 네이버 API에 직접 전달해 서버측에서
        필터링한다 — 전체를 긁은 뒤 사후 필터링하면 대단지에서 페이지 수가
        폭증해 타임아웃 원인이 된다. same_address_group=True면 같은 물건을
        여러 중개사가 올린 중복 매물을 하나로 묶는다.
        """
        params_base: dict = {
            "tradeType": trade_type,
            "order": "rank",
        }
        if price_min is not None and price_min > 0:
            params_base["priceMin"] = str(price_min)
        if price_max is not None and price_max < 999999:
            params_base["priceMax"] = str(price_max)
        if same_address_group:
            params_base["sameAddressGroup"] = "true"

        all_articles: list[dict] = []
        page = 1
        while True:
            data = self._get(
                f"/articles/complex/{complex_no}",
                {**params_base, "page": str(page)},
            )
            batch = data.get("articleList")
            if not isinstance(batch, list) or not isinstance(data.get("isMoreData"), bool):
                raise ResponseSchemaError("아파트 목록 응답 형식이 달라 검색을 중단했습니다.")
            if any(not isinstance(a, dict) or not a.get("articleNo") for a in batch):
                raise ResponseSchemaError("아파트 목록에 매물번호 없는 항목이 있습니다.")
            if data["isMoreData"] and not batch:
                raise ResponseSchemaError("아파트 목록의 페이지 상태와 빈 응답이 모순됩니다.")
            all_articles.extend(batch)
            if not data.get("isMoreData") or not batch:
                break
            page += 1
            if page > max_pages:  # 안전장치
                break
            time.sleep(REQUEST_DELAY_SEC)
        return all_articles

    def get_complex_detail(self, complex_no: str) -> dict:
        """단지 상세 정보. complexDetail + 평형 목록을 병합해서 반환."""
        raw = self._get(f"/complexes/{complex_no}")
        detail = raw.get("complexDetail", {})
        detail["pyeongList"] = raw.get("complexPyeongDetailList", [])
        return detail

    def get_complex_prices(self, complex_no: str) -> dict:
        """단지 평형별 시세 + 실거래가 조회.

        반환: {pyeongNo: {시세, 실거래가 리스트}} 형태.
        """
        # 먼저 평형 목록 확인
        detail = self.get_complex_detail(complex_no)
        pyeong_list = detail.get("pyeongList", [])

        result: dict[str, Any] = {
            "complexNo": complex_no,
            "complexName": detail.get("complexName", ""),
            "address": detail.get("address", ""),
            "pyeongs": [],
        }

        for py in pyeong_list:
            area_no = py.get("pyeongNo")
            if not area_no:
                continue

            entry: dict[str, Any] = {
                "pyeongName": py.get("pyeongName", ""),
                "exclusiveArea": py.get("exclusiveArea", ""),
                "supplyArea": py.get("supplyArea", ""),
                "householdCount": py.get("householdCountByPyeong", ""),
                "roomCnt": py.get("roomCnt", ""),
                "bathroomCnt": py.get("bathroomCnt", ""),
            }

            # 호가 범위 (articleStatistics)
            stats = py.get("articleStatistics", {})
            if stats:
                entry["dealCount"] = stats.get("dealCount", "0")
                entry["dealPriceRange"] = stats.get("dealPriceString", "")

            # 시세 (한국부동산원 + KB부동산)
            for provider, key in [("kab", "marketPrice"), ("kbstar", "kbMarketPrice")]:
                time.sleep(REQUEST_DELAY_SEC)
                try:
                    table = self._get(
                        f"/complexes/{complex_no}/prices",
                        {"complexNo": complex_no, "tradeType": "A1",
                         "year": "5", "areaNo": area_no, "type": "table",
                         "provider": provider},
                    )
                    prices = table.get("marketPrices", [])
                    if prices:
                        p = prices[0]
                        entry[key] = {
                            "dealLow": p.get("dealLowPriceLimit"),
                            "dealHigh": p.get("dealUpperPriceLimit"),
                            "dealAvg": p.get("dealAveragePrice"),
                            "leaseLow": p.get("leaseLowPriceLimit"),
                            "leaseHigh": p.get("leaseUpperPriceLimit"),
                            "leaseAvg": p.get("leaseAveragePrice"),
                        }
                        if provider == "kab":
                            entry["marketPriceBasis"] = table.get(
                                "marketPriceBasisYearMonthDay", ""
                            )
                        else:
                            entry["kbPriceBasis"] = table.get(
                                "marketPriceBasisYearMonthDay", ""
                            )
                except AccessRestrictedError:
                    raise
                except RuntimeError:
                    pass

            # 실거래가 (chart)
            time.sleep(REQUEST_DELAY_SEC)
            try:
                chart = self._get(
                    f"/complexes/{complex_no}/prices",
                    {"complexNo": complex_no, "tradeType": "A1",
                     "year": "5", "areaNo": area_no, "type": "chart"},
                )
                x_list = chart.get("realPriceDataXList", [])
                y_list = chart.get("realPriceDataYList", [])
                f_list = chart.get("floorList", [])
                if len(x_list) > 1:
                    deals = []
                    for i in range(1, min(len(x_list), len(y_list))):
                        floor = f_list[i] if i < len(f_list) else None
                        deals.append({
                            "date": x_list[i],
                            "price": y_list[i],
                            "floor": floor,
                        })
                    deals.reverse()
                    entry["realDeals"] = deals[:5]
            except AccessRestrictedError:
                raise
            except RuntimeError:
                pass

            result["pyeongs"].append(entry)

        return result

    def resolve_region(self, query: str) -> Optional[dict]:
        """지역명을 네이버 검색 API로 조회해 cortarNo/이름/타입을 반환.

        cortarType:
            - city: 시/도 (예: 서울시, 경기도)
            - dvsn: 구/군/시 (예: 강남구, 유성구, 성남시 분당구)
            - sec: 동 (예: 관평동, 개포동)

        정확한 이름 매칭이 있으면 우선 반환. 없으면 첫 결과 반환.
        """
        data = self._get("/search", {"keyword": query})
        regions = data.get("regions") or []
        if not regions:
            return None
        # 쿼리가 cortarName 끝부분과 완전 일치하는 것 우선
        q = query.strip()
        for r in regions:
            name = r.get("cortarName", "")
            last_token = name.split()[-1] if name else ""
            if last_token == q or name == q:
                return r
        return regions[0]

    def search_complex_by_name(self, name: str) -> Optional[str]:
        """단지명으로 검색해 첫 매칭 complexNo 반환.

        네이버 부동산에는 별도 검색 API가 있지만(`/api/search`), 응답이 비어
        있을 수 있어 여기서는 알려진 지역을 순회하지 않는다. 향후 검색 API
        직접 연동으로 확장.
        """
        data = self._get("/search", {"keyword": name})
        # 응답 구조: {"complexes": [{"complexNo": "...", "complexName": "..."}], ...}
        complexes = data.get("complexes") or []
        if complexes:
            return complexes[0].get("complexNo")
        return None


# 모듈 레벨 싱글톤 (FastMCP 도구에서 재사용)
_client = NaverLandClient()


def get_dong_list(cortar_no: str) -> list[dict]:
    return _client.get_dong_list(cortar_no)


def get_complexes(dong_code: str) -> list[dict]:
    return _client.get_complexes(dong_code)


def get_articles(complex_no: str, trade_type: str = "A1", **kwargs) -> list[dict]:
    return _client.get_articles(complex_no, trade_type, **kwargs)


def get_complex_detail(complex_no: str) -> dict:
    return _client.get_complex_detail(complex_no)


def search_complex_by_name(name: str) -> Optional[str]:
    return _client.search_complex_by_name(name)


def get_complex_prices(complex_no: str) -> dict:
    return _client.get_complex_prices(complex_no)


def watch_complexes_data(
    complex_names: list[str],
    price_min: int,
    price_max: int,
    trade_type: str = "A1",
) -> dict[str, Any]:
    """관심 단지 목록의 매물 + 시세 + 실거래가를 한번에 조회.

    Returns:
        {"complexes": [...], "all_articles": [...]}
        - complexes: 단지별 상세 (시세, 실거래가 포함)
        - all_articles: 전체 매물 flat list (스냅샷 비교용)
    """
    from filter import filter_and_rank

    results: list[dict] = []
    all_articles: list[dict] = []

    for name in complex_names:
        complex_no = _client.search_complex_by_name(name)
        if not complex_no:
            results.append({"name": name, "error": f"단지를 찾을 수 없음: {name}"})
            continue

        time.sleep(REQUEST_DELAY_SEC)

        # 매물 조회 + 필터링 (가격 필터는 API에 직접 전달해 페이지 수 절감)
        articles = _client.get_articles(
            complex_no,
            trade_type,
            price_min=price_min,
            price_max=price_max,
            same_address_group=True,
        )
        for a in articles:
            a["_complexNo"] = complex_no
            a["_complexName"] = name

        filtered = filter_and_rank(articles, price_min=price_min, price_max=price_max)
        all_articles.extend(filtered)

        # 단지 기본정보 (시세/실거래가 없이 빠르게)
        time.sleep(REQUEST_DELAY_SEC)
        detail = _client.get_complex_detail(complex_no)

        # 대표 평형 1개만 시세+실거래가 조회 (속도 최적화)
        pyeong_list = detail.get("pyeongList", [])
        representative_pyeong = []
        if pyeong_list:
            py = pyeong_list[0]
            area_no = py.get("pyeongNo")
            entry: dict[str, Any] = {
                "pyeongName": py.get("pyeongName", ""),
                "exclusiveArea": py.get("exclusiveArea", ""),
            }
            # 시세 (한국부동산원 + KB부동산)
            if area_no:
                for provider, key in [("kab", "marketPrice"), ("kbstar", "kbMarketPrice")]:
                    time.sleep(REQUEST_DELAY_SEC)
                    try:
                        table = _client._get(
                            f"/complexes/{complex_no}/prices",
                            {"complexNo": complex_no, "tradeType": "A1",
                             "year": "5", "areaNo": area_no, "type": "table",
                             "provider": provider},
                        )
                        mp = table.get("marketPrices", [])
                        if mp:
                            p = mp[0]
                            entry[key] = {
                                "dealLow": p.get("dealLowPriceLimit"),
                                "dealHigh": p.get("dealUpperPriceLimit"),
                                "dealAvg": p.get("dealAveragePrice"),
                                "leaseLow": p.get("leaseLowPriceLimit"),
                                "leaseHigh": p.get("leaseUpperPriceLimit"),
                                "leaseAvg": p.get("leaseAveragePrice"),
                            }
                            if provider == "kab":
                                entry["marketPriceBasis"] = table.get("marketPriceBasisYearMonthDay", "")
                            else:
                                entry["kbPriceBasis"] = table.get("marketPriceBasisYearMonthDay", "")
                    except AccessRestrictedError:
                        raise
                    except RuntimeError:
                        pass
                # 실거래가
                time.sleep(REQUEST_DELAY_SEC)
                try:
                    chart = _client._get(
                        f"/complexes/{complex_no}/prices",
                        {"complexNo": complex_no, "tradeType": "A1",
                         "year": "5", "areaNo": area_no, "type": "chart"},
                    )
                    x_list = chart.get("realPriceDataXList", [])
                    y_list = chart.get("realPriceDataYList", [])
                    f_list = chart.get("floorList", [])
                    if len(x_list) > 1:
                        deals = []
                        for i in range(1, min(len(x_list), len(y_list))):
                            floor = f_list[i] if i < len(f_list) else None
                            deals.append({"date": x_list[i], "price": y_list[i], "floor": floor})
                        deals.reverse()
                        entry["realDeals"] = deals[:3]
                except AccessRestrictedError:
                    raise
                except RuntimeError:
                    pass
            representative_pyeong.append(entry)

        results.append({
            "name": detail.get("complexName", name),
            "complexNo": complex_no,
            "address": detail.get("address", ""),
            "articleCount": len(filtered),
            "articles": filtered,
            "pyeongs": representative_pyeong,
        })

    return {"complexes": results, "all_articles": all_articles}


def resolve_region(query: str) -> Optional[dict]:
    """지역명 → cortarNo/이름/타입 조회 (전국 지원)."""
    return _client.resolve_region(query)


def crawl_district(
    district: str,
    price_min: int,
    price_max: int,
    trade_type: str = "A1",
    limit: Optional[int] = None,
) -> tuple[list[dict], dict]:
    """지역 내 매물 수집. 동/구/시 단위 자동 감지.

    지원 형식:
    - 동 단위: "관평동", "개포동" → 해당 동 전체 단지
    - 구/군 단위: "강남구", "유성구", "성남시 분당구" → 구 하위 동 전체 순회
    - 시/도 단위: "서울시", "경기도" → 거부 (범위 너무 넓음)

    흐름:
    1. 네이버 search API로 cortarNo 조회
    2. cortarType 분기: sec(동) → 직접 단지 조회 / dvsn(구) → 동 순회
    3. 매물 수 내림차순 상위 단지부터, 가격 필터를 API에 전달해 수집
    4. limit 충족 또는 시간 예산(CRAWL_TIME_BUDGET_SEC) 소진 시 조기 종료

    Returns:
        (articles, meta) — meta에 수집 범위/조기종료 여부가 담긴다.
    """
    deadline = time.monotonic() + CRAWL_TIME_BUDGET_SEC

    region = resolve_region(district)
    if not region:
        raise ValueError(f"지역을 찾을 수 없음: {district}")

    cortar_no = region["cortarNo"]
    cortar_type = region.get("cortarType")
    region_name = region.get("cortarName", district)

    if cortar_type == "city":
        raise ValueError(
            f"{region_name}은 범위가 너무 넓습니다. 구/군/동 단위로 지정해주세요."
        )

    max_total = DEFAULT_MAX_COMPLEXES * 5  # 전체 단지 상한 (25개)
    deal_key = {"A1": "dealCount", "B1": "leaseCount", "B2": "rentCount"}.get(
        trade_type, "dealCount"
    )

    # 동 단위면 바로 단지 조회, 구 단위면 하위 동 순회
    all_complexes: list[dict] = []
    if cortar_type == "sec":
        dong_name = region_name.split()[-1]
        time.sleep(REQUEST_DELAY_SEC)
        complexes = _client.get_complexes(cortar_no)
        for c in complexes:
            if (c.get(deal_key) or 0) > 0:
                c["_dongName"] = dong_name
                all_complexes.append(c)
    else:
        # dvsn (구/군) — 하위 동 순회
        dongs = _client.get_dong_list(cortar_no)
        dongs = [d for d in dongs if d.get("cortarType") == "sec"]
        for dong in dongs:
            if time.monotonic() > deadline:
                break
            dong_code = dong.get("cortarNo")
            dong_name = dong.get("cortarName")
            if not dong_code:
                continue
            time.sleep(REQUEST_DELAY_SEC)
            complexes = _client.get_complexes(dong_code)
            for c in complexes:
                if (c.get(deal_key) or 0) > 0:
                    c["_dongName"] = dong_name
                    all_complexes.append(c)

    # 매물 수 내림차순 정렬 → 상위만 크롤링
    all_complexes.sort(key=lambda c: c.get(deal_key, 0), reverse=True)

    results: list[dict] = []
    scanned = 0
    lookup_failures = 0
    time_exceeded = False
    for cx in all_complexes[:max_total]:
        if time.monotonic() > deadline:
            time_exceeded = True
            break
        if limit is not None and len(results) >= limit:
            break
        cno = cx.get("complexNo")
        if not cno:
            continue
        time.sleep(REQUEST_DELAY_SEC)
        # 필요한 만큼만 페이지 수집 (페이지당 약 20건)
        if limit is not None:
            remaining = limit - len(results)
            max_pages = max(1, -(-remaining // 20))
        else:
            max_pages = 20
        try:
            articles = _client.get_articles(
                cno,
                trade_type,
                price_min=price_min,
                price_max=price_max,
                max_pages=max_pages,
                same_address_group=True,
            )
        except (AccessRestrictedError, ResponseSchemaError):
            raise
        except RuntimeError:
            lookup_failures += 1
            continue
        scanned += 1
        for a in articles:
            a["_complexNo"] = cno
            a["_complexName"] = cx.get("complexName")
            a["_dongName"] = cx.get("_dongName")
            a["_cortarAddress"] = cx.get("cortarAddress")
            results.append(a)

    if lookup_failures and not results:
        raise RuntimeError("아파트 목록 조회가 실패했습니다. 매물 없음으로 처리하지 않습니다.")
    meta = {
        "regionName": region_name,
        "complexesTotal": len(all_complexes),
        "complexesScanned": scanned,
        "timeExceeded": time_exceeded,
        "lookupFailures": lookup_failures,
    }
    return results, meta
