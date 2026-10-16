"""Fixed Steam profile URI contract; IDs never pass through a JS number."""
import re


def steam_profile_uri(steam_id):
    if (not isinstance(steam_id, str)
            or re.fullmatch(r'[1-9][0-9]{0,19}', steam_id) is None
            or int(steam_id) > (1 << 64) - 1):
        raise ValueError('invalid_steam_id')
    return f'steam://url/SteamIDPage/{steam_id}'
