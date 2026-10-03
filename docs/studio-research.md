# 작업실 조사 조건과 응답

`search_studio_spaces`는 동 단위의 상가(SG)·사무실(SMS) 월세(B2) 광고를 조사한다. 실제 응답의 목록 `area2`는 소수점이 생략될 수 있고, 상세 `articleSpace.exclusiveSpace`가 더 정밀하다. 목록의 114㎡가 상세에서는 114.75㎡인 사례를 확인했다.

## 입력

| 입력 | 기본값 | 범위·의미 |
|---|---|---|
| `district` | 개포동 | 동 단위. 시·구 전체는 거부 |
| `monthly_rent_lt` | 150 | 월세 만원 단위, **미만** 조건 |
| `min_area_pyeong`, `max_area_pyeong` | 15, 25 | 광고상 전용면적, 경계 포함 |
| `min_floor` | 2 | 지상 최소 층수, 2 이상 |
| `deposit_max` | null | 보증금 상한 만원. null은 무제한 |
| `center_lat`, `center_lon` | null | 둘 다 주면 직선거리 우선 정렬 |
| `limit` | 30 | 분류별 반환 한도, 1~100 |
| `max_pages` | 2 | 목록 조회 페이지 한도, 1~3 |
| `detail_limit` | 5 | 경계·확인 필요 광고부터 상세 확인, 0~10 |

주차·엘리베이터·연식으로 자동 제외하지 않는다. 준공 10년 이내 여부는 참고 표시다. 실제 음악 작업·임대인 허가·방음 공사·관리규약 허용 여부는 별도 확인한다.

## 분류와 정밀도

- `matchingAdvertisements`: 광고상 필수 조건을 충족한다. 실측이 완료됐다는 의미가 아니다.
- `needsVerification`: 면적·층수·월세 등 필수 정보가 없거나 경계 판정에 정밀도가 부족하다.
- `excludedAdvertisements`: 확인된 필수 조건을 만족하지 않는다.

목록의 정수 면적에는 보수적으로 ±1㎡ 판정 여유를 둔다. 이 구간이 15평·25평 경계와 겹치면 상세 전용면적을 확인하거나 확인 필요로 남긴다. 공급면적은 전용면적의 대용으로 사용하지 않는다. 상세 조회 이후에는 상세의 광고상 전용면적을 사용한다. 이 여유는 실측 오차의 추정치가 아니다.

지하 B1·지하 1층·음수 층수를 구분하며 저·중·고층과 옥탑은 정확한 층수로 간주하지 않는다. 상세의 양수 층수 숫자보다 `B1/5` 같은 명시적인 지하 표기를 우선한다.

35초 처리 예산과 페이지·상세 한도를 두고, 완료하지 못한 범위는 `truncated`와 `timeBudgetReached`로 표시한다. 서로 다른 광고번호를 같은 공간으로 자동 합치지 않는다.

## 상세와 사진

`get_article_detail`과 `get_article_photos`는 아파트를 포함한 모든 광고 유형에 적용한다. `get_studio_article`은 상세 도구의 호환 별칭이다. 상세 `realestateTypeCode`와 목록 `realEstateTypeCode`, 확인일의 `articleConfirmYMD`/`articleConfirmYmd` 차이를 처리한다.

사진 상태는 `available`, `not_published`, `unknown`, `unusable`이다. 조회 도구는 유효한 상세의 `articlePhotos` 목록을 요구하며, 목록이 없거나 형식이 달라지면 오류로 반환한다. 빈 목록만 `not_published`로 판정한다. 공개 HTTPS URL만 반환하고 사진을 내려받지 않는다.

`monthlyManagementCost` 등의 원문과 광고 확인일을 보존한다. 관리비 단위를 추정하거나 부가세·공과금을 포함한 월 부담액을 자동 확정하지 않는다. 건축물대장 엘리베이터 수와 광고 주차 표시도 계약상의 사용 권리와 구분한다.

`review_studio_articles`는 같은 조건으로 저장된 네이버 형식 JSON 최대 500개를 분류한다. 네트워크 요청·최신성 확인·개인 후보 문서 수정은 하지 않는다.

## 근거

기반은 [원본 프로젝트](https://github.com/kimju1416/naver-land-mcp)다. 목록·상세 응답의 초기 조사에는 [RentMap 공개 구현 설명](https://github.com/jhpower901/RentMap/blob/main/docs/naver-land-crawling.md)을 참고했고, 현재 경로와 필드는 실제 `neo.land.naver.com` 응답으로 검증했다. 익명화한 계약 자료는 `tests/fixtures/`에 둔다. 네이버의 공식 API 계약이나 지속적인 접근 보장을 뜻하지 않는다.
