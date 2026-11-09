# #56 초기화 예외 조사와 진단 보완

2026-11-09. 비교 기준은 공개 dev28 / `fb21be6092940e02f5e05f41a5c38f3dceb54870`이다.

## 확인된 범위

2026-11-09 후속: dev29의 [#58](https://github.com/misosiruda/bongo-cat-chat/issues/58)에서 `read_session/TypeLoadException`으로 범위가 좁혀졌고, 사용자는 제보자의 게임 재설치 직후 연결 복구를 확인했다. 특정 파일이 실제로 누락됐다는 직접 증거와는 구분한다. dev30 사전 검사와 안내 보완은 [후속 기록](issue-58-dependencies.md)을 따른다. 아래 미확정 설명은 dev29 조사 당시의 기록이다.

[#56](https://github.com/misosiruda/bongo-cat-chat/issues/56)은 새 연결에서 `status=2`, `stage=7`, `managed_exception=true`, `load_error=0`을 보고했다. 이는 Mono가 `Install` 호출 과정에서 관리 예외를 반환했다는 의미다. 이후 `source=existing` 시도는 기존 실패 기록과 응답을 확인했으며 모듈을 재로드한 기록이 아니다. 게임 화면의 단순 응답 지연으로 분류하지 않는다. 기존 Auto Chest 설치 이력이 있다는 후속 사용자 설명은 있지만, 그것이 원인이라는 증거는 없다.

해당 PC의 예외 종류와 세부 단계는 dev28 기록에 없으므로 복원할 수 없다. 현재 PC의 검증된 게임 메타데이터·Mono를 별도 프로세스에서 사용한 초기화는 통과했고, 한글·공백·이모지 경로에서도 실패를 재현하지 못했다. 이것은 제보자 PC의 원인 해결이나 실제 게임 인수가 아니다.

## 변경

- 관리 예외가 확인된 초기화 실패는 `bridge_initialization_failed`로 표시하고 앱을 닫기 전 버그 제보를 안내한다. 기존 dev28 기록도 같은 오류로 분류한다. 미확인 로드/실행 결과와 응답 지연은 기존 별도 분류를 유지한다.
- `Install`은 호출 진입과 설정 읽기·설정 검증·어셈블리 확인·ledger 읽기·게임 필드 연결·메인 루프 연결·콜백 등록을 고정 코드로 표시한다. 본문 진입 전 의존성 해석 실패를 설정 읽기 실패로 표시하지 않는다. 예외를 숨기거나 성공으로 바꾸지 않는다.
- 콜백 등록이 실패했는데 `installed=true`가 남을 수 있던 순서를 고친다. 실제 등록 성공 뒤에만 완료 상태가 된다. 합성 가짜 게임에서 등록 실패를 주입해 완료 표시가 남지 않음을 검사한다. 이 결함이 #56의 원인으로 확인됐다는 뜻은 아니다.
- 부트스트랩은 예외가 있을 때만 Mono 메타데이터/필드 접근자로 최대 세 단계의 예외 종류와 고정된 실패 코드를 분류한다. 예외의 `ToString`, 속성 getter나 추가 관리 메서드를 호출하지 않는다. 예외와 메시지는 검사 동안만 고정하고 핸들을 해제한 뒤 스레드를 분리한다.
- `System.Exception`의 원래 필드를 조회해 사용자 정의 예외가 같은 이름의 다른 타입 필드를 숨기는 경우도 피한다. 타입 이름은 허용 목록만 남기며 알 수 없는 이름은 `other`가 된다. 메시지는 95 UTF-16 코드 단위 이하만 내부 비교하고, 정확히 일치하는 자체 고정 코드만 결과에 남긴다. 임의 메시지·경로·스택·메모리 주소는 진단 결과·파일·제보에 추가하지 않는다.
- 제한된 결과를 기존 `attach-result.json`에 함께 보존해 수동 재연결 때 진단이 사라지지 않게 한다. 기존 기록·ledger 삭제, 실패한 모듈 재로드, 소비 재시도는 추가하지 않는다. 진단 스냅샷의 예외 목록도 복사해 호출자의 변경이 원본에 영향을 주지 않는다.

Mono API의 의미는 [공식 embedding 설명](https://www.mono-project.com/docs/advanced/embedding/), [공식 공개 헤더](https://github.com/mono/mono/blob/main/mono/metadata/object.h), [필드 조회 구현](https://github.com/mono/mono/blob/main/mono/metadata/class.c)을 참고하고 지원 게임의 실제 네이티브 export·명령어와 별도 프로세스 실행으로 대조했다. 64비트 핸들은 `mono_gchandle_new_v2` / `mono_gchandle_free_v2`를 사용한다. 개발 중 구형 32비트 해제 API를 쓴 격리 시험이 접근 위반으로 실패해 수정했으며, 이를 통과한 검사로 세지 않는다. 모의 핸들도 32비트를 넘는 값으로 검사한다.

## 검증과 다음 확인

초기 집중 검사 `pytest -q tests/test_bug_report.py tests/test_merge_connection.py tests/test_merge_install.py tests/test_merge_bootstrap.py tests/test_localization.py`는 **165 passed / 73.14초**, 실패·생략 0개였다. 네이티브 ABI, bounded 예외 체인/순환/빈 핸들/알 수 없는 타입/긴 메시지, 개인정보 제외, 7,500자 URL 제한, 이전 기록 재사용, 한국어·영어 실제 오프라인 Qt 안내, 합성 C# 연결 모듈을 포함한다. 후속 버전/문서·배포 검사 결과는 제품 검증 기록에서 구분한다.

현재 지원 게임의 메타데이터로 자체 모듈을 컴파일하고 경량 런타임의 모든 참조를 확인했다. 게임 Mono를 로드한 **별도 Python 프로세스 자신의 PID만** 대상으로 정상 초기화, 프로세스 식별 불일치, 어셈블리 식별 불일치, 설정 파일 누락을 확인했다. 세 실패는 각각 `validate_session/process_mismatch`, `verify_assemblies/automation_files_changed`, `read_session/System.IO.FileNotFoundException`으로 구분됐다. 실제 게임에 연결하거나 상자·합성·포인트를 소비하지 않았다. 로컬 근거는 Git에서 제외한 `artifacts/issue56/`에 보존한다.

새 진단은 실행 중인 옛 모듈에 소급되지 않는다. 업데이트 뒤 사용자가 진행 중인 결과를 먼저 확인하고 게임·앱을 한 번 완전히 종료한 새 연결에서 수집한다. 재발하면 앱 종료 전에 버그 제보로 새 단계·예외 분류를 전달한다. 그 결과로 #56의 원인을 확인하기 전에는 이슈를 해결 완료로 닫지 않는다.
