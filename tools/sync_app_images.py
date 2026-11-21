"""Publish the Bottle Shots library into the app's docs/img/.

The library and the app drifted apart: the library held 421 cut-out masters
while docs/img/ still had 274 files, 256 of the library's never having been
published at all. Nothing connected the two, so every batch collected since
the library was created improved the library and not the game.

The app asks for `img/<restored UPC>.webp`, which is the manifest's upc12
column, so the mapping is direct.

Output is RGBA WebP trimmed to the bottle and scaled to a common height, which
is what the existing files do dimensionally (400px tall, variable width) --
except those are opaque RGB. Keeping the alpha means a cut-out sits on the
card's own background instead of carrying a white box across it.

    python sync_app_images.py              # add what is missing
    python sync_app_images.py --replace    # also overwrite existing files
    python sync_app_images.py --dry-run
"""

import argparse
import csv
import io
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = r"C:\Users\admin\OneDrive\Documents\Claude\Claude\Bottle Shots"
MASTERS = os.path.join(LIB, "masters")
MANIFEST = os.path.join(LIB, "manifest.csv")
OUT = os.path.join(HERE, "..", "docs", "img")

HEIGHT = 400          # matches what is already published
QUALITY = 82


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replace", action="store_true",
                    help="overwrite files the app already has. Worth doing: "
                         "the originals came from crowd-sourced photographs "
                         "and some are a hand holding a bottle, or a barcode.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    rows = list(csv.DictReader(io.open(MANIFEST, encoding="utf-8")))

    added = replaced = skipped = missing = 0
    for r in rows:
        upc = r["upc12"]
        if not upc:
            continue
        src = os.path.join(MASTERS, r["filename"])
        if not os.path.exists(src):
            missing += 1
            continue
        dst = os.path.join(OUT, upc + ".webp")
        exists = os.path.exists(dst)
        if exists and not args.replace:
            skipped += 1
            continue

        if not args.dry_run:
            im = Image.open(src).convert("RGBA")
            bb = im.getbbox()
            if bb:
                im = im.crop(bb)
            w, h = im.size
            if h != HEIGHT:
                im = im.resize((max(1, int(round(w * HEIGHT / float(h)))), HEIGHT),
                               Image.LANCZOS)
            im.save(dst, "WEBP", quality=QUALITY, method=6)

        if exists:
            replaced += 1
        else:
            added += 1

    total = len(os.listdir(OUT)) if os.path.isdir(OUT) else 0
    size = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT)) / 1e6
    print("added %d, replaced %d, left alone %d, master missing %d"
          % (added, replaced, skipped, missing))
    print("docs/img now %d files, %.1f MB" % (total, size))
    print("\nremember to bump CACHE in docs/sw.js")


if __name__ == "__main__":
    main()
