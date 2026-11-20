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
}

KEEP_UPPER = {"XO","VS","VSOP","XXO","XXL","NA","RTD","IPA","USA","DIY","VMC","LBV"}
SIZES_OK = {"750ML","1.75L","1L","375ML","700ML","355ML","500ML"}

def clean_item(item, brand):
    s = item.upper().strip()
    # cut at the container word — everything after is packaging/proof/size
    m = re.search(r"\s+(?:%s)\b" % "|".join(CONTAINERS), s)
    if m:
        s = s[:m.start()]
    # strip trailing proof + size if no container word was present
    s = re.sub(r"\s*(<|>)?\d+(\.\d+)?(-\d+)?\+?\s*PROOF.*$", "", s)
    s = re.sub(r"\s*\d+(\.\d+)?(ML|L)\s*$", "", s)
    s = re.sub(r"\s*\d+\s*PK\s*$", "", s)
    def one(w):
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
        if re.fullmatch(r"\d+", w) or re.fullmatch(r"\d+P", w):
            return ""
        if "'" in w:
            head, _, tail = w.partition("'")
            return head.capitalize() + "'" + tail.lower()
        if "-" in w:
            return "-".join(one(p) or p.capitalize() for p in w.split("-"))
        return w.capitalize()

    words = [x for x in (one(w) for w in s.split()) if x]
    name = " ".join(words)
    name = re.sub(r"\s{2,}", " ", name).strip(" -&")
    return name or brand.title()

def title_brand(b):
    out = []
    for w in b.upper().split():
        if w in KEEP_UPPER: out.append(w)
        elif "'" in w:
            h,_,t = w.partition("'"); out.append(h.capitalize()+"'"+t.lower())
        elif "-" in w: out.append("-".join(p.capitalize() for p in w.split("-")))
        else: out.append(w.capitalize())
    return " ".join(out)

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
bank, skipped = [], collections.Counter()
for r in rows:
    try:
        price = float(r["avg_retail_price"]); accts = int(r["num_accounts"])
    except ValueError:
        skipped["bad number"] += 1; continue
    if r["size"] not in SIZES_OK: skipped["size"] += 1; continue
    if accts < 10:                skipped["thin distribution"] += 1; continue
    if not (4.0 <= price <= 400): skipped["price outlier"] += 1; continue
    bank.append({
        "i": len(bank),
        "c": CAT_LABEL.get(r["category"], r["category"].title()),
        "b": title_brand(r["brand"]),
        "n": clean_item(r["item"], r["brand"]),
        "s": r["size"].replace("ML", "mL").replace("1.75L", "1.75L"),
        "p": round(price, 2),
        "t": TIER_LABEL.get(r["price_tier"], r["price_tier"].title()),
        "f": proof_of(r["item"]),
        "a": accts,
    })

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("// Generated from 'Average Price Checker.csv' — do not edit by hand.\n")
    fh.write("// i=index c=category b=brand n=name s=size p=avg retail price t=tier f=proof a=accounts\n")
    fh.write("window.BOTTLES = ")
    json.dump(bank, fh, ensure_ascii=False, separators=(",", ":"))
    fh.write(";\n")

print("kept:", len(bank), "| skipped:", dict(skipped))
print("size on disk:", round(os.path.getsize(OUT)/1024, 1), "KB")
print("categories:", dict(collections.Counter(b["c"] for b in bank)))
print()
for b in bank[::90]:
    print(f"  {b['c']:<20} {b['b']:<22} {b['n']:<46} {b['s']:<7} ${b['p']:<7} {b['t']}")
