"""Fill docs/img/ with bottle photos, named by restored UPC.

Two sources, in order of preference:

1. A drop folder, tools/incoming/. Put any images you already hold there --
   supplier media-kit shots, your own photographs -- named by UPC
   (080480280024.jpg) or by the bottle's exact name. They are resized and
   converted with no network involved. This is the best source: highest
   quality, and licensed for trade use, which scraped retail photography
   is not.

2. upcitemdb's trial endpoint, as a slow trickle. It is capped near 100 a day
   and throttles hard inside a burst, so this cannot fill 965 bottles in one
   go. The run is resumable: every UPC tried is recorded in state.json, so
   running it daily picks up where it stopped. Highest-volume brands are
   fetched first, so the bottles you see most often get pictures soonest.

Nothing here is required for the app to work. A bottle with no photo draws
itself instead.

    python tools/fetch_images.py              # drop folder, then API
    python tools/fetch_images.py --local      # drop folder only, no network
    python tools/fetch_images.py --limit 40   # smaller API batch
"""

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BANK = os.path.join(ROOT, "docs", "data", "bottles.js")
OUTDIR = os.path.join(ROOT, "docs", "img")
INCOMING = os.path.join(HERE, "incoming")
STATE = os.path.join(HERE, "image_state.json")

SIZE = 440          # longest edge; the card never shows it bigger than ~164pt
QUALITY = 82
UA = "price-check-app/1.0"
API = "https://api.upcitemdb.com/prod/trial/lookup?upc="
PAUSE = 7.0         # the trial endpoint 429s well before its stated 100/day


def load_bank():
    src = io.open(BANK, encoding="utf-8").read()
    m = re.search(r"window\.BOTTLES = (\[.*?\]);", src, re.S)
    if not m:
        sys.exit("could not read %s -- run build_bank.py first" % BANK)
    return json.loads(m.group(1))


def load_state():
    try:
        with io.open(STATE, encoding="utf-8") as fh:
            s = json.load(fh)
    except Exception:
        s = {}
    s.setdefault("tried", {})     # upc -> "ok" | "none" | "error"
    return s


def save_state(s):
    with io.open(STATE, "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent=1, sort_keys=True)


def save_image(raw, upc):
    """Normalise whatever we were handed into one small, square-ish webp."""
    im = Image.open(io.BytesIO(raw))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (255, 255, 255))
        flat.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
        im = flat
    else:
        im = im.convert("RGB")

    im.thumbnail((SIZE, SIZE), Image.LANCZOS)
    if min(im.size) < 80:
        raise ValueError("too small (%dx%d)" % im.size)

    os.makedirs(OUTDIR, exist_ok=True)
    im.save(os.path.join(OUTDIR, upc + ".webp"), "WEBP", quality=QUALITY, method=6)
    return im.size


def have(upc):
    return os.path.exists(os.path.join(OUTDIR, upc + ".webp"))


# ---------------------------------------------------------------- drop folder
def from_incoming(bottles):
    if not os.path.isdir(INCOMING):
        os.makedirs(INCOMING, exist_ok=True)
        return 0

    by_upc = {b["u"]: b for b in bottles if b.get("u")}
    by_name = {}
    for b in bottles:
        if b.get("u"):
            by_name.setdefault(b["n"].lower(), b)

    done = 0
    for fn in sorted(os.listdir(INCOMING)):
        path = os.path.join(INCOMING, fn)
        if not os.path.isfile(path):
            continue
        stem, ext = os.path.splitext(fn)
        if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
            continue

        key = re.sub(r"\D", "", stem)
        upc = None
        if key and key in by_upc:
            upc = key
        elif key.zfill(12) in by_upc:
            upc = key.zfill(12)
        else:
            hit = by_name.get(stem.lower().strip())
            if hit:
                upc = hit["u"]

        if not upc:
            print("  ?  %-44s no matching UPC or bottle name" % fn[:44])
            continue
        try:
            w, h = save_image(io.open(path, "rb").read(), upc)
            print("  OK %-44s -> %s.webp  %dx%d" % (fn[:44], upc, w, h))
            done += 1
        except Exception as e:
            print("  !! %-44s %s" % (fn[:44], str(e)[:40]))
    return done


# ----------------------------------------------------------------------- API
def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read()


def from_api(bottles, state, limit):
    # most-played brands first, so coverage is felt soonest
    weight = {}
    for b in bottles:
        weight[b["b"]] = weight.get(b["b"], 0) + 1
    todo = [b for b in bottles
            if b.get("u") and not have(b["u"]) and b["u"] not in state["tried"]]
    todo.sort(key=lambda b: (-weight[b["b"]], -b["a"]))

    if not todo:
        print("  nothing left to try -- every UPC has been attempted")
        return 0

    got = 0
    for n, b in enumerate(todo[:limit], 1):
        upc = b["u"]
        try:
            d = json.loads(fetch(API + upc))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("  rate limited after %d -- stopping, run again tomorrow" % (n - 1))
                break
            state["tried"][upc] = "error"
            print("  !! %-40s HTTP %s" % (b["n"][:40], e.code))
            time.sleep(PAUSE)
            continue
        except Exception as e:
            print("  !! %-40s %s" % (b["n"][:40], str(e)[:34]))
            time.sleep(PAUSE)
            continue

        imgs = (d.get("items") or [{}])[0].get("images", []) if d.get("items") else []
        saved = False
        for src in imgs[:4]:
            try:
                w, h = save_image(fetch(src, timeout=30), upc)
                print("  OK %-40s %s  %dx%d" % (b["n"][:40], upc, w, h))
                saved = True
                got += 1
                break
            except Exception:
                continue

        state["tried"][upc] = "ok" if saved else "none"
        if not saved:
            print("  -- %-40s %s  no usable image" % (b["n"][:40], upc))
        save_state(state)
        time.sleep(PAUSE)

    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="drop folder only, no network")
    ap.add_argument("--limit", type=int, default=60, help="max API lookups this run")
    args = ap.parse_args()

    bottles = load_bank()
    usable = [b for b in bottles if b.get("u")]
    os.makedirs(OUTDIR, exist_ok=True)

    print("bank: %d bottles, %d with a usable UPC" % (len(bottles), len(usable)))
    print("\ndrop folder (tools/incoming/):")
    local = from_incoming(bottles)
    if not local:
        print("  empty -- put supplier images here, named by UPC or bottle name")

    if not args.local:
        state = load_state()
        print("\nupcitemdb (limit %d this run):" % args.limit)
        from_api(bottles, state, args.limit)
        save_state(state)

    n = len([f for f in os.listdir(OUTDIR) if f.endswith(".webp")])
    kb = sum(os.path.getsize(os.path.join(OUTDIR, f))
             for f in os.listdir(OUTDIR) if f.endswith(".webp")) / 1024.0
    print("\n%d of %d bottles have a photo (%.1f%%), %.0f KB on disk"
          % (n, len(usable), 100.0 * n / max(1, len(usable)), kb))
    if n < len(usable):
        print("the rest draw themselves; run again tomorrow or fill tools/incoming/")


if __name__ == "__main__":
    main()
