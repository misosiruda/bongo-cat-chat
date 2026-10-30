# 노트북 dev19 자동 합성 연결 수정 — 2026-10-30

## 조사 기준

- `git fetch origin --prune --tags` 후 원격 main과 `v0.1.0.dev19`는 `9a1219f3e0423867efed7277c6b398ff7847e92c`였다. 최신 공개 릴리스도 dev19였다. 기존 로컬 main `68b9b85`와 작업 폴더를 보존하고 별도 `fix/laptop-auto-merge` worktree에서 수정했다. 최초 조사·로컬 검증 단계에서는 커밋·푸시·PR·공개 배포를 수행하지 않았다.
- 실제 실행 앱은 설치 폴더의 `versions/0.1.0.dev19/BongoCatChatApp/BongoCatChatApp.exe`였다. EXE FileVersion/ProductVersion 모두 dev19, 설치 표식 active=dev19 / previous=dev18, 업데이트 결과 applied=dev19였다. 과거 개발 EXE와 혼동한 상태가 아니다.
- 게임은 Steam 설치의 BongoCat.exe, Windows x64(PE machine 0x8664), build 25936063, 2026-10-30 09:57:19 KST 생성 프로세스였다. 게임을 종료·재시작하지 않았다.
- 집 PC의 비공개 자료를 복원하거나 복사하지 않았다. 노트북에는 조사 시작 시 사용자 프로필의 merge-bridge 세션 폴더가 없었다. 기존 시험 2회 ledger를 삭제·초기화·재사용하지 않았다.

## 수정 전 실제 실패

정식 설치본에서 사이드바와 자동 합성 패널 열기는 성공했다. **게임에 연결**을 누르면 `연결 확인 필요`와 `현재 게임 버전은 자동 합성 연결을 지원하지 않습니다. 호환되는 앱 업데이트가 필요합니다.`가 표시됐다. 그룹 선택·최대값·시작은 비활성 상태였다.

같은 설치본의 패키지 계약과 실제 게임 파일을 수정 전 검증 함수에 입력했을 때 안전한 오류 코드 `unsupported_game_build`가 재현됐다. 연결 전에 실패하여 세션·attach-attempt가 생성되지 않았다. 이전 세션의 source hash 누락이나 수동 합성 화면 때문에 발생한 실패가 아니다.

| 검사 | 결과 |
| --- | --- |
| Bridge.cs / MergePrepare.exe / Mono.Cecil.dll / contract.json | 모두 존재, 계약의 3개 자체 자산 해시 일치 |
| 지원 대상 게임 파일 12개 | 모두 존재, 11개는 dev19 계약과 동일 |
| 유일한 불일치 | BongoCat_Data/Managed/BongoAutoChest.dll |
| dev19 허용 해시 | `ed3d3a7f8ae702605ec91a0029ce78c766c424d52f207b47fc4f2bbf4a0b754a` |
| 노트북 실제 해시 | `8cc81f48322fd544b711291d67655a4f63cb0a88bf37b7e4c7f3f895e10f320e` |
| .NET Framework x64 C# 도구 | 존재, 이후 실제 로컬 메타데이터 컴파일 성공 |

게임 build 번호가 같아도 Auto Chest DLL의 전체 파일 해시가 다르면 거부하는 계약이 직접 원인이다. 기존 앱에는 파일 조합과 게임 버전을 구분하는 안내가 없었다.

## 추가 허용의 근거와 한계

- Assembly-CSharp.dll과 firstpass, Unity CoreModule, Heathen, Steamworks.NET, Newtonsoft, Mono, mscorlib/System/System.Core 및 EXE는 기존 계약과 바이트 단위로 동일하다.
- Mono.Cecil로 설치 게임과 해시가 확인된 로컬 원본 백업의 645개 타입·3,500개 메서드를 비교했다. 메서드 추가·삭제 없이 MainCat.Update와 ShopItem.Callback만 다르다. 합성 관련 ItemExchange, CatInventory, ExchangeSlot, SteamItemRuntime와 합성 코루틴·클로저는 이 변경 대상에 포함되지 않는다. 로컬 백업 비교이며 배포사의 원본 서명 검증은 아니다.
- ItemExchange의 슬롯·합성 중 상태·횟수·그룹·레시피 필드, GetDuplicateItems(Boolean), SlotDuplicates/SlotDuplicate, TryExchange, ExchangeRoutine 및 원본 결과 콜백 `<ExchangeRoutine>b__2`와 `items` 필드를 확인했다. 이 구조를 포함한 게임 어셈블리 전체가 기존 계약과 같다.
- 노트북 Auto Chest의 메타데이터와 멤버 참조를 확인했다. 합성 타입·선택·교환 API 참조가 없고, 상자 처리 및 그 상태 필드 조회를 사용한다. 임의 메서드 호출이나 어셈블리 로딩 참조가 없으며 native import는 GetAsyncKeyState다. 이 사실을 모든 Auto Chest 버전의 호환성으로 확대하지 않는다.
- 앱의 Bridge.cs는 dev19 배포본과 동일하다. 로컬 게임 메타데이터로 컴파일 후 Mono.Cecil 참조 검사, 별도 일회용 Mono 프로세스의 로딩·Install 성공을 확인했다. 이 별도 프로세스 검사는 실행 중인 게임의 합성 성공을 뜻하지 않는다.

## 수정

- 기존 12개 파일 검사를 유지하고 Auto Chest 한 파일에만 검증한 두 SHA-256을 허용한다. 다른 11개 파일은 기존 단일 해시를 유지한다. 누락·변조·목록 밖 해시를 허용하지 않는다. 순정 설치나 다른 build를 추가 지원한 변경이 아니다.
- 배포 계약 schema 3에서 명시적인 SHA-256 목록을 지원한다. 기존 schema 2의 단일 해시 계약도 읽는다. 빈 목록·잘못된 해시·불완전한 계약은 연결하지 않는다. 패키징 준비 및 개발 빌드/설치 도구도 동일한 허용 목록을 사용한다.
- 파일 조합 불일치 `unsupported_game_files`, 파일 누락 `merge_game_files_missing`, 읽기 실패 `merge_game_files_unreadable`를 구분한다. 한국어·영어 UI는 고정 안내만 표시하며 원본 오류·파일 경로를 전달하지 않는다.
- 연결·세션 재사용·프로세스 수명·source_sha256·attach-attempt·ledger 및 준비 실패 정리 정책은 변경하지 않는다. 원본 선택, 종류별 1개 보존, 보호 옵션, 매 요청 1회, 명시적 시작·상한·결과 확인 정책도 그대로다.

## 로컬 검증

소스의 실제 게임 연결, 패키지의 오프라인 검사, 후속 재개한 패키지 실게임 UI 검사를 구분한다.

- 실제 게임 조회는 `tools/probe_merge_readonly.py --connect-readonly --output <비공개 결과 폴더>`로 별도 offline 채팅 프로필의 실제 Qt 패널에서 먼저 확인했다. 이 도구는 `snapshot`/`group` 외의 명령을 코드에서 거부한다. 두 그룹 조회·최대값·동일 세션 재연결이 성공했고 명령은 group 2회, snapshot 1회였다. 캐릭터·모자·봉고 183회 / 이모티콘·UI 테마 194회, 즐겨찾기 포함 ON / 이벤트 제외 ON을 관찰했다. 재고 수량은 시점별 값이며 기존 집 PC 수량과 비교한 소비 계산이 아니다.
- 실제 snapshot은 manual merge visible=false, selected_units=0, exchanges=0, exchanging=false, spent=0, test_budget=0, pending/run 없음이었다. source_sha256과 현재 프로세스 수명이 일치했고 attach 결과 status=1 / stage=7 / managed_exception=false였다. authorization과 ledger는 아직 생성되지 않았다. 연결이 소비 권한을 부여하지 않는 상태다.

- Python/Qt 집중 회귀: `python -m pytest -q tests/test_merge_install.py tests/test_merge_connection.py tests/test_merge_bootstrap.py tests/test_merge_bridge.py tests/test_auto_merge.py tests/test_auto_merge_desktop.py tests/test_localization.py` → **123 passed**. 가짜 파일·IPC·Qt renderer와 C# 모의 게임 검사이며 실제 아이템 소비가 아니다.
- 테스트는 확인된 대체 해시 허용, 다른 파일 변경·미검증 해시 차단, 누락·읽기 실패 및 UI 시작 차단, 준비 실패 후 재연결과 증거 파일 보존을 포함한다. 기존 상한·중지·미확인 결과·재생 방지 회귀를 함께 실행했다.
- `node --check src/bongo_chat/ui/app.js`, `git diff --check` 통과.
- 기존 노트북 개발 환경을 사용한 첫 패키징은 필수 WinRT 5개 누락으로 배포 감사에서 실패했다. 같은 이유로 최초 설치/배포 테스트는 32 passed / 1 failed였다. 기존 환경은 보존하고 worktree의 별도 `.venv`에 프로젝트 지정 의존성을 설치했다. `pip check`는 통과했다. 초기 실패를 제품 연결 원인이나 통과 결과로 혼동하지 않는다.
- 새 환경의 pyproject 설치만으로는 간접 의존성 7개가 배포 잠금 버전과 달랐다. `pip install -r requirements-lock.txt`로 맞춘 뒤 의존성 감사의 누락/불일치 0개와 `pip check` 통과를 확인했다. 잠금 버전을 변경하거나 감사 규칙을 완화하지 않았다.
- 그 환경을 정리하기 전 빌드와 병렬로 실행한 검사에서 154 passed / 2 failed(라이선스 수집의 archspec 버전 불일치, 모의 파일 IPC 실행 1건)가 나왔다. IPC 검사는 단독 재실행에서 통과했다. 최종 검증은 잠금 환경에서 빌드와 분리해 실행한다. 이 일시 실패의 원인은 확정하지 않았으며 게임의 실제 교환 실패 근거가 아니다.
- 최종 잠금 환경에서 위 7개 집중 파일에 `tests/test_packaging.py tests/test_distribution.py`를 함께 지정한 검사: **156 passed in 83.45s, 실패·건너뜀 0**. 초기 실행 결과와 합산하지 않는다. 설치 테스트는 무해한 모의 실행 파일과 격리된 설치/데이터 폴더를 사용하며 사용자 정식 설치를 교체하지 않는다. Qt의 GPU 진단 메시지는 있었으나 테스트 실패 또는 renderer JavaScript 오류로 기록하지 않는다.
- 최종 `packaging/build.ps1 -AllowUnsigned -OutputRoot dist/laptop-merge-final` 성공. 파일 527개, 배포 감사 차단 항목 0개, 의존성 불일치 0개, 라이선스/대응 소스 고지 수집 성공. 배포물에 게임 바이너리가 포함되지 않았다.
- 최종 패키지의 schema 3 계약과 자체 자산 해시, 12개 로컬 게임 파일 검사, 패키지 Bridge.cs를 사용한 컴파일·메타데이터 참조 검사 성공. EXE는 공개 dev19와 다른 해시이며 로컬 검사용으로 버전 표기는 dev19를 유지한다. 기존 정식 설치를 덮어쓰지 않았다.
- 패키징된 BongoCatChatApp.exe의 격리된 `--offline --data-dir ... --smoke-report ...` 실행: exit 0, renderer=true, console_errors=[], steam_connected=false. 실제 게임 연결 검사가 아니다.
- 최초 패키지 UI 확인은 창 선택에서 물리 Escape 중단 신호를 받아 멈췄다. 당시 연결·그룹·최대값 검사는 미완료로 기록했다. 이후 사용자가 화면 조작 재개를 명시적으로 승인하여 아래 실제 패키지 UI 검증을 완료했다.
- 추가 실제 합성 시험 **0회**. 실제 게임에 begin/select/merge/TryExchange를 시험하지 않는다.

## 후속: 수정 EXE의 실제 화면 검증 완료

2026-10-30 사용자 재개 승인 후, `dist/laptop-merge-final/BongoCatChat/versions/0.1.0.dev19/BongoCatChatApp/BongoCatChatApp.exe`를 별도 비공개 데이터 폴더로 실행했다. Windows 창의 실행 경로를 기존 정식 설치본과 구분한 뒤 실제 마우스·키보드로 조작하고 접근성 트리의 상태를 확인했다. 소스 실행이나 모의 renderer로 대신한 검사가 아니다. 대화 원문·식별정보는 결과에 기록하지 않았다.

| 실제 EXE UI 검사 | 결과 |
| --- | --- |
| 연결 전 | 가능 횟수 확인 필요, 그룹/최대값/시작 비활성 |
| 게임에 연결 | 게임 연결됨. 기존 동일 소스 모듈의 세션 재사용 성공 |
| 이모티콘·UI 테마 조회·최대값 | 194회 표시, 최대값 버튼으로 194 입력, 시작 활성 표시 |
| 캐릭터·모자·봉고 조회·최대값 | 183회 표시, 최대값 버튼으로 183 입력, 시작 활성 표시 |
| 양방향 그룹 변경 | 변경 중 입력·시작 차단. 변경 후 이전 상한 초기화, 새 그룹 수량 표시, 상한을 다시 넣기 전 시작 차단 |
| 상한 비우기 / 0 / -1 / 1.5 | `합성 횟수는 1 이상의 정수로 입력해 주세요.` 표시, 시작 비활성 |
| 상한 1 | 예정 최대 1회 표시, 시작 활성. 버튼은 누르지 않음 |
| 다시 연결 | 게임 연결됨으로 복귀, 194회 재조회, 자동 시작 없음 |
| 보호 옵션 | 즐겨찾기 포함 ON / 이벤트 제외 ON 유지, 옵션 변경 없음 |

비어 있는 숫자 입력은 Windows 접근성 값에 0으로 나타난다. 실제 `Ctrl+A → Backspace`로 비운 동작과 명시적 0 입력을 각각 수행하고 차단 상태를 확인했다. 드롭다운은 방향키와 Tab으로 선택을 확정했으며 시작 버튼에는 입력하지 않았다.

실제 세션의 명령 순번은 검사 전 3에서 검사 후 7로 증가했다. 연결/재연결의 snapshot 2회, 양방향 그룹 변경의 group 2회에 해당한다. 최대값·상한 편집은 게임 명령을 추가하지 않았다. 최종 상태는 **spent=0, test_budget=0, confirmed_completed=0, selected_units=0, exchanges=0**, pending/run 없음, authorization/ledger 파일 없음이다. source_sha256과 09:57:19 KST에 시작한 동일 게임 수명이 일치한다. 수동 합성 화면은 닫힘, 교환 진행 없음이며 게임·기존 Auto Chest를 변경하거나 재시작하지 않았다.

검증 창은 상한을 비워 시작이 비활성인 상태로 남겼다. 앞서 생성한 숨김 시험 인스턴스만 정리했으며 기존 정식 설치본과 게임은 유지했다. 현재 실제 환경에서 만들지 않은 조건(수동 합성 화면 열림·직접 선택 재료·재고 소진·결과 미확인·실행 중 중지)은 앞선 모의 테스트 근거로만 남긴다. 실제 아이템을 선택하거나 소비해 차단을 유발하지 않았다.

## 변경 파일

| 파일 | 변경 |
| --- | --- |
| src/bongo_chat/merge_install.py | 제한된 해시 목록과 파일 누락/읽기 오류 구분 |
| src/bongo_chat/merge_connection.py | 고정된 안전한 오류 코드 전달 |
| src/bongo_chat/ui/app.js, translations.json | 한국어/영어 연결 오류 안내 |
| tools/merge_bridge/local-contract.json | 확인된 Auto Chest 해시 하나 추가, 다른 11개 유지 |
| tools/merge_bridge/prepare-assets.ps1 | 배포 계약 schema 3 생성 |
| tools/merge_bridge/build.ps1, install.py | 개발 도구의 동일 해시 목록 적용 |
| tests/test_merge_install.py, test_merge_connection.py | 제한 유지·오류·UI 차단 회귀 |
| docs/decisions.md, item-auto-merge.md, windows-app.md, 이 문서 | 근거·범위·검증 결과와 미완료 항목 |

## 남은 인수와 배포

수정 EXE의 실제 UI 연결·조회·그룹·최대값·유효/무효 상한 상태 검증은 완료했다. 현재 게임에는 앞선 소스 Qt 검사에서 설치한 동일 Bridge.cs의 소비 허용량 0 모듈이 있어 재연결 경로를 확인한 것이다. 세션을 삭제하지 않았다. 새 게임 수명에서 패키지가 최초 설치하는 경로의 인수는 별도다.

실제 합성 소비·보상·종류별 재고 전후 대조, 장시간·최소화·수동 조작 경쟁과 다른 설치 조합은 검증하지 않았다. 기존 집 PC의 2회 결과나 모의 게임 성공으로 대체하지 않는다. 다음 배포에는 변경 검토, 버전·릴리스 문서 갱신, 최종 패키지/설치/업데이트 서명 및 전환 검증이 필요하다. 기존 업데이트 키·피드와 사용자 데이터를 유지해야 한다.

사용자는 이 로컬 검증을 확인한 뒤 이번 연결 수정에 한해 커밋·푸시·PR 검수·머지와 공개 배포를 별도로 승인했다. 실제 아이템 소비 시험 금지는 계속 유지한다. 승인 자체를 병합·배포 완료나 최종 공개 자산 검증으로 기록하지 않는다.

### 배포 준비 중 최종 검사기 보완

공개 배포 경로를 검토하면서 `tools/verify_review_bundle.py`가 여전히 배포 계약 schema 2를 요구하는 누락을 확인했다. 앞서 만든 실제 로컬 묶음에 검사기를 실행해 `Packaged merge source differs from this checkout` 실패를 재현했다. 검사기를 schema 3으로 맞추고 패키지의 게임 파일 목록 전체를 소스 계약과 대조하도록 보완했다. 자체 소스·도구 해시 검사도 유지한다. 구 schema·누락 목록·대체 해시 누락·소스/도구 변경을 거부하는 모의 회귀 6개를 추가했다.

dev20 버전 준비 상태에서 잠금 환경의 전체 검사 `.venv/Scripts/python.exe -m pytest -q --junitxml=<비공개 결과>`는 **876 passed in 262.32s**였다. 위 최종 검사기 보완은 이 전체 실행의 수집 이후 추가했으므로 전체 통과에 포함된 것으로 세지 않는다. 보완 후 영향받은 `tests/test_distribution.py`를 별도로 실행해 **24 passed in 2.97s**를 확인했다. 전체 테스트 재실행으로 이 둘을 합산한 결과라고 표현하지 않는다.

보완된 검사기로 동일한 로컬 패키지를 다시 검사하여 계약/자체 자산/고지/WinRT/배포 감사 및 격리된 오프라인 renderer 검사가 통과했다. 이 패키지는 앞서 실게임 UI를 확인한 로컬 dev19 표기 묶음이며 최종 공개 dev20 파일의 검사와 구분한다.
