# 두 Windows PC에서 번갈아 배포하기

2026-10-16: 두 PC에서 배포를 요청하고 승인·서명은 [별도 릴리스 저장소](https://github.com/misosiruda/bongo-cat-chat-release)에서 수행하는 경로를 도입한다. 최종 Release는 기존 `misosiruda/bongo-cat-chat`에 게시하므로 이미 설치된 앱의 저장소·공개키·manifest 형식을 바꾸지 않는다. Windows Authenticode/SignPath는 별개이며 현재 경로는 명시적으로 확인한 미서명 개발판이다.

## PC에서 할 일

1. 실제 작업 폴더, Git 루트, 변경 파일을 확인한다. 다른 PC의 작업을 강제로 덮거나 초기화하지 않는다.
2. 배포할 버전을 소스에 반영하고 PR 검토·필요한 검사를 완료한다. 현재 원격 main의 전체 SHA를 확인한다.
3. GitHub CLI 로그인 상태를 확인한 뒤 어느 PC에서든 아래 명령으로 배포 후보를 요청한다.

```powershell
./tools/request-release.ps1 -SourceSha <검토한-main의-40자리-SHA> -Version <새-버전> -AllowUnsignedWindows
```

브라우저의 [Request release candidate](https://github.com/misosiruda/bongo-cat-chat-release/actions/workflows/release.yml)에서도 같은 요청을 할 수 있다. 요청 시 main을 선택한다. 새 버전은 소스 버전과 일치하고 최신 공개 버전보다 높아야 한다.

## 승인과 게시

키 없는 Windows 실행기에서 테스트·빌드·오프라인 화면 검사를 수행한다. 별도 작업이 생성된 ZIP·설치 파일·대응 소스의 SHA-256을 계산한다. 소스 diff, 실행 결과와 파일 해시를 확인한 뒤 `release-signing`을 직접 승인한다. 앱 코드나 후보 EXE는 서명 작업에서 실행하지 않는다.

성공한 작업은 릴리스 저장소의 `approved-v<version>-<run-id>-<attempt>` prerelease에 서명된 결과를 둔다. 이 위치에 올리는 것만으로 기존 이용자의 앱이 업데이트되지는 않는다.

```powershell
# 서명·출처·전체 파일 해시 검증만 수행
./tools/request-release.ps1 -Action Publish -CandidateTag <approved-태그>

# 기존 앱 업데이트 피드에 실제 게시 요청
./tools/request-release.ps1 -Action Publish -CandidateTag <approved-태그> -Publish
```

실제 게시에는 앱 저장소의 `release-publishing` 승인이 필요하다. 게시기는 독립 도구의 고정 커밋을 사용하고 개인키를 받지 않는다. 승인 기록, 서명 작업의 성공과 source main 포함 여부, 모든 자산 해시를 재검사한다. 새 draft에 올린 파일도 다시 내려받아 검증한 뒤 일반 최신 Release로 공개한다. 기존 태그·자산을 덮어쓰지 않으며 실패한 draft/tag는 원인 확인 후 수동 처리한다.

게시기는 초안 생성 응답의 Release ID를 업로드·조회·공개까지 유지하고, 자산은 Asset ID로 다시 내려받는다. 공개 전 이름·ID·크기·업로드 상태와 기존 서명·해시를 검사하며, 공개 직전 자산 목록을 재확인한다. 공개 후 동일 Release ID가 최신 일반 릴리스로 조회되어야 성공한다. 이미 공개된 승인 후보만 태그 조회를 사용한다.

2026-10-16 dev12의 [게시 CI](https://github.com/misosiruda/bongo-cat-chat/actions/runs/38870480192)는 초안 생성 후 태그 조회 404로 중단됐고, [같은 초안을 별도로 검증·공개해 복구](https://github.com/misosiruda/bongo-cat-chat/releases/tag/v0.1.0.dev12)했다. 후속 게시 도구 수정은 [릴리스 저장소 PR #2](https://github.com/misosiruda/bongo-cat-chat-release/pull/2)에 있다. 앱 워크플로의 검증·게시 작업은 모두 해당 수정 커밋 `819c8a6c5c68dcf248d8b44aa8e4b6adaf4a6413`을 사용한다. 릴리스 도구 PR을 검토·병합한 뒤 이 워크플로 변경을 병합한다. 두 저장소의 변경을 병합하는 것만으로 새 릴리스가 게시되지는 않는다.

실패 시 로그의 Release ID와 최신 릴리스 상태를 먼저 확인한다. 공개 요청 뒤 응답·최신 조회가 실패했다면 이미 공개됐을 수 있다. 초안·태그를 자동 삭제하거나 기존 버전을 재실행하지 않는다. 고정 커밋을 이전 버전으로 되돌리면 태그 조회 결함도 돌아오며 이미 생성된 외부 자산은 복구되지 않는다. 합성 회귀 테스트는 실제 GitHub 업로드·공개와 설치 앱 업데이트의 인수를 대신하지 않는다.

두 PC가 같은 버전을 동시에 요청하지 않는다. 서버 작업은 같은 배포 흐름을 직렬화하며 이미 공개된 버전의 재게시·다운그레이드를 거부한다. 로컬 GitHub 인증은 요청용이며 별도 저장소 간 장기 게시 토큰을 새로 공유하지 않는다.

## 기존 키와 호환성

기존 `src/bongo_chat/update-config.json`의 공개키, 기존 Ed25519 개인키, manifest schema 1, data schema 1, bootstrap schema 1을 유지한다. 추가된 승인 기록은 게시 과정의 검증 자료이며 기존 클라이언트의 업데이트 규약을 변경하지 않는다.

2026-10-15에 두 PC에 동일 키를 각 사용자 DPAPI로 보관했던 이력은 유지한다. 새 환경의 키 검증은 이미 공개된 dev11 manifest에 다시 서명하고 공개 서명과 바이트 단위로 대조하는 방식이다. 이 검증은 새 제품 릴리스를 게시하지 않는다.

클라우드 키 검증과 독립 복구용 백업 확인 전에는 두 PC의 키를 삭제하지 않는다. 양쪽 개발 계정에 남은 키 사본을 모두 제거한 뒤에만 로컬 키 접근까지 분리 완료로 기록한다. 원래 `tools/release.py pack`은 전환 중 복구 경로이며 새 운영 배포 요청에는 사용하지 않는다. DPAPI 파일만 복사한 것을 다른 PC·계정에서도 쓸 수 있는 백업으로 간주하지 않는다.

## 검증 범위와 한계

- 독립 서명 도구: 기존 공개 dev11 서명, 합성 파일 변조·키 불일치·출처·버전·실행 attempt·체크섬 검사
- 패키징 도구: 기존 ZIP 경로와 manifest 형식의 합성 호환성 검사
- 실제 서명 환경·승인·게시 워크플로 실행 결과와 키 사본 회수는 별도로 확인한다.
- 2026-10-16 [클라우드 키 검증 실행](https://github.com/misosiruda/bongo-cat-chat-release/actions/runs/38862746955)은 사용자의 실제 Environment 승인 후 성공했다. 기존 공개 dev11 manifest SHA-256 `e175e8fc0328479b0429ed5f580fede19fe862d47afacf2c52640c3adb77889d`의 서명과 완전히 일치했고 새 릴리스를 게시하지 않았다. 독립 복구 백업은 사용자가 확인하지 못한 상태이므로 로컬 키 사본은 보존한다.
- 단독 운영자의 수동 승인은 두 사람의 독립 검토가 아니다. GitHub 관리자 계정·서명 도구 침해와 악성 변경 오승인은 잔여 위험이다.
- 실제 게임·순정 환경·다른 PC·장시간 실행·Windows 게시자 신뢰 검증을 대신하지 않는다.

보호 설정, 키 이전 도구와 복구 절차는 [릴리스 저장소 설명](https://github.com/misosiruda/bongo-cat-chat-release#기존-키-이전과-복구)을 따른다.
