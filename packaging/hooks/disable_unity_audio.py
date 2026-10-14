"""Disable unused UnityPy audio exports before its eager export imports run.

This is project-owned packaging code; it does not edit UnityPy or its licence.
UnityPy 1.25.4 imports AudioClipConverter even for texture-only use. The real
converter and FMOD dependencies are excluded from the frozen application.
"""
from importlib.machinery import ModuleSpec
import sys
from types import ModuleType


def _unsupported_audio(*args, **kwargs):
    raise NotImplementedError("Audio export is not included in Bongo Cat Chat")


_name = "UnityPy.export.AudioClipConverter"
_module = ModuleType(_name, "Audio export is deliberately disabled in this application.")
_module.__spec__ = ModuleSpec(_name, loader=None)
_module.extract_audioclip_samples = _unsupported_audio
sys.modules[_name] = _module
