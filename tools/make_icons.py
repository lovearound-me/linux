"""Writes the app icon in the hicolor sizes: tools/make_icons.py <dir>."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lovearound import icons  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

out = sys.argv[1]
for px in SIZES:
    folder = os.path.join(out, "%dx%d" % (px, px), "apps")
    os.makedirs(folder, exist_ok=True)
    icons.app_icon(px).write_to_png(os.path.join(folder, "me.lovearound.LoveAround.png"))
