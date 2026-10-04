"""Draw the original geometric desktop branding at every Windows icon size."""

from pathlib import Path

from PIL import IcoImagePlugin, Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "assets"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
<defs><linearGradient id="blue" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#3c82f7"/><stop offset="1" stop-color="#245bdc"/></linearGradient></defs>
<rect x="8" y="8" width="240" height="240" rx="56" fill="url(#blue)"/>
<path d="M56 97 L94 121 L128 67 L162 121 L200 97 L183 168 H73 Z" fill="white"/>
<rect x="74" y="184" width="108" height="15" rx="7.5" fill="white"/>
<circle cx="56" cy="93" r="8" fill="white"/><circle cx="128" cy="62" r="8" fill="white"/><circle cx="200" cy="93" r="8" fill="white"/>
</svg>"""


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    scale = 4
    size = 256 * scale
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((32, 32, 992, 992), radius=224, fill=255)
    icon = Image.new("RGBA", (size, size))
    pixels = icon.load()
    assert pixels is not None
    for y in range(size):
        ratio = y / (size - 1)
        color = tuple(
            round(first + (last - first) * ratio) for first, last in zip((60, 130, 247), (36, 91, 220), strict=True)
        )
        for x in range(size):
            pixels[x, y] = (*color, 255)
    icon.putalpha(mask)
    draw = ImageDraw.Draw(icon)
    draw.polygon(
        [
            (x * scale, y * scale)
            for x, y in ((56, 97), (94, 121), (128, 67), (162, 121), (200, 97), (183, 168), (73, 168))
        ],
        fill="white",
    )
    draw.rounded_rectangle((74 * scale, 184 * scale, 182 * scale, 199 * scale), radius=7.5 * scale, fill="white")
    for x, y in ((56, 93), (128, 62), (200, 93)):
        draw.ellipse(((x - 8) * scale, (y - 8) * scale, (x + 8) * scale, (y + 8) * scale), fill="white")
    icon = icon.resize((256, 256), Image.Resampling.LANCZOS)
    icon.save(ASSETS / "clash-desktop.png")
    icon.save(ASSETS / "clash-desktop.ico", sizes=[(value, value) for value in ICON_SIZES])
    (ASSETS / "clash-desktop.svg").write_text(SVG, encoding="utf-8")
    with Image.open(ASSETS / "clash-desktop.ico") as saved:
        assert isinstance(saved, IcoImagePlugin.IcoImageFile)
        assert saved.ico.sizes() == {(value, value) for value in ICON_SIZES}
    print(f"Original desktop icons saved: {ASSETS}")


if __name__ == "__main__":
    main()
