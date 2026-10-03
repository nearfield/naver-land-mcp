# naver-land-mcp

네이버 부동산의 아파트 조회 기능에 **상가·사무실 작업실 조사와 공통 상세·사진 조회**를 더한 MCP 서버입니다. 공개 웹 조회 경로를 사용하며, 네이버가 공식 제공·보장하는 API는 아닙니다.

[원본 프로젝트](https://github.com/kimju1416/naver-land-mcp)의 MIT 라이선스를 유지한 확장입니다. 개선점은 월세와 보증금의 분리, 전용면적 경계의 상세 확인, 명시적인 사진 상태, 접근 제한 처리, 재현 가능한 검증입니다.

## 기능

| 도구 | 용도 |
|---|---|
| `search_studio_spaces` | 동 단위 상가·사무실 월세 광고를 작업실 조건으로 분류 |
| `review_studio_articles` | 저장된 네이버 JSON을 같은 조건으로 검토. 외부 요청 없음 |
| `get_article_detail` | 아파트·상가·사무실 등 모든 유형의 광고 상세 |
| `get_article_photos` | 공개 사진 URL 및 `available` / `not_published` 상태 |
| `get_studio_article` | 초기 작업실 확장과 호환되는 상세 조회 별칭 |
| `search_apartments` | 기존 동·구·군 단위 아파트 매매·전세·월세 검색 |
| `watch_complexes` | 관심 단지 광고·시세·실거래·스냅샷 비교 |
| `get_complex_info` | 아파트 단지 상세 |
| `get_complex_price_info` | 단지 평형별 시세·실거래 |
| `resolve_district` | 지역명 조회 |
| `list_districts` | API가 반환하는 시·도 목록 |

작업실 검색 기본값은 **월세 150만원 미만, 광고상 전용 15~25평, 지상 2층 이상, 보증금 제한 없음**입니다. 월세·면적·층수·보증금은 입력으로 조정할 수 있습니다. 주차·엘리베이터·연식은 자동 제외 조건이 아닙니다. 지역을 동 단위로 지정하고 기준 좌표를 주면 수집한 광고를 직선거리로 정렬합니다.

목록에서 소수점이 생략된 면적은 경계에서 곧바로 제외하지 않습니다. 제한된 상세 조회로 확인하거나 `needsVerification`으로 남깁니다. 광고상 면적은 실측·임대 범위 확인을 대신하지 않습니다. [검색 조건과 분류 기준](docs/studio-research.md).

## 설치와 로컬 실행

조직 구성원에게 배포하려면 저장소의 `plugin.json`·`mcp.json`과 `.agents/plugins/marketplace.json`을 사용합니다. **네이버 부동산 조사** 플러그인은 Desktop에서 uv와 잠금 파일로 실행합니다. [조직 관리자 배포와 멤버 설치 안내](docs/organization-plugin.md).

Python 3.10 이상을 사용합니다.

```sh
python -m venv .venv
# macOS/Linux
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python stdio_server.py
```

Windows에서는 `.venv/bin/python` 대신 `.venv\Scripts\python.exe`를 사용합니다. `stdio_server.py`는 `PORT` 환경변수와 관계없이 로컬 stdio로 실행합니다. 원본 `server.py`의 선택적 HTTP 실행 방식은 유지합니다.

MCP 클라이언트의 설정 예시입니다. 실제 설치 경로로 바꾸세요.

```json
{
  "mcpServers": {
    "naver-land": {
      "command": "/absolute/path/naver-land-mcp/.venv/bin/python",
      "args": ["/absolute/path/naver-land-mcp/stdio_server.py"]
    }
  }
}
```

이 설정 예시는 앱에 자동 등록하지 않습니다. 원하는 클라이언트의 설정 방식에 맞춰 적용해야 합니다.

## 검증

개발 도구를 설치하고 기본 검증을 실행합니다. 기본 검증과 GitHub Actions는 네이버에 요청하지 않습니다.

```sh
.venv/bin/python -m pip install pytest pytest-cov ruff
.venv/bin/python scripts/verify.py --output .verification/offline.json
```

검증 항목은 정적 검사, 공개 대상 파일의 제한된 개인정보·토큰 검사, 회귀 테스트와 새 핵심 코드의 분기 포함 커버리지 85% 이상, 실제 stdio 연결의 11개 도구 발견·저장본 검토입니다. 테스트 자료는 실제 응답 형식을 유지하되 매물번호·주소·연락처·사진 경로를 익명화했습니다.

실제 네이버 응답은 명시적으로 요청할 때만 확인합니다.

```sh
.venv/bin/python scripts/verify.py --live --district 개포동 --output .verification/live.json
# 샘플에 사진이 없다면 공개 사진이 있는 실제 매물번호를 직접 지정합니다.
.venv/bin/python scripts/verify.py --live --district 개포동 --photo-article LISTING_WITH_PUBLIC_PHOTOS
```

실시간 성공에는 실제 상가·사무실 목록과 상세, 공개 사진 URL 1개 이상, 기존 아파트 목록, 아파트 상세 사진 상태가 필요합니다. ‘사진 없음’은 유효한 상세 응답에 빈 사진 목록이 있을 때만 정상입니다. 오류·빈 응답을 성공으로 바꾸지 않습니다. 범위 내 후보가 없으면 성공 기준을 낮추지 않고 실패로 남깁니다.

검증 결과 `passed`, `failed`, `blocked`를 구분하며 종료 코드는 각각 0, 1, 2입니다. 결과에는 소스 해시·검증 시각·검증 항목이 포함되며 실제 매물 원문·인증정보는 저장하지 않습니다. 실행 결과는 `.verification/`에서 현재 파일만 유지하고 Git에 포함하지 않습니다.

2026-10-03 개발 환경(Python 3.12)에서 전체 실시간 검증을 통과했습니다. API는 이후 바뀌거나 제한될 수 있습니다. GitHub Actions는 Python 3.10·3.12·3.13에서 같은 기본 검증을 실행합니다. [원격 자동 검증 결과](https://github.com/nearfield/naver-land-mcp/actions/workflows/tests.yml) · [검증 설계와 재현 기준](docs/testing.md).

## 제한과 데이터 해석

- 요청 간 최소 1초를 두며 접근 제한·CAPTCHA·401·403·429·리다이렉트에서 후속 요청을 중단합니다. 도메인·프록시 변경이나 인증정보 추출로 우회하지 않습니다.
- 개인 찜 목록이나 사용자 로그인 정보는 읽지 않습니다. 공개 세션 토큰은 메모리 안에서만 유지합니다.
- 공개 사진 URL을 반환하며 이미지를 내려받지 않습니다. 사진이 등록되지 않은 광고도 있습니다.
- 월세는 관리비·부가세·공과금·권리금과 별개입니다. 관리비 원문은 단위를 임의 추정하지 않습니다.
- 동일 광고번호만 중복 제거합니다. 다른 광고번호가 동일 공간인지는 수동 대조가 필요합니다.
- 부분 수집은 `truncated`로 표시하며 실제 도보 시간이나 음악 작업·공사 허가는 확정하지 않습니다.
- 후보 문서·사용자 비교면적·기존 자동화는 수정하지 않습니다.

[API 계약](docs/api-reference.md) · [기여 안내](CONTRIBUTING.md) · [라이선스](LICENSE)
