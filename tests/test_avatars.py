"""Synthetic pixels and prefab geometry only; no game assets or Steam access."""
import base64
from io import BytesIO
import sys
import time
from types import SimpleNamespace as NS

from PIL import Image, ImageDraw
import pytest

from bongo_chat.avatars import AvatarLayer, Avatars, avatar_layout, compose_avatar


def pointer(value=None):
    return NS(path_id=1 if value is not None else 0, read=lambda: value)


def transform(name, parent=None, position=(0, 0)):
    return NS(m_GameObject=pointer(NS(m_Name=name)), m_Father=pointer(parent), m_Children=[],
              m_AnchoredPosition=NS(x=position[0], y=position[1]), m_SizeDelta=NS(x=128, y=128),
              m_Pivot=NS(x=.5, y=.5), m_AnchorMin=NS(x=.5, y=.5), m_AnchorMax=NS(x=.5, y=.5),
              m_LocalScale=NS(x=1, y=1, z=1), m_LocalRotation=NS(x=0, y=0, z=0, w=1))


def reader(kind, value):
    return NS(type=NS(name=kind), read=lambda: value)


@pytest.fixture
def prefab():
    root = transform('LobbyMember')
    cat = transform('Cat_Multiplayer', root)
    visuals = transform('Visuals', cat)
    bob = transform('BobTransform', visuals)
    layers = [transform('Body', bob, (-6.3, 9.8)), transform('Hat', bob, (10, 45)),
              transform('RightPaw', bob, (-6.3, 9.8))]
    bob.m_Children = [pointer(layer) for layer in layers]
    return bob, [reader('RectTransform', item) for item in [root, cat, visuals, bob, *layers]]


def sprite(image):
    texture = NS(m_Width=image.width, m_Height=image.height, image=image)
    return NS(m_Rect=NS(width=image.width, height=image.height, x=0, y=0),
              m_RD=NS(texture=pointer(texture)))


@pytest.fixture
def sprites():
    body = Image.new('RGBA', (256, 256))
    ImageDraw.Draw(body).rectangle((32, 128, 224, 208), fill='green')
    hat = Image.new('RGBA', (256, 256))
    draw = ImageDraw.Draw(hat)
    draw.rectangle((80, 160, 112, 224), fill='red')
    draw.rectangle((80, 0, 112, 12), fill='red')  # Tall hat tip above the body's frame.
    paw = Image.new('RGBA', (256, 256))
    ImageDraw.Draw(paw).rectangle((120, 135, 140, 155), fill='blue')
    return {'FixtureLeft': sprite(body), 'FixtureRight': sprite(paw), 'FixtureHat': sprite(hat)}


def test_prefab_uses_relative_positions_upward_y_and_sibling_order(prefab):
    bob, objects = prefab
    assert avatar_layout(objects) == (AvatarLayer('Body', 0, 0), AvatarLayer('Hat', 33, -70),
                                      AvatarLayer('RightPaw', 0, 0))
    # A common translation must not change the avatar; draw order comes from the prefab.
    for child in bob.m_Children:
        child.read().m_AnchoredPosition.x += 100
        child.read().m_AnchoredPosition.y -= 40
    bob.m_Children.reverse()
    assert [layer.name for layer in avatar_layout(objects)] == ['RightPaw', 'Hat', 'Body']
    assert avatar_layout(objects)[1] == AvatarLayer('Hat', 33, -70)


def test_hat_position_front_paw_occlusion_and_tall_tip(prefab, sprites):
    image = compose_avatar(sprites, avatar_layout(prefab[1]), 'Fixture', 'FixtureHat')
    assert image.size == (256, 256)
    # The complete 289 x 326 layout is centered in a 326-square and fitted to 256.
    def pixel(x, y):
        return image.getpixel((round((x + 18) * 256 / 326), round((y + 70) * 256 / 326)))
    assert pixel(118, 110) == (255, 0, 0, 255)  # Hat above body, shifted right.
    assert pixel(130, 145) == (0, 0, 255, 255)  # Front paw covers the hat.
    assert pixel(90, 180) == (0, 128, 0, 255)  # Old hat position now shows the body.
    assert pixel(128, -64) == (255, 0, 0, 255)  # Negative-Y tip was not cropped.


def test_no_hat_preserves_skin_pixels_and_size(prefab, sprites):
    expected = Image.alpha_composite(sprites['FixtureLeft'].m_RD.texture.read().image,
                                    sprites['FixtureRight'].m_RD.texture.read().image)
    actual = compose_avatar(sprites, avatar_layout(prefab[1]), 'Fixture', None)
    assert actual.size == expected.size
    assert actual.tobytes() == expected.tobytes()


@pytest.mark.parametrize('problem', ['missing', 'duplicate', 'preview', 'missing_layer', 'duplicate_layer',
                                    'rotation', 'scale', 'size', 'anchor', 'pivot', 'nan', 'far'])
def test_unknown_layout_is_rejected(prefab, problem):
    bob, objects = prefab
    hat = bob.m_Children[1].read()
    if problem == 'missing':
        objects.clear()
    elif problem == 'duplicate':
        objects.append(reader('RectTransform', bob))
    elif problem == 'preview':
        bob.m_Father = pointer(transform('Preview'))
    elif problem == 'missing_layer':
        bob.m_Children.pop()
    elif problem == 'duplicate_layer':
        bob.m_Children.append(pointer(hat))
    elif problem == 'rotation':
        hat.m_LocalRotation.z = .5
    elif problem == 'scale':
        hat.m_LocalScale.x = 2
    elif problem == 'size':
        hat.m_SizeDelta.y = 64
    elif problem == 'anchor':
        hat.m_AnchorMin.x = 0
    elif problem == 'pivot':
        hat.m_Pivot.y = 0
    elif problem == 'nan':
        hat.m_AnchoredPosition.x = float('nan')
    elif problem == 'far':
        hat.m_AnchoredPosition.x = 10000
    with pytest.raises(ValueError):
        avatar_layout(objects)


@pytest.mark.parametrize('problem', ['missing', 'ambiguous', 'size', 'rect_offset'])
def test_unknown_sprites_are_rejected(prefab, sprites, problem):
    if problem == 'missing':
        del sprites['FixtureHat']
    elif problem == 'ambiguous':
        sprites['FixtureHat'] = None
    elif problem == 'size':
        sprites['FixtureHat'] = sprite(Image.new('RGBA', (128, 128)))
    elif problem == 'rect_offset':
        sprites['FixtureHat'].m_Rect.x = 1
    with pytest.raises(ValueError):
        compose_avatar(sprites, avatar_layout(prefab[1]), 'Fixture', 'FixtureHat')


def test_worker_caches_composed_png_without_game_access(prefab, sprites, monkeypatch, tmp_path):
    objects = prefab[1]
    for name, value in sprites.items():
        value.m_Name = name
        objects.append(reader('Sprite', value))
    monkeypatch.setitem(sys.modules, 'UnityPy', NS(load=lambda *args: NS(objects=objects)))
    avatars = Avatars(tmp_path)
    try:
        deadline = time.monotonic() + 5
        result = None
        while result is None and time.monotonic() < deadline:
            result = avatars.get('Fixture', 'FixtureHat')
            time.sleep(.01)
        assert avatars.stage == 'ready' and avatars.error == ''
        assert result is not None
        image = Image.open(BytesIO(base64.b64decode(result.split(',', 1)[1])))
        expected = compose_avatar(sprites, avatar_layout(objects), 'Fixture', 'FixtureHat')
        assert image.tobytes() == expected.tobytes()
        assert avatars.get('Fixture', 'FixtureHat') == result
    finally:
        avatars.close()
