"""Widgets/WebEngine app: retain linked Qt dependencies, omit unused QML plugins.

The default hook collects the entire QML tree, including GPL-only add-ons.
This application does not load QML documents. Revisit if that changes.
"""
from PyInstaller.utils.hooks.qt import add_qt6_dependencies
from pathlib import Path

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
# Debugger/profiler plugins pull Quick3D into an otherwise LGPL-only bundle.
binaries = [entry for entry in binaries if "qmltooling" not in Path(entry[0]).parts]
