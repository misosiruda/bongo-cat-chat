# -*- coding: utf-8 -*-
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "nsDialogs.nsh"
!include "FileFunc.nsh"
Var UpdateCheckbox
Var UpdatePermission
!ifndef APP_ID
  !define APP_ID "BongoCatChat"
!endif
!ifndef APP_NAME
  !define APP_NAME "Bongo Cat Chat"
!endif
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
Name "${APP_NAME}"
BrandingText "Bongo Cat Chat"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP_ID}"
RequestExecutionLevel user
!ifdef SIGNING_ENABLED
  ; Sign the generated uninstaller before NSIS embeds it in Setup.exe.
  ; The config stays in the parent process environment, outside the command string.
  !uninstfinalize '"$%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "packaging\sign-file.ps1" -Path "%1"' = 0
!endif
ManifestDPIAware true
SetCompressor /SOLID zlib
ShowInstDetails nevershow
ShowUninstDetails nevershow
VIProductVersion "${NUMERIC_VERSION}"
VIAddVersionKey /LANG=1042 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=1042 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1042 "FileDescription" "${APP_NAME} 설치"
VIAddVersionKey /LANG=1042 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1042 "LegalCopyright" ""
!define MUI_ABORTWARNING
!define MUI_ICON "${APP_ICON}"
!define MUI_UNICON "${APP_ICON}"
!define MUI_WELCOMEPAGE_TITLE "${APP_NAME} 설치"
!define MUI_WELCOMEPAGE_TEXT "Bongo Cat의 로비 채팅을 별도 창에서 읽고 입력하는 메신저입니다.$\r$\n$\r$\n현재 Windows 사용자에게 설치합니다. Python이나 개발 도구를 따로 준비할 필요가 없습니다.$\r$\n$\r$\n실행 중인 Bongo Cat Chat을 닫은 뒤 계속하세요. 기존 대화 기록과 설정은 유지됩니다.$\r$\n$\r$\n버전 ${APP_VERSION} · 개발판"
!define MUI_DIRECTORYPAGE_TEXT_TOP "설치할 폴더를 선택하세요. 기존 버전이 있으면 같은 폴더에 설치합니다."
!insertmacro MUI_PAGE_WELCOME
!define MUI_PAGE_HEADER_TEXT "개인정보 처리 안내"
!define MUI_PAGE_HEADER_SUBTEXT "저장되는 정보와 연결 대상을 확인하세요."
!define MUI_LICENSEPAGE_TEXT_TOP "로컬 기록, Steam 채팅 및 GitHub 업데이트 통신 안내입니다."
!define MUI_LICENSEPAGE_TEXT_BOTTOM "다음 페이지에서 GitHub 업데이트 통신 사용 여부를 선택할 수 있습니다."
!define MUI_LICENSEPAGE_BUTTON "다음 >"
!insertmacro MUI_PAGE_LICENSE "${PRIVACY_FILE}"
Page custom UpdateOptions UpdateOptionsLeave
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DirectoryLeave
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "설치가 완료되었습니다"
!define MUI_FINISHPAGE_TEXT "시작 메뉴에서 ${APP_NAME}을 실행하세요.$\r$\n$\r$\nSteam과 Bongo Cat을 실행하고 게임 로비에 참여하면 앱에서 연결 상태를 확인할 수 있습니다.$\r$\n$\r$\n업데이트 통신과 개인정보 안내는 앱 설정에서 다시 확인할 수 있습니다."
!insertmacro MUI_PAGE_FINISH
!define MUI_UNCONFIRMPAGE_TEXT_TOP "앱을 제거합니다. 대화 기록과 설정은 이 PC에 남습니다.$\r$\n$\r$\n기록도 지우려면 제거 전에 앱의 기록 삭제 기능을 사용하세요."
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "앱을 제거했습니다"
!define MUI_FINISHPAGE_TEXT "대화 기록과 설정은 보존되었습니다."
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "Korean"

Function .onInit
  SetShellVarContext current
  SetRegView 64
  ClearErrors
  ReadRegDWORD $UpdatePermission HKCU "Software\${APP_ID}" "AllowUpdateChecks"
  ${If} ${Errors}
    StrCpy $UpdatePermission 1
  ${EndIf}
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/UPDATECHECKS=" $1
  ${IfNot} ${Errors}
    ${If} $1 != "0"
    ${AndIf} $1 != "1"
      SetErrorLevel 10
      Quit
    ${EndIf}
    StrCpy $UpdatePermission $1
  ${EndIf}
  ${IfNot} ${RunningX64}
  ${OrIfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "Windows 10 이상, 64비트 PC가 필요합니다." /SD IDOK
    SetErrorLevel 10
    Quit
  ${EndIf}
  ReadRegStr $0 HKCU "${UNINSTALL_KEY}" "InstallLocation"
  ${If} $0 != ""
    StrCpy $INSTDIR $0
  ${EndIf}
FunctionEnd

Function UpdateOptions
  !insertmacro MUI_HEADER_TEXT "개인정보와 업데이트" "GitHub 통신 사용 여부를 선택하세요."
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 65u "채팅과 초안은 이 PC에 평문으로 30일 보관합니다. 직접 보낸 채팅은 Steam 로비 참여자에게 전달됩니다.$\r$\n$\r$\n업데이트를 허용하면 GitHub에 연결하여 새 버전을 확인하고 내려받습니다. GitHub는 IP 주소 등 연결 정보를 처리할 수 있습니다. 대화와 게임 식별정보는 보내지 않습니다."
  Pop $0
  ${NSD_CreateCheckbox} 0 75u 100% 20u "GitHub 업데이트 확인 및 다운로드 허용"
  Pop $UpdateCheckbox
  ${If} $UpdatePermission == 1
    ${NSD_Check} $UpdateCheckbox
  ${EndIf}
  ${NSD_CreateLabel} 0 103u 100% 45u "해제해도 Steam 채팅은 사용할 수 있습니다. 자동·수동 업데이트 확인이 모두 중지되며, 앱 설정에서 다시 켤 수 있습니다.$\r$\n현재 사용자용 앱 파일, 시작 메뉴와 Windows 제거 항목을 설치합니다. 제거 시 대화와 설정은 남습니다."
  Pop $0
  nsDialogs::Show
FunctionEnd

Function UpdateOptionsLeave
  ${NSD_GetState} $UpdateCheckbox $UpdatePermission
FunctionEnd

Function DirectoryLeave
  ReadRegStr $0 HKCU "${UNINSTALL_KEY}" "InstallLocation"
  ${If} $0 != ""
  ${AndIf} $0 != $INSTDIR
    MessageBox MB_OK|MB_ICONEXCLAMATION "기존 설치 폴더를 선택하세요. 설치 위치를 바꾸려면 먼저 Windows 설정에서 앱을 제거하세요." /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Section "설치"
  Call DirectoryLeave
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\bundle"
  File /r "${BUNDLE_DIR}\*"
  WriteUninstaller "$PLUGINSDIR\bundle\Uninstall.exe"
  DetailPrint "앱을 설치하고 있습니다..."
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "$PLUGINSDIR\bundle\install.ps1" -Destination "$INSTDIR" -ShortcutName "${APP_NAME}"'
  Pop $0
  Pop $1
  ${If} $0 == "error"
  ${OrIf} $0 == "timeout"
    StrCpy $0 40
  ${EndIf}
  ${If} $0 != 0
    ${If} $0 == 20
      MessageBox MB_OK|MB_ICONEXCLAMATION "Bongo Cat Chat이 실행 중입니다. 앱을 닫은 뒤 설치 프로그램을 다시 실행하세요." /SD IDOK
    ${ElseIf} $0 == 11
      MessageBox MB_OK|MB_ICONEXCLAMATION "다른 위치의 설치본이 시작 메뉴를 사용하고 있습니다. 기존 설치 폴더를 선택하거나 먼저 기존 앱을 제거하세요." /SD IDOK
    ${ElseIf} $0 == 30
      MessageBox MB_OK|MB_ICONINFORMATION "더 새로운 버전이 이미 설치되어 있습니다. 시작 메뉴에서 앱을 실행하세요." /SD IDOK
    ${Else}
      MessageBox MB_OK|MB_ICONSTOP "설치하지 못했습니다. 설치 폴더와 디스크 여유 공간을 확인한 뒤 다시 시도하세요. 오류 코드: $0" /SD IDOK
    ${EndIf}
    SetErrorLevel $0
    Abort
  ${EndIf}
  SetOutPath "$INSTDIR"
  ClearErrors
  WriteRegDWORD HKCU "Software\${APP_ID}" "AllowUpdateChecks" $UpdatePermission
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "업데이트 통신 선택을 저장하지 못했습니다. 앱을 실행하기 전에 설치 프로그램을 다시 실행하세요." /SD IDOK
    SetErrorLevel 41
    Abort
  ${EndIf}
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\BongoCatChat.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "URLInfoAbout" "https://github.com/misosiruda/bongo-cat-chat"
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" ${INSTALLED_KB}
  SetErrorLevel 0
SectionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
FunctionEnd

Section "Uninstall"
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  # Use the removal engine embedded in this uninstaller, not a mutable installed script.
  File /oname=remove-app.ps1 "${REMOVAL_SCRIPT}"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "$PLUGINSDIR\remove-app.ps1" -Destination "$INSTDIR" -ShortcutName "${APP_NAME}"'
  Pop $0
  Pop $1
  ${If} $0 == "error"
  ${OrIf} $0 == "timeout"
    StrCpy $0 40
  ${EndIf}
  ${If} $0 != 0
    ${If} $0 == 20
      MessageBox MB_OK|MB_ICONEXCLAMATION "Bongo Cat Chat이 실행 중입니다. 앱을 닫은 뒤 다시 제거하세요." /SD IDOK
    ${Else}
      MessageBox MB_OK|MB_ICONSTOP "앱을 제거하지 못했습니다. 설치 폴더의 접근 권한을 확인한 뒤 다시 시도하세요. 오류 코드: $0" /SD IDOK
    ${EndIf}
    SetErrorLevel $0
    Abort
  ${EndIf}
  # Do not remove another installation's registration or shortcut.
  ReadRegStr $0 HKCU "${UNINSTALL_KEY}" "InstallLocation"
  ${If} $0 == $INSTDIR
    DeleteRegKey HKCU "${UNINSTALL_KEY}"
  ${EndIf}
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  SetErrorLevel 0
SectionEnd
