"""Export the checked-in icon master to desktop and browser sizes (Pillow)."""
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / 'docs/design/assets/bongo-cat-chat-master.png'
UI = ROOT / 'src/bongo_chat/ui'
WINDOWS_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
FAVICON_SIZES = (16, 32, 48)


def main():
    with Image.open(MASTER) as source:
        if source.width != source.height or source.width < 256:
            raise ValueError('The icon master must be square and at least 256px')
        if source.mode != 'RGBA' or source.getextrema()[3][0] != 0:
            raise ValueError('The icon master must have a transparent background')
        image = source.copy()
    # Artwork is unchanged; only resample and encode the delivery formats.
    image.resize((256, 256), Image.Resampling.LANCZOS).save(UI / 'app-icon.png', optimize=True)
    for name, sizes in [('app-icon.ico', WINDOWS_SIZES), ('favicon.ico', FAVICON_SIZES)]:
        # DIB frames work in both Windows and the NSIS installer icon reader.
        image.save(UI / name, format='ICO', sizes=[(s, s) for s in sizes], bitmap_format='bmp')
        print(f'{name}: {", ".join(map(str, sizes))}px')


if __name__ == '__main__':
    main()
