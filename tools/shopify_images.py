"""Pull bottle photos from a Shopify liquor retailer's public catalogue.

Shopify exposes /products.json, so a whole shop comes down in a handful of
requests instead of three or four per bottle. That is the point of this
script: against a shared request budget it is an order of magnitude cheaper
than searching per product.

The risk is not bandwidth, it is mismatching. Showing the wrong bottle is
worse than showing none, because the player prices what they see. So the
matcher is deliberately strict: size must agree when both sides state one,
pack size must agree, the brand has to appear, and the remaining words need
real overlap. Anything short of that is skipped and left to the drawn bottle.

    python tools/shopify_images.py --shop woodencork.com --dry-run
    python tools/shopify_images.py --shop woodencork.com
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_images import load_bank, save_image, have, OUTDIR   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "shopify_cache")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

STOP = {"the", "a", "an", "and", "of", "with", "by", "in", "ml", "l",
        "bottle", "bottles", "pack", "pk", "liquor", "spirits", "buy"}

# Words that name a category rather than a maker. Many brands in this file are
# literally "LALO TEQUILA" or "CUTWATER COCKTAIL", so requiring only that some
# brand word appears let "tequila" alone satisfy the check -- which is how Lalo
# Blanco ended up wearing a Cincoro bottle.
GENERIC = {"tequila", "vodka", "rum", "gin", "whiskey", "whisky", "bourbon",
           "scotch", "cognac", "brandy", "cordial", "cocktail", "liqueur",
           "seltzer", "wine", "spirits", "alcohol", "non", "alcoholic", "nonalc"}

# Mutually exclusive descriptors. If both names state one from the same group
# and they differ, it is a different product however well the rest overlaps:
# Woodford Double Oaked Rye is not Woodford Double Oak Bourbon.
EXCLUSIVE = [
    {"bourbon", "rye", "scotch", "irish", "canadian", "tennessee"},
    {"blanco", "reposado", "anejo", "cristalino", "joven"},
    {"white", "gold", "dark", "spiced", "black", "aged"},
    {"vs", "vsop", "xo", "xxo"},
]

# words that describe the same thing on both sides
SYN = {
    "whisky": "whiskey", "bourbon": "bourbon", "scotch": "scotch",
    "tequila": "tequila", "anejo": "anejo", "añejo": "anejo",
    "reposado": "reposado", "blanco": "blanco", "silver": "blanco",
    "plata": "blanco", "cognac": "cognac", "vodka": "vodka", "gin": "gin",
    "rum": "rum", "rhum": "rum", "brandy": "brandy", "liqueur": "cordial",
    "cordials": "cordial", "cordial": "cordial",
}


def strip_measures(s):
    """Remove size and pack text so their digits are not mistaken for part of
    the product's name."""
    s = SIZE_RE.sub(" ", s or "")
    s = PACK_RE.sub(" ", s)
    return s


def norm_tokens(s):
    s = strip_measures(s).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    out = []
    for w in s.split():
        if w in STOP:
            continue
        out.append(SYN.get(w, w))
    return out


def identifiers(s):
    """Numbers left once size and pack are gone: age statements and the names
    that are numbers. Dropping these is what matched Flor de Cana Centenario
    25 Year to the 12 Year, and Belvedere Organic to Belvedere 10 Organic --
    two wrong photos on cards whose price hinges on exactly that digit.
    """
    toks = re.findall(r"\b\d+\b", strip_measures(s or "").lower())
    # "12yr" / "12 year" both reduce to 12; a bare year like 1942 stays as is
    return set(toks)


SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|l|liter|litre)\b", re.I)


def size_ml(text):
    """Return millilitres stated in a string, or None."""
    m = SIZE_RE.search(text or "")
    if not m:
        return None
    v = float(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("l"):
        v *= 1000
    return int(round(v))


def bottle_size_ml(b):
    return size_ml(b["s"])


PACK_RE = re.compile(r"(\d+)\s*(?:pk|pack)\b", re.I)


def pack_of(text):
    m = PACK_RE.search(text or "")
    return int(m.group(1)) if m else None


def fetch(url, timeout=30, tries=6):
    """Back off on 429 rather than hammering a limiter."""
    delay = 20
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or n == tries - 1:
                raise
            print("    429 -- waiting %ds" % delay)
            time.sleep(delay)
            delay = min(delay * 2, 300)
    raise RuntimeError("unreachable")


def dump_catalogue(shop, max_pages=40):
    """Page through /products.json, caching each page so a rerun is free."""
    os.makedirs(CACHE, exist_ok=True)
    products, page = [], 1
    while page <= max_pages:
        path = os.path.join(CACHE, "%s-%d.json" % (shop.replace(".", "_"), page))
        if os.path.exists(path):
            raw = io.open(path, encoding="utf-8").read()
        else:
            url = "https://%s/products.json?limit=250&page=%d" % (shop, page)
            try:
                raw = fetch(url).decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                print("  page %d: HTTP %s -- stopping" % (page, e.code))
                break
            io.open(path, "w", encoding="utf-8").write(raw)
            time.sleep(1.5)
        try:
            batch = json.loads(raw).get("products", [])
        except ValueError:
            print("  page %d: not JSON -- stopping" % page)
            break
        if not batch:
            break
        products.extend(batch)
        print("  page %d: %d products (%d total)" % (page, len(batch), len(products)))
        page += 1
    return products


def index_shop(products):
    """One entry per product: tokens, size, pack, best image."""
    out = []
    for p in products:
        imgs = p.get("images") or []
        if not imgs:
            continue
        title = p.get("title") or ""
        # a variant often carries the real size
        sizes = {size_ml(title)}
        for v in (p.get("variants") or []):
            sizes.add(size_ml(v.get("title") or ""))
        sizes = {s for s in sizes if s}
        out.append({
            "title": title,
            "tokens": set(norm_tokens(title)),
            "ids": identifiers(title),
            "sizes": sizes,
            "pack": pack_of(title),
            "src": imgs[0].get("src"),
        })
    return out


def score(b, cand):
    """0..1 confidence that this shop product is this bottle."""
    bs = bottle_size_ml(b)
    if bs and cand["sizes"] and bs not in cand["sizes"]:
        return 0.0                      # a different size is a different product
    if (b.get("k") or None) != cand["pack"] and (b.get("k") or cand["pack"]):
        return 0.0                      # 4-pack is not an 18-pack
    # age statements and numeric names must agree exactly: 25 Year is not
    # 12 Year, and Belvedere 10 Organic is not Belvedere Organic
    if identifiers(b["n"]) != cand["ids"]:
        return 0.0
    bt = set(norm_tokens(b["n"]))
    # the maker's own words, not the category it sits in
    brand = set(norm_tokens(b["b"])) - GENERIC
    if brand and not (brand & cand["tokens"]):
        return 0.0
    if not bt:
        return 0.0
    for group in EXCLUSIVE:
        ours, theirs = bt & group, cand["tokens"] & group
        if ours and theirs and not (ours & theirs):
            return 0.0
    inter = bt & cand["tokens"]
    union = bt | cand["tokens"]
    jacc = len(inter) / float(len(union))
    covered = len(inter) / float(len(bt))   # how much of our name is accounted for
    bonus = 0.1 if (bs and bs in cand["sizes"]) else 0.0
    return min(1.0, 0.45 * jacc + 0.45 * covered + bonus)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default="woodencork.com")
    ap.add_argument("--min-score", type=float, default=0.62)
    ap.add_argument("--dry-run", action="store_true",
                    help="show the matches and download nothing")
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()

    bottles = load_bank()
    need = [b for b in bottles if b.get("u") and not have(b["u"])]
    print("bank: %d bottles, %d still without a photo" % (len(bottles), len(need)))

    print("\ncatalogue dump from %s:" % args.shop)
    products = dump_catalogue(args.shop)
    if not products:
        sys.exit("  got nothing -- the shop blocked us or has no public catalogue")
    shop = index_shop(products)
    print("  %d products carry an image" % len(shop))

    print("\nmatching (min score %.2f):" % args.min_score)
    scored = []
    for b in need:
        best, bestscore = None, 0.0
        for c in shop:
            s = score(b, c)
            if s > bestscore:
                best, bestscore = c, s
        if best and bestscore >= args.min_score:
            scored.append((b, best, bestscore))

    # One shop product can only be one bottle. Two of ours landing on the same
    # product means the thing that tells them apart was lost, so give it to the
    # better match and drop the other rather than show the same photo twice.
    scored.sort(key=lambda x: -x[2])
    pairs, claimed = [], set()
    for b, c, s in scored:
        key = c["title"]
        if key in claimed:
            continue
        claimed.add(key)
        pairs.append((b, c, s))
    if len(scored) != len(pairs):
        print("  dropped %d that collided on the same product" % (len(scored) - len(pairs)))
    print("  %d confident matches of %d missing\n" % (len(pairs), len(need)))
    for b, c, s in pairs[:15]:
        print("  %.2f  %-40s -> %s" % (s, b["n"][:40], c["title"][:44]))
    if len(pairs) > 15:
        print("  ... and %d more" % (len(pairs) - 15))

    if args.dry_run:
        print("\ndry run -- nothing downloaded. Check the pairs above, then rerun"
              "\nwithout --dry-run, or raise --min-score if any look wrong.")
        return

    print("\ndownloading:")
    got = 0
    for b, c, s in pairs[:args.limit]:
        try:
            w, h = save_image(fetch(c["src"], timeout=40), b["u"])
            got += 1
            print("  OK %-40s %dx%d" % (b["n"][:40], w, h))
        except Exception as e:
            print("  !! %-40s %s" % (b["n"][:40], str(e)[:36]))
        time.sleep(0.8)

    n = len([f for f in os.listdir(OUTDIR) if f.endswith(".webp")])
    print("\n+%d photos, %d total" % (got, n))


if __name__ == "__main__":
    main()
