"""Strict, bounded decoding of the observed game protocol."""
import json
import unicodedata

MAX_PACKET = 4096
# Development guard from the PoC; not a claim about the game's input limit.
MAX_SEND_UNITS = 50

# BongoCat localization entry 4796346370, inspected in build 25902419.
# These 18 case-folded values cover all 27 shipped locales. See the source
# snapshot in tests/fixtures/meow-localizations.json; never guess translations.
_MEOW_MESSAGES = frozenset(text.casefold() for text in (
    "Meow Meow", "야옹 야옹", "にゃんにゃ～ん", "喵~喵~", "喵嗚～",
    "Miaou Miaou", "Mňau Mňau", "Mjav Mjau", "Miauw Miauw", "Miu Mau",
    "Miau Miau", "Νιάου Νιάου", "מיאו מיאו", "Miao Miao", "Mjau Mjau",
    "Мяу Мяу", "Miyav Miyav", "Няв Няв",
))


def is_meow_message(text: str) -> bool:
    """Match a whole click-meow text; the wire format cannot prove its source."""
    return unicodedata.normalize("NFC", text).strip().casefold() in _MEOW_MESSAGES


class InvalidMessage(ValueError):
    pass


def validate_text(text: str, *, sending=False) -> str:
    if not isinstance(text, str) or not text.strip():
        raise InvalidMessage("empty_text")
    if any(unicodedata.category(c) in {"Cs", "Cc"} and c not in "\n\t" for c in text):
        raise InvalidMessage("control_character")
    if sending and len(text.encode("utf-16-le")) // 2 > MAX_SEND_UNITS:
        raise InvalidMessage("development_limit_50")
    return text


def encode(text: str) -> bytes:
    validate_text(text, sending=True)
    packet = json.dumps({"Channel": 3, "Message": text}, ensure_ascii=False,
                        separators=(",", ":")).encode("utf-8")
    if len(packet) > MAX_PACKET:
        raise InvalidMessage("packet_too_large")
    return packet


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidMessage("duplicate_key")
        result[key] = value
    return result


def decode(raw: bytes) -> str | None:
    if not raw or len(raw) > MAX_PACKET:
        raise InvalidMessage("packet_size")
    try:
        envelope = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InvalidMessage("invalid_json") from exc
    if not isinstance(envelope, dict):
        raise InvalidMessage("invalid_envelope")
    if type(envelope.get("Channel")) is not int:
        raise InvalidMessage("invalid_channel")
    if envelope["Channel"] != 3:
        return None
    text = validate_text(envelope.get("Message"))
    return None if is_meow_message(text) else text
