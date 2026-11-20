"""Generate the app icons for price check.

A soft lavender -> mint -> cream wash (the home-screen hero gradient) with a
heavy dark dollar glyph, drawn at 4x and downsampled so the edges stay clean.
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = "C:/Users/admin/OneDrive/Documents/Claude/Claude/Price Checker/app/icons"
G1 = (220, 216, 242)   # lavender
G2 = (204, 229, 218)   # mint
G3 = (243, 234, 218)   # cream
INK = (18, 18, 17)

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\seguibl.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
]


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def wash(size):
    """Diagonal three-stop gradient."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x / (size - 1) * 0.55 + y / (size - 1) * 0.45)
            px[x, y] = lerp(G1, G2, t / 0.52) if t <= 0.52 else lerp(G2, G3, (t - 0.52) / 0.48)
    return img


def pick_font(px):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, px)
            except OSError:
                continue
    return ImageFont.load_default()


def glyph(size, inset):
    """Draw the $ centred, occupying `inset` of the canvas height."""
    S = size * 4
    img = wash(S).convert("RGBA")
    d = ImageDraw.Draw(img)
    f = pick_font(int(S * inset))
    box = d.textbbox((0, 0), "$", font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text((S / 2 - w / 2 - box[0], S / 2 - h / 2 - box[1]), "$", font=f, fill=INK)
    return img.resize((size, size), Image.LANCZOS).convert("RGB")


def rounded(img, radius_frac=0.2237):
    """iOS-style squircle-ish corner mask, for the non-maskable icons."""
    size = img.size[0]
    S = size * 4
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * radius_frac), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


os.makedirs(OUT, exist_ok=True)

# apple-touch-icon: iOS applies its own mask, so ship it square and full-bleed
glyph(180, 0.56).save(os.path.join(OUT, "icon-180.png"))
rounded(glyph(192, 0.56)).save(os.path.join(OUT, "icon-192.png"))
rounded(glyph(512, 0.56)).save(os.path.join(OUT, "icon-512.png"))
# maskable: keep the glyph inside the 80% safe zone
glyph(512, 0.40).save(os.path.join(OUT, "icon-maskable-512.png"))

for n in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, n)
    print("  {:28s} {:>7,} bytes".format(n, os.path.getsize(p)))
