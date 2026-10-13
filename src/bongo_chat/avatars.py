"""Local installed sprites only; no downloaded icons or bundled game artwork."""
from collections import OrderedDict
import base64
from io import BytesIO
import queue
import threading
from pathlib import Path


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
        key = (skin, hat)
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
            from PIL import Image
            data = self.root / "BongoCat_Data"
            env = UnityPy.load(str(data / "sharedassets0.assets"), str(data / "resources.assets"))
            sprites = {}
            for obj in env.objects:
                if self.stop.is_set():
                    return
                if obj.type.name == "Sprite":
                    sprite = obj.read()
                    if sprite.m_Name in sprites:
                        sprites[sprite.m_Name] = None  # Ambiguous mappings are unsupported.
                    else:
                        sprites[sprite.m_Name] = sprite
            self.stage = "ready"
            while not self.stop.is_set():
                try:
                    skin, hat = self.requests.get(timeout=.5)
                except queue.Empty:
                    continue
                layers = [skin+"Left", skin+"Right"] + ([hat] if hat else [])
                result = None
                try:
                    canvas = Image.new("RGBA", (256, 256))
                    for name in layers:
                        sprite = sprites.get(name)
                        if sprite is None:
                            raise ValueError("sprite_missing")
                        texture = sprite.m_RD.texture.read()
                        if (texture.m_Width, texture.m_Height, sprite.m_Rect.width, sprite.m_Rect.height) != (256,256,256,256):
                            raise ValueError("unsupported_sprite_geometry")
                        canvas.alpha_composite(texture.image.convert("RGBA"))
                    output = BytesIO()
                    canvas.save(output, format="PNG")
                    result = "data:image/png;base64,"+base64.b64encode(output.getvalue()).decode("ascii")
                except Exception as exc:
                    self.error = type(exc).__name__  # No names, identifiers or original text.
                with self.lock:
                    key = (skin, hat)
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
