"""Local installed sprites only; no downloaded icons or bundled game artwork."""
from collections import OrderedDict
from dataclasses import dataclass
import base64
from io import BytesIO
import math
import queue
import threading
from pathlib import Path


SPRITE_SIZE = 256
LAYER_NAMES = {"Body", "Hat", "RightPaw"}


@dataclass(frozen=True)
class AvatarLayer:
    name: str
    x: int
    y: int


def _is_lobby_visuals(transform):
    """Select the game prefab, excluding inventory and preset previews."""
    for name in ("BobTransform", "Visuals", "Cat_Multiplayer", "LobbyMember"):
        if transform.m_GameObject.read().m_Name != name:
            return False
        parent = transform.m_Father
        if name == "LobbyMember":
            return not parent.path_id
        if not parent.path_id:
            return False
        transform = parent.read()
    return False


def avatar_layout(objects):
    """Read sibling order and relative placement from installed RectTransforms."""
    candidates = []
    for obj in objects:
        if obj.type.name != "RectTransform":
            continue
        transform = obj.read()
        if transform.m_GameObject.read().m_Name == "BobTransform" and _is_lobby_visuals(transform):
            candidates.append(transform)
    if len(candidates) != 1:
        raise ValueError("avatar_layout_missing_or_ambiguous")
    layers = []
    for child in candidates[0].m_Children:
        transform = child.read()
        name = transform.m_GameObject.read().m_Name
        if name in LAYER_NAMES:
            layers.append((name, transform))
    if len(layers) != 3 or {name for name, _ in layers} != LAYER_NAMES:
        raise ValueError("avatar_layers_missing_or_ambiguous")
    body = next(transform for name, transform in layers if name == "Body")
    side = body.m_SizeDelta.x
    if not math.isfinite(side) or not 0 < side <= 1024:
        raise ValueError("unsupported_avatar_geometry")
    result = []
    for name, transform in layers:
        # Only the known unrotated, equally sized square UI layers are supported.
        vectors = (transform.m_AnchorMin, transform.m_AnchorMax, transform.m_Pivot)
        scale, rotation, size = transform.m_LocalScale, transform.m_LocalRotation, transform.m_SizeDelta
        if (any((v.x, v.y) != (.5, .5) for v in vectors)
                or (scale.x, scale.y, scale.z) != (1, 1, 1)
                or (rotation.x, rotation.y, rotation.z, rotation.w) != (0, 0, 0, 1)
                or (size.x, size.y) != (side, side)):
            raise ValueError("unsupported_avatar_geometry")
        x = (transform.m_AnchoredPosition.x - body.m_AnchoredPosition.x) * SPRITE_SIZE / side
        y = (body.m_AnchoredPosition.y - transform.m_AnchoredPosition.y) * SPRITE_SIZE / side
        if any(not math.isfinite(v) or abs(v) > SPRITE_SIZE for v in (x, y)):
            raise ValueError("unsupported_avatar_geometry")
        result.append(AvatarLayer(name, round(x), round(y)))
    return tuple(result)


def compose_avatar(sprites, layout, skin, hat):
    """Compose in game order, then fit the complete result into a square avatar."""
    from PIL import Image

    names = {"Body": skin + "Left", "RightPaw": skin + "Right", "Hat": hat}
    layers = []
    for layer in layout:
        name = names[layer.name]
        if name is None:
            continue
        sprite = sprites.get(name)
        if sprite is None:
            raise ValueError("sprite_missing")
        texture = sprite.m_RD.texture.read()
        rect = sprite.m_Rect
        if (texture.m_Width, texture.m_Height, rect.width, rect.height, rect.x, rect.y) != (
                SPRITE_SIZE, SPRITE_SIZE, SPRITE_SIZE, SPRITE_SIZE, 0, 0):
            raise ValueError("unsupported_sprite_geometry")
        layers.append((layer, texture.image.convert("RGBA")))
    left = min(layer.x for layer, _ in layers)
    top = min(layer.y for layer, _ in layers)
    width = max(layer.x + SPRITE_SIZE for layer, _ in layers) - left
    height = max(layer.y + SPRITE_SIZE for layer, _ in layers) - top
    side = max(width, height)
    canvas = Image.new("RGBA", (side, side))
    for layer, image in layers:
        canvas.alpha_composite(image, (layer.x - left + (side - width) // 2,
                                       layer.y - top + (side - height) // 2))
    if side != SPRITE_SIZE:
        canvas = canvas.resize((SPRITE_SIZE, SPRITE_SIZE), Image.Resampling.LANCZOS)
    return canvas


class Avatars:
    def __init__(self, root):
        self.root = root
        self.requests = queue.Queue(maxsize=64)
        self.cache = OrderedDict()
        self.requested = set()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.stage, self.error = "loading", ""
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def get(self, skin, hat):
        if not skin:
            return None
        return self._request((skin, hat))

    def get_emote(self, name):
        """The game's SteamItemRuntime uses Name.Replace(' ', '') + 'Icon'."""
        if not isinstance(name, str) or not 0 < len(name) <= 256:
            return None
        return self._request((name.replace(" ", "") + "Icon",))

    def _request(self, key):
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            if key not in self.requested:
                try:
                    self.requests.put_nowait(key)
                    self.requested.add(key)
                except queue.Full:
                    pass
        return None

    def run(self):
        try:
            import UnityPy
            data = self.root / "BongoCat_Data"
            env = UnityPy.load(str(data / "sharedassets0.assets"), str(data / "resources.assets"))
            objects = env.objects
            sprites = {}
            for obj in objects:
                if self.stop.is_set():
                    return
                if obj.type.name == "Sprite":
                    sprite = obj.read()
                    if sprite.m_Name in sprites:
                        sprites[sprite.m_Name] = None  # Ambiguous mappings are unsupported.
                    else:
                        sprites[sprite.m_Name] = sprite
            layout = avatar_layout(objects)
            self.stage = "ready"
            while not self.stop.is_set():
                try:
                    key = self.requests.get(timeout=.5)
                except queue.Empty:
                    continue
                result = None
                try:
                    if len(key) == 1:
                        sprite = sprites.get(key[0])
                        if sprite is None or not (0 < sprite.m_Rect.width <= 512 and 0 < sprite.m_Rect.height <= 512):
                            raise ValueError("unsupported_emote_sprite")
                        texture = sprite.m_RD.texture.read()
                        if not (0 < texture.m_Width <= 4096 and 0 < texture.m_Height <= 4096):
                            raise ValueError("unsupported_emote_texture")
                        canvas = sprite.image.convert("RGBA")
                    else:
                        canvas = compose_avatar(sprites, layout, *key)
                    output = BytesIO()
                    canvas.save(output, format="PNG")
                    result = "data:image/png;base64,"+base64.b64encode(output.getvalue()).decode("ascii")
                except Exception as exc:
                    self.error = type(exc).__name__  # No names, identifiers or original text.
                with self.lock:
                    self.requested.discard(key)
                    self.cache[key] = result
                    while len(self.cache) > 128:
                        self.cache.popitem(last=False)
        except Exception as exc:
            self.stage = "unavailable"
            self.error = type(exc).__name__
            if isinstance(exc, ModuleNotFoundError):
                self.error += ":" + str(exc.name)
            elif isinstance(exc, FileNotFoundError) and exc.filename:
                self.error += ":" + Path(exc.filename).name
            return

    def close(self):
        self.stop.set()
        self.thread.join(1)
