# 채팅 알림 기술 검증

검증일: 2026-10-16 / Asia/Seoul. 최초 Windows 실행의 소스 기준: `9bdd0ba`. 출하 준비는 최신 main `f587a30` 위에서 수행했다.

## 결론

요청한 세 기능은 현재 Python/Qt 구조에서 구현 가능하다. 작업 표시줄 깜빡임과 Windows 배너는 가상 수신을 사용한 Windows 시험 및 사용자 확인을 받았다. 독립 ON/OFF와 재실행 후 설정 유지도 확인했다. **제품 수신 경로·설정 화면·설치본에는 아직 반영하지 않았다.**

제품 구현은 [이슈 #24: 새 채팅의 작업 표시줄·Windows 알림과 개별 설정 구현](https://github.com/misosiruda/bongo-cat-chat/issues/24)에서 진행한다. 연결 지점·설정 계약·오류와 종료 경계·설치 등록·자동 및 Windows 인수 조건을 포함한다. 이 검증 문서의 출하만으로 구현 이슈를 닫지 않는다.

| 요구사항 | 결과 | 확인 수준 |
| --- | --- | --- |
| 다른 창을 사용하는 동안 새 채팅이 오면 작업 표시줄 깜빡임 | 가능. `QApplication.alert` 사용 | 최소화 상태에서 Windows 배너를 끈 단독 시험을 사용자 확인. 두 기능을 켠 시험도 사용자 확인 |
| Windows 기본 알림 | 가능. Qt 트레이 배너와 WinRT 토스트 경로를 각각 시험 | Qt 배너는 사용자 확인. 별도 WinRT 토스트는 발송 프로세스 종료 후에도 Windows 알림 기록에 시험 알림 1건이 남는 것을 API로 확인 |
| 알림 ON/OFF 설정 | 가능. 각각 별도 boolean으로 저장 | 네 가지 조합·포커스 조건 테스트, 실제 체크박스 조작, 둘 다 OFF로 저장한 뒤 GUI 재실행 확인 |

여기서 Windows 기본 알림은 배너·알림 센터 기능을 뜻한다. 시계 앱의 예약 알람이나 반복 경보는 검증 범위에 포함하지 않았다. 소리의 실제 재생은 확인하지 않았다.

## 환경과 격리

- Windows 11 `10.0.26300`, Python `3.13.3`, PySide6/Qt `6.12.0`
- 저장소의 `main`은 시작 시 깨끗했고 `.cursor/rules/`는 없었음
- Qt 시험은 `tools/probe_notifications.py`, WinRT 시험은 `tools/probe_windows_toast.ps1` 사용
- 기존 `ChatService`와 `Store`에 가상 계정·로비·메시지를 넣은 별도 SQLite만 사용
- Steam 작업자를 시작하거나 실사용 로비로 메시지를 보내지 않음
- 실행 중인 제품 앱, 실제 기록, 게임 설정 및 Windows 알림 설정을 변경하지 않음
- WinRT 시험은 전용 AUMID `BongoCatChat.NotificationProbe.20261016`와 임시 시작 메뉴 바로가기를 사용. 시험 후 자기 알림 기록과 동일 해시의 자기 바로가기만 정리

## 기능별 근거

### 작업 표시줄

Qt의 `QApplication.alert(window, 0)`는 비활성 창의 작업 표시줄 항목에 주의를 요청한다. 사용자에게 포커스를 강제로 옮기지 않는다. 다시 활성화하거나 해당 옵션을 끄면 시험 도구는 `FlashWindowEx`의 `FLASHW_STOP`으로 표시를 해제한다. `FlashWindowEx` 반환값은 이전 캡션 활성 상태이므로 성공 여부로 해석하지 않는다.

실제 시험 로그:

| 조건 | flash 호출 | Qt 배너 호출 | 포커스 유지 |
| --- | --- | --- | --- |
| 창 활성, 두 기능 ON | 아니오 | 아니오 | 확인 |
| 최소화, 두 기능 ON | 예 | 예 | 확인 |
| 최소화, 두 기능 OFF | 아니오 | 아니오 | 확인 |
| 다른 프로그램 활성, Windows 배너만 ON | 아니오 | 예 | 확인 |
| 최소화, 깜빡임만 ON | 예 | 아니오 | 확인 및 사용자 육안 확인 |

사용자는 처음 깜빡임만 켰을 때 변화가 없다고 보고했다. 해당 실행 기록은 `foreground=true`여서 알림 억제가 적용된 경우였다. 최소화 조건으로 다시 시험한 기록은 `foreground=false`, `flash=true`, `toast=false`였고 사용자가 단독 깜빡임을 확인했다. 따라서 현재 확보한 근거에서 두 알림이 서로 의존한다는 결함은 재현되지 않았다.

### Windows 기본 알림: 두 경로의 차이

Qt `QSystemTrayIcon.showMessage`는 Windows에서 내부적으로 `Shell_NotifyIcon(NIM_MODIFY)`를 호출한다. 이 배너는 사용자에게 실제 보였지만 **Windows 11 알림 센터 보관 요구까지 이 API만으로 충족한다고 볼 수 없다.** Microsoft 문서는 Windows 11에서 이 방식의 배너가 사라지면 알림 센터에 남지 않는다고 명시한다.

알림 센터에 남기는 기능을 위해 별도로 다음 WinRT 경로를 시험했다.

1. 시험 전용 시작 메뉴 바로가기에 `System.AppUserModel.ID` 지정
2. `ToastNotificationManager.CreateToastNotifier(시험 AUMID)` 호출
3. 고정된 가상 문장으로 `ToastGeneric` 알림 1건 발송
4. `notifier.Setting=Enabled`, `History.GetHistory(AUMID)`의 시험 tag/group 1건 확인
5. 발송 프로세스 종료 후 별도 PowerShell 프로세스로 재조회하여 1건 유지 확인
6. 시험 전용 기록·바로가기 정리 확인

WinRT 배너의 별도 육안 확인, 실제 알림음, 클릭으로 앱 복귀·특정 로비 이동은 이번 시험에서 확정하지 않았다. Qt 시험 창의 알림 클릭 핸들러는 준비했지만 클릭 인수는 수행하지 않았다. 사용자에게 확인받은 배너는 두 옵션을 켠 Qt 시험이다.

제품에 알림 센터 보관을 포함한다면 **Windows 토스트 경로를 선택**한다. Qt 트레이 배너를 함께 발송해 중복 알림을 만들지 않는다. 본 PowerShell 파일은 검증 도구이며, 제품에서 메시지마다 PowerShell을 실행하는 구조를 권장하는 것은 아니다. 제품의 Python WinRT 바인딩 또는 작은 네이티브 어댑터와 패키징 방법은 구현 단계에서 선택·검증해야 한다.

### 설정과 수신 필터

시험은 기존 SQLite `settings` 테이블에 `probe_notification_flash`, `probe_notification_toast`를 독립 저장했다. 시험 기본값은 둘 다 ON이며 제품 기본값 결정이 아니다.

제품 적용 지점은 다음과 같다.

- `service.py`의 `ChatService.receive`: 실제로 수락한 새 상대 메시지를 명시적인 반환값/이벤트로 전달
- `desktop.py`의 `Controller.poll`: 위 결과를 받아 GUI 스레드에서 포커스·최신 설정을 확인하고 알림 어댑터 호출
- `Controller.dispatch`의 setting 허용 목록: 새 boolean 키와 엄격한 타입 검사 추가
- `ChatService.view`와 `ui/index.html`, `ui/app.js`: 설정값 전달 및 두 스위치 표시
- Windows 설치/업데이트/제거: 고정 제품 AUMID, 시작 메뉴 등록, 앱 아이콘, 제거 시 자기 알림 정리

현재 `receive`는 결과를 반환하지 않아 시험 도구는 **동기 호출 직전/직후 revision 변화**로 수락 여부를 관찰했다. 이는 시험용 연결이며 제품 알림 인터페이스로 채택하지 않는다.

알림은 숨김·미확인 상대·중복 콜백·자동 고양이 문구·이전 로비·오래된 연결을 걸러낸 뒤 실행해야 한다. 자기 메시지·자기 에코와 기록 조회/검색/화면 재렌더링도 새 상대 수신 알림의 근거로 쓰지 않는다. 포커스는 채팅 입력칸의 DOM focus가 아닌 Qt 애플리케이션 활성 상태를 사용해 앱 내 설정창 등도 고려한다.

알림 센터에 대화 내용을 기록하면 게임에서 사용자를 숨긴 뒤에도 OS에 본문이 남을 수 있다. 첫 제품 구현에서는 일반적인 새 메시지 안내만 표시하는 방향을 제안한다. 발신자·본문 미리보기를 넣으려면 기존 숨김 정책, 해당 알림 삭제, 개인정보 설명을 함께 설계해야 한다. 기본값·미리보기·연속 수신 묶기는 아직 확정하지 않았다.

## 실행한 검증과 재현

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_notification_probe.py -q
# 23 passed

.\.venv\Scripts\pythonw.exe tools/probe_notifications.py --data artifacts/notification-probe-20261016

powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -File tools/probe_windows_toast.ps1 -Action Show -EvidenceDirectory artifacts/notification-probe-20261016/winrt
powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -File tools/probe_windows_toast.ps1 -Action Inspect -EvidenceDirectory artifacts/notification-probe-20261016/winrt
powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -File tools/probe_windows_toast.ps1 -Action Cleanup -EvidenceDirectory artifacts/notification-probe-20261016/winrt

git diff --check
```

네이티브 시험은 실제 알림을 띄운다. `Show`는 같은 시험 등록이 있으면 중단하며 `Cleanup` 후 재실행한다. 시험 폴더를 제품 데이터 폴더로 지정하지 않는다. Qt GUI의 체크박스는 Qt 배너를 제어하고, 별도 WinRT PowerShell 시험은 그 스위치와 연결되어 있지 않다.

23개 테스트는 포커스 × 네 가지 설정 조합 8건, 필터 제외 8건, 설정 재열기 4건, 잘못된 키·타입 거부 3건이다. Windows 표시를 자동 테스트 통과로 주장하지 않는다.

출하 준비에서는 main `f587a30` 위에서 다음 집중 검사를 추가 실행했다. 알림 정책과 기존 서비스·자동 울음 필터의 회귀 검사이며 제품 알림 통합 인수는 아니다. 로컬 제품 전체 테스트·설치본 빌드·릴리스는 실행하지 않았다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_notification_probe.py tests/test_core.py tests/test_meow_filter.py -q
# 136 passed
```

PowerShell AST 파서로 `tools/probe_windows_toast.ps1`의 구문 오류가 없음을 확인했다. 출하 검수 중 Qt 시험 체크박스의 저장 실패 복구가 실패한 DB를 다시 읽지 않도록 수정했다. 이 실패 경로의 실제 GUI 인수는 별도로 수행하지 않았다.

검증 결과는 [식별정보 없는 요약](evidence/2026-10-16-notification-validation.json)에 저장한다. 원본 시험 이벤트는 Git 제외 경로 `artifacts/notification-probe-20261016/`에 보관한다.

## 남은 제품 인수

- 실제 새 채팅 수신 → 필터 → 포커스 → 각 스위치 → 알림까지 연결한 통합 검증
- 설치 EXE의 이름·아이콘·고정 AUMID, 업데이트 후 동일 정체성 유지
- 알림 클릭 시 실행 중 창 복귀, 이미 종료된 앱 처리, 오래된 로비 처리
- Windows 알림 OFF·방해 금지·전체 화면 게임·작업 표시줄 깜빡임 비활성 환경
- Windows 10 및 다른 PC, 모달·다중 모니터·사용자 세션 전환
- 연속 수신의 알림 빈도·묶기, 설정 저장 실패 시 UI 복구

Windows 정책으로 배너·소리가 제한될 수 있다. 앱 스위치 ON을 OS의 실제 표시 보장으로 안내하지 않는다. 앱을 종료한 동안 새 메시지를 수신하는 기능은 추가하지 않았다.

## 공식 근거

- [Qt QApplication.alert](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QApplication.html): 비활성 창 알림과 Windows 작업 표시줄 동작
- [Qt QSystemTrayIcon](https://doc.qt.io/qt-6/qsystemtrayicon.html): 시스템 설정에 따른 표시 제한과 메시지 클릭
- [Qt 6.12 Windows 트레이 구현](https://raw.githubusercontent.com/qt/qtbase/v6.12.0/src/plugins/platforms/windows/qwindowssystemtrayicon.cpp): `Shell_NotifyIcon` 호출 확인
- [Microsoft Shell_NotifyIconW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shell_notifyiconw): Windows 10/11의 배너·알림 센터 동작 차이
- [Microsoft AppUserModelID로 데스크톱 토스트 활성화](https://learn.microsoft.com/en-us/windows/win32/shell/enable-desktop-toast-with-appusermodelid): 시작 메뉴 바로가기의 앱 ID 등록
- [Microsoft FlashWindowEx](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-flashwindowex): 창 활성화와 구분되는 알림 및 반환값 의미
