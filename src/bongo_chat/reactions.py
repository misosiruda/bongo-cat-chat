"""Short-lived rendering only. No storage, sending, notification or replay."""
from collections import deque
import time

REACTION_TTL = 1.2  # Decode/IPC grace, not an animation or replay queue.
MAX_REACTIONS = 24


def png(value):
    return isinstance(value, str) and value.startswith("data:image/png;base64,") and len(value) <= 1024 * 1024


class ReactionAssets:
    """Resolve real assets asynchronously; discard overload and expired work."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.pending = deque(maxlen=MAX_REACTIONS)

    def add(self, event):
        # The bounded deque replaces the oldest pending reaction under load.
        self.pending.append(dict(event))

    def ready(self, state, steam, avatars):
        now = self.clock()
        context = {k: state.get(k, "") for k in ("account", "lobby", "generation")}
        result = []
        for _ in range(len(self.pending)):
            event = self.pending.popleft()
            sender = event["sender"]
            profile = state.get("profiles", {}).get(sender)
            if (not avatars or not state.get("lobby_verified") or event["context"] != context
                    or not 0 <= now - event["observed"] < REACTION_TTL or not profile
                    or sender != context["account"] and state.get("hidden", {}).get(sender) is not False):
                continue
            if event["kind"] == "emote":
                if "item_name" not in event:
                    # Never interpret a hat/chest/tap packet as an emote image.
                    try:
                        tags = (steam.definition(event["item"], "tags") or "").split(";")
                        name = steam.definition(event["item"], "name")
                    except UnicodeError:
                        continue  # A bad optional item definition cannot stop chat.
                    if not {"itemslot:emote", "itemslot:consumable"}.intersection(tags):
                        continue
                    event["item_name"] = name
                event["image"] = avatars.get_emote(event["item_name"])
            if png(profile.get("avatar")) and (event["kind"] == "meow" or png(event.get("image"))):
                result.append(dict(event, avatar=profile["avatar"]))
            else:
                self.pending.append(event)
        return result
