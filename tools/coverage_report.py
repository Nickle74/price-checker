"""Which bottles in the bank have a photo and which do not.

Writes a workbook with three sheets: a per-category summary, everything we
hold an image for, and everything still missing -- the missing sheet ordered
by brand volume, so the top of it is always the work worth doing next.

    python coverage_report.py
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
LIB = r"C:\Users\admin\OneDrive\Documents\Claude\Claude\Bottle Shots"
MANIFEST = os.path.join(LIB, "manifest.csv")
OUT = os.path.join(HERE, "..", "Bottle Shot Coverage.xlsx")

HEAD = PatternFill("solid", fgColor="1F3864")
BAND = PatternFill("solid", fgColor="EDF2F9")
WHITE = Font(color="FFFFFF", bold=True)


def gtin14(upc):
    return re.sub(r"\D", "", str(upc)).zfill(14)


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


def sheet(wb, title, columns, rows, widths):
    ws = wb.create_sheet(title)
    ws.append(columns)
    for c in range(1, len(columns) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill, cell.font = HEAD, WHITE
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = widths[c - 1]
    for i, r in enumerate(rows):
        ws.append(r)
        if i % 2:
            for c in range(1, len(columns) + 1):
                ws.cell(row=i + 2, column=c).fill = BAND
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def main():
    bottles, vol = bank()
    lib = library()

    have, missing = [], []
    for b in bottles:
        g = gtin14(b["u"]) if b.get("u") else None
        rec = lib.get(g) if g else None
        common = [b["b"], b["n"], b["s"], b.get("k") or "", b["c"], b.get("t", ""),
                  b.get("p", ""), round(vol.get(b["b"], 0)), b.get("a", "")]
        if rec:
            have.append(common + [g, rec.get("size_confirmed", ""),
                                  rec.get("note", ""), rec.get("source_site", ""),
                                  rec.get("filename", "")])
        else:
            why = "no UPC in the price file" if not b.get("u") else "not found yet"
            missing.append(common + [g or "", why])

    missing.sort(key=lambda r: (-r[7], r[0], r[1]))
    have.sort(key=lambda r: (r[4], r[0], r[1]))

    cats = {}
    for b in bottles:
        g = gtin14(b["u"]) if b.get("u") else None
        d = cats.setdefault(b["c"], [0, 0])
        d[0 if (g and g in lib) else 1] += 1

    wb = Workbook()
    wb.remove(wb.active)

    summary = [[k, v[0], v[1], v[0] + v[1],
                round(100.0 * v[0] / (v[0] + v[1]), 1)]
               for k, v in sorted(cats.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))]
    tot_h = sum(v[0] for v in cats.values())
    tot_m = sum(v[1] for v in cats.values())
    summary.append(["ALL", tot_h, tot_m, tot_h + tot_m,
                    round(100.0 * tot_h / (tot_h + tot_m), 1)])
    ws = sheet(wb, "Summary",
               ["Category", "Have image", "Missing", "Total", "% covered"],
               summary, [26, 12, 10, 10, 11])
    for c in range(1, 6):
        ws.cell(row=len(summary) + 1, column=c).font = Font(bold=True)

    cols = ["Brand", "Product", "Size", "Pack", "Category", "Price tier",
            "Avg retail", "Brand 9L cases", "Accounts"]
    w = [24, 40, 9, 6, 20, 14, 11, 15, 10]
    sheet(wb, "Have image (%d)" % len(have),
          cols + ["GTIN-14", "Size confirmed", "Flag", "Source", "Filename"],
          have, w + [17, 14, 30, 22, 52])
    sheet(wb, "Missing (%d)" % len(missing),
          cols + ["GTIN-14", "Why"], missing, w + [17, 24])

    wb.save(OUT)
    print("%d have, %d missing -> %s" % (len(have), len(missing),
                                         os.path.abspath(OUT)))


if __name__ == "__main__":
    main()
