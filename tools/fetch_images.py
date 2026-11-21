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
    """barcodelookup.com v3.

    Their quota is only deducted on a 200, so products they do not hold cost
    nothing -- a probe is charged for its hits alone. The ceiling is 100
    requests a minute. A miss is a 404, not an empty body, so it has to be
    caught here or every miss would count as an error and skew the probe.

    Their images are served from images.barcodelookup.com rather than pointing
    at a retailer's CDN, which is a better footing than hotlinked store
    photography -- still read their terms before republishing.
    """
    name = "barcodelookup"
    key_env = "BARCODE_LOOKUP_KEY"
    # Their cheapest plan is $99/month for 5,000 calls, so about $0.02 a call
    # -- but it is a monthly subscription, not metered. Filling this book is a
    # ~971-call one-off, which means the real price is $99 for one month and a
    # reminder to cancel, not $20 of usage.
    cost = 99.0 / 5000
    pause = 0.7           # ~85/min, under their 100/min ceiling
    URL = "https://api.barcodelookup.com/v3/products?barcode=%s&formatted=y&key=%s"

    def images(self, upc):
        try:
            d = json.loads(fetch(self.URL % (upc, read_key(self.key_env))))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False, []          # not in their catalogue, and not billed
            if e.code == 403:
                raise SystemExit("barcodelookup rejected the key (403). "
                                 "Check BARCODE_LOOKUP_KEY / tools/api_keys.json.")
            raise
        prods = d.get("products") or []
        if not prods:
            return False, []
        return True, prods[0].get("images", []) or []


class OpenFoodFacts(Provider):
    """Open Food Facts. Free, no key, no subscription, and the images are
    contributor photographs under CC-BY-SA rather than a retailer's
    copyrighted studio shots -- the best licensing position of anything here,
    as long as the attribution in the README stays.

    They ask for an identifying User-Agent and reasonable pacing; 100/min is
    their published guidance for product queries.
    """
    name = "openfoodfacts"
    cost = 0.0
    pause = 2.5   # they throttle well below their published 100/min
    URL = ("https://world.openfoodfacts.org/api/v2/product/%s.json"
           "?fields=product_name,image_front_url,image_url")

    def images(self, upc):
        try:
            d = json.loads(fetch(self.URL % upc))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False, []
            raise
        if d.get("status") == 0 or not d.get("product"):
            return False, []
        p = d["product"]
        urls = [u for u in (p.get("image_front_url"), p.get("image_url")) if u]
        return True, urls


PROVIDERS = {p.name: p for p in [UpcItemDb(), BarcodeLookup(), OpenFoodFacts()]}


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
    # tried is per provider: one catalogue not holding a product says nothing
    # about another, and a shared list would make the second skip it
    s.setdefault("tried", {})     # provider -> {upc: "ok" | "none" | "error"}
    if s["tried"] and all(not isinstance(v, dict) for v in s["tried"].values()):
        s["tried"] = {"upcitemdb": s["tried"]}      # migrate the flat old shape
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

    found = withimg = errors = tested = 0
    print("  sampling %d of %d bottles via %s\n" % (len(pick), len(usable), prov.name))
    for b in pick:
        try:
            ok, imgs = prov.images(b["u"])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # stop, and score only what was actually asked -- dividing by the
                # full sample here would understate coverage and wrongly condemn
                # a provider that was merely throttled
                print("  rate limited after %d lookups -- scoring those only" % tested)
                break
            errors += 1
            continue
        except Exception:
            errors += 1
            continue
        tested += 1
        if ok:
            found += 1
        if imgs:
            withimg += 1
        print("  %-3s %-44s %s" % ("img" if imgs else ("--" if ok else "no"),
                                   b["n"][:44], b["u"]))
        time.sleep(prov.pause)

    done = max(1, tested)
    if tested < len(pick):
        print("\n  (sample cut short at %d of %d)" % (tested, len(pick)))
    print("\n  in catalogue : %d of %d" % (found, done))
    print("  with a photo : %d of %d  (%.0f%%)" % (withimg, done, 100.0 * withimg / done))
    if errors:
        print("  errors       : %d" % errors)
    if prov.cost:
        total = len([b for b in bottles if b.get("u")])
        hits = total * found / done          # vendors bill for hits, not misses
        print("  filling the book at this rate: about %d usable photos, about $%.2f"
              % (total * withimg / done, hits * prov.cost))
        if prov.name == "barcodelookup":
            print("  (but their floor is a $99/month plan, so the real cost is")
            print("   $99 for one month and a note to cancel it)")
    if withimg * 1.0 / done < 0.5:
        print("\n  Under half. Not worth paying for -- the gap is catalogue coverage,")
        print("  which a bigger plan does not fix. Try another provider or use")
        print("  supplier images via tools/incoming/.")


def from_api(bottles, state, limit, prov):
    # most-played brands first, so coverage is felt soonest
    weight = {}
    for b in bottles:
        weight[b["b"]] = weight.get(b["b"], 0) + 1
    seen = state["tried"].setdefault(prov.name, {})
    todo = [b for b in bottles
            if b.get("u") and not have(b["u"]) and b["u"] not in seen]
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
            seen[upc] = "error"
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

        seen[upc] = "ok" if saved else "none"
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
