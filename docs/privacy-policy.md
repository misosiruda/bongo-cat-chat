# Privacy policy / 개인정보 처리 안내

기준: 2026-10-14, `0.1.0.dev6` 소스와 이번 서명 준비 변경. 독립 개발자가 유지하는 비공식 Bongo Cat 보조 프로그램이다. 문의는 [프로젝트 이슈](https://github.com/misosiruda/bongo-cat-chat/issues)를 사용한다. 공개 이슈에 대화 원문, 계정·로비 식별정보를 올리지 않는다.

## 로컬 기록과 게임 연동

앱이 실행 중 수신한 채팅과 앱에서 작성한 메시지, 초안, 표시 이름, Steam 계정 ID, 로비 ID 및 화면 설정을 이 PC에 저장한다. 기본 위치는 `%LOCALAPPDATA%/BongoCatChat/history.sqlite3`다. 평문 SQLite 파일이며 별도 암호화·클라우드 백업을 제공하지 않는다. 이 파일에 접근할 수 있는 사람이 내용을 읽을 수 있다.

계정별로 화면과 기록을 구분한다. 채팅·초안은 30일 보관 후 앱 실행 시 또는 실행 중 정리하며, 앱이 꺼져 있는 동안에는 정리 작업이 실행되지 않는다. 설정에서 선택한 로비나 현재 계정의 전체 기록을 확인 후 삭제할 수 있다. 삭제가 저장장치 수준의 복구 불가능성을 보장하지는 않는다. 앱 제거는 기록·설정을 보존한다. 기록도 삭제하려면 제거 전에 앱의 기록 삭제 기능을 사용한다.

기존 게임 로비와 연동하기 위해 로컬에 설치된 게임의 Steam API DLL을 로드하고, 호환성·현재 로비·외형·숨김 상태 등을 읽기 전용으로 조회한다. 설치된 게임 리소스에서 외형 이미지를 읽어 메모리에서 표시한다. 게임 파일 수정, DLL 주입, 메모리 쓰기 기능은 제품 범위에 포함하지 않는다. 프로그램을 실행하지 않은 동안의 대화를 복원하지 않는다.

사용자가 전송한 채팅은 Steam의 기존 로비 채팅으로 전달되어 해당 로비의 다른 참여자에게 보인다. Steam 서비스의 처리는 [Valve 개인정보 정책](https://store.steampowered.com/privacy_agreement/)을 따른다. 전송 접수는 상대방이 읽었다는 뜻이 아니다.

## 업데이트 통신

정상 설치본은 실행 약 15초 후, 실행 중 주기적으로, 게임 호환성 오류 또는 사용자의 업데이트 확인 요청 시 GitHub의 공개 릴리스 정보를 확인한다. 새 버전이 있으면 업데이트 파일을 내려받아 검증하고 다음 앱 실행 때 적용한다.

연결 대상은 `api.github.com`, `github.com`과 업데이트 자산 다운로드에 사용하는 GitHub 호스트다. 대화 원문, Steam 계정 ID, 로비 ID, 로컬 DB를 업데이트 서버에 보내지 않는다. 일반 HTTPS 요청으로 GitHub가 IP 주소, 요청 시각, User-Agent 등 연결 정보를 처리할 수 있다. [GitHub 개인정보 정책](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement)을 참고한다.

현재 설치 UI에는 자동 업데이트 통신만 끄는 선택지가 없다. `--offline` 실행은 업데이트와 실제 게임 연결을 함께 사용하지 않는 개발·검증 모드다. 독립적인 업데이트 거부 선택지로 안내하지 않는다. SignPath 신청 전 설치 중 개인정보 고지와 업데이트 통신 선택권에 대한 조건을 확인하고 필요한 UI를 반영해야 한다.

## 그 밖의 전송

현재 구현은 개발자에게 채팅을 업로드하는 서버, 클라우드 동기화, 광고·분석용 텔레메트리, 자동 오류 보고를 제공하지 않는다. 향후 데이터 처리나 연결 대상이 바뀌면 이 안내와 관련 사용자 제어를 함께 갱신한다.

## English summary for reviewers

Bongo Cat Chat stores received lobby messages, drafts, display names, Steam account/lobby identifiers and settings in a local, unencrypted SQLite database. Messages and drafts are retained for 30 days, with cleanup while the application is running. Users can delete the selected lobby's history or all history for the current account. Uninstallation preserves local data.

User-authored chat is sent through Steam lobby chat. The application reads local game state and installed resources without patching game files or writing to game memory. Installed copies automatically contact GitHub for update metadata and downloads; chat content and game identifiers are not included in these requests. GitHub may process ordinary connection metadata such as IP addresses. There is no developer-operated chat collection, telemetry or cloud-sync service. A dedicated installer option to disable update requests is not implemented yet; this limitation is disclosed for the SignPath review.
