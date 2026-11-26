"""Which bottles have a usable photo, which need one, ranked by volume.

Three states, not two. "Has an image" stopped being the useful question once
the Learn card started drawing bottles at 330px: 53 of the published photos
are phone snapshots that paint their own grey rectangle on the card, and for
the purpose of going and getting a better one they belong with the missing
rather than with the done. photo_audit.py decides which is which; this reads
its verdict and joins it to the bank.

    Summary    per category: good, poor, missing
    To shoot   poor + missing in one list, biggest brands first -- the
               working list, with the UPC to name a dropped file by
    Have       the clean cut-outs, for checking what is already covered

Run photo_audit.py first; without its CSV every published photo is simply
counted as present and the workbook says so.

    python photo_audit.py && python coverage_report.py
"""

import csv
import io
import json
import os
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
BANK = os.path.join(HERE, "..", "docs", "data", "bottles.js")
IMG = os.path.join(HERE, "..", "docs", "img")
AUDIT = os.path.join(HERE, "..", "Photo Audit", "photo_audit.csv")
LIB = r"C:\Users\admin\OneDrive\Documents\Claude\Claude\Bottle Shots"
MANIFEST = os.path.join(LIB, "manifest.csv")
OUT = os.path.join(HERE, "..", "Bottle Shot Coverage.xlsx")

HEAD = PatternFill("solid", fgColor="1F3864")
BAND = PatternFill("solid", fgColor="EDF2F9")
POOR = PatternFill("solid", fgColor="FCE8E6")
WHITE = Font(color="FFFFFF", bold=True)


def bank():
    src = io.open(BANK, encoding="utf-8").read()
    bottles = json.loads(
        re.search(r"window\.BOTTLES = (\[.*?\]);", src, re.S).group(1))
    ranks = json.loads(
        re.search(r"window\.BRAND_RANKS = (\{.*?\});", src, re.S).group(1))
    vol = {}
    for rowset in ranks.values():
        for brand, cases in rowset:
            vol[brand] = vol.get(brand, 0) + cases
    return bottles, vol


def library():
    by_gtin = {}
    if os.path.exists(MANIFEST):
        with io.open(MANIFEST, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                by_gtin[r["gtin14"]] = r
    return by_gtin


def verdicts():
    """upc -> (kind, score, why) from the photo audit, where it has run."""
    out = {}
    if os.path.exists(AUDIT):
        with io.open(AUDIT, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out[r["upc12"]] = (r["kind"], r["score"], r["why"])
    return out


def stale_verdicts():
    """Published photographs newer than the audit that judged them.

    The audit is a file, not a measurement taken at report time, so a
    replaced photograph keeps its old verdict until photo_audit.py runs
    again. That is quiet and it is wrong in the direction that matters: a
    bottle whose bad picture has just been replaced still reads "poor",
    still appears on the To shoot sheet, and still counts against coverage.

    It happened. Twenty bottles fixed over one morning -- Angel's Envy, the
    Cutwater carton, the Kraken counter shot -- were all still being
    reported as poor against an audit written before any of them were
    filed, and the published files were byte-identical to ones the same run
    called good.
    """
    if not os.path.exists(AUDIT):
        return []
    cut = os.path.getmtime(AUDIT)
    if not os.path.isdir(IMG):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(IMG)
                  if os.path.getmtime(os.path.join(IMG, f)) > cut)


def gtin14(upc):
    return re.sub(r"\D", "", str(upc)).zfill(14)


def sheet(wb, title, columns, rows, widths, flag_col=None):
    ws = wb.create_sheet(title)
    ws.append(columns)
    for c in range(1, len(columns) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill, cell.font = HEAD, WHITE
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = widths[c - 1]
    for i, r in enumerate(rows):
        ws.append(r)
        poor = flag_col is not None and str(r[flag_col]).startswith("poor")
        for c in range(1, len(columns) + 1):
            if poor:
                ws.cell(row=i + 2, column=c).fill = POOR
            elif i % 2:
                ws.cell(row=i + 2, column=c).fill = BAND
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def main():
    bottles, vol = bank()
    lib = library()
    vd = verdicts()
    published = set(f[:-5] for f in os.listdir(IMG) if f.endswith(".webp"))

    good, poor, missing = [], [], []
    for b in bottles:
        upc = b.get("u") or ""
        g = gtin14(upc) if upc else ""
        rec = lib.get(g)
        has = upc in published
        kind, score, why = vd.get(upc, ("", "", ""))

        common = [b["b"], b["n"], b["s"], b.get("k") or "", b["c"], b.get("t", ""),
                  b.get("p", ""), round(vol.get(b["b"], 0)), b.get("a", ""), upc]

        if not has:
            missing.append(common + [
                "missing", "no UPC in the price file" if not upc else "never found",
                "", ""])
        elif kind == "opaque, boxed":
            poor.append(common + [
                "poor - visible box", why or "opaque background", score,
                (rec or {}).get("source_site", "(pre-library)")])
        else:
            good.append(common + [
                kind or "published", why, score,
                (rec or {}).get("source_site", "(pre-library)")])

    # the working list: both kinds of gap, biggest brands first
    todo = poor + missing
    todo.sort(key=lambda r: (-r[7], r[0], r[1]))
    good.sort(key=lambda r: (-r[7], r[0], r[1]))

    cats = {}
    for r in good:
        cats.setdefault(r[4], [0, 0, 0])[0] += 1
    for r in poor:
        cats.setdefault(r[4], [0, 0, 0])[1] += 1
    for r in missing:
        cats.setdefault(r[4], [0, 0, 0])[2] += 1

    wb = Workbook()
    wb.remove(wb.active)

    summary = []
    for k, v in sorted(cats.items(), key=lambda kv: -sum(kv[1])):
        tot = sum(v)
        summary.append([k, v[0], v[1], v[2], tot, round(100.0 * v[0] / tot, 1)])
    tg = sum(v[0] for v in cats.values())
    tp = sum(v[1] for v in cats.values())
    tm = sum(v[2] for v in cats.values())
    summary.append(["ALL", tg, tp, tm, tg + tp + tm,
                    round(100.0 * tg / (tg + tp + tm), 1)])
    ws = sheet(wb, "Summary",
               ["Category", "Good photo", "Poor photo", "No photo", "Total",
                "% good"],
               summary, [24, 12, 12, 11, 9, 10])
    for c in range(1, 7):
        ws.cell(row=len(summary) + 1, column=c).font = Font(bold=True)

    cols = ["Brand", "Product", "Size", "Pack", "Category", "Price tier",
            "Avg retail", "Brand 9L cases", "Accounts", "UPC (name the file this)"]
    w = [24, 40, 9, 6, 20, 14, 11, 15, 10, 22]

    sheet(wb, "To shoot (%d)" % len(todo),
          cols + ["State", "Why", "Audit score", "Current source"],
          todo, w + [19, 26, 11, 20], flag_col=10)
    sheet(wb, "Have (%d)" % len(good),
          cols + ["State", "Flags", "Audit score", "Source"],
          good, w + [19, 20, 11, 20])

    wb.save(OUT)
    print("good %d, poor %d, missing %d  ->  %s"
          % (len(good), len(poor), len(missing), os.path.abspath(OUT)))
    if not vd:
        print("NOTE: no photo_audit.csv, so nothing is marked poor. "
              "Run photo_audit.py first.")
    else:
        late = stale_verdicts()
        if late:
            print("\nWARNING: %d published photograph%s newer than the audit "
                  "that judged %s." % (len(late), "" if len(late) == 1 else "s",
                                       "it" if len(late) == 1 else "them"))
            print("The good/poor split above is wrong for %s. Run "
                  "photo_audit.py, then this again."
                  % ("that one" if len(late) == 1 else "those"))
            print("  " + ", ".join(late[:12])
                  + (" ..." if len(late) > 12 else ""))


if __name__ == "__main__":
    main()
