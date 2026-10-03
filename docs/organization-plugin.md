# 조직용 플러그인 배포

이 저장소는 **네이버 부동산 조사** 플러그인과 `nearfield-real-estate` 배포 목록을 포함합니다. ChatGPT Desktop에서 멤버별 로컬 MCP 서버를 실행합니다. 서버에는 아파트·상가·사무실 검색, 공통 광고 상세·공개 사진 조회 등11개 도구가 있습니다.

## 관리자 배포

조직 관리자 계정에서 ChatGPT 웹의 Admin → Plugins → Add → Import marketplace를 엽니다.

| 입력 | 값 |
|---|---|
| Source | `https://github.com/nearfield/naver-land-mcp` |
| Path | 비워 둠(저장소 루트) |
| Branch, tag, or commit | `main` |

가져오기 결과에서 **네이버 부동산 조사**가 오류 없이 생성됐는지 확인합니다. 필요한 역할에 Installation policy를 **Available**로 지정합니다. 멤버는 조직 Plugins에서 선택해 설치합니다. 설치 완료와 사용 가능 여부는 멤버별로 확인해야 합니다. 조직의 기능·권한이 허용되지 않으면 관리자가 먼저 해당 정책을 확인해야 합니다.

GitHub 관리 배포는 기본적으로 매일 동기화하며, Admin → Plugins → Marketplaces → Sync now로 직접 갱신할 수 있습니다. 업데이트 후 오류가 있으면 이전 정상 버전을 유지하므로 동기화 결과를 확인합니다.

## 멤버의 실행 준비

1. [uv 공식 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 uv를 설치하고 앱 실행 환경에서 `uv` 명령을 찾을 수 있게 합니다. 관리 장비는 조직 관리자가 배포할 수 있습니다.
2. 조직 Plugins에서 **네이버 부동산 조사**를 설치하고 활성화합니다.
3. 새 로컬 대화에서 플러그인을 선택한 뒤 원하는 매물 조건을 입력합니다. 첫 실행에서는 잠금 파일의 Python 패키지를 설치하므로 시간이 더 걸릴 수 있습니다.

플러그인은 설치 경로를 `${PLUGIN_ROOT}`로 받아 `uv run --frozen`으로 실행합니다. 코드와 잠금 파일이 함께 배포되므로 별도의 개발자 컴퓨터 경로나 가상환경을 참조하지 않습니다. `uv.lock`에 고정된 의존성을 사용하며, 첫 실행·업데이트에 패키지 다운로드가 필요할 수 있습니다.

호출 예시: “네이버 부동산 조사로 개포동 상가·사무실 월세 매물을 찾아줘. 전용15~25평, 지상2층 이상, 월세150만원 미만으로 검토하고 공개 사진도 확인해줘.” 서버 이름을 직접 지정하려면 `naver-land`를 문장에 포함합니다. 모델이 실제 도구를 호출했는지 대화의 실행 내역을 확인합니다.

조직 배포한 로컬 MCP 플러그인은 **Desktop only**입니다. 웹·모바일에서 사용하려면 별도의 원격 서버·앱 연결 구성이 필요합니다. 로컬 등록을 이미 사용 중이라면 플러그인 연결을 확인한 후 기존 수동 MCP 항목을 비활성화하여 중복을 피합니다.

## 검증과 데이터 범위

```sh
uv sync --frozen --extra dev
.venv/bin/python scripts/verify.py --output .verification/offline.json
.venv/bin/python scripts/verify_plugin.py
```

플러그인 검증은 Git 공개 대상만 임시 경로로 옮겨 원래 작업 폴더 밖에서 `mcp.json`의 실제 실행 명령으로 연결합니다. 도구11개와 익명화 자료 검토를 확인하며, 네이버 API 요청과 실제 사용자 자료 전송은 하지 않습니다. GitHub Actions는 Python3.10·3.12·3.13에서 같은 검증을 실행합니다. 조직 관리자 화면의 실제 가져오기·역할 설정·멤버 설치는 별도 확인 항목입니다.

개인 후보 문서·사진·로그인 정보·찜 목록은 패키지에 포함하지 않습니다. 검색 기본값은 입력으로 바꿀 수 있으며 광고 면적·관리비·음악 사용 허가를 확정하지 않습니다. `watch_complexes`의 비교 스냅샷은 실행한 멤버 컴퓨터의 `~/.naver-land`에 저장되며 조직 공용 자료가 아닙니다.

[OpenAI 조직 가져오기 안내](https://learn.chatgpt.com/docs/enterprise/plugin-management) · [플러그인 패키지 안내](https://developers.openai.com/plugins/build/plugins) · [프로젝트 안내](../README.md)
