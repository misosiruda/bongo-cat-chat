# #58 게임 의존성 검사와 복구 안내

2026-11-09. 공개 dev29 / `87f347b1ac8b0167dbac6c04ee7cb4b8dfe480c4` 기준.

## 관측과 사용자 확인

[#58](https://github.com/misosiruda/bongo-cat-chat/issues/58)은 새 연결에서 `status=2`, `stage=7`, `initialization_step=read_session`, `System.InvalidOperationException → System.TypeLoadException`을 보고했다. 사용자는 해당 이용자가 Bongo Cat을 재설치한 직후 연결이 해결됐다고 확인했다. 이는 사용자 PC의 복구 확인이며, 우리가 해당 PC의 설치 전후 파일을 직접 비교한 증거는 아니다. 특정 DLL의 실제 누락·손상 여부나 기존 Auto Chest의 책임은 확정하지 않는다.

현재 PC의 게임 build 26431657, Steam depot 3419431 / manifest 1889994575812027590에는 `BongoCat_Data/Managed/System.Numerics.dll`이 기본 배포 파일로 들어 있다. 설치 파일의 크기 39,424바이트와 SHA-1 `855c87cde64b128861f4fc5e038e2ceaf92f6bb2`가 이 배포 명세와 일치한다. 지원 SHA-256은 `d59c65c3e029b0af41e4d2bec1f96830fc2db4da95c893a6506179e6179fa7c5`다. 게임 파일은 커밋·배포하지 않는다.

게임 파일의 별도 복사본과 자체 Mono 테스트 프로세스에서 정상 초기화 → 이 DLL만 제외하면 #58과 같은 단계·예외 조합 → 파일 복원 후 정상 초기화를 확인했다. JSON 값 읽기에서 쓰는 간접 의존성을 기존 사전 검사가 빠뜨린 점은 재현됐다. 이 실험은 제보 PC에서 누락된 파일을 특정한 것은 아니다.

## dev30 변경

- `System.Numerics.dll`을 필수 관리 의존성에 포함한다. 계약이 이 파일을 빠뜨리거나 선택 사항으로 바꿀 수 없게 검사한다. 해시·메타데이터 식별·검사 전후 변경 확인·컴파일 전후 검증에 함께 포함한다.
- 누락은 `bridge_dependency_missing`, 읽기 실패는 `bridge_dependency_unreadable`, 다른 검증 입력이 일치하지만 이 파일이 지원 목록과 다르면 `bridge_dependency_incompatible`로 게임 프로세스를 열기 전에 차단한다. 지원 목록 불일치를 곧바로 파일 손상으로 단정하지 않는다.
- 초기화 중 타입·메서드·필드 로드 또는 어셈블리 로드 실패가 확인되면 `bridge_dependency_load_failed`로 안내한다. 특정 DLL 이름을 추측하지 않는다. 설정 파일 자체가 없을 수도 있는 `FileNotFoundException`은 이 분류에 넣지 않는다.
- 새 연결과 기존 실패 기록 모두 같은 분류를 쓴다. 실패한 모듈 재로드, 기록·ledger 삭제, 소비 요청 재전송은 추가하지 않는다. 게임·기존 설치·도우미 설정을 앱이 자동 복구하거나 바꾸지 않는다.
- 한국어·영어 상자/합성 화면에서 정확한 오류와 사용자 조치를 표시한다. 필요한 경우 진행 중 결과 확인 → 게임 종료 → Steam의 파일 무결성 확인 → 다시 실행 순서로 안내한다. 로드 실패가 계속되면 게임 재설치와 버그 제보를 안내한다.

파일 복구 메뉴는 [Steam 공식 무결성 확인 안내](https://help.steampowered.com/en/faqs/view/0C48-FCBD-DA71-93EB)를 따른다. 무결성 확인·재설치는 게임 파일을 복구하므로 기존 모드/도우미의 패치에도 영향을 줄 수 있다. 사용자가 진행하며 앱이 실행하지 않는다. 버그 제보는 앱 종료 전에 수행하고, 공개 본문에는 기존 허용 목록의 오류·단계·예외 종류만 포함한다.

## 검증 범위

합성 설치에서 누락·변경·읽기 거부를 주입해 프로세스 열기·컴파일·모듈 연결 이전에 차단됨을 검사한다. 반복 연결에도 기존 ledger와 실패 기록을 보존하고, 파일을 복구한 합성 설치는 검증을 통과한다. 새 연결과 기존 실패 기록의 타입 로드 분류, 별도 일반 초기화 오류, 한국어·영어 양쪽 자동화 화면과 제보 오류 코드도 검사한다.

실제 지원 게임의 복사본에서도 사전 검사 결과가 누락 → `bridge_dependency_missing`, 변조 → `bridge_dependency_incompatible`, 복원 → 정상으로 나뉜다. 현재 설치의 파일은 읽기만 했다. 실행 중 게임 연결·파일 변경·재시작·실제 소비는 수행하지 않는다. 상세 결과는 [제품 검증 기록](product-validation.md), 로컬 원본은 Git에서 제외한 `artifacts/issue58/`에 보존한다.
