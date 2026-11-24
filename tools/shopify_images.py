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

# Places, which belong to a style rather than to a maker. The brand test asks
# only that ONE of the brand's words appears in the listing, and "Kentucky"
# appears in hundreds of bourbon titles -- so "Kentucky Deluxe" matched
# "Bulleit Bourbon Kentucky Straight" and "willett kentucky straight bourbon",
# two different distilleries. Stripped from the BRAND tokens only: a title is
# still free to say Kentucky, and a brand whose words are all places falls
# through to the squashed-string test below.
GEO = {"kentucky", "tennessee", "canadian", "irish", "mexican", "caribbean",
       "highland", "islay", "speyside", "jalisco", "barbados", "jamaica",
       "puerto", "rico", "france", "french", "london", "dry"}

# Mutually exclusive descriptors. If both names state one from the same group
# and they differ, it is a different product however well the rest overlaps:
# Woodford Double Oaked Rye is not Woodford Double Oak Bourbon.
# A listing selling several bottles at once photographs the box, not the
# bottle, so it can never be the right picture for one card.
MULTI = ("bundle", "trio", "duo", "gift set", "collection", "variety set",
         "sampler", "combo", " & ", " and ")

# The spirit itself. Gray Whale Gin is not Gray Whale Vodka.
SPIRIT = {"tequila", "vodka", "rum", "gin", "whiskey", "cognac", "brandy"}
CAT_SPIRIT = {
    "Tequila": "tequila", "Vodka": "vodka", "Rum": "rum", "Gin": "gin",
    "Whiskey": "whiskey", "Cognac": "cognac", "Brandy": "brandy",
}

EXCLUSIVE = [
    {"bourbon", "rye", "scotch", "irish", "canadian", "tennessee"},
    {"blanco", "reposado", "anejo", "cristalino", "joven"},
    {"white", "gold", "dark", "spiced", "black", "aged"},
    {"vs", "vsop", "xo", "xxo"},
]

# Words that name a specific expression or flavour rather than describe the
# category. If the shop's title carries one and our name does not, it is a
# different bottle. The EXCLUSIVE one-sided rule below only fires inside a
# group we already share a word with, so a qualifier we had NO counterpart for
# skipped the check completely -- Captain Morgan Spiced -> Captain Morgan
# SILVER Spiced, Rum Chata Cream -> COCONUT Cream, Macallan 12 -> 12 DOUBLE
# CASK, Nolet's -> The RESERVE ($35 bottle, $700 bottle). All four scored
# above 0.85 and all four were a different bottle.
#
# Deliberately NOT here: the spirit-type words (bourbon, rye, scotch, irish,
# canadian). Our file abbreviates, so "Crown Royal Whiskey" vs "Crown Royal
# Canadian Whisky" is a good match and a one-sided rule would bin it. Those
# stay clash-only in EXCLUSIVE.
DISTINCT = {
    # age, colour and tier
    "blanco", "reposado", "anejo", "cristalino", "joven",
    "white", "gold", "dark", "spiced", "black", "aged", "silver", "platinum",
    # cask, finish and strength
    "cask", "double", "triple", "sherry", "oak", "port", "barrel", "bonded",
    # expression names
    "reserve", "manifest", "heritage", "limited", "anniversary", "vintage",
    "extra", "prestige", "select", "infusions", "another", "edition",
    # named limited expressions. A list can never be complete -- Hendrick's
    # SUNSPELL got through at 0.85 and only reading the pair caught it -- but
    # each one seen is one that cannot come back. NOT here: "original", which
    # marks the flagship ("Captain Morgan Original Spiced" IS our Captain
    # Morgan Spiced), and not "small"/"batch", which appear on both sides.
    "sunspell", "orbium", "lunar", "neptunia", "amazonia", "adora", "flora",
    "quinetum", "midsummer", "cristalino",
    # sub-brands that ride on the parent name: Sauza Silver is not
    # Sauza HORNITOS Plata, a different tier at a different price.
    "hornitos", "centenario", "familia", "coleccion",
    "sour",
    # flavours
    "coconut", "vanilla", "peach", "apple", "cherry", "mango", "pineapple",
    "strawberry", "watermelon", "grape", "orange", "lemon", "lime", "rose",
    # blackberry was missing while blueberry was here, and the bank has a
    # Crown Royal Blackberry: without it "Jack Daniels Black" and "jack
    # daniels blackberry" differ by one unguarded word
    "raspberry", "blueberry", "blackberry", "banana", "mint", "coffee", "chocolate",
    "caramel", "cinnamon", "ginger", "pear", "honey", "berry", "citrus",
    "melon", "peppermint", "salted", "pepper", "cucumber", "elderflower",
    # The ready-to-drink half of the vocabulary, which lived only in
    # rtd_match.py because that matcher was built for cans and this one was
    # not. Loosening the sums made the gap bite: "Nutrl Assorted" reached 0.91
    # against "nutrl vodka CRANBERRY seltzer variety", and "High Noon Iced Tea
    # Assorted" reached 0.92 against a "variety iced tea LAKE pack" -- both
    # real products, neither of them ours.
    "cranberry", "tangerine", "kiwi", "blood", "prickly", "passion", "pina",
    "lemonade", "limeade", "grapefruit", "tropical", "cola", "espresso",
    "gingerbread", "punch", "drop", "tang", "tease", "lemonsqueezy",
    # cocktail styles: a margarita is not a paloma
    "margarita", "martini", "paloma", "colada", "mudslide", "mule",
    "russian", "transfusion", "vodkarita", "rita", "tiki", "shirley",
    "washington", "bali",
    # co-brands and sub-lines that ride on the parent name
    "dole", "fugu", "ocean", "spray", "refreshers", "breeze",
    # a limited assortment is not the standing one
    "lake",
    # NOT here, on purpose: classic, light, golden, green, sweet, half, fruit
    # and authentic. Each reads as an expression name but each also turns up
    # as marketing boilerplate on a retailer's title, and a one-sided DISTINCT
    # word REJECTS -- the same trap as "blue", which looks like an expression
    # until you notice "100% blue agave" on half the tequila listings.
}

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
        # a stripped apostrophe leaves a bare "s" that matches every possessive
        # brand in the book -- that is how Tito's matched Hendry's
        if w in STOP or len(w) < 2:
            continue
        out.append(SYN.get(w, w))
    return out


def proof(s):
    r"""Proof statements, which identifiers() cannot see.

    "120pf" has no word boundary between the digits and the letters, so the
    \b\d+\b in identifiers() never matched it -- and Everclear Grain Alcohol
    matched "Everclear Grain Alcohol 120pf". 120 proof and 190 proof are
    different bottles with the number printed on the label.
    """
    return set(re.findall(r"\b(\d+(?:\.\d+)?)\s*(?:pf|proof)\b",
                          (s or "").lower()))


def identifiers(s):
    """Numbers left once size and pack are gone: age statements and the names
    that are numbers. Dropping these is what matched Flor de Cana Centenario
    25 Year to the 12 Year, and Belvedere Organic to Belvedere 10 Organic --
    two wrong photos on cards whose price hinges on exactly that digit.
    """
    toks = re.findall(r"\b\d+\b", strip_measures(s or "").lower())
    # "12yr" / "12 year" both reduce to 12; a bare year like 1942 stays as is
    return set(toks)


# US retailers list cans in fluid ounces, not millilitres. Without oz here,
# every RTD -- High Noon, Cutwater, Surfside, the whole 355mL category --
# parses as "no size stated" and is then refused for not being 750mL.
SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|l|liter|litre|fl\.?\s*oz|oz)\b", re.I)


def size_ml(text):
    """Return millilitres stated in a string, or None."""
    m = SIZE_RE.search(text or "")
    if not m:
        return None
    v = float(m.group(1))
    unit = re.sub(r"[\s.]", "", m.group(2).lower())
    if unit in ("l", "liter", "litre"):
        v *= 1000
    elif unit in ("oz", "floz"):
        # 12 oz -> 354.9; the trade calls that a 355mL can, so snap to 5mL
        v = round(v * 29.5735 / 5.0) * 5
    return int(round(v))


def bottle_size_ml(b):
    return size_ml(b["s"])


# "4pk", "4 pack" and "4-Pack" are the same thing
PACK_RE = re.compile(r"(\d+)\s*-?\s*(?:pk|pack)\b", re.I)


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


# Words that cost a match without telling the two products apart, removed
# from the SUMS only and never from the gates.
#
# The score is 0.45*jaccard + 0.45*coverage + 0.1*size, so a single word in
# our name that the retailer leaves out costs about 0.30 -- enough on its own
# to push a correct pair under any sane threshold:
#
#   "Pinnacle Original Vodka"       vs "Pinnacle Vodka"        0.70
#   "Bulleit Bourbon Whiskey"       vs "Bulleit Bourbon"       0.70
#   "Caravella Limoncello Cordials" vs "Caravella Limoncello"  0.70
#
# GENERIC is the category a bottle sits in rather than the maker's own words,
# so it is already the right vocabulary -- except that `bourbon` and `scotch`
# are also EXCLUSIVE[0] members, and those stay out: the gate protects a clash
# but the sums should still reward agreeing on the style.
#
# `original` joins them for the reason DISTINCT already records in its own
# comment: it marks the flagship, so "Captain Morgan Original Spiced" IS our
# Captain Morgan Spiced. The alternatives to a flagship are flavours and
# tiers, and those are guarded.
FILLER = (GENERIC - {"bourbon", "scotch"}) | {"original"}

# Words that are the same thing under two names. Folded rather than dropped,
# so a variety pack still cannot match a single-flavour one.
#
#   assorted / variety  -- our file's word against the retailers'.
#   silver / plata / blanco -- the same unaged tequila. These matter to the
#   DISTINCT tests below: without the fold, "Don Julio Silver" carries a
#   DISTINCT word that "Don Julio Blanco Tequila" lacks, and the mirror test
#   would throw away a pair that is plainly the same bottle.
SYNONYM = {"assorted": "variety", "silver": "blanco", "plata": "blanco"}

# Plural and participle forms of words that are already DISTINCT. Without
# these the mirror test reads a word form as a different product: "Woodford
# Reserve Double Oak" carries `oak`, the listing says "Double Oaked", and the
# pair is refused over a letter. Found by scanning the 143,744 listings for
# every DISTINCT word whose -ed/-s/-d variant appears on its own; no general
# stemmer, because stemming "black" and "blackberry" together is exactly the
# mistake this file keeps having to undo.
SYNONYM.update({
    "barreled": "barrel", "barrels": "barrel", "casks": "cask",
    "drops": "drop", "editions": "edition", "grapes": "grape",
    "lakes": "lake", "oaked": "oak", "oaks": "oak",
    "reserves": "reserve", "roses": "rose", "selected": "select",
})


def fold(tokens):
    """Synonyms folded together. Nothing removed."""
    return {SYNONYM.get(t, t) for t in tokens}


def squash(tokens, agreed):
    """Tokens that count toward the sums.

    Filler is dropped ONLY where it is not already agreed on. Dropping it
    everywhere made the change cut both ways: removing a word the two sides
    SHARE shrinks the intersection and the union together, so the remaining
    mismatch looms larger and the score falls.

        "Ronrico Silver Rum" vs "Ronrico Light Rum Silver Label"
        raw      inter 3 / union 5 -> 0.82
        squashed inter 2 / union 4 -> 0.78   <- lost a match it used to make

    Three of the twenty-three photographs collected an hour earlier failed
    that way. Keeping agreed filler in means the result can only ever rise:
    the intersection is unchanged and both denominators can only shrink, so
    no pair that matched before can stop matching now.
    """
    return {t for t in tokens if t not in FILLER} | agreed


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
    low = " " + (cand["title"] or "").lower() + " "
    if any(m in low for m in MULTI):
        return 0.0                      # a box of bottles, not this bottle

    bt = set(norm_tokens(b["n"]))
    # the maker's own words, not the category it sits in
    brand = set(norm_tokens(b["b"])) - GENERIC - GEO
    if not brand:
        # Brands like "E&J" reduce to single characters, which norm_tokens
        # drops -- leaving an empty set that skipped the check entirely and
        # let E&J VSOP match Shabo VSOP. Fall back to a squashed form of the
        # raw brand and look for it anywhere in the title.
        raw = re.sub(r"[^a-z0-9]", "", b["b"].lower())
        raw = re.sub(r"(brandy|whiskey|whisky|vodka|rum|gin|tequila|cognac|"
                     r"cordials?|cocktail|liqueur)$", "", raw)
        flat = re.sub(r"[^a-z0-9]", "", (cand["title"] or "").lower())
        if raw and raw not in flat:
            return 0.0
    elif not (brand & cand["tokens"]):
        return 0.0
    if not bt:
        return 0.0

    mine = CAT_SPIRIT.get(b["c"])
    theirs = cand["tokens"] & SPIRIT
    if mine and theirs and mine not in theirs:
        return 0.0                      # a gin is not a vodka
    for group in EXCLUSIVE:
        ours, theirs = bt & group, cand["tokens"] & group
        if ours and theirs and not (ours & theirs):
            return 0.0
        # one-sided qualifier: we say Reposado, they say Reposado Cristalino.
        # The sets overlap, so the clash test above passes, but a cristalino is
        # a filtered tequila and a different product at a different price.
        if ours and (theirs - ours):
            return 0.0
    # The same test, but for a qualifier there is no word of our own to
    # compare against. See DISTINCT. Both directions, because a distinctive
    # word is distinctive whichever side holds it: a retailer's listing with
    # a word we lack is a richer product than ours, and OUR name with a word
    # the listing lacks is a richer product than theirs. Only the first was
    # tested, so "Jack Daniels Tennessee Honey" matched "jack daniels
    # tennessee whiskey", "Evan Williams Black" matched plain Evan Williams,
    # and "1800 Silver Coconut" matched "1800 Silver Tequila".
    #
    # The mirror costs nothing where it is not needed: measured over every
    # bottle in the bank without a photograph, not one match at 0.84 or above
    # carries a one-sided word of ours. It bites only below that bar, which
    # is what makes a lower bar worth considering at all.
    bf, cf = fold(bt), fold(cand["tokens"])
    if (cf & DISTINCT) - bf:
        return 0.0
    if (bf & DISTINCT) - cf:
        return 0.0
    if proof(b["n"]) != proof(cand["title"]):
        return 0.0
    # Every GATE above reads the raw tokens. Only the arithmetic below reads
    # the squashed ones, so loosening the sums cannot loosen a refusal: a rye
    # against a bourbon is still EXCLUSIVE[0], a gin against a vodka is still
    # CAT_SPIRIT, and a one-sided flavour is still DISTINCT.
    bf, cf = fold(bt), fold(cand["tokens"])
    inter = bf & cf
    bts = squash(bf, inter) or bf
    cts = squash(cf, inter) or cf
    union = bts | cts
    jacc = len(inter) / float(len(union))
    covered = len(inter) / float(len(bts))  # how much of our name is accounted for
    bonus = 0.1 if (bs and bs in cand["sizes"]) else 0.0
    return min(1.0, 0.45 * jacc + 0.45 * covered + bonus)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default="woodencork.com")
    # 0.62 looked reasonable until the pairs were read end to end: below about
    # 0.9 it was matching Buffalo Trace to the Antique Collection and Jim Beam
    # Honey to Jim Beam Peach. Near-exact only.
    ap.add_argument("--min-score", type=float, default=0.95)
    ap.add_argument("--dry-run", action="store_true",
                    help="show the matches and download nothing")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--upgrade", action="store_true",
                    help="also replace photos that came from Open Food Facts. "
                         "Those are contributor snapshots -- correct products, "
                         "but often cropped or shot on a worktop -- and a "
                         "catalogue studio shot is a straight improvement.")
    args = ap.parse_args()

    bottles = load_bank()
    need = [b for b in bottles if b.get("u") and not have(b["u"])]
    print("bank: %d bottles, %d still without a photo" % (len(bottles), len(need)))

    if args.upgrade:
        # only the ones Open Food Facts supplied: never overwrite a catalogue
        # image with another, and never touch a hand-placed file
        state = os.path.join(HERE, "image_state.json")
        soft = set()
        try:
            tried = json.load(io.open(state, encoding="utf-8"))["tried"]
            soft = {u for u, s in tried.get("openfoodfacts", {}).items() if s == "ok"}
        except Exception:
            print("  no state file -- cannot tell which photos came from where")
        upg = [b for b in bottles if b.get("u") in soft and have(b["u"])]
        print("  plus %d to upgrade from Open Food Facts" % len(upg))
        need = need + upg

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
