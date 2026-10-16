# Open-source notices and corresponding sources

Bongo Cat Chat's own source is MIT licensed. Qt, PySide6 and Shiboken6 are
distributed under their applicable LGPL open-source options. Qt WebEngine also
includes Chromium components under their respective licences, including LGPL
2.1. No commercial Qt licence is asserted. See THIRD-PARTY-NOTICES.txt,
CHROMIUM-LICENSES.html and the included GPL/LGPL texts.

## Exact source set

The adjacent `sources.lock.json` lists the full HTTPS download URL, SHA-256 and
size of every Qt/PySide source archive. These are complete upstream archives,
including the bundled Chromium sources in the WebEngine archive. Qt 6.12.0 and
WebEngine/Pdf 6.140.0 are separate releases; the Chromium version is
140.0.7339.225. No Qt, PySide, Shiboken or Chromium source patch is used by this
application. The Unity audio hook is application code disabling an unused
feature, not a modified UnityPy binary or source distribution.

The source modules are qtbase, qtdeclarative, qtimageformats, qtsvg, qtserialport,
qtpositioning, qtwebchannel (6.12.0), pyside-setup (6.12.0), and qtwebengine
(6.140.0). The WebEngine archive is from Qt's official online SDK repository.
The archive hashes were checked against the official download.qt.io metadata.

The repository build tool downloads and verifies this source set:

```powershell
python tools/prepare_source_notices.py --cache dist/signpath-sources --download
```

CI retains these archives as a separate source artifact. For any future public
binary release made from this branch, publish that source artifact alongside
the installer/update assets, keep it available for as long as the binaries,
and link it on the same download page. A short-lived CI artifact alone is not
the source-distribution plan for public releases. Older dev6/dev7 assets are
not rebuilt or retrospectively cleared by these notices.

Qt source notices include third-party attributions and licence files from the
source archives. This is a conservative superset, including upstream tools,
tests and other platforms. A GPL notice in that collection does not mean an
unused GPL-only Qt module is shipped; the native distribution audit checks
the actual Windows payload separately. Individual upstream copyrights and
licence terms remain in force.

## Replace or rebuild LGPL libraries

The application uses separate dynamic libraries in
`versions/<version>/BongoCatChatApp/_internal/PySide6` and `shiboken6`.
There is no integrity check preventing a user from replacing these libraries
in their own installation. Close the app, back up the installation, rebuild
the same compatible modules/ABI for Windows x64, and replace the relevant
DLLs, Python extension modules, plugins and WebEngine resources together.
Preserve the directory layout. Incompatible binaries can prevent startup.

Use the included upstream README/CMake/build instructions. Qt's build guide:
https://doc.qt.io/qt-6/windows-building.html
PySide's build guide:
https://doc.qt.io/qtforpython-6/building_from_source/windows.html
For PySide/shiboken, use the same CPython 3.13 x64 ABI and a supported MSVC
toolchain. The repository's requirements-lock.txt and packaging/build.ps1
record the Python package versions and application packaging commands.
Full application source is available at:
https://github.com/misosiruda/bongo-cat-chat

Modification for personal use, relinking/replacing the LGPL libraries, and
reverse engineering for debugging those modifications are permitted under
the applicable licences. Bongo Cat Chat adds no contractual restriction on
these rights. Disable update checks before using modified libraries; an
already staged update may still be installed on the next launch, so apply
local library replacements after that launch or rebuild a standalone app.

## Other native components

The notification implementation uses five PyWinRT 3.2.1 wheels (runtime,
Foundation, Foundation.Collections, Data.Xml.Dom and UI.Notifications). Their
metadata specifies MIT but these wheels omit the licence text. The upstream
v3.2.1 licence, including Microsoft and David Lechner notices, is pinned by
commit and SHA-256 in additional-notices.json and included in
THIRD-PARTY-NOTICES.txt as PyWinRT-3.2.1-LICENSE.txt. Upstream source:
https://github.com/pywinrt/pywinrt/tree/21cbd0fd7ff91422ed76b4e3611d3fb52716e017.

Python 3.13.3 and its bundled libraries retain the Python Windows distribution
notices. Additional OpenSSL 3.0.16 notices cover libssl-3.dll/libcrypto-3.dll.
The cryptography wheel has its own bundled-library notices. Pillow, codecs,
UnityPy, Mono.Cecil and the PyInstaller bootloader retain their package notices
and exceptions. Source/project URLs are included in THIRD-PARTY-NOTICES.txt.

Qt's opengl32sw.dll identifies Mesa 11.2.2 and LLVM 3.6.2 in its embedded version
strings; their notices are included. The NSIS installer/uninstaller uses the
NSIS 3.13 COPYING notice. Microsoft C/C++ runtime DLLs shipped with the official
Python/Qt wheels remain Microsoft runtime components, not project-owned code
or MIT-licensed files. Their inclusion is disclosed as a System Libraries
case for SignPath review. No upstream DLL or QtWebEngineProcess.exe is signed
using this project's certificate policy.

Steam/game binaries and game artwork are not included. Runtime loading from a
user's installed game does not establish endorsement or blanket redistribution
permission from Valve or the game developer.
