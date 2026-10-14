# SignPath 신청을 위한 라이선스 검토

기준일: 2026-10-14. 소스 기준은 `45e7d1e`와 `build/windows-code-signing`의 로컬 변경이다. 그 뒤 `main`에서 진행 중인 다른 기능 변경은 이 검토에 자동 포함되지 않는다. 공개 릴리스 `v0.1.0.dev6`의 실제 파일, 설치된 잠금 버전의 패키지 메타데이터, 원저작자의 문서를 대조했다.

## 판정

자체 코드에는 소유자가 선택한 **MIT**를 [LICENSE](../LICENSE)와 `pyproject.toml`에 적용했다. SignPath의 OSI 라이선스 요건에 사용할 수 있는 선택이다. 그러나 자체 라이선스 결정은 패키지 전체의 재배포 조건, 게임 연동 허가 또는 SignPath 승인 완료를 뜻하지 않는다.

| 대상 | 확인한 사실 | 이번 조치 / 남은 확인 |
| --- | --- | --- |
| 자체 소스·문서 | 기존 원격 저장소는 공개이지만 LICENSE 미지정 | 소유자의 MIT 선택을 로컬에 적용. 게시 후 원격 표시 확인 |
| FMOD | 기존 번들에 `fmod_toolkit/libfmod/Windows/x64/fmod.dll` 존재. MIT인 Python 래퍼와 FMOD Engine의 이용 조건은 다름 | 앱이 쓰지 않는 AudioClip 변환과 FMOD를 빌드에서 제외. 새 번들 검증 결과는 아래 기록 |
| Qt QML 부가 모듈 | 기존 번들에 Qt Graphs/Quick3D/VirtualKeyboard 등 앱에서 쓰지 않는 모듈이 포함됨 | QML 리소스·디버그 플러그인·가상 키보드 수집을 제한. Widgets/WebEngine과 Windows 기본 입력 경로 유지 |
| Qt/PySide6 | 사용 모듈은 LGPL 경로 검토 대상. 패키지 한 개의 라이선스 문자열로 모든 Qt DLL을 판정할 수 없음 | 모듈별 고지, 라이브러리 교체·재빌드 설명, 대응 소스 접근을 확인 |
| 공개 고지 파일 | `v0.1.0.dev6`에 `THIRD-PARTY-NOTICES.txt` 자산이 이미 존재. FMOD 별도 조건도 언급됨 | LGPL 전문과 Chromium 고지의 완전성을 확인한 자료가 아니므로 그대로 재사용해 “검토 완료” 처리하지 않음 |
| 게임·Steam | 게임/Steam DLL과 그림을 번들에 넣지 않으며 설치된 파일을 읽거나 로드함 | 이 사실만으로 SignPath의 System Libraries 예외 해당 여부나 게임사의 연동 허가가 확정되지는 않음. 심사자에게 동작 설명 필요 |
| Windows 런타임 | Python·MSVC 및 시스템 API 의존 | CPython 고지와 재배포 런타임 고지/예외 범위 확인 |

FMOD의 무료 사용 조건은 OSI 오픈소스 라이선스와 동일하지 않다. 일반적인 “무료 앱”이라는 사유로 SignPath의 비공개 구성요소 제한을 통과한다고 판단하지 않는다. [FMOD 조건](https://www.fmod.com/legal), [SignPath 신청 조건](https://signpath.org/terms).

Qt PDF는 현재 공식 문서에 LGPLv3 선택지가 있으므로 이름만 보고 GPL 전용으로 분류하지 않았다. Qt WebEngine에는 Chromium의 별도 라이선스들이 포함된다. [Qt 모듈별 라이선스](https://doc.qt.io/qt-6/licensing.html), [Qt PDF](https://doc.qt.io/qt-6/qtpdf-index.html), [Qt WebEngine](https://doc.qt.io/qt-6/qtwebengine-licensing.html).

## LGPL 및 네이티브 고지 준비

다음은 MIT와 별개로 최종 배포 전에 완료할 항목이다. 이 문서는 완료되지 않은 제공 약속을 만들지 않는다.

1. 설치물 안에서 MIT·각 라이브러리 저작권/허가 고지·LGPLv3/GPLv3 관련 전문을 열람할 수 있게 한다. Qt/Chromium, Python/OpenSSL, Pillow·텍스처 디코더 등 네이티브 하위 구성요소도 확인한다.
2. 실제 Windows wheel과 일치하는 Qt/PySide/Chromium 대응 소스, 패치 유무, 빌드 자료를 확보하고 배포 페이지에서 버전별로 접근할 수 있게 한다. 일반적인 다운로드 홈페이지 링크만으로 대응 소스 검증을 완료했다고 쓰지 않는다.
3. DLL을 분리한 onedir 구조를 유지하고 사용자가 라이브러리를 교체하거나 소스에서 다시 빌드해 실행할 수 있게 한다. 라이브러리 수정·디버깅을 위한 역공학을 금지하는 EULA를 추가하지 않는다. 자동 업데이트와 로컬 교체본의 상호작용도 검증한다.
4. 최종 새 버전의 패키지와 소스 태그를 연결하고 SHA-256 및 구성요소 목록을 보관한다. 의존성 버전이나 PyInstaller hook이 바뀌면 다시 검사한다.

이번 변경은 `tools/collect_license_notices.py`로 패키지에 포함된 고지, CPython·Mono.Cecil 고지, 공식 GNU 라이선스 전문과 자체 MIT·개인정보 안내를 모아 앱의 `_internal/bongo_chat/legal/`에 동봉한다. FMOD 래퍼와 개발 전용 도구는 수집 대상에서 제외한다. 수집된 문서에도 네이티브 검토가 남았음을 표시한다. Qt/Chromium의 구성요소별 대응 소스와 고지의 완전성, 설치 UI에서의 안내는 별도 완료 항목이다.

Qt의 대응 소스 제공·교체 가능성·고지 요구사항은 [Qt LGPL 안내](https://www.qt.io/development/open-source-lgpl-obligations)를 기준으로 정리했다. 공식 [Qt 6.12.0 소스 인덱스](https://download.qt.io/archive/qt/6.12/6.12.0/)와 [PySide6 6.12.0 소스](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.12.0-src/)의 존재를 확인했다. 모든 내장 서브모듈의 정확한 대응 및 해시 검증까지 마친 것은 아니다.

설치된 Qt wheel이 `LicenseRef-Qt-Commercial.txt`만 라이선스 파일 메타데이터에 열거하는 경우가 있다. 이것만으로 상용 라이선스를 취득했다고 간주하지 않는다. 공식 PySide 배포 설명은 같은 PyPI wheel의 오픈소스 사용 경로도 명시한다. [PySide6 WebEngine 배포 설명](https://pypi.org/project/PySide6-WebEngine/6.12.0.140/).

## 재현 가능한 점검

```powershell
.venv/Scripts/python tools/audit_distribution.py --output dist/license-review/dependencies.json
.venv/Scripts/python tools/audit_distribution.py --bundle dist/review/BongoCatChat --output dist/license-review/bundle.json
./packaging/build.ps1 -OutputRoot dist/review -AllowUnsigned
```

`audit_distribution.py`는 잠금 파일 39개 배포 패키지의 설치 버전·라이선스 메타데이터·고지 파일 경로를 기록하고, 번들의 네이티브 파일 해시와 알려진 금지 파일을 검사한다. FMOD, 게임 파일, 사용하지 않는 Qt GPL 모듈이 있거나 잠금 버전이 맞지 않으면 실패한다. 메타데이터가 비어 있거나 SPDX 표현식이 없다고 임의의 라이선스를 부여하지 않는다. 통과는 **알려진 파일 검사 통과**이며 법률 검토·완전한 SBOM·전체 고지 검증 완료를 뜻하지 않는다.

`packaging/hooks/disable_unity_audio.py`는 앱이 쓰지 않는 UnityPy 오디오 변환 진입점을 명시적으로 비활성화한다. UnityPy 소스나 공용 가상환경을 수정하지 않는다. 이미지 변환은 유지하며 오디오 변환 호출은 `NotImplementedError`로 실패한다. 빌드 환경에는 UnityPy의 선언 의존성으로 FMOD 래퍼가 설치될 수 있지만 배포 실행 파일에서 해당 모듈·네이티브 라이브러리를 제외한다.

QML hook은 현재 Widgets 앱에 필요한 동적 의존성을 수집하되 QML 전체 플러그인과 프로파일러를 넣지 않는다. 향후 QML·가상 키보드·오디오 기능을 추가할 경우 이 결정을 재검토한다.

## 검증 기록

- 패키지 메타데이터: `requirements-lock.txt`의 39개 버전 일치 확인.
- FMOD import를 금지한 새 Python 프로세스에서 실제 UnityPy를 불러와 합성 RGBA 픽셀을 변환하고 오디오 기능의 명시적 실패를 검사함.
- 첫 전체 빌드에서 Qt VirtualKeyboard와 Quick3D profiler의 간접 의존성을 검사기가 검출함. 해당 수집 hook을 수정한 뒤 다시 빌드함.
- 최종 빌드·오프라인 UI·설치 파일·회귀 검사 결과는 [SignPath 준비 검증](signpath-validation.md)에 별도로 기록한다.
- 실제 SignPath 서버 검증, 인증서 서명, SmartScreen 변화, 다른 PC 또는 실제 게임 아바타 표시는 이번 검사에서 확인하지 않는다.

## 신청 전에 남은 항목

- [x] 자체 소스 MIT 선택과 로컬 적용
- [x] 의존성/네이티브 배포 차단 요소 조사 및 자동 검사 추가
- [ ] 최종 LGPL/Chromium/네이티브 고지와 대응 소스 제공 검토 완료
- [ ] 설치 중 개인정보 안내와 업데이트 통신 선택권 요건 확인·구현
- [ ] Steam/게임 라이브러리 외부 의존을 SignPath 심사자가 수용하는지 확인
- [ ] GitHub 호스팅 빌드 성공 URL 확보
- [ ] 라이선스·정책 문서를 원격 저장소와 릴리스 안내에 게시
- [ ] 계정·MFA·서명 담당자 설정 및 신청 제출

## 패키지 메타데이터 목록

잠금 파일의 설치 버전을 대조한 목록이다. 개발 도구도 포함하며, 최종 번들의 네이티브 하위 구성요소 전체 목록은 아니다. SPDX 표현식이 없는 경우 배포자가 적은 라벨을 유지한다. FMOD 래퍼의 MIT는 엔진 DLL의 라이선스가 아니다.

| 패키지 | 버전 | 배포 메타데이터의 라이선스 |
| --- | --- | --- |
| altgraph | 0.17.5 | MIT |
| archspec | 0.2.6 | Apache-2.0 OR MIT |
| astc-encoder-py | 0.1.12 | MIT License |
| attrs | 26.1.0 | MIT |
| brotli | 1.2.0 | MIT |
| cffi | 2.1.1 | MIT-0 |
| colorama | 0.4.6 | BSD License |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| etcpak | 0.9.15 | MIT License |
| fmod_toolkit | 0.1.3 | MIT License |
| fsspec | 2026.9.0 | BSD-3-Clause |
| greenlet | 3.5.6 | MIT AND PSF-2.0 |
| iniconfig | 2.3.1 | MIT |
| lz4 | 4.4.5 | BSD License |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pefile | 2024.8.26 | MIT |
| pillow | 12.3.0 | MIT-CMU |
| playwright | 1.63.0 | Apache-2.0 |
| pluggy | 1.6.0 | MIT |
| psutil | 7.2.2 | BSD-3-Clause |
| pycparser | 3.11 | BSD-3-Clause |
| pyee | 13.0.1 | MIT |
| pyfmodex | 0.7.2 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| pyinstaller | 6.22.3 | GPL-2.0-or-later + bootloader distribution exception |
| pyinstaller-hooks-contrib | 2026.8 | Apache Software License; GNU General Public License v2 (GPLv2) |
| PySide6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Addons | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Essentials | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_Pdf | 6.12.0.140 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| PySide6_WebEngine | 6.12.0.140 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| pytest | 9.1.1 | MIT |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause |
| setuptools | 84.0.0 | MIT |
| shiboken6 | 6.12.0 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| texture2ddecoder | 1.0.6 | MIT License |
| tpk_ar | 0.2.4 | MIT License |
| typing_extensions | 4.16.0 | PSF-2.0 |
| UnityPy | 1.25.4 | MIT License |
