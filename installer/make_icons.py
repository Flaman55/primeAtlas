"""
make_icons.py -- regenerates primeatlas/core/assets/ from the master artwork
(primeatlas/core/assets/primeatlas_icon_source.png, 1024x1024, transparent background):

  primeatlas.ico          16/20/24/32/40/48/64/128/256 px -- every size Windows picks from
                          across DPI settings (window, taskbar, shortcuts, installer)
  primeatlas_256.png      Tk iconphoto fallback (non-Windows, or iconbitmap failing)
  primeatlas_<N>.rgba     raw RGBA for the ring_viz GLFW window (N = 16, 32, 48), so the
                          renderer needs no Pillow just to set its icon

Pass a new artwork file to replace the master first; it is cleaned (faint edge specks
dropped, near-opaque body made fully opaque), cropped to its visible content, padded
square and scaled to 1024 px.

Needs Pillow (a build-time tool only -- the app itself never needs it for the icon).

Usage:
    python installer/make_icons.py [NEW_ARTWORK.png]
"""
import os
import sys

from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(REPO_ROOT, "primeatlas", "core", "assets")
MASTER = os.path.join(ASSETS_DIR, "primeatlas_icon_source.png")
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
RGBA_SIZES = (16, 32, 48)


def normalize(artwork_path):
    src = Image.open(artwork_path).convert("RGBA")
    # Faint specks around the edge -> fully transparent; the near-opaque body (generated
    # artwork often stops at alpha ~253) -> fully opaque, so the icon never looks washed out.
    alpha = src.getchannel("A").point(lambda v: 0 if v < 24 else (255 if v >= 232 else v))
    src.putalpha(alpha)
    crop = src.crop(alpha.getbbox())
    side = max(crop.size)
    pad = round(side * 0.02)
    square = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    square.paste(crop, ((square.width - crop.width) // 2, (square.height - crop.height) // 2), crop)
    return square.resize((1024, 1024), Image.LANCZOS)


def main():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    if len(sys.argv) > 1:
        normalize(sys.argv[1]).save(MASTER, optimize=True)
        print(f"master  {os.path.relpath(MASTER, REPO_ROOT)}")
    master = Image.open(MASTER).convert("RGBA")

    master.save(os.path.join(ASSETS_DIR, "primeatlas.ico"), sizes=[(s, s) for s in ICO_SIZES])
    master.resize((256, 256), Image.LANCZOS).save(
        os.path.join(ASSETS_DIR, "primeatlas_256.png"), optimize=True)
    for size in RGBA_SIZES:
        with open(os.path.join(ASSETS_DIR, f"primeatlas_{size}.rgba"), "wb") as f:
            f.write(master.resize((size, size), Image.LANCZOS).tobytes())
    print(f"wrote   {os.path.relpath(ASSETS_DIR, REPO_ROOT)}")


if __name__ == "__main__":
    main()
