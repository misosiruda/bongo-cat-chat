# Windows 개발판 검증 기록

## 2026-10-28 입퇴장 안내와 채팅 차단 결합 검수

#37의 실제 병합 커밋 `e35456f672929fdd60ed22dca10b2649dff68578`을 차단 브랜치에 반영했다. 별도 `presence_events`·공유 순번·구버전 롤백 호환성을 유지하면서 입퇴장 감지·기존 안내 조회에도 계정별 앱 차단을 적용했다. 차단 시 이름 확인을 기다리던 후보를 버리고, 차단 중 관찰한 지연 표본이 해제 뒤 안내로 저장되지 않도록 원래 관찰 시각을 검사한다. 현재 구성원에서 빠진 퇴장 대상도 계정 차단 목록으로 판단한다.

- `tests/test_blocking.py tests/test_presence.py tests/test_presence_desktop.py tests/test_presence_rollback.py -q --tb=short --show-capture=no`: **57 passed / 6.13초**. 차단/해제·목록 읽기 실패·기준 표본 재설정·지연 입장·보관 로비의 퇴장 안내·실제 Qt 화면·구버전 복귀를 확인했다.
- `QT_QPA_PLATFORM=offscreen`, `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`, `BONGO_TEST_NSIS_PATH=<dist/tooling/nsis-3.13 절대 경로>`에서 `.venv/Scripts/python.exe -m pytest -q --tb=short --show-capture=no --junitxml=<작업 산출물>/combined-pytest.xml`: **747 passed / 147.27초, 실패·skip 0개**. Qt SharedImageManager 진단은 남았다.
- 결합 후 개인정보 안내 문구를 맞춘 뒤 `tests/test_distribution.py tests/test_localization.py -q --tb=short --show-capture=no`: **31 passed / 2.69초**.
- 합성 Playwright/Edge의 한 줄 목록·메뉴 검사를 재실행해 1240×840 / 400×500, 한영·밝음/어두움·차단·키보드·포커스·연결 변경을 확인했다. `tests/browser_profile_check.py`도 1240×840 / 960×540 / 400×500, 9개 캡처에서 통과했고 두 검사 모두 콘솔 오류·경고 0건이다. Steam 프로토콜은 mock이고 게임은 연결하지 않았다.
- PR #38 최초 Ready 자동 Code Review·Security는 `4d451fc6b3bf91c5999ca3805ae8adf740caccc0`에서 지적 없이 완료됐다. 위 결합 수정은 이후의 자체 검수·로컬 검사이며 최초 자동 리뷰가 결합 수정까지 검사했다고 표현하지 않는다. 최종 head의 원격 CI는 PR에서 별도로 확인한다.

#37 병합 선행 조건은 충족했지만 사용자 요청에 따라 배포 보류를 유지한다. 버전·태그·릴리스·업데이트 manifest·실사용 설치본을 변경하지 않았고 실제 게임 인수도 수행하지 않았다.

## 2026-10-28 채팅 차단 출하 검수

최종 한 줄 참여자 UI를 포함한 `feat/steam-id-chat-blocking`에서 전체 회귀 검사를 다시 실행했다. `QT_QPA_PLATFORM=offscreen`, `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu` 조건의 `.venv/Scripts/python.exe -m pytest -q --tb=short --show-capture=no --junitxml=<작업 산출물>/shipping-pytest.xml` 결과는 **709 passed, 5 skipped / 125.89초**다. skip은 NSIS 환경 변수 미지정에 따른 설치기 통합 검사다.

`BONGO_TEST_NSIS_PATH=dist/tooling/nsis-3.13`의 절대 경로를 지정한 `tests/test_windows_signing.py -k nsis`는 **4 passed / 6.27초**, `test_installer_update_choice_is_shared_and_preserved`는 **1 passed / 8.66초**였다. 별도 임시 설치 대상·서명 test double을 사용했으며 실사용 설치본을 바꾸지 않았다. Python compileall, `node --check src/bongo_chat/ui/app.js`, `git diff --check`도 통과했다. Qt offscreen의 SharedImageManager 진단은 남았다.

사용자 요청에 따라 공개 배포를 보류한다. 로비 입·퇴장 안내 #37 병합은 향후 배포 선행 조건이며, 이 검증 결과는 해당 변경과 합친 결과가 아니다. 결정 번호는 #37의 D-030과 겹치지 않도록 차단 정책을 D-031로 지정했다. 게임·Steam·실사용 데이터 연결은 수행하지 않았다.

## 2026-10-28 참여자 목록 한 줄 정리

후속 UI 피드백에 따라 참여자 목록을 높이 48px의 `고양이 · 이름 · ⋯` 한 줄로 줄였다. Steam ID·프로필 열기·차단/해제는 ⋯ 메뉴에 묶고 차단한 상대만 작은 상태 표시를 붙인다. 긴 이름은 목록에서 말줄임하고 메뉴에서 전체 이름을 확인한다. 메뉴는 창 밖으로 잘리지 않도록 배치하며 계정·로비·연결 구간 변경이나 대상 퇴장 시 닫는다.

- 실제 Qt·QWebChannel 차단/프로필·언어 검사: `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`에서 `pytest tests/test_profile_desktop.py tests/test_blocking.py tests/test_localization.py -q --tb=short --show-capture=no`, **55 passed / 9.58초**. Qt offscreen의 SharedImageManager 진단은 기존처럼 남았다.
- Browser plugin not available 조건에서 Playwright/Edge와 합성 로컬 서버를 사용했다. 1240×840 및 400×500의 한 줄 높이·말줄임·메뉴 위치, 라이트/다크·한국어/영어, 정확한 ID 차단, Enter/방향키/Escape, 포커스 복귀, 바깥 클릭·같은 버튼으로 닫기, 프로필 갱신과 연결 구간 변경을 확인했다. 콘솔 오류·경고 0건이며 화면 캡처는 저장소 밖에 보관했다.
- 메뉴 진입 경로를 반영한 `tests/browser_profile_check.py --browser <Edge> --output <작업 산출물>/compact-profiles`도 통과했다. 1240×840 / 960×540 / 400×500의 라이트·다크 화면 9개, Enter/Space, 초안·검색·스크롤 보존, 프로필 갱신 포커스와 이전 연결 구간 요청 거절을 확인했다. 콘솔 오류·경고는 0건이며 Steam 프로토콜은 mock으로 처리했다.
- 게임·Steam·실사용 데이터 연결과 설치본 배포는 수행하지 않았다. 변경 범위는 참여자 목록·메뉴와 관련 접근성·번역·회귀 검사다.


## 2026-10-28 게임 숨김 분리와 Steam ID 채팅 차단

[요구사항과 정책](chat-blocking.md), D-031에 따라 게임 숨김을 수신 조건에서 제거하고 계정별 `blocked_users`를 추가했다. 참여자 버튼과 설정의 ID 입력·해제를 제공하며 같은 계정의 모든 로비·검색·알림·반응·기록에 적용한다. 기존 게임 숨김 목록은 자동 이전하지 않는다.

- 소프트웨어 렌더링 환경(`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`)의 `.venv/Scripts/python.exe -m pytest -q --tb=short --show-capture=no`: **709 passed, 5 skipped / 126.95초**. NSIS 경로 환경 변수가 없는 설치기 통합 5개를 건너뛰었다. Qt offscreen의 `SharedImageManager` 진단은 남았으며 GPU 경로 인수와 구분한다.
- 초기 화면 검사에서 새 차단 버튼이 기존 `.participant-profile` 선택자를 공유하던 문제를 발견해 별도 `.block-action`으로 분리했다. 테스트의 화면 재로드 완료 대기도 보완한 뒤 실제 Qt 브리지·기존 프로필 검사 **19 passed / 7.02초**를 확인했다. 이 검사는 위 전체 실행보다 앞선 집중 검사이며 합산하지 않는다.
- Browser plugin not available. 기존 Playwright와 설치된 Edge를 사용해 로컬 합성 HTTP 화면과 실제 `ChatService`·SQLite를 연결했다. 게임 숨김 `True`·미확인 상태에서 채팅 표시, 키보드 차단, 인접 SteamID64·동명이인 분리, 직접 입력, uint64 초과 거절, 저장 실패 시 이전 목록 유지, 해제, 재로드, 다른 로비의 신규 저장 차단을 확인했다. 초안·검색·포커스를 보존했다.
- 합성 차단 화면: 1240×840 / 400×680, 한국어·영어, 라이트·다크. 페이지 URL·제목·내용·오류 오버레이 없음·스크린샷·가로 넘침 없음·콘솔 오류/경고 0건을 확인했다. 사용자 데이터 대신 명시적인 샘플 이름·합성 ID·문장만 사용했다. 스크린샷과 임시 검증 코드는 저장소 밖의 작업 산출물 폴더에 보관했다.
- `tests/browser_scroll_check.py --browser <Edge> --output <작업 산출물>/scroll`: 7개 시나리오 통과, 1280×800 / 480×800, 콘솔 오류·경고 0건. `tests/browser_profile_check.py`는 1240×840 / 960×540 / 400×500에서 라이트·다크·Enter/Space와 9개 화면을 검사했고 오류·경고 0건이었다.

- 최종 검토에서 작업자가 콜백의 원래 `observed`를 그대로 전달하도록 유지하고 이를 작업자 회귀 검사에 고정했다. 차단·작업자·기록·검색·번역표 집중 검사 **134 passed / 3.56초**를 확인했다. 전체 709개 결과 이후의 변경이므로 합산하지 않는다.
- 설정 상단에 차단 항목을 넣으면 좁은 창에서 언어 선택이 첫 화면 밖으로 밀리는 회귀를 발견했다. 기존 언어·테마 순서를 유지하고 차단을 테마 아래로 옮겼다. 최종 Qt 차단·언어 검사 **37 passed / 2.44초**, 차단 브라우저 흐름 재검사, 언어 브라우저 6개 레이아웃 검사가 통과했다. 읽던 위치 변화는 0px, 브라우저 콘솔 오류는 0건이었다.
- 반응 브라우저 검사도 통과했다. 합성 반응 100개 순간 입력, 24개 동시 표시, 좁은 창 10개, 연속 80개 및 앱 차단 시 제거를 확인했고 콘솔 오류·경고는 0건이었다. 실제 게임 리소스·Steam 연결 없이 합성 PNG를 사용했다.
- `git diff --check` 통과. 변경한 읽기 전용 진단 스크립트 3개는 AST 구문 검사만 실행했다. 새 작업자 상태의 `members`·`lobby_verified`에 맞춰 진단 필드를 갱신했으며 실사용 진단을 실행한 것은 아니다.

실제 Steam 초기화·게임 조작·실사용 로비 전송·실사용 DB 열기·설치본 교체·빌드·커밋·공개 배포는 수행하지 않았다. 게임에서 고양이 숨김을 직접 조작한 실제 자연 수신, 다른 PC·순정 게임·장시간 운영 인수는 미검증이다. 과거 실제 숨김 조회 검증을 이번 분리 정책의 게임 인수로 대체하지 않는다.


## 2026-10-28 로비 입·퇴장 안내

`origin/main`의 `7658736`에서 별도 `feat/lobby-presence-notices` 워크트리를 만들고 [입·퇴장 안내](lobby-presence.md)를 구현했다. 기존 `C:\Project\bongo-cat-chat` 작업 폴더의 브랜치·파일을 수정하지 않았다. 아래 결과는 게임/Steam 작업자를 실행하지 않은 합성 검증이다.

- Python 3.13.16, pytest 9.1.1, PySide6 6.12.0. 기존 개발 환경의 Python 실행 파일을 재사용하되 작업 디렉터리와 `PYTHONPATH`는 새 워크트리로 지정했다. 실제 사용자 DB 대신 테스트별 임시 SQLite만 열었다.
- 집중 검사: `python -m pytest -q tests/test_presence.py tests/test_presence_desktop.py tests/test_core.py tests/test_worker.py tests/test_scroll_service.py tests/test_privacy.py tests/test_localization.py` → **156 passed / 8.38초**. 최초 실행에서 새 테스트 도우미의 중복 인자 오류 3건을 수정한 뒤의 결과다.
- 전체 검사: `python -m pytest -q` → **713 passed, 5 skipped / 138.12초**. 건너뛴 5개는 `BONGO_TEST_NSIS_PATH` 미지정으로 생략된 실제 NSIS 컴파일러 통합 검사다. 기본 Qt offscreen GPU 경로에서 D3D/Skia/SharedImage 진단이 출력됐지만 테스트 실패는 없었다. 제품 GPU 설정은 변경하지 않았다.
- 실제 Qt 렌더러·QWebChannel 검사에서 입장 → 퇴장 안내, HTML처럼 생긴 이름의 텍스트 표시, 이름 보존, 한·영 전환, 다시 로드, 읽던 위치와 초안 유지, 대화 검색 복귀, 숨김/해제 반영을 확인했다. 작업자 없음·송신 명령 없음·메시지 알림 경로 호출 없음도 확인했다.
- Browser 플러그인이 제공되지 않아 기존 Playwright 방식으로 Edge **156.0.4314.50**에서 실제 제품 화면을 확인했다. 로컬 fixture 주소 `http://127.0.0.1:63402/`, **1240×840 / 480×800**, 밝은/어두운 테마와 긴 이름 줄바꿈을 검사했다. 화면 식별, 비어 있지 않음, 오류 오버레이 없음, 입장 → 대화 → 퇴장, 언어·초안·검색·스크롤 유지, 새 메시지 배지 제외를 확인했고 앱 콘솔 오류/경고는 **0개**다. 테스트 서버는 종료했다. 최초 브라우저 검사의 새 메시지 배지 단언은 미읽음 일반 대화 60건을 먼저 읽도록 fixture 순서를 보완한 뒤 통과했다.
- `node --check src/bongo_chat/ui/app.js`, 변경 Python 파일의 `compileall`, `git diff --check`가 통과했다.
- 안내·개인정보 문서를 갱신한 후 `python -m pytest -q tests/test_distribution.py tests/test_localization.py`를 실행해 **31 passed / 2.66초**를 확인했다. 이 수치는 전체 suite 결과와 합산하지 않는다.

위 수치는 최초 구현 단계의 결과다. PR #37 리뷰에서 자동 업데이트 롤백과의 충돌을 지적받아 schema 2 전환을 제거했다. 최종 구현은 기존 schema 1·messages 형식을 유지하고 별도 presence_events 테이블을 추가한다. 실제 dev16 Store 원문 fixture와 bootstrap.run_app()으로 새 버전 DB 기록 후 조기 실패·구버전 선택·대화/초안/설정 읽기·추가 쓰기·새 버전 재열기까지 검사했다. 관련 집중 검사 tests/test_presence.py, tests/test_presence_rollback.py, tests/test_presence_desktop.py, tests/test_updates.py는 80 passed / 6.29초였다.

최종 전체 검사는 `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`, `BONGO_TEST_NSIS_PATH=C:\Project\bongo-cat-chat\dist\tooling\nsis-3.13` 조건의 `python -m pytest -q --junitxml=<저장소 밖 검증 폴더>/presence-shipping-tests.xml`로 **722 passed, 0 skipped, 0 failed / JUnit 150.62초**를 확인했다. NSIS 5개 검사도 실제 사용 설치본과 분리된 임시 fixture에서 실행했다. 최종 저장 구조로 Edge 화면 검사도 다시 통과했다(1240×840 / 480×800, 밝은/어두운 테마, 한·영 전환, 초안·검색·스크롤 유지, 미읽음 제외, 긴 이름 줄바꿈, 콘솔 오류/경고 0개). 검사 서버와 브라우저는 종료했다.

실제 사용자 데이터의 변환·복원, 실제 사용 설치본 교체·배포, 실제 로비 입·퇴장·빠른 방문·순정 설치·다른 PC·장시간 실행은 수행하지 않았다. PR의 자동 Windows 빌드 산출물은 검토용이며 공개 릴리스 게시와 구분한다.

## 2026-10-23 한·영 UI와 영문 README

PR #36 코드 리뷰의 저장소 복구 지적을 반영했다. 저장된 English 설정을 두고 최초 조회를 실패시키는 검사에서 새로고침이 오류를 잘못 해제하는 실패를 먼저 재현했다. 복구 시 언어를 다시 읽고, 실패 중에는 저장 오류·기존 값을 유지하며, 성공 시 저장된 언어와 Qt signal/view를 복원하도록 수정했다. 소프트웨어 렌더링 조건의 `pytest tests/test_localization.py tests/test_desktop.py -q --junitxml=artifacts/release-dev16/review-fix.xml`은 **55 passed / 49.63초**였다. Qt offscreen의 SharedImageManager 진단은 남았으며 기본 GPU 경로 인수와 구분한다.

dev16 준비 시 번역·고지 생성 검사를 다시 실행했다. `QT_QPA_PLATFORM=offscreen`, `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu` 조건의 `.venv/Scripts/python.exe -X utf8 -m pytest tests/test_localization.py tests/test_distribution.py -q --junitxml=artifacts/release-dev16/focused.xml`은 **31 passed / 6.39초**였다. 배포 번역표와 영어 개인정보 고지의 소스 일치 검사를 추가했으며 실제 동결 파일 검증 결과는 빌드 단계와 구분한다.

사용자가 선택한 한·영 UI와 영문 README 범위를 `feat/english-localization`의 로컬 소스에 구현했다. [번역 범위](localization.md)와 D-029/FR-19를 따른다. 187개 영어 문구, 로컬 언어 선택·저장·복구, 영문 README와 개인정보 고지를 추가했다. 대화·이름·초안은 원문을 유지하고, 공개 배포와 설치본 적용은 수행하지 않았다.

- 전체 `.venv/Scripts/python.exe -X utf8 -m pytest -q`: **686 passed, 5 skipped / 202.51초**. 건너뛴 5개는 NSIS 경로 환경 변수가 없는 설치기 통합 검사였다. 이후 `BONGO_TEST_NSIS_PATH=dist/tooling/nsis-3.13`의 절대 경로를 지정해 해당 5개만 실행하여 **5 passed / 30.29초**를 확인했다. 처음에는 실행 파일 경로를 지정해 경로 해석에 실패했으며, 컴파일러 폴더로 수정한 후 통과했다. 실제 인증서·기존 설치본 대신 격리된 fixture와 서명 test double을 사용한다.
- 후속 영어 고지 검사를 추가한 집중 실행: `tests/test_localization.py`, `test_notice_collection_keeps_licences_and_excludes_unused_fmod`, 한·영 토스트 XML 검사 **15 passed / 2.73초**. 최종 언어 선택 키보드 포커스 복원 변경 후 `tests/test_localization.py` **12 passed / 1.63초**. 이 후속 검사 수를 전체 suite 결과에 합산하지 않는다.
- 시작 시 언어 설정 읽기 실패가 앱 시작 전체를 막지 않도록 보완한 뒤 `tests/test_localization.py tests/test_desktop.py` 최종 집중 검사 **55 passed / 54.80초**를 확인했다. 저장 오류 상태·송신 차단을 유지하면서 시스템 언어로 화면을 열고 기존 값을 덮어쓰지 않는다.
- Qt 실제 bridge·SQLite·렌더러: 시스템 언어 선택, 한↔영 전환, 창 제목, 재로드·Controller 재생성 후 유지, 저장 실패·잘못된 값 거부, 원문 이름/본문/초안과 검색 유지, 선택 제어의 포커스 복원을 검사했다. 기존 UI·반응·알림·프로필 집중 검사 72개도 통과했다.
- Chrome/Playwright의 합성 제품 화면: `tests/browser_localization_check.py`로 1240×840·960×540·400×500, 라이트·다크 설정창 **6개 조합**, 대화 및 설정의 수평 넘침·고정 닫기 버튼·삭제 확인 접근을 확인했다. 초기 화면·제목·주소 일치, 빈 화면/오류 오버레이 없음, **콘솔 오류 0개**, 언어 전환 뒤 읽던 메시지 앵커 오차 **0px**. 설정 저장 실패와 오프라인·연결 확인·읽기 전용·숨김 확인·미지원 게임·작업자 종료 및 업데이트 진행/실패/롤백 문구를 확인했다.
- 영어 선택을 저장한 별도 데이터 폴더에서 `python -m bongo_chat --offline --data-dir <격리 폴더> --smoke-report <검증 파일>`를 실행했다. **exit 0, renderer=true, console_errors=[], offline=true, steam_connected=false**였다. Qt offscreen의 GPU context/shared-image 진단 로그가 발생했으며, 이 결과를 실제 Windows GPU 화면 인수로 확대하지 않는다. 제품 GPU 설정은 변경하지 않았다.
- `git diff --check`와 새 문서의 로컬 링크 검사를 통과했다. 스크린샷·JUnit·오프라인 DB는 저장소 밖의 현재 작업 검증 폴더에 보관하며, 합성 자료만 사용했다.

게임 실행·실사용 송신·게임/Steam 종료·기존 사용자 DB 변경은 수행하지 않았다. 설치 마법사는 한국어를 유지한다. 공개 바이너리 빌드·코드 서명·릴리스 게시·실제 로비·영어 Windows 설치본·다른 PC 인수는 남아 있다.

## 2026-10-21 고양이 반응 파티클

사용자 승인 시안의 아래→위 2.2초 효과를 제품 수신·Qt 채팅창에 연결했다. 실제 게임 코드의 채널 6과 아이템 아이콘 참조, Steam 아이템 정의, 설치 게임의 스킨·모자·아이콘 이미지 읽기를 확인했다. 상세 범위와 재현 방법은 [반응 검증](reaction-particles.md), 식별정보 없는 수치는 [검증 데이터](evidence/2026-10-21-reaction-particles.json)에 기록한다.

- dev14 출하 전 최종 전체 pytest: **660 passed, 0 skipped, 0 failed / 174.78초**. 닉네임을 포함한 최종 소스에서 NSIS 3.13을 `BONGO_TEST_NSIS_PATH`에 지정해 설치 통합 검사도 수행했다. Qt는 `QT_QPA_PLATFORM=offscreen`, `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu` 조건이며 SharedImageManager 진단 로그가 남았다. 기본 GPU 경로 검증으로 확대하지 않는다. `pip check`와 `git diff --check`도 통과했다.
- 실제 Qt/QWebChannel/Controller와 합성 수신: 동일 사용자 5개 반응, 알림 호출 0회, 기록·초안 보존, 만료 정리, 지연된 브리지 응답의 재생 방지.
- Edge 제품 UI와 실제 로컬 게임 이미지: 개별 반복 6개, 순간 100개 중 최대 12개, 390px 화면 최대 5개, 상승 방향과 2.2초 수명, 기존 60개 메시지·스크롤·초안 보존, 숨김·검색·다크·움직임 줄이기, JS 오류 0건.
- 실제 자연 수신·게임 화면 비교·순정 게임/다른 PC·설치판 교체·공개 배포는 미검증이다. 실사용 로비로 메시지나 반응을 전송하지 않았다.

### 닉네임 이름표 후속 확인

사용자 추가 요청으로 파티클 아래에 최대 너비 112px·높이 22px, 11px 글자의 한 줄 이름표를 추가했다. 이름은 현재 허용된 발신자 프로필에서 읽고 텍스트로 표시한다. 짧은 이름·긴 한글·긴 영문·HTML 형태 문자열·줄바꿈을 포함한 이름 등 6개 표본에서 크기 제한·말줄임표·문자열 표시를 확인했다. Edge에서 390px 다크 화면, 입력 유지, 반응과 함께 제거, JS 오류 0건을 확인했다. 위 최종 전체 pytest와 Edge 반응 검사는 이름표 변경 후 결과다. 상세 로컬 결과와 캡처는 `artifacts/reactions/nicknames/`, 출하 전 결과는 `artifacts/release-dev14/`에 있다.

## 초기 Windows 개발판

검증일: 2026-10-13 / Windows x64 / 기존 Auto Chest Opener 패치 환경 / Bongo Cat 빌드 `25723683`.

PR #3의 `db78bda`에서 시작해 실제 저장소·원본 PoC·프로필 관찰 자료를 확인했다. 이 문서는 디자인 시안의 38개 UI 검사와 별개다. 게임·Steam 재시작, 로비 변경, 게임 파일 수정, DLL 주입·패치, 게임 메모리 쓰기는 하지 않았다. 순정 환경 인수나 일반 배포 승인을 의미하지 않는다.

## 2026-10-20 이슈 #32 기본 아바타

사용자는 캐릭터·모자 중 하나라도 해제하면 프로필 아이콘이 비어 퇴장한 이용자처럼 보인다고 제보했다. 이번 PC에서는 게임 실행이 불가능하다는 사용자 조건에 따라 Bongo Cat·Steam을 초기화하지 않고 아래 검사를 수행했다.

- **수정 전·후 합성 비교:** 원격 main `be9c8ff`의 작업자는 스킨 아이템 이름이 없으면 아바타 생성을 건너뛴다. 기본 캐릭터+모자, 양쪽 미착용은 수정 전 이미지 요청이 없었고 수정 후 각각 `Cat`+모자, `Cat`+모자 없음으로 요청된다. 캐릭터 착용+모자 미착용, 모두 착용은 기존에도 요청되며 수정 후 유지됐다. 모자만 해제한 제보의 실제 발생 조건은 게임에서 재현하지 못했으므로 별도 원인을 확정하지 않는다.
- **설치 파일 정적 확인:** 게임 빌드 `25936063`의 `CatCosmetics.Unequip`는 로비 슬롯에 `-1`을 기록하고 `CatCosmeticsMultiplayer.EquipCosmetic`은 이를 해제로 처리한다. `Cat.SetSkin(null)`의 기본 필드와 로비 프리팹의 참조를 대조해 정지 기본 스프라이트가 `CatLeft`·`CatRight`임을 확인했다. Mono.Cecil/UnityPy로 파일만 읽었으며 게임 어셈블리를 로드·실행하거나 파일을 수정하지 않았다.
- **설치 리소스 정적 합성:** 기본 `Cat`/착용 예시 `Black`과 모자 없음/`BongoCatHat`의 네 조합 모두 256×256의 비어 있지 않은 이미지를 생성했다. 실제 게임 화면 대조가 아니며 게임 그림·바이너리를 저장소나 배포물에 추가하지 않았다.
- **집중 회귀 검사:** `tests/test_default_avatars.py`, `tests/test_avatars.py`, `tests/test_worker.py` **48 passed in 19.75s**. 명시적 `-1`과 누락·잘못된 값·정의 실패 구분, 네 조합의 서로 다른 합성 PNG, 해제·재착용 및 캐시 복원, 기존 메시지·참여자 목록의 실제 Qt 이미지 로드와 갱신을 확인했다. 송신·실제 Steam 호출은 없다.
- **dev13 전체 검사:** 별도 작업 폴더의 고정 의존성 가상환경에서 `pytest -q --tb=short --junitxml=artifacts/issue-32/pytest.xml` **626 passed in 200.15s**, 실패·생략 0개. NSIS 3.13을 `BONGO_TEST_NSIS_PATH`에 지정해 설치 통합 검사를 포함했다. `pip check`, 변경 Python 컴파일, `git diff --check`도 통과했다. Qt의 SharedImageManager 진단 로그는 남았으며 기본 GPU 경로 검증으로 확대하지 않는다.

Qt는 `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu` 및 오프스크린 조건이다. 제품 GPU 설정은 바꾸지 않았다. 실제 로비 착용 변경, 설치 앱과 게임의 시각 대조, 다른 PC·순정 환경·장시간 인수는 남아 있다. 이 조건을 유지한 소스 수정·검수·병합·배포·이슈 종료는 사용자가 요청했으며, 종료를 실제 게임 재현 검증 완료로 표현하지 않는다.

## 2026-10-16 줄바꿈 메시지 수신 누락 수정

사용자가 게임에는 보이는 여러 줄 메시지가 앱에서는 누락된다고 제보했다. `4356a7b` 기준 `validate_text`는 LF·탭만 허용하고 CR을 금지된 제어 문자로 분류했다. 따라서 정상 JSON 본문에 Windows CRLF 또는 단독 CR이 있으면 `Steam.pump`가 메시지 전체를 거부해 저장·화면에 도달하지 못했다. 합성 패킷으로 이 경로를 재현했으며 사용자 원문 패킷을 수집하지 않아 제보 메시지의 실제 줄바꿈 바이트는 확정하지 않았다.

- CR을 허용하고 수신·저장·자기 에코 비교의 원문을 보존한다. 화면에서만 CRLF·CR을 LF로 바꾼다. Qt WebEngine에 단독 CR을 그대로 전달하면 줄이 나뉘지 않는 현상도 오프라인 렌더러에서 확인했다.
- 수정 전 프로토콜·저장·콜백 회귀 검사는 **6 failed, 10 passed**였다. 실패 6개는 CRLF·CR의 전체 메시지 거부였다. 수신 검사만 고친 중간 상태에서는 화면의 단독 CR 줄바꿈 검사 1개가 실패했고, 표시 변환까지 적용한 관련 검사는 **19 passed**였다.
- 화면 수정 후 관련 검사 **221 passed in 61.32s**. LF·CRLF·CR, 빈 줄·탭·한글·이모지, 50 UTF-16 단위를 넘는 수신, 저장소 재열기·검색, 정확한 자기 에코 병합, 화면의 실제 줄 간격·검색 강조를 확인했다. 다른 제어 문자·잘못된 유니코드·빈 메시지 차단, 송신 상한, 숨김·울음 필터, 작업자·스크롤 회귀도 포함한다.

격리 작업 디렉터리에서 기존 개발 가상환경을 사용한 최종 명령:

```powershell
$env:QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu'
& C:\Project\bongo-cat-chat\.venv\Scripts\python.exe -m pytest -q tests/test_core.py tests/test_callback.py tests/test_meow_filter.py tests/test_privacy.py tests/test_worker.py tests/test_desktop.py tests/test_scroll_service.py tests/test_scroll_desktop.py --tb=short --show-capture=no
node --check src/bongo_chat/ui/app.js
git diff --check
```

JavaScript 문법·diff 공백 검사도 통과했다. Qt 검사는 오프스크린·GPU 가속을 끈 테스트 프로세스에서 실행했으며 Chromium의 SharedImageManager 진단 로그는 남았다. 제품 GPU 설정은 변경하지 않았다. 실제 게임·Steam 송수신, 제보 입력의 원본 패킷 대조, 설치본 교체·릴리스 게시·기본 GPU 화면 인수는 수행하지 않았다. 기존에 거부되어 저장되지 않은 메시지는 복원할 수 없다.

### 금지 규칙의 도입 이유와 허용 범위 재검토

금지 규칙의 도입 배경을 확인하기 위해 `git blame`, 파일 변경 이력, 최초 [구현 커밋 ecf6f3a](https://github.com/misosiruda/bongo-cat-chat/commit/ecf6f3a5123df44c62c6e3f259daaab8fa27ef9d), [PR #4](https://github.com/misosiruda/bongo-cat-chat/pull/4)의 본문·일반 댓글·리뷰·인라인 댓글과 당시 EC-13을 조사했다.

- 확인된 목적은 잘못된 JSON·허용하지 않은 제어문자·비정상 유니코드의 방어적 검증이다. `Cc`·`Cs`를 일괄 차단하고 LF·탭을 예외로 둔 최초 코드가 이후 그대로 유지됐다. 당시 테스트는 LF 왕복·NUL·단독 서로게이트 거부를 확인했으며 CRLF 사례는 없었다.
- 확인한 기록에는 CR만 금지해야 하는 특정 취약점·게임 제약·사용자 결정이 없다. Windows 줄바꿈 예외가 빠진 것으로 판단하지만 작성 당시의 정확한 의도를 확정할 수는 없다. 당시 보안 리뷰 완료 표시는 이 CR 예외를 개별 검토했다는 증거로 사용하지 않는다.
- 현재 송신과 Qt 브리지는 JSON 직렬화를 사용하고, 작업자 전달은 객체 큐, DB 저장은 파라미터 바인딩, 화면은 텍스트 노드를 사용한다. 채팅 본문을 줄 단위 명령·HTTP 헤더·진단 로그에 삽입하는 경로는 확인되지 않았다. 허용되는 CR은 정상 JSON을 해석한 뒤의 문자열이며 JSON 문자열에 이스케이프 없이 들어온 CR/LF는 계속 거부한다.
- 마지막 경계를 회귀 검사 3개로 추가하고 송신 바이트에서 CR/LF가 이스케이프되는지도 확인했다. `& C:\Project\bongo-cat-chat\.venv\Scripts\python.exe -m pytest -q tests/test_core.py tests/test_callback.py tests/test_meow_filter.py --tb=short`는 **140 passed in 1.42s**였다. 이 후속 검사에서 제품 코드의 허용 범위를 추가로 넓히지는 않았다.

## 2026-10-16 이슈 24 제품 알림 연결

이슈 [#24](https://github.com/misosiruda/bongo-cat-chat/issues/24)의 작업 표시줄 알림·WinRT 토스트·독립 설정을 제품 수신에 연결했다. 최초 base `a2fd477`에서 시작하고, 이슈 #23을 병합한 최신 main `dffe75b`에 통합했다. 기존 작업·제품 설치·실사용 기록은 보존했다. 사용자 지시에 따라 **Bongo Cat을 실행하지 않았고 Steam 작업자·실사용 로비 송신도 시작하지 않았다.**

| 검사 | 결과 | 경계 |
| --- | --- | --- |
| 전체 자동 검사 | **570 passed**, 건너뜀 없음 | Windows/Qt/SQLite·설치 엔진·실제 NSIS 컴파일 포함. OS 발송은 대체 |
| 알림 정책·Windows 어댑터 집중 검사 | 61 passed | 새 수신, 포커스×4조합, 필터·중복·미저장·빈도·종료·설정·WinRT 초기 등록 오류 |
| 실제 Qt HTML/QWebChannel | 전체 검사에 포함 | 설정 왕복·재로딩·실패 복구·초안 보존·OS 오류와 저장 오류 분리 |
| 제품 브라우저 검사 | 통과, console 오류 0 | 1536×1024·1240×840·960×540·480×800·400×500. 라이트/다크·Space 설정 네 조합·스크롤·닫기·초안/검색 보존 |
| 프로필 브라우저 회귀 | 통과, console 오류·경고 0 | 1240×840·960×540·400×500, Enter/Space·포커스. 외부 프로토콜 대체 |
| 실제 Windows API 합성 수신 | 네 설정 조합에서 기록 **0/1/1/0건** 및 정리 확인 | 제품 Controller.poll→필터→정책→실제 WinRT/Flash API. 최소화·앱 비활성 유지. 개인 등록과 충돌하지 않게 AUMID만 고유 시험 값으로 대체 |
| 이전 소스와 새 설정 DB | 통과 | `a2fd477` ChatService를 새 bool 키가 있는 합성 DB로 실행, 기존 조회·테마·키 보존 확인. 구버전 설치본 롤백 인수는 아님 |
| 의존성·라이선스 | pip check 통과 | WinRT 5개 3.2.1/MIT 메타데이터 확인. wheel에 전문이 없어 upstream commit/SHA-256 고정 LICENSE 추가 |
| 최종 검토 묶음 | 빌드·고지·동결 화면 통과 | 실제 EXE의 PYZ와 동봉 WinRT 네이티브 확장을 개발 site-packages 없는 인터프리터로 읽어 XML/토스트 구성. 실제 OS 발송 없음 |
| 실제 Setup/제거 | 격리 설치·재설치·시작·제거 통과 | 별도 test identity·임시 APPDATA/LOCALAPPDATA 사용. 고정 제품 AUMID·런처 바로가기, 오프라인 renderer=true/console_errors=[]/steam_connected=false, 합성 DB 바이트 보존 확인. 기존 제품 등록은 변경하지 않음 |

실제 합성 시험에서 첫 `ToastNotifier.Setting`이 `0x80070490`으로 실패했다. 최초 `Show` 후 Enabled가 되는 것을 대조하고 이 오류만 정상 발송 경로로 넘기도록 수정했다. 권한 거부 등 다른 오류는 발송하지 않으며 OS 설정을 변경하지 않는다. `create_toast_notifier_with_id`, `remove_group_with_id` 오버로드도 실제 projection에서 확인했다.

Qt 오프스크린 검사에서 Chromium SharedImage/GLES 초기화 경고가 stderr에 있었다. 최종 테스트 실패나 제품 JavaScript console 오류는 없었다. 이를 GPU·배너·깜빡임 육안 인수로 설명하지 않는다. Browser 플러그인/skill이 없어 저장소 Playwright와 설치된 Edge/Chromium을 사용했다.

```powershell
$env:QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu'
$env:BONGO_TEST_NSIS_PATH='<검증한 NSIS 3.13 폴더>'
.venv/Scripts/python.exe -m pytest -q --tb=short
.venv/Scripts/python.exe -m pytest -q tests/test_windows_notifications.py tests/test_notifications.py --tb=short
.venv/Scripts/python.exe tests/browser_check.py --browser '<로컬 msedge.exe>' --output '<저장소 외부 폴더>'
.venv/Scripts/python.exe tests/browser_profile_check.py --browser '<로컬 msedge.exe>' --output '<저장소 외부 폴더>'
.venv/Scripts/python.exe -m pip check
node --check src/bongo_chat/ui/app.js
git diff --check
pwsh -NoProfile -File packaging/build.ps1 -OutputRoot dist/notification-integrated -AllowUnsigned
.venv/Scripts/python.exe tools/verify_review_bundle.py --bundle dist/notification-integrated/BongoCatChat --evidence '<저장소 외부 폴더>'
pwsh -NoProfile -File packaging/build-setup.ps1 -Bundle dist/notification-integrated/BongoCatChat -NsisPath '<NSIS 3.13>' -OutputRoot dist/notification-integrated-setup -TestIdentity -AllowUnsigned
```

네이티브 합성 시험은 저장소 외부 일회성 코드에서 제품 Controller와 가상 상태·메시지를 연결했다. 기본 제품 바로가기는 수정하지 않았고 자기 시험 바로가기·알림 그룹만 정리했다. 로컬 원본 산출물·스크린샷은 공개하지 않으며 [식별정보 없는 결과](evidence/2026-10-16-product-notifications.json)만 기록한다.

실제 설치본의 고정 제품 AUMID로 받는 배너·깜빡임 육안 확인, Windows 아이콘 표시 대조, Windows 알림 OFF·방해 금지·Windows 10·다른 PC·게임 자연 수신은 미검증이다. 클릭 활성화는 구현하지 않았다. 기존 설치본 교체·공개 릴리스·병합·이슈 종료는 이 결과와 별개다. [정책·등록·정리 안내](notifications.md).

### 출하 자체 검수 보완

후속 출하·검수 요청에서는 시작 시 설정 조회 오류를 키 미존재로 취급해 기본 ON이 될 수 있는 경계를 수정했다. 시작 조회 실패 때 두 알림을 보류하고, 수동 새로고침의 저장소 복구가 성공하면 저장된 두 값을 원자적으로 다시 읽는다. 각 키의 조회 실패 2개 회귀 검사를 추가해 저장된 OFF·기존 메시지가 보존됨을 확인했다.

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_notifications.py tests/test_core.py tests/test_notification_desktop.py tests/test_windows_notifications.py --tb=short
# 130 passed in 10.46s
```

앞선 전체 570개와 패키지 검사는 `134083a` 기준이며, 보완 소스의 집중 130개 결과와 구분한다. 게임 실행·작업자·실사용 수신 시험은 추가하지 않았다.

최초 Ready 자동 Code Review는 `b3a0ee2`에서 이전 프로세스가 남긴 토스트 정리 누락(P2)을 지적했다. 현재 프로세스가 새 알림을 제출하지 않았더라도 최초 상태 동기화·첫 옵션 OFF·종료 경계에서 자기 그룹 정리를 한 번 수행하도록 보완했다. 정리 실패의 반복 방지와 새 수신 계속 처리를 포함한 회귀 4개를 추가했다. 같은 집중 명령은 보완 후 **134 passed**로 통과했다. 리뷰 대상 SHA와 후속 수정 SHA를 동일하다고 표현하지 않는다.

후속 `4480805`의 로컬 전체 검사는 **576 passed in 126.97s**였지만 [원격 CI](https://github.com/misosiruda/bongo-cat-chat/actions/runs/38856717514)는 **575 passed, 1 failed**였다. 기존 스크롤 검사의 기록 350건 생성 중 Qt 이벤트 루프를 처리하지 않아 2.5초 상태 유효기간이 지나면 남은 합성 수신이 차단되는 조건을 확인했다. 저장마다 10ms 지연을 넣은 외부 재현 검사에서도 기록이 154건에 그치고 같은 UI 대기 조건이 실패했다. 대량 합성 기록 생성마다 시험 상태를 갱신하도록 `test_scroll_desktop.py`만 보정한 뒤 동일 지연 검사에서 기록 351건과 자기 송신 의도 1건, 총 352건이 유지되며 **1 passed**였다. 제품의 상태 유효기간·수신 차단·UI 인수 조건은 바꾸지 않았다.

보정 소스의 동일 전체 명령은 **576 passed in 124.19s**, 건너뜀 없음이었다. 실제 Windows API 합성 시험에서도 별도 프로세스가 남긴 시험 토스트가 새 Controller의 최초 동기화에서 제거됨을 확인했다. 원격 CI·자동 리뷰·실제 병합 상태는 이 로컬 검증으로 대신하지 않는다.

그다음 `057e1be`의 [원격 CI](https://github.com/misosiruda/bongo-cat-chat/actions/runs/38857841440)는 스크롤 검사가 통과했지만 기존 서비스 페이지 검사에서 같은 상태 만료가 발생해 **575 passed, 1 failed**였다. 저장마다 15ms 지연을 넣어 기록 157건·조회 0건과 같은 실패를 재현했다. 기존 서비스 단위 fixture도 다른 이력·프로필 검사처럼 명시적인 시계를 사용하도록 보정했다. 상태 만료 검사는 별도로 3초를 진행하는 자체 시계를 유지한다. Qt 대량 기록 헬퍼는 `test_desktop.py`로 모아 미저장 기록 검사에도 적용했다.

외부 지연 주입 검사 세 경우(연속 이력·미저장 이력·서비스 페이지)는 **3 passed in 12.39s**였다. 서비스 페이지는 230건 저장·최신 100건 조회를 확인했다. 최종 보정 소스의 전체 검사는 **576 passed in 109.00s**, 건너뜀 없음이었다. 두 CI 실패와 후속 결과를 구분하며 테스트 대기 시간·제품 유효기간·UI 기대값을 완화하지 않았다.

## 2026-10-16 이슈 #23 Steam 프로필 열기

원격 `main`의 `f587a30588be6c823725da251afa084a7f99feaa`에서 `feat/steam-profile` 브랜치를 만들어 실제 제품의 참여자 목록과 메시지 이름·아바타에 `Steam 프로필 열기`를 구현했다. [이슈 #23](https://github.com/misosiruda/bongo-cat-chat/issues/23)에 기록된 기존 진단 코드의 실제 URI 시험과 이번 제품 통합 검사를 구분한다.

**이번 PC에서는 사용자 요청으로 Bongo Cat을 실행하지 않았다.** 자동 검사는 합성 계정·대화·임시 DB를 사용하고 Steam 작업자와 실제 OS 프로토콜 실행을 차단했다. 실제 제품 버튼 → Steam의 정확한 상대 프로필 표시는 미검증이다. 게임 파일·개인 대화 DB·설치본을 변경하거나 메시지·친구 요청을 보내지 않았다.

| 검사 | 확인 결과와 범위 |
| --- | --- |
| 새 서비스·Qt 검사 | `tests/test_profiles.py`, `tests/test_profile_desktop.py`의 65개 검사가 최종 전체 실행에서 통과. ASCII/uint64 문자열·고정 URI, 대상/context·숨김·오래된 연결·읽기 전용·부분 확인, 종료/재시작·재진입, OS False/OSError/RuntimeError 격리, 저장/송신 상태 보존, 실제 QWebChannel ID/context 전달, UI 갱신·포커스·본문 URL 차단 포함 |
| 프로필 브라우저 검사 | 실제 제품 HTML + 합성 브리지 + Chrome/Playwright. 참여자/메시지 진입점, 동명이인, Enter·Space·더블클릭, 보관 로비·generation 변경·표본 만료, 초안·검색·스크롤 보존 통과. 1240×840·960×540·400×500 × 라이트/다크, 캡처 9개. JavaScript 오류·경고 0개 |
| 기존 UI 브라우저 검사 | 5개 창 크기, 설정 배치 6개 조합, 모달 갱신 12개 표본 통과. JavaScript 오류 0개 |
| 기존 스크롤 브라우저 검사 | 1280×800·480×800에서 기존 회귀 7개 통과. JavaScript 오류·경고 0개 |
| 최종 전체 pytest | **477 passed, 5 skipped in 85.34s**. NSIS 경로 `BONGO_TEST_NSIS_PATH`를 지정하지 않아 실제 NSIS 컴파일러 통합 5개는 미실행. 제품 설치 파일 빌드 결과로 표현하지 않음 |
| 정적 검사 | `node --check src/bongo_chat/ui/app.js`, `git diff --check` 통과 |

Browser 플러그인/`browser` 스킬이 제공되지 않아 기존 로컬 Playwright·Chrome 경로를 사용했다. 검사 서버는 `127.0.0.1`의 임의 포트였으며 검사 종료 시 닫았다. 화면 캡처는 저장소 밖 `C:/Users/user/Documents/Codex/qa/bongo-profile-issue23-20261016/`에만 보관한다. 이미지에는 합성 대화만 있다. Qt는 기존 검사 조건인 `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`를 사용했고 제품 GPU 설정은 바꾸지 않았다. Qt 자체 GPU/mailbox 경고와 페이지 JavaScript 오류는 구분했다.

### 기존 설정창 검사의 크기 반영 경합

최초 전체 검사 두 번은 각각 `476 passed, 5 skipped, 1 failed`였다. 기존 `test_settings_close_stays_reachable_after_scroll_and_reopen`의 라이트 960×540 또는 400×500 조합이 시간 초과됐다. 설정창 6개 조합만 재실행하면 통과했다.

수정 전 원격 `main`을 저장소 밖 별도 복사본으로 풀고 선행 검사와 설정창 검사를 실행해 동일한 400×500 실패를 재현했다(`106 passed, 1 failed`, `--maxfail=1`). 실패 시 viewport는 400×500으로 반영됐지만 설정 내용은 이전 배치 기준으로 일부만 스크롤되어 확인 버튼이 화면 아래에 남았다. Qt의 비동기 viewport 반영 전에 같은 테마 확인이 즉시 끝날 수 있었다.

`tests/test_desktop.py`에서 요청한 `innerWidth/innerHeight`가 반영된 뒤 기존 스크롤 검사를 시작하도록 보정했다. 기존 좌표·hit test·초안·포커스 인수 조건은 유지했다. 이 보정 후 위 최종 전체 실행이 통과했다. 이번 프로필 기능과 별도 테스트 보정이며 실제 사용자 환경의 GPU/모달 깜빡임 문제를 해결했다는 의미는 아니다.

### 실행 명령과 남은 실제 인수

```powershell
$env:QTWEBENGINE_CHROMIUM_FLAGS = '--disable-gpu'
.venv/Scripts/python.exe -m pytest -q tests/test_profiles.py tests/test_profile_desktop.py tests/test_core.py tests/test_desktop.py tests/test_worker.py
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe tests/browser_profile_check.py --browser 'C:/Program Files/Google/Chrome/Application/chrome.exe' --output <저장소-외부-캡처-폴더>
.venv/Scripts/python.exe tests/browser_check.py --browser 'C:/Program Files/Google/Chrome/Application/chrome.exe' --output <저장소-외부-캡처-폴더>
.venv/Scripts/python.exe tests/browser_scroll_check.py --browser 'C:/Program Files/Google/Chrome/Application/chrome.exe' --output <저장소-외부-캡처-폴더>
node --check src/bongo_chat/ui/app.js
git diff --check
```

실제 제품 버튼에서 Steam의 정확한 프로필 표시, Steam 미등록 핸들러·로그인 만료·다른 PC·설치본 통합은 남아 있다. OS False/예외 검사는 대체 함수의 실패 격리를 입증하며 실제 Steam 표시 성공을 뜻하지 않는다. 친구 추가 버튼 클릭·관계 변경, 릴리스 게시·설치본 교체는 이번 작업 범위에 포함하지 않는다. [FR-16](product-spec.md), [D-025](decisions.md#d-025-현재-로비-상대의-steam-프로필을-외부-steam-창으로-연다)를 따른다.

### 최신 main 통합 출하 검수

후속 출하·검수 요청 시 원격 `main`에 PR #26의 알림 검증 문서·도구·정책 테스트가 추가돼 있었다. `a2fd477137a4180f32312e97ce9c7fb0b591248d`를 정상 merge로 보존·통합했고 제품 코드 충돌은 없었다. 통합 커밋 `aab71e47a9d0dc957430dc8345a4076df73f0f70`에서 전체 pytest를 다시 실행해 **500 passed, 5 skipped in 90.42s**를 확인했다. 추가된 알림 정책 테스트는 오프라인 검사이며 Windows 알림 도구나 게임을 실행하지 않았다. 건너뛴 검사는 동일한 NSIS 컴파일러 통합 5개다.

자체 검수에서는 문자열 ID/context·대상 허용, 외부 URI 권한 제한·OS 예외 격리, 수명주기·중복 실행·포커스 보존을 다시 확인했다. 앞선 `63253f0`의 [Windows CI](https://github.com/misosiruda/bongo-cat-chat/actions/runs/38852585261)는 테스트·대응 소스 검사·미서명 앱 빌드·동결 EXE 오프라인 렌더러·설치 파일 컴파일까지 성공했다. 최신 head의 CI·자동 리뷰와 실제 병합 상태는 [PR #25](https://github.com/misosiruda/bongo-cat-chat/pull/25)의 결과로 확인한다. 실제 Steam 프로필 표시 인수와 공개 릴리스는 이 소스 검수로 완료 처리하지 않는다.

## 2026-10-15: 앱 아이콘과 파비콘

원작 고양이에 보라색 말풍선을 더한 투명 마스터와 앱 로고·Windows ICO·파비콘을 추가했다. [디자인·참조·재생성](design/app-icon.md)에 파일과 생성 프롬프트를 기록했다. 이 검증은 로컬 오프라인 UI와 미서명 검토용 빌드에 한정한다.

- 실제 Qt WebEngine에서 로고 PNG와 파비콘을 로드하고, 창 아이콘의 16·20·24·32·40·48·64·96·128·256px 프레임을 확인했다. 라이트·다크 화면과 16~128px 크기별 밝은/어두운 배경을 캡처해 확인했다. 최초 offscreen GPU 캡처는 context lost로 빈 화면이었으며 검사 프로세스에만 `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`를 지정해 다시 캡처했다. 제품 GPU 설정은 변경하지 않았다.
- WebEngine 파일 허용 목록은 로고와 파비콘 두 파일만 확장했다. 저장소의 다른 파일 및 외부 HTTPS 이미지 차단 유지, JavaScript 콘솔 오류 0개, Steam 작업자 미실행을 확인했다.
- 기존 `tests/test_desktop.py -k test_actual_qt_bridge_history_theme_hide_ime` **1개 통과**. `tests/browser_check.py`는 로컬 Chrome에서 5개 화면 크기, 설정 배치 6개 경우와 모달 갱신 12개 표본 검사를 통과했으며 콘솔 오류는 없었다. 브라우저 검사 서버 두 곳에 신규 이미지 MIME·경로를 추가했다. 전체 테스트 묶음과 별도 스크롤 검사 전체를 다시 실행한 것은 아니다.
- `packaging/build.ps1`로 `dist/icon-preview-20261015/`에 앱·실행기를 빌드하고 `tools/verify_review_bundle.py`로 동봉 자산의 소스 일치·의존성 고지·동결 EXE 오프라인 렌더러를 확인했다. 배포 의존성 감사의 알려진 차단 항목은 0개다.
- `packaging/build-setup.ps1 -TestIdentity -AllowUnsigned`로 `dist/icon-preview-20261015-setup/`에 NSIS 설치 파일을 생성했다. 앱·실행기·설치 EXE에서 아이콘 10개 프레임의 SHA-256이 소스 ICO 프레임과 일치했다. 설치·제거 프로그램은 동일한 ICO로 컴파일했다. 이번에 설치·제거 실행이나 Explorer·작업 표시줄 캐시 갱신을 검증하지는 않았다.

원본 참조, 크기별 비교 이미지, Qt 화면, 빌드·검사 로그는 Git에서 제외되는 `artifacts/icon-design/`에 보관한다. 설치된 앱 교체·버전 상승·공개 릴리스는 수행하지 않았다.

## 2026-10-14: 이슈 #9 설정창 스크롤·깜빡임 대응

[이슈 #9](https://github.com/misosiruda/bongo-cat-chat/issues/9)의 영상에서 설정 내용 아래쪽으로 스크롤하면 제목과 닫기 버튼이 보이지 않는 상태를 확인했다. 수정 전 실제 Qt WebEngine에서도 삭제 확인을 화면에 넣으면 제목·닫기 버튼의 표시 영역 검사가 실패했다. 설정 전체를 스크롤하던 구조를 고정 헤더와 내부 스크롤 영역으로 나누고, 다시 열 때 스크롤·삭제 확인을 초기화했다.

- `tests/test_desktop.py`: 실제 Qt WebEngine·QWebChannel·임시 SQLite에서 1,240×840, 960×540, 최소 창 400×500과 라이트·다크를 조합한 회귀 검사 6개를 추가했다. 제목·닫기·삭제 확인의 실제 좌표와 hit test, 재진입 위치·초점, 초안·기록 보존을 확인했다. 기존 Qt 검사를 포함해 **16개 통과**.
- `tests/browser_check.py`: 로컬 Chrome/Playwright와 합성 대화로 같은 6개 경우를 검사했다. 휠 스크롤 뒤 닫기 버튼의 고정 좌표를 실제 클릭해 닫기, 재진입 후 Esc 닫기·설정 버튼으로 초점 복귀, 검색·초안·대화 스크롤 보존을 확인했다. 기존 1,536×1,024·480×800 검사도 통과했으며 **JavaScript 콘솔 오류 0개**. 화면 캡처는 Git 외부에 보관했다.
- `node --check src/bongo_chat/ui/app.js`, `git diff --check` 통과.

검증 명령은 아래와 같다. 공유 개발 환경의 Python만 재사용하고 `PYTHONPATH`와 작업 디렉터리는 이슈 전용 워크트리로 지정했다. Browser 플러그인이 없는 환경에서 기존 Playwright 검사 경로를 사용했다.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:QTWEBENGINE_CHROMIUM_FLAGS = '--disable-gpu'
C:/Project/bongo-cat-chat/.venv/Scripts/python.exe -m pytest -q tests/test_desktop.py
C:/Project/bongo-cat-chat/.venv/Scripts/python.exe tests/browser_check.py --browser 'C:/Program Files/Google/Chrome/Application/chrome.exe' --output <저장소-외부-캡처-폴더>
node --check src/bongo_chat/ui/app.js
git diff --check
```

게임·Steam 작업자는 시작하지 않았다. 실제 게임 송신·사용자 대화 삭제·업데이트 다운로드·설치판 재빌드·배포는 이 검증에 포함하지 않는다. Qt 오프스크린 실행의 GPU 초기화 경고는 위 JavaScript 오류 검사와 구분한다. 이번 결과는 소스의 UI 회귀 검사이며 공개 dev6 설치 파일이 교체됐다는 의미가 아니다.

### 추가 확인: 닫혔다 열리는 것처럼 보이는 모달

위 레이아웃 검사만으로 영상의 모달 깜빡임까지 해결됐다고 판단할 수 없다. 소스에는 모달을 주기적으로 닫고 다시 여는 처리가 없으며 화면 상태는 600ms마다 갱신한다. 배경 흐림을 제거하기 전 오프스크린 Qt에서 합성 대화를 갱신하며 12.06초 동안 69회 관찰했을 때 `open` 속성 변경·닫힘 표본은 모두 0개였다. 이 결과는 DOM 상태 관찰이며 영상 제보자의 환경을 직접 관찰한 결과가 아니다.

Windows Qt WebEngine에서 `backdrop-filter: blur()`를 사용하는 화면이 깜빡이고 녹화 중 악화됐다는 [별도 앱 개발자의 재현 보고](https://github.com/ankitects/anki/issues/4470)가 있다. 제품의 `dialog::backdrop`에도 같은 효과가 있어 유력한 원인 후보로 보고 제거했다. 설정·참여자 모달은 배경을 반투명 단색으로 어둡게 처리한다. 제품의 GPU 가속 설정은 변경하지 않았으며, 외부 보고만으로 이슈 #9의 원인을 확정하지 않는다.

- `tests/test_desktop.py`: 설정·참여자 모달을 각각 연 채 합성 발언·프로필·업데이트 상태를 6회씩 변경한다. 모달 상태·제목 hit test·초점 유지와 계산된 배경 필터가 `none`인지 확인했다. 앞선 16개를 포함해 **18개 통과**.
- `tests/browser_check.py`: 두 모달에서 합성 발언·프로필 갱신 **12개 표본** 동안 `open` 속성 변경 0개, 헤더 캡처 해시 동일, Esc 닫기를 확인했다. 기존 창 크기·테마 검사도 다시 통과했으며 JavaScript 콘솔 오류 0개다.
- GPU 가속을 끄지 않은 오프스크린 Qt 프레임 캡처는 D3D/Skia context 오류와 검은 프레임으로 실패했다. 그 프레임의 동일 해시는 시각 검증에 사용할 수 없다. 위 Qt 회귀 검사는 `--disable-gpu` 환경의 기능 검사이며, Chrome 캡처 역시 제보 PC의 Qt GPU 깜빡임 해소를 입증하지 않는다.

현재 완료 범위는 의심되는 합성 효과 제거와 기능 회귀 검사다. 설치판 재빌드·배포, 제보 PC의 실제 Qt 창에서 녹화·상태 갱신 중 깜빡임이 사라졌는지 확인하는 인수는 남아 있다.

## 구현과 증거

| 영역 | 이번에 확인한 것 | 증거 수준·한계 |
| --- | --- | --- |
| 실제 연결 | 현재 프로세스·Steam 계정·게임 로비·멤버 대응, 새로 찾은 숨김 사전 조회 | 현재 프로세스 한 곳. 재시작·다른 PC 아님 |
| 실제 프로필 | 이름·스킨·모자 데이터 연결, 관찰 시점 16개 프로필 이미지 합성 | 설치 리소스를 메모리에서 읽음. 게임 화면과 정확한 시각 대조는 미검증 |
| 연결 수명주기 | 로비·계정·PID 생성 시각별 구간과 재검증 구현, 종료 시 Steam Shutdown만 호출 | 전환은 합성 검사. 읽기 시험 전후 동일 게임 로비와 게임 실행 유지 확인 |
| 실제 송신 | 사용자 승인 두 문구를 각각 실제 Qt UI에서 1회 송신 | 총 2회. 아래 API/자기 수신/사용자 확인을 구분 |
| 실제 상대 수신 | 첫 UI 실행에서 상대 메시지 1건 저장, 두 번째에서 12건 표시·저장 | 원문·계정·방 ID는 비공개 DB에만 보관 |
| 영구 기록 | 자기 메시지 각각 1행, 앱 종료 후 SQLite 재열기 검색 각 1건, integrity check `ok` | 운영 장기 보존·대용량 부하 결과 아님 |
| 숨김 | 실제 캐시 읽기 연결. 기록·검색·프로필·새 저장 필터와 실패 시 차단 검사 | 제품 UI와 실제 게임 숨김 조작 대조는 아직 없음. 원본 PoC의 조작 결과와 분리 |
| UI | 실제 Qt/QWebChannel/SQLite 검사 + Chromium 두 창 크기 검사 | 한국어 조합 이벤트는 합성. 실제 OS IME 직접 입력은 미검증 |

읽기 전용 탐색은 주소를 저장하거나 이전 PoC 주소를 재사용하지 않았다. 첫 성공한 독립 탐색은 58.74초, 이어진 관찰은 15초였다. 그 구간의 프로필 16개·숨김 캐시 18개는 서로 다른 모집단이다. 캐시에 이전 참여자가 남을 수 있으므로 캐시 건수를 현재 로비 인원수로 표시하지 않는다. 해당 구간 채팅 콜백은 0개로, 실제 상대 수신 증거는 후속 UI 시험에서 얻었다.

## 사용자 승인 실제 송수신

| 시험 | 명시한 문구 | 실행·결과 |
| --- | --- | --- |
| 첫 승인 | `Bongo Cat Chat 앱 송수신 확인입니다` | UI 보내기 1회, Steam API `accepted`, 자기 수신 후보 병합, 앱 표시, DB 재열기 검색 1건 |
| 사용자 추가 요청 | `이 채팅이 보이면 야옹야옹 해주세요` | UI 보내기 1회, API `accepted`, 자기 수신 후보 병합, 앱 표시, DB 재열기 검색 1건 |

사용자가 현재 로비 시험을 허용했고, 첫 시험 이후 두 번째 문구를 **추가로 직접 요청**했다. 오류에 따른 자동 재전송이 아니다. 각 시험은 승인한 계정·로비·PID 생성 시각을 비공개 계획과 다시 비교했다. 보내기 전에 일회용 시도 표식을 기록했으며 같은 계획을 다시 실행하면 거부한다. 실제 UI는 오프스크린 Qt WebEngine에서 제품 `app.js` → QWebChannel → Controller → 작업자 → Steam으로 실행했다.

두 번째 요청 후 사용자가 **“채팅 잘 떴어”**라고 확인했다. 이는 게임 채팅 표시의 **사용자 확인**이며 상대 PC 화면을 도구로 직접 검사한 증거는 아니다. 두 번째 송신 후 45초 동안 상대 메시지 12건을 앱에서 표시·저장했으나 `야옹야옹`이 포함된 응답은 0건이었다. 따라서 그 특정 응답을 수신했다고 기록하지 않는다. 읽음 표시는 구현하지 않았다.

두 실행 모두 목적지·게임 프로세스가 유지됐고 앱 종료 후 게임이 실행 중이었다. 별도의 읽기 전용 종료 시험에서는 게임 메모리의 현재 로비가 종료 전후 같은지도 확인했다. 앱이 받기 전이나 실행을 종료한 동안의 대화를 복원하지 않는다.

## 오프라인 검사

### 2026-10-14 스크롤 회귀 수정

main `2cc8348`을 기준으로 정렬한 `fix/chat-scroll-history` 워크트리에서 다음 동작을 가상 메시지와 제품 렌더러로 검증했다. 기존 연결 초기화·Meow 필터를 유지했다. 실제 게임 송수신·상대 화면·설치된 개발판 인수를 뜻하지 않는다.

| 항목 | 결과와 검증 범위 |
| --- | --- |
| 읽던 위치 | 최신 100개 범위에서 새 수신 5개가 와도 같은 메시지·화면 내 위치 유지 |
| 수동 최신 도착 | 1,280×800·480×800에서 새 메시지 표시와 이동 버튼 해제 |
| 고정 이동 버튼 | 대화 중간에서 접근하고 실제 최신 메시지의 맨 아래로 이동 |
| 기록 끝 | 정확히 100개일 때 이전 기록 버튼 숨김, 빈 페이지로 이동하지 않음 |
| 연속 기록 | 위로 스크롤하면 이전 기록 추가, 1,000개 범위의 아래쪽에서 다음 범위 연결 |
| 과거 열람 중 수신·전송 | 범위 밖의 새 수신 안내, 내 전송 후 최신 구간과 상태 표시 |
| 방·검색 | 방 복귀·검색 해제의 범위와 메시지 위치 복원, 검색 대상 뒤의 대화 표시 |
| 숨김·격리 | 대화와 신규 표시에서 숨김 상대 제외. 다른 계정·로비·만료 기록·기존 Meow 기록을 메타데이터에서도 제외 |

실행한 검사:

- `python -m pytest -q`: 최신 main과 결합한 전체 **305개 통과**. 실제 Qt WebEngine·QWebChannel의 새 스크롤 검사, Meow 메타데이터 회귀 검사와 기존 제품 검사를 포함한다. `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`인 오프스크린 환경에서 실행했다. 초기 기준의 별도 실행에서 GPU mailbox 진단이 출력됐으며 테스트 실패나 제품 JavaScript 오류로 판정하지 않았다.
- `python tests/browser_scroll_check.py --browser <로컬 Chromium> --output <외부 검증 폴더>`: 가상 기록 최대 1,250개로 **7개 흐름 통과**, 콘솔 오류·경고 없음.
- `python tests/browser_check.py --browser <로컬 Chromium> --output <외부 검증 폴더>`: 기존 1,536×1,024·480×800·1,240×840·960×540·400×500 화면 검사, 설정 배치 6개 경우·모달 갱신 12개 표본 통과.
- `node --check src/bongo_chat/ui/app.js`, `git diff --check`: 통과.

PR 게시 전 로컬 검수에서 지연된 조회 응답이 이미 읽은 메시지의 표시를 다시 켜는 경우를 추가로 재현했다. 읽지 않은 상대 메시지의 최대 순번 `unseen_seq`를 현재 UI 확인 순번과 비교하도록 수정했다. `tests/test_scroll_desktop.py`에서 실제 QWebChannel 응답을 보류하고 수동 최신 도착·다시 위로 이동·응답 해제를 수행한 회귀 검사가 통과했다.

이 추가 수정 후 `python -m pytest tests/test_core.py tests/test_desktop.py tests/test_scroll_service.py tests/test_scroll_desktop.py -q` **91개 통과**, 스크롤 브라우저 검사 **7개 흐름 재통과**, JavaScript 구문 검사 통과를 확인했다. 위의 전체 305개 결과는 추가 수정 전 기준이며, 최신 코드의 영향 범위는 이 별도 결과로 구분한다.

새 창 크기·긴 메시지·실제 Windows 입력·설치 패키지와 실사용 Steam 연결의 조합은 추가 인수 범위다. DB schema와 송신 API 변경이 없어 이전 코드로 복귀해도 저장 기록을 변환할 필요는 없다. 화면 정책과 조회 계약은 같은 앱 묶음으로 반영해야 한다.

- `tests/test_core.py`: 엄격한 UTF-8 JSON·채널·길이·제어문자 검사, 원본 한글 52바이트의 해시, 자기 수신 순서·반복 발언·앱 이벤트 중복, 계정·로비·구간 분리, 숨김·미확인·오래된 표본, 저장 실패, 30일 보관, 직접 삭제, 230건 페이지 조회, 송신 직전 재검증.
- `tests/test_callback.py`: 네이티브 콜백 메모리를 해제 시 덮어써도 복사된 본문과 앱 UUID만 남는지 검사.
- `tests/test_memory.py`: 이전 프로세스 주소를 읽기 전에 차단, 읽기 실패와 빈 목록 구분, 선언된 필드 수를 넘어서 다른 타입의 메타데이터를 읽지 않는지 검사.
- `tests/test_desktop.py`: 실제 Qt 렌더러·QWebChannel·SQLite에서 한글/HTML처럼 생긴 본문을 텍스트로 표시, 테마·초안·사이드바·합성 IME·숨김 DOM 제거, JavaScript 콘솔 오류 검사.
- `tests/browser_check.py`: 1,536×1,024 및 480×800 Chromium 화면, 합성 대화 48건, 라이트·다크·시스템, 테마 전환의 초안·스크롤 보존, 사이드바·검색·숨김·조회 실패·합성 IME. 검사 전용 로컬 전송 대역이며 실제 Steam 검사가 아니다.

실행 명령과 최종 수치는 [식별정보 없는 결과 JSON](evidence/2026-10-13-product-validation.json)에 기록한다. 초기 시안의 검사 수를 제품 검사에 더하지 않는다.

출하 전 로컬 검수에서 로비 변경 응답과 추가 입력이 겹치는 초안 혼입, 삭제 확인 중 계정 변경, 조회 실패 후 이전 상대 대화 잔류를 수정했다. 실제 QWebChannel 응답 하나를 지연한 Qt 검사에서 이전 방 입력은 원래 방에 저장되고 새 방의 저장된 초안만 새 송신 요청에 들어가는지 확인했다. 이 검사의 송신은 로컬 큐까지만 실행하고 네이티브 작업자는 시작하지 않았다. 다른 방 삭제 중 자기 수신 대응 보존, 저장 성공 메시지의 미저장 중복 표시 방지, 생성에 실패했던 저장 세션 복구도 추가 검사했다. 수정 후 전체 `pytest` **49개**, JavaScript 문법·Python 컴파일, 두 창 크기의 브라우저 검사가 통과했다. 이어 보관 방 삭제 후 현재 방으로 돌아오는 사례를 추가하고 영향 범위 Qt 검사 **5개**가 통과했다. 나머지 45개는 동일 코드·환경의 결과를 재사용하며 중복을 제외한 검사 사례는 50개다. 추가 실제 송신은 하지 않았다.

PR #4의 최초 코드·보안 자동 리뷰는 `57dd8c2`를 대상으로 모두 완료됐다. 코드 리뷰의 P2 지적에 따라 저장 장애 후 복구 메시지가 미저장 메시지보다 먼저 표시되는 문제를 수정했다. 수정 전 회귀 검사 4개에서 순서 역전을 재현했고, 커밋된 SQLite 순번에 미저장 구간을 연결한 뒤 같은 검사들이 통과했다. 수신 시각 동일·역행·증가, 두 번의 장애 구간, 검색으로 기준 메시지가 제외되는 경우를 포함한다. 실제 Qt에서는 미저장 메시지가 목록 첫 행일 때 검색 결과에서 대화로 이동, 이전 100건 페이지, 최신 페이지 복귀도 확인했다.

수정 후 `.venv/Scripts/python -m pytest -q tests/test_core.py tests/test_desktop.py` **50개**와 JavaScript 문법·Python 컴파일 검사가 통과했다. 변경하지 않은 콜백·메모리 검사 4개는 앞선 결과를 재사용해 현재 고유 사례는 **54개**다. 오프스크린 Qt 종료 중 GPU context 경고와 JavaScript 콘솔 오류 검사는 구분한다. 수정 커밋의 검증은 로컬 재검증이며 최초 자동 리뷰가 최신 수정본까지 검사했다고 표현하지 않는다.

## 2026-10-14 클릭 울음 제외

사용자의 클릭 울음 숨김 요청에 따라 신규 수신·저장과 기존 대화·검색·미저장 표시에서 해당 문구를 제외했다. 기존 저장 행과 DB 스키마는 유지한다. 게시된 dev6 설치본에 반영된 결과로 해석하지 않는다.

- **게임 정적 분석:** 설치 빌드 `25902419`의 `Vfx.CatSpeech.get_MeowText`, `SendSpeech`, `SteamMultiplayer.SendSpeech`, `LobbyMessage` 필드를 읽었다. 빈 입력이 번역된 울음으로 바뀌며 일반 채팅과 같은 채널·본문만 전달되고 자동 울음 표시가 없음을 확인했다. 게임 DLL을 실행하거나 변경하지 않았다.
- **번역 리소스:** 설치된 `BongoCat` 테이블의 항목 `4796346370`에서 27개 언어·원문 19개·대소문자 통합 후 18개 문구를 확인했다. 장면과 고양이 프리팹의 `CatSpeech` 직렬화 데이터에서도 같은 항목 키를 확인했다. 필요한 울음 문구·빌드·DLL 해시만 [번역 기준 파일](../tests/fixtures/meow-localizations.json)에 기록하며 게임 바이너리·이용자 대화·식별자는 포함하지 않았다.
- **회귀 검사:** [울음 필터 검사](../tests/test_meow_filter.py)는 전체 언어, 일반 문장의 보존, 자기/상대 콜백 해제와 정상 수신 연속 처리, 저장 실패 시 미저장 노출 방지, 기존 DB 재열기·검색·100개 페이지 경계를 확인한다. 실제 Steam 호출은 사용하지 않는다.
- **실행:** `.venv/Scripts/python -m pytest -q tests/test_meow_filter.py tests/test_core.py tests/test_callback.py tests/test_desktop.py` → **114 passed**. Qt WebEngine GPU context 경고가 출력됐으며 검사 실패는 없었다.
- **출하 후보 재검증:** 최신 `main`의 `845c264`를 기준으로 울음 필터 변경만 옮긴 워크트리에서 Python 3.13.3으로 `C:/Project/bongo-cat-chat/.venv/Scripts/python -B -m pytest -q tests/test_meow_filter.py tests/test_core.py tests/test_callback.py tests/test_desktop.py`를 실행해 **114 passed (25.09s)**를 확인했다. 병행 중인 연결 초기화 변경은 포함하지 않았으며 Qt GPU 경고와 실제 화면 인수는 구분한다.
- **미검증:** 실제 게임 클릭·언어 전환·새 설치 파일 빌드/배포는 실행하지 않았다. 자동과 동일한 문구를 직접 입력하면 함께 숨겨지며, 이후 게임의 번역 변경은 목록 재확인이 필요하다.

## 패키징과 남은 인수

PyInstaller 묶음의 첫 실행은 `QtCore` DLL 로딩 오류로 실패했다. 진단용 콘솔 빌드에서 실제 오류를 확인했고, 빌드 PATH의 다른 도구가 제공한 ICU DLL이 잘못 수집된 것을 찾았다. 이 파일을 제외한 실행은 통과했다. 최종 빌드는 Windows와 빌드 Python 경로만 사용해 다시 분석하며, 예상하지 않은 ICU·게임 바이너리 동봉을 검사한다. 일반 배포 의존성 이용 조건 검토는 별도다.

고양이 이미지의 첫 패키징 시험은 0개 합성으로 실패했다. CPU 메타데이터와 UnityPy가 간접 import하는 `fmod_toolkit`의 DLL이 누락돼 있었다. PyPI 의존성의 파일을 패키징에 포함한 뒤 최종 EXE에서 **연결 ready·16개 프로필 중 16개 이미지 합성·읽기 전용 송신 차단·상대 메시지 3건 저장·JavaScript 오류 0개**를 확인했다. 게임의 DLL·추출 이미지를 동봉한 것이 아니다.

실제 읽기 전용 시험 당시 묶음은 614,617,346바이트였다. 출하 검수 수정본은 별도 `dist/reviewed/BongoCatChat`에 다시 빌드했으며 614,619,087바이트다. 두 묶음의 해시를 [결과 JSON](evidence/2026-10-13-product-validation.json)에 구분한다. 수정본의 세 UI 파일은 소스와 해시가 일치한다. 한글·공백이 있는 별도 로컬 경로에 다시 설치하고, 개발 도구가 없는 PATH와 설치 폴더를 작업 디렉터리로 사용해 EXE를 실행했다. 오프라인 렌더러 검사는 종료 코드 0으로 통과했다. 제거 후 EXE·의존 파일이 삭제되고 대화 DB·시험용 별도 파일은 보존됐다. 시작 메뉴 바로가기는 생성하지 않았다. 현재 PC의 이 결과와 **개발 도구가 없는 별도 Windows PC** 인수는 구분한다. 수정본 EXE의 실제 Steam 연결은 다시 시험하지 않았다.

메시지 순서 지적을 반영한 묶음은 `dist/review-fix/BongoCatChat`에 별도로 빌드했고 **614,619,784바이트**다. 이 묶음에서도 UI 소스 해시 일치, 한글·공백 경로 설치, 개발 도구를 제외한 PATH의 오프라인 EXE 종료 코드 0·JavaScript 오류 0개, 제거 후 DB·별도 파일 보존을 다시 확인했다. 게임 연결·송신은 다시 실행하지 않았으며 최초 실제 연결 묶음과 이 수정본의 해시·검증 범위를 JSON에서 분리한다.

출하 검수 중 기본 출력 폴더 재빌드는 기존 개발판이 실행 중이어서 DLL 잠금으로 실패했다. 실패 때 지워진 동일 버전 의존 파일 60개를 복구했고 기존 파일을 덮어쓰거나 실행 중인 창을 종료하지 않았다. 빌드 전에 해당 출력 폴더의 앱/렌더러 실행을 검사하는 방어를 추가했으며 실제 실행 중인 묶음에서 PyInstaller 시작 전 거부됨을 확인했다. 수정본은 다른 출력 폴더에 빌드해 설치·실행·제거를 검증했다.

개발판 UI의 검증 환경은 Windows 11, 실제 오프스크린 Qt WebEngine과 로컬 Chromium이다. Browser 플러그인이 없어 Playwright를 사용했으며 서버는 시험 중 `127.0.0.1`의 임시 포트에만 열렸다. 제품은 이 서버를 사용하지 않는다.

| UI 확인 | 결과 | 확인 근거 |
| --- | --- | --- |
| 페이지·제목 | 통과 | 실제 제품 HTML과 개발판 제목 |
| 빈 화면·오류 덮개 | 통과 | 대화 DOM 및 화면 캡처 직접 확인 |
| 콘솔 | 통과 | JavaScript 오류 0개. 오프스크린 Qt의 GPU 경고는 별개 |
| 테마·검색·초안·스크롤 | 통과 | 설정 변경·시스템 밝기 변경·검색·합성 IME 이후 상태 비교 |
| 숨김·실패 | 통과 | 숨김 후 메시지·새 메시지 안내 제거, 미확인 상태 전송 차단·연결 표시 |
| 좁은 창 | 통과 | 480×800에서 메뉴·서랍·입력창 접근 |

테마의 시스템 미디어 이벤트를 즉시 단정하던 시험은 비동기 상태 대기로 고쳤고, 실패 시에도 브라우저·SQLite를 닫도록 검사 도구를 수정했다. 디자인과 비교해 두 열 구성·보라색 강조·테마·사이드바를 유지했다. 시험 화면의 기본 윤곽은 합성 프로필이며 실제 게임 외형 확인을 대신하지 않는다. 캡처는 Git 외부에 둔다.

미검증 항목:

- 순정 게임 설치·다른 PC·다른 게임/Mono/Steam 버전.
- 실제 게임·Steam 재시작, 시작/종료 순서, 계정 교체, 네트워크 재연결.
- 실제 로비 이동·빠른 A→B→A 전환, 같은 방 재입장 후 지연 이벤트.
- 제품 UI에서 실제 숨김·해제, 숨김 중 송수신·재시작·게임 업데이트 호환성.
- 실제 Windows 한글 IME 직접 입력, 게임 화면의 이름·고양이 외형 대조와 특수 외형.
- 장시간 실행·대량 누적·실제 디스크 고갈·강제 종료 중 SQLite 복구.
- 별도 깨끗한 Windows PC의 설치·실행·삭제, 시작 메뉴 바로가기, 코드 서명·설치 마법사.
- 일반 배포 채택·개발자 연락·소스 라이선스·암호화/백업·전체 채팅 끄기/언어 필터 정책.

현재 dev6은 채팅·숨김·로비·프로필 기능 계약과 네이티브 ABI·실행 중 내부 구조를 확인한 경우 연결한다. 관리 DLL 전체 해시가 달라져도 관련 기능이 같으면 허용한다. 미확인 구조는 상대 대화와 송신을 막는다. [기능별 업데이트 검사 기록](game-update-compatibility.md)은 이전 빌드의 파일 해시 방식과 구분한다.

## 2026-10-14 모자 위치 수정

사용자가 제공한 게임·채팅 앱 비교 화면에서 모자가 몸통과 겹치는 문제를 확인했다. 기존 합성은 256×256 스킨 두 장과 모자를 같은 좌표에 순서대로 덮었다. 설치 리소스의 로비 고양이 프리팹을 읽으면 세 레이어 크기는 각각 128×128이고 몸통·앞발 위치는 약 `(-6.3, 9.8)`, 모자는 `(10, 45)`다. 256픽셀 원본 기준 상대 이동은 오른쪽 32.6픽셀·위쪽 70.4픽셀이며, 합성은 각각 33·70픽셀로 반올림한다. 자식 순서는 몸통 → 모자 → 앞발이다.

`avatars.py`는 이 배치와 순서를 설치 리소스에서 읽고 모자를 이동한 전체 영역을 정사각형 PNG로 축소한다. 아이템별 보정값이나 게임 이미지를 코드·배포물에 추가하지 않았다. 배치가 누락·중복되거나 회전·배율·앵커·레이어 크기가 지원 범위를 벗어나면 합성을 보류한다.

- `tests/test_avatars.py` **20개 통과**: 상대 좌표·Y축 변환·자식 순서, 모자와 앞발의 겹침 순서, 위쪽 이미지 경계 보존, 모자 없는 스킨의 픽셀 유지, 잘못된 배치·스프라이트 거부, 비동기 합성과 PNG 캐시를 합성 자료로 검사했다.
- `python -B -m pytest -q tests/test_avatars.py tests/test_core.py tests/test_desktop.py` **75개 통과**. 기존 채팅 코어와 오프스크린 Qt/QWebChannel/SQLite 검사를 포함한다. 워크트리를 작업 디렉터리로 사용하고 기존 개발 환경의 Python을 실행했다.
- 실제 설치 리소스의 `FireCat`·`SatanicIncarnation` 조합을 기존 방식과 수정 방식으로 합성해 제보와 같은 겹침을 재현하고 수정 후 위치를 이미지로 대조했다. 게임에서 새 메시지를 보내거나 실행 중인 앱을 교체한 시험이 아니다.
- 실제 `Avatars` 작업자에서도 같은 스킨과 모자 3종·모자 없음의 **4개 조합**이 모두 PNG로 합성됐고 `stage=ready`, 오류 없음으로 종료했다. Steam 작업자를 시작하지 않은 별도 오프라인 Qt 창에서 수정 PNG의 256×256 디코딩·대화 DOM 표시·JavaScript 오류 0개를 확인했다. 오프스크린 창 캡처에는 GPU context 오류가 발생했으므로 캡처 성공이나 실제 설치판 화면 인수로 기록하지 않는다.
- 비교 PNG는 Git에서 제외한 워크트리의 `research/private/2026-10-14-avatar-alignment/`에만 보관한다. 제보 화면의 다른 이용자 이름·대화·계정·로비 정보와 게임 그림을 커밋하지 않는다.

실행 중인 설치판에는 아직 반영하지 않았다. 모든 스킨·모자 조합, 회전·반전·동작·효과, 설치 파일 재빌드·업데이트 적용 및 실제 앱에서의 사용자 확인은 이 검증에 포함하지 않는다.

## 2026-10-14 초기 연결과 숨김 동기화 분리

[D-021](decisions.md#d-021-로비-연결과-숨김-동기화를-분리한다)에 따라 Steam 로비 발견·초안 입력, 실제 게임 로비 검증, 사용자별 숨김 확인을 분리했다. 이 절은 후속 소스와 별도 로컬 빌드의 검사이며 공개 dev6 설치본을 교체하거나 새 릴리스를 게시한 기록이 아니다. [식별정보 없는 측정·소스 지문·빌드 근거](evidence/2026-10-14-startup-latency.json)를 함께 본다.

현재 PC에서 변경 전 소스의 초기화 단계를 직접 측정한 결과 `ready`까지 61.55초, 주소 탐색 57.86초, 실제 숨김 사전 읽기 0.014초였다. 첫 측정은 Qt와 이미지 렌더링을 제외했다. 직접 타입 조회를 도입하기 전 검색 방식의 실제 작업자는 이미지 준비를 활성화한 읽기 전용 시험에서 로비 발견 0.81초, 실제 로비 검증·숨김 동기화 완료 33.41초, 세 검색 단계 11.19초·10.77초·10.42초였다. 최대 상태 갱신 간격은 0.81초였다. Qt 창 시작을 포함한 앱 전체 실행 시간이나 여러 PC의 성능 보장은 아니며 각 환경에서 반복 냉시작 측정은 남아 있다.

대용량 검색은 `MemoryScan.exe`로 옮겼고 Python이 기존 메타데이터·관리 도메인·루트 구조와 게임 프로세스 수명을 다시 확인한다. 검색 결과와 실제 게임 로비를 얻기 전에는 전송을 허용하지 않는다. 숨김 조회만 실패한 경우 상대 표시·신규 저장을 보류하면서 검증된 송신 경로는 유지한다. 이 시험에서는 실제 송신을 하지 않았다.

실행한 검사:

```powershell
.venv/Scripts/python -m pytest -q
node --check src/bongo_chat/ui/app.js
.venv/Scripts/python -m compileall -q src tools/probe_startup.py
.venv/Scripts/python tools/probe_startup.py --timeout 150 --avatars
.venv/Scripts/python tests/browser_check.py --browser 'C:\Program Files\Google\Chrome\Application\chrome.exe' --output artifacts/startup-ui
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build.ps1 -OutputRoot dist/early-lobby-connection
git diff --check
```

- 전체 `pytest` 181개가 85.38초에 통과했다. 실제 컴파일된 검색기의 합성 버퍼와 Python 기준 결과를 비교해 정렬·별칭·중첩·청크 경계·후보 상한을 확인했다. 잘못된 응답, 프로세스 수명 변경, 탐색 취소 시 자체 검색기 종료, 탐색 실패 시 Steam 유지도 검사했다.
- 서비스·Qt 검사는 로비 발견 중 초안 작성과 유지, 검증 전 송수신 차단, 숨김 조회 실패 중 검증된 송신 준비와 자기 수신 병합, 확인된 상대만 표시·저장, 로비 변경 시 이전 요청 폐기를 확인했다. 모의 송신과 실제 상대 게임 화면을 구분한다.
- Chrome의 1,536×1,024 및 480×800 검사가 통과했고 JavaScript 오류는 0개였다. 로비 확인 중 상태의 합성 화면을 직접 확인했다. 실제 게임 대화나 사용자를 화면 자료로 저장하지 않았다.
- 별도 PyInstaller 빌드에 검색기가 포함됐고 컴파일한 검색기와 SHA-256이 일치했다. 개발 도구를 PATH에서 제외한 오프스크린 Qt에서 `--offline --smoke-report`와 `--read-only --connection-report`가 각각 종료 코드 0으로 통과했다. 실제 읽기 전용 연결은 `ready`, 프로필·렌더링 12개, JavaScript 오류 0개, 저장 메시지 0개, 송신 비활성으로 확인됐다. 별도 데이터 폴더를 사용했다.
- 소스 진단의 송신·본문 해석·DB 생성·로비 변경·메모리 쓰기는 모두 0이었다. 검사 종료 후 게임이 유지됐고 남은 검색기 프로세스는 0개였다.

실제 새 송신·상대 화면, 숨김·해제 및 로비·계정 전환, 순정 설치·다른 PC·장시간 실행은 이번 변경에서 검증하지 않았다. 설치된 앱과 공개 릴리스는 변경하지 않았다.

## 2026-10-14 Mono 타입 목록 직접 조회로 초기화 단축

앞선 33.41초는 실제 로비 검증을 위한 전체 메모리 검색 대기였다. 상세 측정에서는 세 단계가 약 5.16 GiB를 읽었고 읽기 호출에 약 22.83초, 패턴 비교에 약 4.60초를 사용했다. 숨김 사전 조회 자체를 늦추는 것으로 해결되지 않아 직접 타입 조회를 도입했다. [측정 및 소스 지문](evidence/2026-10-14-catalog-startup.json)은 이전 검색기 기반 빌드 기록과 구분한다.

- 지원 Mono의 로드된 어셈블리 목록, 이미지별 타입 캐시, 타입별 도메인 vtable을 읽어 전체 메모리 검색 세 단계를 정상 경로에서 제거했다. 같은 게임 프로세스에서 기존 검색과 타입·vtable 위치가 같음을 대조했다. 주소는 출력·파일 저장하지 않았다.
- 게임 로비 대조와 숨김 필터를 유지한다. 두 탐색 방식 모두 기존 필드·정적 루트·같은 관리 도메인 검증을 통과해야 한다. 직접 조회가 초기화·동시 변경으로 실패하면 제한된 검색으로 대체하지만, 로드된 접근자 코드 불일치·프로세스 변경·취소는 우회하지 않는다.
- 고양이 이미지의 자원 해석은 검증 완료 상태를 발행한 뒤 시작한다. 빠른 타입 조회와 이미지 해석이 동시에 Python 실행 시간을 경쟁하던 지연을 제거했다.
- 실제 작업자를 새 프로세스로 세 번 실행했다. 아바타 기능을 켠 읽기 전용 조건에서 로비 검증·숨김 완료는 **0.7915 / 0.7162 / 0.7131초**, 상대 수신 허용 조건 성립은 **0.9947 / 0.9185 / 0.9227초**였다. 직접 탐색은 **0.0267~0.0307초**였고 전체 검색은 실행되지 않았다. Qt 시작 전 단계부터 잰 앱 전체 실행 시간은 아니다.
- 별도 데이터 폴더의 오프스크린 소스 Qt 앱은 import 전부터 검증·숨김 완료 화면까지 **2.811초**였다. 실제 게임 상태를 읽었지만 Steam 어댑터는 송신과 콜백 본문 해석을 차단했다. 저장 메시지·JavaScript 오류 모두 0개였다. 합성 데이터 검사와 구분하며 최종 설치 EXE의 성능으로 확대하지 않는다.
- 최종 `.venv/Scripts/python -m pytest -q`는 **208 passed in 81.88s**였다. 타입 목록 순환·중복·다른 이미지·크기 제한·도중 변경, vtable의 클래스·도메인 불일치와 변경, 접근자 코드 불일치, 취소·시간 제한, 대체 검색의 공통 검증을 검사했다. 작업자 검사는 일반 모드 송신 가능 상태가 이미지 시작 전에 발행되고 읽기 전용 모드는 계속 차단되는지 확인했다.

이번 변경에서는 실제 메시지 전송·상대 화면·게임 재시작·숨김/로비 전환을 시험하지 않았다. 세 작업자 시험은 같은 실행 중인 게임과 같은 PC를 사용하므로 반복 냉시작 또는 모든 환경의 1초 보장이 아니다. 새 설치 파일 빌드·기존 설치 교체·릴리스 게시도 수행하지 않았다. 앞 절의 EXE 검사는 이번 직접 조회 코드가 들어가기 전 결과다.

## 2026-10-14 최신 main 통합 후 출하 후보 검수

`97a6052`의 모자·설정창·클릭 울음 필터를 반영한 뒤 초기 연결 변경을 검수했다. 최종 런타임 커밋은 `e4e720b`이며, 아래 결과는 앞 절의 208개 검사와 별도다. [검증 데이터](evidence/2026-10-14-startup-shipping.json)에 실행 명령·커밋·런타임 트리·묶음 해시를 기록했다.

- 전체 `pytest`는 **285 passed, 1 failed (113.38s)**였다. 실패는 작은 창의 설정창 스크롤 가시성 검사 `test_settings_close_stays_reachable_after_scroll_and_reopen[light-size2]`의 Qt 대기 시간 초과다. GPU context 경고가 있었지만 직접 원인은 확정하지 못했다. 제품 코드 변경 없이 Qt 검사 전체를 재실행해 **19 passed (28.04s)**를 확인했다.
- 로컬 화면 검수에서 설정 안내가 이전의 숨김 실패 시 송신 차단 정책을 설명하는 것을 발견해 현재 동작으로 정정했다. 수정 후 Qt 검사 전체 **19 passed (28.64s)**와 브라우저 검사 5개 창 크기, 설정 배치 6개 경우, 모달 갱신 12개 표본이 통과했다. GPU 경고는 남았고 JavaScript 콘솔 오류는 0개다. 전체 검사가 한 번에 모두 성공했다고 표현하지 않는다.
- JavaScript 문법, Python 컴파일, diff 공백 검사가 통과했다. 합쳐진 최종 diff에서 탐색 취소·읽기 핸들 소유권·지원 ABI 제한·목적지 재검증·미확인 상대 본문 차단을 확인했다.
- 새 소스 작업자 1회는 로비 발견 **0.6097초**, 검증·숨김 완료 **0.7847초**, 상대 수신 허용 **0.9782초**였다. 직접 조회 **0.0329초**, 전체 검색 0회이며 송신·본문 해석·DB 생성·게임 쓰기·로비 변경은 0이다. 같은 실행 중인 게임/PC이며 Qt 시작 시간을 포함하지 않는다.
- `dist/connection-reviewed`에 최종 직접 조회 코드를 포함한 PyInstaller 개발용 묶음을 빌드했다. 포함된 설정 HTML·검색기와 소스/컴파일 산출물의 SHA-256 일치를 확인했다. 버전은 기존 `0.1.0.dev7`을 유지하며 새 릴리스로 게시하지 않았다.
- 개발 도구를 PATH에서 제외한 오프스크린 EXE의 오프라인 진단과 읽기 전용 실제 연결 진단이 종료 코드 0으로 통과했다. 연결은 `ready`, 프로필·렌더링 각 11개, 송신 비활성, JavaScript 오류 0개였다. 격리된 비공개 DB에 자연 수신 메시지 1건이 저장됐으며 원문·계정·방 식별자는 읽거나 게시하지 않았다. 빌드에는 미사용 QML assetdownloader 플러그인 및 `fmod.dll` 탐색 경고가 있었고 런타임 진단 실패는 없었다.

실제 송신·상대 화면, 실행 파일의 최초 화면까지 시간, 게임 재시작/냉시작, 숨김·로비·계정 전환, 다른 PC·순정 설치·장시간 실행은 미검증이다. 기존 설치본과 공개 릴리스는 변경하지 않았다. 자동 코드·보안 리뷰와 병합 여부는 이 로컬 검증 기록으로 대신하지 않는다.

## 2026-10-15 복수 Steam 게임 실행 시 로비 탐색 수정

사용자는 Bongo Cat과 다른 Steam 게임을 함께 실행하면 로비를 찾지 못한다고 제보했다. 기존 소스는 `GetFriendGamePlayed`의 App ID가 Bongo Cat이어야 로비를 인정했고, 그 조건을 통과해야 메모리 탐색을 시작했다. 따라서 다른 게임이 보고되면 Bongo Cat의 실제 로비를 읽을 기회도 없었다. [D-024](decisions.md#d-024-여러-steam-게임을-실행해도-bongo-cat의-로비를-직접-확인한다)에 따라 탐색 시작을 친구 게임 정보에서 분리하고 `LobbyData.Current`와 Steam 자기 참여를 연결·송신의 기준으로 사용한다.

검사 대상은 `6ff190985cca23bac67b158c514cef0005f14fda`에서 수정한 로컬 소스다. 원본 채팅·식별자·메모리 주소를 검증 기록에 포함하지 않는다.

- **수정 전 합성 재현:** 다른 게임·빈 친구 게임 정보·오래된 로비 정보와 탐색 시작/실패 상태를 포함한 검사에서 17개 실패, 54개 통과를 확인했다. 사용자 PC의 실제 두 게임 실행을 재현한 결과는 아니다.
- **수정 후 관련 검사:** `tests/test_core.py`, `test_worker.py`, `test_memory.py`, `test_environment.py`, `test_callback.py`, `test_mono_catalog.py`의 **141개가 통과**했다. Bongo Cat 로비만 조회·모의 송신, 다른 게임 정보 변경 시 연결 구간·초안 유지, 로비 없음/읽기 실패 시 보조 정보로 대체 금지, 자기 참여 해제와 로비·계정·프로세스 경합 차단, 메모리 탐색의 15초 재시도와 콜백 비우기를 확인했다.
- **현재 게임의 실제 읽기 전용 연결:** 수정 전 0.7486초, 수정 후 **0.5781초**에 로비 검증·숨김 동기화를 완료했다. 이때는 기존 코드도 연결됐으므로 제보된 복수 게임 오류의 실제 재현 증거로 취급하지 않는다.
- **실제 연결에 다른 게임 정보만 대입한 진단:** `Steam.reported_game`의 반환값만 합성 `(999, '0')`으로 바꾸고 실제 `tools/probe_startup.py --timeout 10` 작업자를 실행했다. 실제 Bongo Cat 메모리·Steam 계정·자기 참여 조회를 통해 `searching_lobby → ready`로 전환했고 **0.6910초**에 로비 검증·숨김 동기화를 완료했다. 실제 다른 게임을 추가 실행한 검사는 아니다.
- 위 두 수정 후 진단의 송신·채팅 본문 해석·DB 생성·로비 변경·게임 메모리 쓰기는 모두 0이었다. 게임 프로세스는 검사 종료 후에도 유지됐다. 측정은 Qt 창·아바타 준비를 제외한 같은 PC의 실행 중 게임 기준이다.
- **기본 환경 전체 검사:** `pytest -q`는 **411 passed, 1 failed, 5 skipped (115.21s)**였다. 실패는 설정창 스크롤 가시성 검사 `test_settings_close_stays_reachable_after_scroll_and_reopen[light-size1]`의 Qt 대기 시간 초과다. GPU context 경고가 함께 발생했다. 설정창의 여섯 경우만 다시 실행하면 4개 통과·2개 실패였고 `light-size2`도 시간 초과가 발생했다.
- **UI 실패 분리 검사:** 수정 전 HEAD의 추적 소스를 `artifacts/multi-game-head-baseline`에 추출해 같은 설정창 검사 6개를 실행하면 모두 통과했다. 수정 후 소스에서 검사 프로세스에만 `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`를 추가해도 **6개 모두 통과**했다. 기본 GPU 경로의 실패 원인은 확정하지 않았고 앱의 GPU 설정이나 UI 구현을 변경하지 않았다.
- **GPU 가속을 끈 테스트 프로세스의 전체 재검사:** `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu` 조건에서 `pytest -q --tb=short --show-capture=no -rs`는 **412 passed, 5 skipped (97.02s)**였다. 건너뛴 5개는 `BONGO_TEST_NSIS_PATH`가 지정되지 않은 실제 NSIS 컴파일러 통합 검사다. 이 결과를 기본 GPU 환경의 전체 통과로 확대하지 않는다.
- **정적 검사:** 변경한 Python 소스·테스트의 `compileall`, `node --check src/bongo_chat/ui/app.js`, `git diff --check`가 통과했다.

아래 후속 시험에서 실제 두 게임 동시 실행 상태를 확인했다. 두 게임의 실행 순서·추가 실행·종료, 로비 이동·계정 전환, 메시지 송신·상대 화면, 다른 PC·순정 설치·장시간 인수는 남아 있다. 이 최초 소스 진단 시점에는 새 설치 파일 빌드·기존 설치 교체·공개 배포를 수행하지 않았다. 이후 출하 후보 버전을 `0.1.0.dev11`로 지정했다.

### 실제 Bongo Cat + Marvel’s Spider-Man Remastered 동시 실행 확인

같은 날 사용자가 스파이더맨 리마스터를 직접 실행한 뒤 읽기 전용 비교를 수행했다. `BongoCat.exe`와 `Spider-Man.exe`의 동시 실행을 확인했고 두 진단 종료 후에도 동일한 게임 프로세스가 유지됐다. Steam 친구 게임 정보는 두 검사 모두 App ID `1817070`과 로비 없음(`0`)을 반환했다. 실행 중인 스파이더맨의 설치 경로에 있는 appmanifest에서 이 App ID와 게임 이름을 대조했다. Steam 응답을 합성값으로 바꾸지 않았다.

| 대상 | 실제 관찰 결과 |
| --- | --- |
| 수정 전 HEAD의 로비 작업자 | 10초 관찰 동안 `no_lobby`, 실제 Bongo Cat 로비 검증에 도달하지 못함 |
| 수정 후 로비 작업자 | `searching_lobby → ready`, **0.5746초**에 실제 Bongo Cat 로비·숨김 동기화 완료 |
| 수정 후 연결 유지 | 검증 완료 후 **30.4313초**, 상태 표본 **59개**, 연결 해제 **0회**, 연결 구간 **1개** 유지 |

두 버전은 같은 지원 모듈과 실제 게임·Steam 상태를 사용하고 로비 작업자 코드만 비교했다. 수정 전 작업자는 `git show HEAD:src/bongo_chat/worker.py`의 원문을 별도 모듈로 읽었다. 실제 작업자의 `read_only=True`와 빈 명령 큐를 사용하고, 진단 어댑터에서 송신·채팅 본문 조회 진입점도 차단했다. 콜백은 본문을 읽지 않고 비웠다. 송신·본문 해석·DB 생성·로비 변경·게임 메모리 쓰기·차단된 함수 호출 시도는 모두 **0**이었다. Qt 화면과 아바타 준비는 포함하지 않았다.

식별정보를 제외한 상태·소스 SHA-256·공개 App ID·측정치는 [실제 동시 실행 검증 데이터](evidence/2026-10-15-multi-game-lobby.json)에 기록했다. 이 결과는 실행 중인 두 게임에서의 로비 발견·30초 연결 유지 검증이며, 메시지 송수신·상대 화면·추가 실행/종료 전환·새 설치본 검증은 아니다.

### dev11 출하 후보 검사

`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`와 검증된 NSIS 3.13 경로를 `BONGO_TEST_NSIS_PATH`로 지정해 전체 검사를 다시 실행했다. **417 passed in 118.85s**, 건너뛴 검사 0개였다. 앞서 생략된 실제 NSIS 컴파일러 통합 검사 5개를 포함한다. CI와 같은 소프트웨어 렌더링 조건이며, 기본 GPU 환경의 Qt 시간 초과 원인을 해결했다는 의미는 아니다. 제품의 GPU 설정은 변경하지 않았다. 로컬 원본 결과는 Git에서 제외한 `artifacts/release-dev11/pytest.xml`과 `pytest.log`에 보관한다.
