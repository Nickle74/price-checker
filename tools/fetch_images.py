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
PAUSE = 7.0         # the free endpoint 429s well before its stated 100/day
KEYFILE = os.path.join(HERE, "api_keys.json")


# ---------------------------------------------------------------- providers
# Each provider turns a UPC into a list of candidate image URLs. Adding a paid
# one means adding a class here; nothing else in the file changes.
#
# Before paying anyone, run --probe. No vendor publishes its coverage of
# spirits, and coverage -- not price, not rate limit -- is what decides whether
# a provider is worth anything to you. upcitemdb's own docs say the free plan
# has "the same full access to our database as the paid plans", and a probe
# found Lunazul and Espolon absent from it entirely (total=0, not throttled),
# so upgrading that one buys throughput you cannot use.

def read_key(name):
    """Key from the environment, else tools/api_keys.json (gitignored)."""
    v = os.environ.get(name)
    if v:
        return v.strip()
    try:
        with io.open(KEYFILE, encoding="utf-8") as fh:
            return (json.load(fh).get(name) or "").strip() or None
    except Exception:
        return None


class Provider(object):
    name = "?"
    key_env = None
    cost = 0.0        # USD per lookup, for the probe's estimate
    pause = PAUSE

    def ready(self):
        return True if not self.key_env else bool(read_key(self.key_env))

    def why_not(self):
        return "set %s in the environment or in tools/api_keys.json" % self.key_env

    def images(self, upc):
        """-> (found_in_catalogue, [image urls])"""
        raise NotImplementedError


class UpcItemDb(Provider):
    name = "upcitemdb"
    cost = 0.0
    URL = "https://api.upcitemdb.com/prod/trial/lookup?upc="

    def images(self, upc):
        d = json.loads(fetch(self.URL + upc))
        items = d.get("items") or []
        if not items:
            return False, []
        return True, items[0].get("images", []) or []


class BarcodeLookup(Provider):
    """barcodelookup.com. Month-to-month plans; they do not publish a public
    price list, so confirm the rate with them before relying on `cost`."""
    name = "barcodelookup"
    key_env = "BARCODE_LOOKUP_KEY"
    cost = 0.005
    pause = 0.4
    URL = "https://api.barcodelookup.com/v3/products?barcode=%s&formatted=y&key=%s"

    def images(self, upc):
        d = json.loads(fetch(self.URL % (upc, read_key(self.key_env))))
        prods = d.get("products") or []
        if not prods:
            return False, []
        return True, prods[0].get("images", []) or []


PROVIDERS = {p.name: p for p in [UpcItemDb(), BarcodeLookup()]}


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


def probe(bottles, prov, sample):
    """Measure coverage on a random sample before committing money to a vendor.

    Reports three numbers that matter in order: how many of your products the
    catalogue knows at all, how many of those carry an image, and what filling
    the whole book would cost at that hit rate.
    """
    import random

    usable = [b for b in bottles if b.get("u")]
    random.seed(11)                       # same sample across providers
    pick = random.sample(usable, min(sample, len(usable)))

    found = withimg = errors = 0
    print("  sampling %d of %d bottles via %s\n" % (len(pick), len(usable), prov.name))
    for b in pick:
        try:
            ok, imgs = prov.images(b["u"])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("  rate limited after %d lookups -- partial sample" % (found + errors))
                break
            errors += 1
            continue
        except Exception:
            errors += 1
            continue
        if ok:
            found += 1
        if imgs:
            withimg += 1
        print("  %-3s %-44s %s" % ("img" if imgs else ("--" if ok else "no"),
                                   b["n"][:44], b["u"]))
        time.sleep(prov.pause)

    n = found + errors
    done = max(1, len(pick) - errors)
    print("\n  in catalogue : %d of %d" % (found, done))
    print("  with a photo : %d of %d  (%.0f%%)" % (withimg, done, 100.0 * withimg / done))
    if errors:
        print("  errors       : %d" % errors)
    if prov.cost:
        total = len([b for b in bottles if b.get("u")])
        print("  filling the book at this rate: about %d usable photos, $%.2f spent"
              % (total * withimg / done, total * prov.cost))
    if withimg * 1.0 / done < 0.5:
        print("\n  Under half. Not worth paying for -- the gap is catalogue coverage,")
        print("  which a bigger plan does not fix. Try another provider or use")
        print("  supplier images via tools/incoming/.")


def from_api(bottles, state, limit, prov):
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
            _found, imgs = prov.images(upc)
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
        time.sleep(prov.pause)

    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="drop folder only, no network")
    ap.add_argument("--limit", type=int, default=60, help="max API lookups this run")
    ap.add_argument("--provider", default="upcitemdb",
                    choices=sorted(PROVIDERS), help="which catalogue to ask")
    ap.add_argument("--probe", type=int, metavar="N",
                    help="measure coverage on N sampled bottles and stop, "
                         "downloading nothing -- run this before paying anyone")
    args = ap.parse_args()

    bottles = load_bank()
    usable = [b for b in bottles if b.get("u")]
    os.makedirs(OUTDIR, exist_ok=True)
    prov = PROVIDERS[args.provider]

    if not prov.ready():
        sys.exit("%s needs a key: %s" % (prov.name, prov.why_not()))

    print("bank: %d bottles, %d with a usable UPC" % (len(bottles), len(usable)))

    if args.probe:
        print("\ncoverage probe -- no images are saved:")
        probe(bottles, prov, args.probe)
        return

    print("\ndrop folder (tools/incoming/):")
    local = from_incoming(bottles)
    if not local:
        print("  empty -- put supplier images here, named by UPC or bottle name")

    if not args.local:
        state = load_state()
        print("\n%s (limit %d this run):" % (prov.name, args.limit))
        from_api(bottles, state, args.limit, prov)
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
