"""Local UI translations. Chat text and identity data never enter this catalog."""
import json
from pathlib import Path

from PySide6.QtCore import QLocale

ENGLISH = json.loads((Path(__file__).with_name('ui') / 'translations.json').read_text(encoding='utf-8'))
LANGUAGES = ('system', 'ko', 'en')


def resolve_language(preference='system', system_locale=None):
    if preference in ('ko', 'en'):
        return preference
    locales = QLocale.system().uiLanguages() if system_locale is None else [system_locale]
    return 'ko' if locales and locales[0].lower().replace('_', '-').split('-')[0] == 'ko' else 'en'


def translate(text, language):
    return ENGLISH.get(text, text) if language == 'en' else text
