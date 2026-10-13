"""Strict, bounded decoding of the observed game protocol."""
import json
import unicodedata

MAX_PACKET = 4096
# Development guard from the PoC; not a claim about the game's input limit.
MAX_SEND_UNITS = 50


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
    return validate_text(envelope.get("Message"))
