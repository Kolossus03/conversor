"""Draws the app icon (src/conversor/qml/icon.png + icon.ico)."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
grad = Image.new("RGBA", (S, S))
px = grad.load()
for y in range(S):
    for x in range(S):
        f = (x + y) / (2 * S)
        px[x, y] = (int(91 + (163 - 91) * f), int(108 + (91 - 108) * f), 240, 255)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((40, 40, S - 40, S - 40), radius=230, fill=255)
icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
icon.paste(grad, mask=mask)
d = ImageDraw.Draw(icon)
w = 70
# upper arrow pointing right, lower arrow pointing left
d.line((260, 400, 740, 400), fill="white", width=w)
d.polygon([(780, 400), (640, 290), (640, 510)], fill="white")
d.line((284, 624, 764, 624), fill="white", width=w)
d.polygon([(244, 624), (384, 514), (384, 734)], fill="white")
out = Path(__file__).resolve().parent.parent / "src" / "conversor" / "qml"
icon.resize((256, 256), Image.Resampling.LANCZOS).save(out / "icon.png")
icon.save(out / "icon.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
print("written", out)
