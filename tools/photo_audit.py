r"""Rank the published bottle photos worst-first, for re-shooting.

The Learn card draws a bottle at up to 330px tall against about 170px in a
round, so photographs that passed at the smaller size do not all survive the
larger one. The library was built from retailer product pages rather than
supplier media kits, so quality varies by where a file came from.

The useful question turned out not to be "which photograph is poor" but
"which one shows its own rectangle". The card puts a photo on a white tile
(.shot.has-photo), so a cut-out with real transparency and an opaque file
that happens to sit on white BOTH look seamless, while an opaque file on a
grey shelf or a dark bar paints a grey box in the middle of the card. That
is what the eye catches first, before it ever notices softness.

So files are grouped by what they do on the tile:

  cut-out        came through the library pipeline: high-resolution source,
                 background removed, alpha kept. Nothing to see.
  opaque, white  no alpha, but its own background is within a few points of
                 white, so the tile swallows it. No work needed.
  opaque, boxed  no alpha and a background that is not white. This is the
                 visible fault, and the real work list.

Within a group each signal is scored 0 (fine) to 1 (bad) and weighted:

  boxed     How far the border sits from white, and how much it varies. A
            studio sweep is flat and bright; a photograph of a shelf is
            neither. Opaque files only.
  upscale   The published file is 400px tall. Where the bottle in the master
            measured less, it was enlarged, and nothing downstream puts
            detail back. Arithmetic rather than taste, so it is trusted most.
  flat      Low contrast across the bottle's own pixels. Cut-outs only: on an
            opaque file this reads the background as much as the bottle.
  wide      A single bottle much wider than the 0.38 median holds something
            else. On the cut-outs this turned out to mean one thing almost
            every time: the supplier shot the bottle NEXT TO ITS GIFT BOX, so
            the bottle itself ends up half the width of the frame and half
            the size on the card. Not a bad photograph, but the wrong one.
            Multipacks are MEANT to be wide -- their own median is 1.00 -- so
            they are judged against that.
  thin      The opposite mis-crop: a sliver where the cut-out caught one edge
            of the bottle and nothing else.

Two things tried and thrown away, recorded so they are not tried again:

  * Colour left on the frame edge, as a test for shelf or hand surviving the
    background removal. It fired on 290 of 389, because sync_app_images crops
    every cut-out to its own alpha bounding box, so a correctly cropped
    bottle touches all four edges by construction. It measured the crop.
  * A flat penalty for having no alpha. It put nine white cartons near the
    top of the list whose borders measure 0-2 points from white: they are
    already invisible on the tile. Those nine are also the ones whose
    background removal was refused on purpose, because rembg was eating the
    artwork off a white carton -- so "republish from the master" would have
    changed nothing. Being opaque is not the fault; being a visible box is.
  * Darkness, as a signal on cut-outs. Checked against a contact sheet it was
    wrong nearly every time: Remy Martin VSOP, Tequila Rose, Buchanan's 18
    and Dalmore 12 are all dark GLASS, photographed properly. It is still
    reported as a column, because it means something on an opaque file, but
    it no longer carries weight in the score.

These scores are a triage order, not a verdict. The contact sheets are the
point: a person looking at them is still the only thing that catches a
retailer's photograph of a soccer ball.

    python photo_audit.py                 # audit + contact sheets
    python photo_audit.py --sheets 0      # numbers only
"""

import argparse
import csv
import io
import json
import os
import re

from PIL import Image, ImageStat

try:
    from PIL import ImageDraw
except ImportError:                                         # pragma: no cover
    ImageDraw = None

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "..", "docs", "img")
BANK = os.path.join(HERE, "..", "docs", "data", "bottles.js")
LIB = r"C:\Users\admin\OneDrive\Documents\Claude\Claude\Bottle Shots"
MANIFEST = os.path.join(LIB, "manifest.csv")
MASTERS = os.path.join(LIB, "masters")
OUT_DIR = os.path.join(HERE, "..", "Photo Audit")

CARD_H = 330                 # the tallest the Learn card ever draws one

# every threshold below was measured off the 389 published files
SINGLE_WIDE = (0.70, 1.10)   # single bottles: median 0.38, p90 0.67
PACK_WIDE = (1.35, 1.80)     # multipacks: median 1.00, p90 1.41
THIN = 0.24                  # only 5 files sit below it
WHITE_OK = 12                # border within this of white vanishes on the tile
SIGNALS = ("boxed", "upscale", "flat", "dark", "wide", "thin")


def bank():
    src = io.open(BANK, encoding="utf-8").read()
    rows = json.loads(re.search(r"window\.BOTTLES = (\[.*?\]);", src, re.S).group(1))
    return {r["u"]: r for r in rows if r.get("u")}


def manifest():
    out = {}
    if os.path.exists(MANIFEST):
        with io.open(MANIFEST, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("upc12"):
                    out[r["upc12"]] = r
    return out


def master_bottle_height(rec):
    """How tall the bottle itself stood in the master, in pixels.

    The manifest records the master's frame, usually square with a lot of air
    around the bottle. sync_app_images crops to the alpha bounding box before
    scaling, so the bounding box is what actually got enlarged.
    """
    if not rec:
        return None
    path = os.path.join(MASTERS, rec.get("filename", ""))
    if not os.path.exists(path):
        return None
    try:
        with Image.open(path) as im:
            bb = im.convert("RGBA").getbbox()
            return (bb[3] - bb[1]) if bb else None
    except Exception:
        return None


def border_stats(im, band=4):
    """How far the outer frame sits from white, and how much it varies."""
    w, h = im.size
    rgb = im.convert("RGB")
    px = []
    for box in ((0, 0, w, band), (0, h - band, w, h),
                (0, 0, band, h), (w - band, 0, w, h)):
        px.extend(list(rgb.crop(box).getdata()))
    n = len(px) or 1
    mean = [sum(p[i] for p in px) / float(n) for i in range(3)]
    dist = 255 - min(mean)
    var = (sum((p[0] - mean[0]) ** 2 + (p[1] - mean[1]) ** 2 +
               (p[2] - mean[2]) ** 2 for p in px) / float(n)) ** 0.5
    return dist, var


def measure(path):
    with Image.open(path) as im:
        has_alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
        rgba = im.convert("RGBA")
        w, h = rgba.size
        a = rgba.getchannel("A")
        grey = rgba.convert("RGB").convert("L")

        mask = a.point(lambda v: 255 if v > 160 else 0)
        px = mask.histogram()[255]
        if px < 200:
            mask = None                 # no usable alpha: judge the whole frame

        st = ImageStat.Stat(grey, mask)
        dist, var = border_stats(rgba)
        return {"w": w, "h": h, "alpha": has_alpha,
                "mean": st.mean[0], "sd": st.stddev[0],
                "border_white": dist, "border_var": var}


def ramp(v, lo, hi):
    return max(0.0, min(1.0, (v - lo) / float(hi - lo)))


def kind_of(m):
    if m["alpha"]:
        return "cut-out"
    if m["border_white"] < WHITE_OK and m["border_var"] < 14:
        return "opaque, white"
    return "opaque, boxed"


def score(m, up, is_pack, kind):
    s = dict((k, 0.0) for k in SIGNALS)
    s["upscale"] = 0.0 if not up else ramp(CARD_H - up, 0, CARD_H)

    if kind == "cut-out":
        # on an opaque file these read the background as much as the bottle,
        # which would double-count whatever `boxed` already caught
        s["flat"] = ramp(46 - m["sd"], 0, 46)
        s["dark"] = ramp(150 - m["mean"], 0, 150)
    else:
        s["boxed"] = max(ramp(m["border_white"], WHITE_OK, 170),
                         ramp(m["border_var"], 14, 90))

    ratio = m["w"] / float(m["h"])
    lo, hi = PACK_WIDE if is_pack else SINGLE_WIDE
    s["wide"] = ramp(ratio, lo, hi)
    s["thin"] = 0.0 if is_pack else ramp(THIN - ratio, 0, 0.08)

    # no weight on `dark`: see the docstring. It survives as a column only.
    s["total"] = round(2.2 * s["boxed"] + 2.0 * s["upscale"] + 1.4 * s["flat"] +
                       1.2 * s["wide"] + 1.2 * s["thin"], 3)
    return s


def sheet(rows, path, title, cols=6, cell_h=300, pad=14):
    cell_w = int(cell_h * 0.72)
    label = 34
    nrows = (len(rows) + cols - 1) // cols
    W = cols * (cell_w + pad) + pad
    H = nrows * (cell_h + label + pad) + pad + 26
    out = Image.new("RGB", (W, H), (244, 243, 240))
    d = ImageDraw.Draw(out)
    d.text((pad, 8), title, fill=(18, 18, 17))

    for i, r in enumerate(rows):
        cx = pad + (i % cols) * (cell_w + pad)
        cy = 26 + pad + (i // cols) * (cell_h + label + pad)
        # the card's own white tile, so a grey box shows here exactly as there
        d.rectangle([cx, cy, cx + cell_w, cy + cell_h],
                    fill=(255, 255, 255), outline=(230, 227, 221))
        try:
            with Image.open(r["path"]) as im:
                im = im.convert("RGBA")
                k = min((cell_w - 12) / float(im.width),
                        (cell_h - 12) / float(im.height))
                im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                               Image.LANCZOS)
                out.paste(im, (cx + (cell_w - im.width) // 2,
                               cy + (cell_h - im.height) // 2), im)
        except Exception:
            d.text((cx + 8, cy + 8), "unreadable", fill=(163, 59, 46))
        d.text((cx + 2, cy + cell_h + 4), "%.2f  %s" % (r["score"]["total"], r["why"]),
               fill=(18, 18, 17))
        d.text((cx + 2, cy + cell_h + 17), r["name"][:30], fill=(108, 105, 97))
    out.save(path, quality=88)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheets", type=int, default=48,
                    help="how many of the worst per group to sheet (0 for none)")
    args = ap.parse_args()

    bk, mf = bank(), manifest()
    os.makedirs(OUT_DIR, exist_ok=True)

    rows = []
    for fn in sorted(os.listdir(IMG)):
        if not fn.endswith(".webp"):
            continue
        upc = fn[:-5]
        b = bk.get(upc)
        if not b:
            continue                      # published, but no longer in the bank
        path = os.path.join(IMG, fn)
        m = measure(path)
        rec = mf.get(upc)
        up = master_bottle_height(rec)
        kind = kind_of(m)
        s = score(m, up, bool(b.get("k")), kind)
        why = ",".join(k for k in SIGNALS if s[k] > 0.45) or "-"
        rows.append({
            "upc": upc, "path": path, "name": b["n"], "brand": b["b"],
            "cat": b["c"], "size": b["s"], "price": b["p"], "pack": b.get("k") or "",
            "src": (rec or {}).get("source_site", ""),
            "bg": (rec or {}).get("bg_removed", ""),
            "has_master": up is not None,
            "bottle_px": up, "m": m, "kind": kind, "score": s, "why": why,
        })

    rows.sort(key=lambda r: -r["score"]["total"])
    cut = [r for r in rows if r["kind"] == "cut-out"]
    white = [r for r in rows if r["kind"] == "opaque, white"]
    boxed = [r for r in rows if r["kind"] == "opaque, boxed"]

    print("%d published photos of bottles in the bank\n" % len(rows))
    print("  %3d cut-outs from the library pipeline" % len(cut))
    print("  %3d opaque, but already white enough to vanish on the tile" % len(white))
    print("  %3d opaque with a visible rectangle  <- the work list" % len(boxed))
    held = [r for r in rows if r["bg"].startswith("none")]
    if held:
        print("\n  (%d of the opaque ones had background removal refused on purpose,"
              % len(held))
        print("   because it was eating the artwork off a white carton. %d of those"
              % sum(1 for r in held if r["kind"] == "opaque, white"))
        print("   are already invisible on the tile and need nothing.)")
    print("")

    def table(title, group, n=20):
        if not group:
            return
        print(title)
        print("  %-5s %-42s %-8s %-9s %s" % ("score", "bottle", "bottlepx", "w x h", "why"))
        for r in group[:n]:
            print("  %-5.2f %-42s %-8s %-9s %s" % (
                r["score"]["total"], r["name"][:42], r["bottle_px"] or "-",
                "%dx%d" % (r["m"]["w"], r["m"]["h"]), r["why"]))
        print("")

    table("WORST — opaque with a visible rectangle", boxed, 24)
    table("WORST — cut-outs (mostly bottle-beside-its-box, not bad photography)", cut, 14)

    counts = {}
    for r in rows:
        for k in r["why"].split(","):
            counts[k] = counts.get(k, 0) + 1
    print("flagged on each signal (above 0.45):")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print("  %-9s %d" % (k, v))

    csv_path = os.path.join(OUT_DIR, "photo_audit.csv")
    with io.open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["score", "kind", "why", "action", "brand", "product", "size",
                    "pack", "category", "avg_retail", "upc12",
                    "bottle_px_in_master", "published_w", "published_h",
                    "border_from_white", "border_variation", "mean_luma",
                    "contrast_sd", "source_site", "bg_removed"] + list(SIGNALS))
        for r in rows:
            s, m = r["score"], r["m"]
            if r["kind"] == "opaque, boxed":
                action = "collect the source again"
            elif r["kind"] == "opaque, white":
                action = "none - invisible on the tile"
            elif s["total"] >= 0.9:
                action = "better source would help"
            else:
                action = "none"
            w.writerow([s["total"], r["kind"], r["why"], action, r["brand"], r["name"],
                        r["size"], r["pack"], r["cat"], r["price"], r["upc"],
                        r["bottle_px"] or "", m["w"], m["h"],
                        round(m["border_white"], 1), round(m["border_var"], 1),
                        round(m["mean"], 1), round(m["sd"], 1), r["src"], r["bg"]] +
                       [round(s[k], 2) for k in SIGNALS])

    if args.sheets and ImageDraw:
        for name, group in (("boxed", boxed), ("cutouts", cut)):
            per = 24
            for i in range(0, min(args.sheets, len(group)), per):
                chunk = group[i:i + per]
                p = os.path.join(OUT_DIR, "worst_%s_%02d-%02d.jpg"
                                 % (name, i + 1, i + len(chunk)))
                sheet(chunk, p, "worst %s, %d-%d of %d, on the card's own white tile"
                      % (name, i + 1, i + len(chunk), len(group)))
                print("\nsheet: %s" % os.path.abspath(p))

    print("\ncsv: %s" % os.path.abspath(csv_path))


if __name__ == "__main__":
    main()
