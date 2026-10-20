"""Unequipped cosmetics through the real profile/compositor/UI path, offline."""
import base64
from io import BytesIO
import json
import sys
import time
from types import SimpleNamespace as NS

from PIL import Image
import pytest

from bongo_chat.avatars import Avatars
from bongo_chat.steam import Steam
from bongo_chat.worker import LiveConnection
from test_avatars import prefab, reader, sprite, sprites
from test_core import FakeGame, FakeMemory, FakeSteam
from test_desktop import js, qt_chat, wait_until


class CosmeticsSteam(FakeSteam):
    skin, hat = 101, 202

    def profile(self, lobby, uid):
        return {"name": "합성 고양이", "skin": self.skin, "hat": self.hat}

    def definition(self, item, prop):
        assert item != -1, "Unequipped slots must not query item definitions"
        return {101: "Fixture", 202: "Fixture Hat"}.get(item)


@pytest.fixture
def rendered_avatars(prefab, sprites, monkeypatch, tmp_path):
    # Distinct synthetic default pixels, never game artwork.
    sprites["CatLeft"] = sprite(Image.new("RGBA", (256, 256), "white"))
    sprites["CatRight"] = sprite(Image.new("RGBA", (256, 256)))
    objects = prefab[1]
    for name, value in sprites.items():
        value.m_Name = name
        objects.append(reader("Sprite", value))
    monkeypatch.setitem(sys.modules, "UnityPy", NS(load=lambda *args: NS(objects=objects)))
    avatars = Avatars(tmp_path)
    try:
        yield avatars
    finally:
        avatars.close()


def profile_image(live):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        live.profile_time = 0
        state, _, _ = live.snapshot()
        image = state["profiles"]["fixture-peer"].get("avatar")
        if image:
            return state, image
        time.sleep(.01)
    pytest.fail("Synthetic avatar did not become ready")


def test_all_outfits_and_repeated_changes(rendered_avatars):
    steam = CosmeticsSteam()
    live = LiveConnection(FakeGame(), FakeMemory(), steam, avatars=rendered_avatars)
    images = {}
    for skin, hat in [(101, 202), (-1, 202), (-1, -1), (101, -1), (101, 202)]:
        steam.skin, steam.hat = skin, hat
        state, data = profile_image(live)
        image = Image.open(BytesIO(base64.b64decode(data.split(",", 1)[1])))
        assert image.size == (256, 256) and image.getbbox() is not None
        assert state["profiles"]["fixture-self"]["avatar"] == data
        if (skin, hat) in images:
            assert images[skin, hat] == data
        images[skin, hat] = data
    assert len(set(images.values())) == 4
    assert not steam.sent
    assert rendered_avatars.error == ""


@pytest.mark.parametrize("slot", ["skin", "hat"])
@pytest.mark.parametrize("unknown", [None, -2, 999, 0])
def test_unknown_slot_or_definition_is_not_an_unequipped_slot(slot, unknown):
    steam = CosmeticsSteam()
    calls = []
    live = LiveConnection(FakeGame(), FakeMemory(), steam,
                          avatars=NS(get=lambda *args: calls.append(args) or "synthetic"))
    live.snapshot()
    assert calls
    calls.clear()
    setattr(steam, slot, unknown)
    live.profile_time = 0
    state, _, _ = live.snapshot()
    assert not calls
    assert "avatar" not in state["profiles"]["fixture-peer"]
    assert state["hidden_ok"] and state["send_enabled"]


@pytest.mark.parametrize("raw, expected", [(b"-1", -1), (b"", None), (None, None),
                                           (b"invalid", None), (b"101", 101)])
def test_native_slot_parsing_preserves_explicit_unequipped_value(raw, expected):
    steam = Steam.__new__(Steam)
    steam.friends = steam.matchmaking = object()
    def bind(name, *_):
        if name == "ISteamMatchmaking_GetLobbyMemberData":
            return lambda *_: raw
        return lambda *_: b"synthetic"
    steam.bind = bind
    row = steam.profile("10", "20")
    assert row["skin"] == row["hat"] == expected


def test_equipment_changes_update_existing_message_and_participant_images(qt_chat, rendered_avatars):
    app, controller, page = qt_chat
    steam = CosmeticsSteam()
    live = LiveConnection(FakeGame(), FakeMemory(), steam, avatars=rendered_avatars)
    js(app, page, "document.querySelector('#participants-button').click()")
    for skin, hat in [(101, 202), (-1, 202), (-1, -1), (101, -1), (101, 202)]:
        steam.skin, steam.hat = skin, hat
        state, image = profile_image(live)
        controller.service.update(dict(controller.service.state, profiles=state["profiles"]))
        expected = json.dumps(image)
        wait_until(app, lambda: js(app, page, f"""(() => {{
          const message=document.querySelector('.message .avatar img');
          const participants=[...document.querySelectorAll('#participant-list .avatar img')];
          return message?.src === {expected} && message.naturalWidth === 256
            && participants.length === 2
            && participants.every(img => img.src === {expected} && img.naturalWidth === 256);
        }})()"""))
        assert js(app, page, "document.querySelectorAll('.message-bubble').length") == 1
    assert controller.worker is None and not steam.sent
