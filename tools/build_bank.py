import csv, json, re, os, collections

SRC = "C:/Users/admin/OneDrive/Documents/Claude/Claude/Price Checker/Average Price Checker.csv"
OUT = "C:/Users/admin/OneDrive/Documents/Claude/Claude/Price Checker/docs/data/bottles.js"

CONTAINERS = ("GLASS","PLASTIC","ALUMINUM","CAN","TETRA","POUCH","BOX","CARTON","PET","ALUM")

ABBR = {
 "WSKY":"Whiskey","WSK":"Whiskey","WHSKY":"Whiskey","BRBN":"Bourbon","CNDN":"Canadian",
 "STRT":"Straight","SNGL":"Single","SNG":"Single","BRL":"Barrel","RSV":"Reserve","RSRV":"Reserve",
 "RESV":"Reserve","TQLA":"Tequila","RPSDO":"Reposado","ANEJO":"Anejo","CRDL":"Cordial",
 "CRDLS":"Cordials","LQR":"Liqueur","LIQ":"Liqueur","VDK":"Vodka","CK":"Cocktail","CKTL":"Cocktail",
 "SLTZR":"Seltzer","SELTZ":"Seltzer","ASST":"Assorted","REG":"Original","ORIG":"Original",
 "WHT":"White","BLK":"Black","BLU":"Blue","TRPL":"Triple","SEC":"Sec","DBL":"Double",
 "ESPL":"Especial","CCNT":"Coconut","TRPCL":"Tropical","INFRN":"Inferno","CNDY":"Candy",
 "GRPFRT":"Grapefruit","STRWBRY":"Strawberry","RSPBRY":"Raspberry","WTRMLN":"Watermelon",
 "PNAPPL":"Pineapple","PNCH":"Punch","MRGRTA":"Margarita","MRGRT":"Margarita","LMNDE":"Lemonade",
 "CHRY":"Cherry","PCH":"Peach","APL":"Apple","ORNG":"Orange","VNLA":"Vanilla","CRML":"Caramel",
 "CNNMN":"Cinnamon","CHOC":"Chocolate","XTRA":"Extra","SPCL":"Special","CLSC":"Classic",
 "PREM":"Premium","SLV":"Silver","GLD":"Gold","PLTNM":"Platinum","CRYSTL":"Crystal",
 "AMER":"American","IRSH":"Irish","SCTCH":"Scotch","JAPNS":"Japanese","CRBBN":"Caribbean",
 "LND":"London","BTNCL":"Botanical","DSTLD":"Distilled","BTLD":"Bottled","BNDD":"Bonded",
 "NA":"Non-Alcoholic","ALC":"Alcohol","MLT":"Malt","GRN":"Grain","HNY":"Honey","GNGR":"Ginger",
 "MNT":"Mint","LME":"Lime","LMN":"Lemon","BRY":"Berry","MXD":"Mixed","VRTY":"Variety",
 "VAP":"Gift Set","GFT":"Gift","LTD":"Limited","EDTN":"Edition","AGD":"Aged","FNSH":"Finished",
 # second pass — the long tail that still read as consonant soup
 "BLND":"Blend","BLNCO":"Blanco","BRB":"Bourbon","BRNDY":"Brandy","BRDY":"Brandy",
 "SLVR":"Silver","CRM":"Cream","LBL":"Label","SCT":"Scotch","PLM":"Plum",
 "STRBRY":"Strawberry","PRVT":"Private","KMMR":"Kammer","KRCH":"Kirsch","KRSCH":"Kirsch",
 "PPMT":"Peppermint","DSTLR":"Distillers","DSTLRY":"Distillery","SPK":"Sparkling",
 "SPC":"Spice","SPCD":"Spiced","GRND":"Grand","SGNTR":"Signature","MRLS":"Morales",
 "PNK":"Pink","WTNY":"Whitney","LMND":"Lemonade","GNTLMN":"Gentleman","SGL":"Single",
 "SHRY":"Sherry","JPN":"Japanese","PRF":"Proof","OVRPRF":"Overproof","FRST":"Forest",
 "RFRNC":"Reference","SHNPS":"Schnapps","SCHNPS":"Schnapps","WLKR":"Walker","CLD":"Cold",
 "WLM":"Williams","FTZGERALD":"Fitzgerald","BND":"Bonded","ANNIV":"Anniversary",
 "SLJIVOVICA":"Slivovitz","OVRPRF.":"Overproof",
 # third pass — the last stragglers, each checked against its source row
 "VD":"Vodka","SMKY":"Smoky","MNSHN":"Moonshine","LNDN":"London","BRW":"Brew",
 "HRM":"Hiram","HRMNY":"Harmony","VLT":"Violet","BLD":"Blood","PDN":"Pudding",
 "BNA":"Banana","TN":"Tennessee","MMS":"Mimosa","ELDRFLWR":"Elderflower",
 "ORG":"Orange","TR":"Triple",
 # fourth pass — turned up while checking image coverage; MRGTA alone was
 # mangling seven cards, and it has vowels so the consonant-soup check missed it
 "MRGTA":"Margarita","MGRTA":"Margarita","CKTL":"Cocktail","EXCLSV":"Exclusiva",
 "RSMRY":"Rosemary","CHRRY":"Cherry","CHY":"Cherry","MPL":"Maple","GLDN":"Golden",
 "MDSLD":"Mudslide","LNG":"Long","ISL":"Island","I-T":"Iced Tea","TRP":"Tropical",
 "FSHN":"Fashioned","BRTSH":"British","DMNT":"Diamante","STY":"Style",
 "WHP":"Whipped","YLW":"Yellow","CSK":"Cask","STR":"Strength","SNTR":"Sinatra",
 "SLCT":"Select","MSTR":"Master","ELDRBRRY":"Elderberry","AUTH":"Authentic",
 # fifth pass -- found by listing every token in the bank and reading the
 # consonant-heavy ones instead of waiting for each to surface. Mostly RTD
 # cans, where the POS truncation is worst: the player was shown "Cutwater
 # Strawbry Margarita" and the matcher had no "strawberry" token to work with.
 "SLVR":"Silver","CARBN":"Carbon","NEUTRL":"Neutral","CLDA":"Colada",
 "MARG":"Margarita","RTA":"Rita","CNTNRO":"Centenario","RSRVA":"Reserva",
 "ARMGNC":"Armagnac","TAYLR":"Taylor","MIDSMR":"Midsummer",
 "TRANSFN":"Transfusion","VDKRITA":"Vodkarita","LMNADE":"Lemonade",
 "SMASHD":"Smashed","WASHINGTN":"Washington","STRAWBRY":"Strawberry",
 "BLACKBRY":"Blackberry","WTRMELON":"Watermelon","GRPFRUIT":"Grapefruit",
 "GNGER":"Ginger","PNAPL":"Pineapple","ELDRFLW":"Elderflower",
 "EDCN":"Edicion","NGRA":"Negra",
 "TROP":"Tropical",
}

KEEP_UPPER = {"XO","VS","VSOP","XXO","XXL","NA","RTD","IPA","USA","DIY","VMC","LBV","TLC","DTG"}
# PHRASES expand across two words, before tokenising. "IS" cannot go in ABBR
# as Island -- it is an ordinary word everywhere else -- but "LG IS" is not.
PHRASES = {"LG IS": "LONG ISLAND"}
SIZES_OK = {"750ML","1.75L","1L","375ML","700ML","355ML","500ML"}

# Sizes held out of the game for now. 1L went at Nick's request: in a
# photograph it is indistinguishable from the 750mL of the same product,
# so the card asks the player to price a bottle they cannot tell apart
# from another one in the book. Empty this set to bring them back --
# nothing else anywhere depends on it.
EXCLUDE_SIZES = {"1L"}

# A brand has to move at least this many 9-litre cases across the whole file to
# appear at all. Below it you are asking someone to price something that barely
# exists in the market, which is guesswork rather than knowledge.
MIN_BRAND_CASES = 10.0

# An item has to be on at least this many shelves to be worth guessing.
# At 10 the book was full of things almost nobody stocks, which is a
# memory test rather than a price test. 200 keeps 613 of 853.
MIN_ACCOUNTS = 200

# Categories held out of the game. Non-alcoholic went at Nick's request:
# it sits in its own price tier (NA SPIRITS PRICE TIER) and its own
# mental model, so it was never really the same guessing game.
EXCLUDE_CATEGORIES = {"Non-Alcoholic"}

# The source file's account counts top out around 500 -- Crown Royal Apple
# 500, Patron Silver 499, Tito's 499, Jack Daniel's 499 -- so that is the
# real ceiling and the denominator for the distribution percentage shown
# on a card. Four rows exceed it and all four are bad data: BUZZBALLZ ASST
# 6PK 200ML at 972 (already out, 200ML is not a listed size), a non-alc
# 'WITHOUT' at 809, and the two Hiyo non-alcs at 578 and 554. Excluding
# non-alcoholic removes the last three, so nothing in the bank is over
# 500 -- but the app still clamps, because the next bad row will come.
MAX_ACCOUNTS = 500

SMALL = {"Of", "The", "And", "De", "Los", "Las", "La", "El", "Du", "Des", "Von"}


def nearest_99(p):
    """Snap to the closest X.99.

    Shelf prices are written .99 and players think in .99, so an average
    of 34.12 reads as a number nobody has ever seen on a shelf. Rounds
    either way to whichever .99 is closer: 34.12 -> 33.99, 34.60 ->
    34.99. Price tiers come from the source file's own column, not from
    this number, so nothing downstream shifts band.
    """
    return round(round(p - 0.99) + 0.99, 2)


def one_word(w):
    """Expand one trade abbreviation and give it sane casing."""
    if w in KEEP_UPPER:
        return w
    base = ABBR.get(w.strip(".,"))
    if base:
        return base
    # initialisms and ampersand brands keep their own casing: W.L., E&J, G-A
    if "." in w or "&" in w:
        return w
    if re.fullmatch(r"\d+YR?", w):
        return re.sub(r"YR?$", "", w) + " Year"
    # "100P" is a proof restatement and goes; a bare number is part of the name
    # (Don Julio 1942, 1800 Tequila, Courvoisier 1738) and must stay, or the
    # cards collapse into each other.
    if re.fullmatch(r"\d+P", w):
        return ""
    # hyphens first: CHI-CHI'S must split into CHI and CHI'S, or the apostrophe
    # rule swallows the whole word and gives "Chi-chi's"
    # slashes split like hyphens: "BLANCO/SLVR" fell through to
    # capitalize() and came out "Blanco/slvr"
    if "/" in w:
        return "/".join(one_word(q) or q.capitalize() for q in w.split("/"))
    if "-" in w:
        return "-".join(one_word(p) or p.capitalize() for p in w.split("-"))
    if "'" in w:
        head, _, tail = w.partition("'")
        return head.capitalize() + "'" + tail.lower()
    return w.capitalize()


def lower_small(words):
    """'Tears Of Llorona' -> 'Tears of Llorona', but never the first word."""
    return [w if i == 0 or w not in SMALL else w.lower() for i, w in enumerate(words)]


def clean_item(item, brand):
    s = item.upper().strip()
    for frm, to in PHRASES.items():
        s = re.sub(r"\b%s\b" % frm, to, s)
    # cut at the container word — everything after is packaging/proof/size
    m = re.search(r"\s+(?:%s)\b" % "|".join(CONTAINERS), s)
    if m:
        s = s[:m.start()]
    # strip trailing proof + size if no container word was present
    s = re.sub(r"\s*(<|>)?\d+(\.\d+)?(-\d+)?\+?\s*PROOF.*$", "", s)
    s = re.sub(r"\s*\d+(\.\d+)?(ML|L)\s*$", "", s)
    s = re.sub(r"\s*\d+\s*PK\s*$", "", s)
    words = lower_small([x for x in (one_word(w) for w in s.split()) if x])
    name = " ".join(words)
    name = re.sub(r"\s{2,}", " ", name).strip(" -&")
    return name or brand.title()

def title_brand(b):
    """Brands go through the same expansion as item names, so 'JIM BEAM BRBN'
    and 'JACOB'S PARDON WSKY' read properly in the volume ranking."""
    words = lower_small([x for x in (one_word(w) for w in b.upper().split()) if x])
    return " ".join(words).strip(" -&") or b.title()

def upc_check_digit(d11):
    return str((10 - sum(int(d11[i]) * (3 if i % 2 == 0 else 1) for i in range(11)) % 10) % 10)


def restore_upc(code):
    """The file's codes are real retail barcodes with the leading zeros and the
    check digit stripped (Excel's doing): TITO'S 750ML is 61994700002 here and
    619947000020 on the bottle. Pad and recompute the check digit to get back a
    valid UPC-A, which is what the product images are keyed on.

    Returns None for the ~50 rows Excel destroyed into '3.77583E+11'.
    """
    code = (code or "").strip()
    if not code.isdigit() or len(code) > 11:
        return None
    d = code.zfill(11)
    return d + upc_check_digit(d)


def pack_of(item):
    """Cans and RTDs are sold by the pack, and the pack size is the single
    biggest driver of their price -- an 8PK and an 18PK of the same Surfside
    are $17.62 and $36.17. It sits after the container word, so read it from
    the raw string before clean_item() cuts there.
    """
    m = re.search(r"\b(\d+)\s*PK\b", item.upper())
    return int(m.group(1)) if m else None


def proof_of(item):
    m = re.search(r"(<|>)?\s*(\d+)(?:-(\d+))?(\+)?\s*PROOF", item.upper())
    if not m: return None
    lo, hi = m.group(2), m.group(3)
    if hi: return f"{lo}-{hi} proof"
    if m.group(1) == "<": return f"under {lo} proof"
    if m.group(4): return f"{lo}+ proof"
    return f"{lo} proof"

CAT_LABEL = {
 "PREPARED COCKTAILS":"Prepared Cocktails","NON-ALCOHOLIC SPIRITS":"Non-Alcoholic",
 "GRAIN ALCOHOL":"Grain Alcohol","CORDIALS":"Cordials","WHISKEY":"Whiskey","TEQUILA":"Tequila",
 "RUM":"Rum","VODKA":"Vodka","GIN":"Gin","BRANDY":"Brandy","COGNAC":"Cognac",
}
TIER_LABEL = {
 "VALUE":"Value","MID":"Mid","PREMIUM":"Premium","SUPER PREM":"Super Premium",
 "ULTRA":"Ultra","LUXURY":"Luxury","NA SPIRITS PRICE TIER":"Non-Alc",
}

rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))

# Brand volume across the whole file, used both to qualify a brand for the app
# and to rank it later. Counted before any row filtering, so a brand is judged
# on everything it sells, not just the bottles that survive the other cuts.
brand_cases = collections.defaultdict(float)
for r in rows:
    try:
        brand_cases[title_brand(r["brand"])] += float(r["nine_l_cases"])
    except ValueError:
        pass
SMALL_BRANDS = {b for b, v in brand_cases.items() if v < MIN_BRAND_CASES}

kept_rows, skipped = [], collections.Counter()
for r in rows:
    try:
        price = float(r["avg_retail_price"]); accts = int(r["num_accounts"])
    except ValueError:
        skipped["bad number"] += 1; continue
    if r["size"] not in SIZES_OK: skipped["size"] += 1; continue
    if r["size"] in EXCLUDE_SIZES: skipped["size held out"] += 1; continue
    if accts < MIN_ACCOUNTS:      skipped["thin distribution"] += 1; continue
    if CAT_LABEL.get(r["category"], r["category"].title()) in EXCLUDE_CATEGORIES:
        skipped["category held out"] += 1; continue
    if not (4.0 <= price <= 400): skipped["price outlier"] += 1; continue
    if title_brand(r["brand"]) in SMALL_BRANDS:
        skipped["brand under %g cases" % MIN_BRAND_CASES] += 1; continue
    kept_rows.append({
        "c": CAT_LABEL.get(r["category"], r["category"].title()),
        "b": title_brand(r["brand"]),
        "n": clean_item(r["item"], r["brand"]),
        "s": r["size"].replace("ML", "mL"),
        "p": nearest_99(price),
        "t": TIER_LABEL.get(r["price_tier"], r["price_tier"].title()),
        "f": proof_of(r["item"]),
        "a": accts,
        "u": restore_upc(r["upc"]),
        "k": pack_of(r["item"]),
    })

# ---- one card per product -------------------------------------------------
# The file carries the same product on several rows (different UPCs or
# suppliers) at different averages -- DON JULIO 1942 ANEJO 750ML appears three
# times between $159.95 and $196.93. Two identical-looking cards with different
# right answers is an unwinnable round, so keep the most widely stocked row:
# that is the price the most shelves actually show.
by_card = collections.OrderedDict()
for row in kept_rows:
    # pack size is part of a product's identity, not a detail: an 8PK and an
    # 18PK of the same can are different products at very different prices
    k = (row["n"], row["s"], row["k"])
    cur = by_card.get(k)
    # widest distribution wins; a usable UPC breaks a tie, since that is what
    # the product image is keyed on
    if cur is None or (row["a"], row["u"] is not None) > (cur["a"], cur["u"] is not None):
        by_card[k] = row
skipped["duplicate product"] = len(kept_rows) - len(by_card)

bank = []
for row in by_card.values():
    row["i"] = len(bank)
    bank.append(row)

# ---- brand volume ranking, by category AND price segment -------------------
# Keyed on both, so the comps a player sees sit in the same price segment as
# the bottle they just guessed. Ranking Hennessy VS against the whole cognac
# category puts it next to XO, which is a different business; against the rest
# of its own tier it is a real comparison.
#
# Built from EVERY row in the file, not just the playable ones, so the ranking
# reflects real depletions rather than whatever survived the filters.
vol = collections.defaultdict(float)
for r in rows:
    try:
        cases = float(r["nine_l_cases"])
    except ValueError:
        continue
    brand = title_brand(r["brand"])
    if brand in SMALL_BRANDS:
        continue              # not in the app, so not in its comparisons either
    cat = CAT_LABEL.get(r["category"], r["category"].title())
    tier = TIER_LABEL.get(r["price_tier"], r["price_tier"].title())
    vol[(cat, tier, brand)] += cases

ranks = collections.defaultdict(list)
for (cat, tier, brand), cases in vol.items():
    ranks[cat + "|" + tier].append([brand, round(cases, 1)])
for k in ranks:
    ranks[k].sort(key=lambda x: -x[1])

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("// Generated from 'Average Price Checker.csv' — do not edit by hand.\n")
    fh.write("// i=index c=category b=brand n=name s=size p=avg retail price\n")
    fh.write("// t=tier f=proof a=accounts u=restored UPC-A (null where Excel ate it)\n")
    fh.write("// k=pack size for multipacks, null for single bottles\n")
    fh.write("window.BOTTLES = ")
    json.dump(bank, fh, ensure_ascii=False, separators=(",", ":"))
    fh.write(";\n")
    fh.write("// Brands per 'Category|Tier' segment, ranked by 9L cases: [brand, cases]\n")
    fh.write("window.BRAND_RANKS = ")
    json.dump(ranks, fh, ensure_ascii=False, separators=(",", ":"))
    fh.write(";\n")

print("kept:", len(bank), "| skipped:", dict(skipped))
print("size on disk:", round(os.path.getsize(OUT)/1024, 1), "KB")
print("categories:", dict(collections.Counter(b["c"] for b in bank)))
print()
for b in bank[::90]:
    print(f"  {b['c']:<20} {b['b']:<22} {b['n']:<46} {b['s']:<7} ${b['p']:<7} {b['t']}")
