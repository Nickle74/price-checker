# price check

A mobile web app where you guess the average retail price of real bottles.
Ten bottles a round, scored on how close you land.

Design language borrowed from [Ro (iOS)](https://mobbin.com/apps/ro-ios-ba654651-4a36-4b50-93ba-70bbf2a42430):
warm off-white ground, soft gradient hero, black pill buttons, oversized light
headlines, thin-line tab bar.

## How it plays

- **A round** is 10 bottles drawn at random. You see the category, price tier,
  expression, size, proof and how many accounts stock it — never the price.
- **Each bottle** is worth up to **1,000 points**, scored on *percentage* error,
  so a $5 miss on a $20 bottle costs the same as a $50 miss on a $200 one.
  60% off or worse scores nothing.

  | Band | Within | Points |
  |---|---|---|
  | Dead on | 3% | 926–1,000 |
  | Nailed it | 8% | 807–926 |
  | Close | 15% | 650–807 |
  | In range | 30% | 354–650 |
  | Off | 60% | 0–354 |

- **Streaks**: land within 15% and you start a streak. Every bottle after the
  first in a streak adds +50, capped at +250. A perfect round is 11,750.
- **Multipacks** show their pack size and are priced as a pack, not a can —
  the same Surfside is $17.62 as an 8-pack and $36.17 as an 18-pack.
- **Each bottle shows a picture**: a photo when `docs/img/<upc>.webp` exists,
  otherwise one drawn from the category and brand, so a card is never empty.
  See *Bottle pictures* below.
- **After each guess** you get the answer and where that brand sits on volume
  in its category — the two brands above it and the two below, by 9-litre
  cases. The ranking is built from every row in the file, not just the playable
  ones, so it reflects real depletions.
- **The daily** draws one fixed set of ten from the date itself, so everyone
  opens the app to the same round. One attempt, then share the grid:

  ```
  price check · Nov 20
  6,312 pts · 21% off
  🟩🟩🟩🟧⬜🟩🟨🟩🟧🟩
  https://nickle74.github.io/price-checker/
  ```

  🟩 within 15%, 🟨 within 30%, 🟧 within 60%, ⬜ beyond. It resets at local
  midnight, and the round is derived from the date with a seeded shuffle, so no
  server is involved.
- **Form** tracks rounds, best round, best streak, daily streak and accuracy per
  category, in `localStorage` on the device. Nothing leaves the phone.

## Layout

```
Price Checker/
├─ Average Price Checker.csv     source data (not read at runtime)
├─ docs/                         everything that gets deployed (Pages root)
│  ├─ index.html
│  ├─ styles.css
│  ├─ app.js
│  ├─ sw.js                      offline shell
│  ├─ manifest.webmanifest
│  ├─ icons/
│  └─ data/bottles.js            generated — do not edit by hand
└─ tools/
   ├─ build_bank.py              CSV  ->  app/data/bottles.js
   └─ make_icons.py              regenerates the app icons
```

## Rebuilding the question bank

Drop a new `Average Price Checker.csv` in this folder and run:

```
python tools/build_bank.py
```

Then bump `CACHE` in `docs/sw.js` so installed copies pick up the new data.

**What the builder keeps.** Of 1,320 rows in the file, 1,001 become playable:

| Dropped | Rows | Why |
|---|---|---|
| Duplicate products | 129 | the same product on several rows at different averages |
| Thin distribution | 95 | stocked in fewer than 10 accounts, so the average is a one-store fluke |
| Odd sizes | 79 | 50 mL, 100 mL, 200 mL, "REM SIZE" etc. — unguessable |
| Price outliers | 16 | under $4 or over $400, including a $1,305 Hennessy 700 mL |

The duplicates matter most. `DON JULIO 1942 ANEJO 750ML` appears three times
between $159.95 and $196.93 on different UPCs, and two identical-looking cards
with different right answers is an unwinnable round. The builder keeps the most
widely stocked row of each product — the price the most shelves actually show.
Pack size counts as part of the identity, so the 8-, 12- and 18-packs of one
can stay three separate products rather than collapsing into one.

It also expands the trade abbreviations in `item` and `brand` into something
readable — `MACALLAN 12YR DBL CASK SCT WSK GLASS 86 PROOF 750ML` becomes
*Macallan 12 Year Double Cask Scotch Whiskey* — and strips the packaging, proof
and size out of the name, since those are shown as their own fields. Bare
numbers are kept deliberately: *Don Julio 1942*, *1800 Silver* and
*Rémy Martin 1738* lose their identity without them.

## Bottle pictures

Photos live in `docs/img/`, named by the bottle's UPC: `080480280024.webp`.
If the file is there the card shows it; if not, the card draws a bottle from
the category and the brand's initials. Coverage can be partial without ever
looking broken.

**The UPCs in the file are real.** They look wrong — 9 to 11 digits where a
UPC-A is 12 — because Excel stripped the leading zeros and the check digit.
Tito's 750 mL is `61994700002` in the sheet and `619947000020` on the bottle.
`build_bank.py` pads and recomputes the check digit, recovering 965 of 1,001.
The other 36 are rows Excel mangled into `3.77583E+11`, which cannot be undone.

```
python tools/fetch_images.py            # drop folder, then a small API batch
python tools/fetch_images.py --local    # drop folder only, no network
```

**Use the drop folder.** Put images in `tools/incoming/` named by UPC
(`080480280024.jpg`) or by the exact bottle name, and the script resizes and
converts them with no network involved. Supplier media-kit shots belong here:
they are better pictures than anything scraped, and they are licensed for
trade use, which retail product photography is not.

**Measure coverage before paying any vendor.**

```
python tools/fetch_images.py --probe 40                        # free catalogue
python tools/fetch_images.py --provider barcodelookup --probe 40
```

The probe samples your real UPCs, downloads nothing, and reports the only
figure that decides a purchase: how many of *your* products the catalogue
knows, how many carry an image, and what filling the book would cost at that
rate. No vendor publishes coverage for spirits, and it is the thing that
varies. Keys go in `tools/api_keys.json` (gitignored) or the environment; a
new provider is one small class in `fetch_images.py`.

Early numbers on the free catalogue: roughly half, and every miss is
`total=0` — the product is absent, not throttled. upcitemdb's own docs say
the free plan has *"the same full access to our database as the paid plans"*,
so upgrading that one buys throughput you have no use for.

**The free API is a trickle, not a solution.** `fetch_images.py` will also try
upcitemdb, but that endpoint rate-limits after about six lookups regardless of
pacing, and it has no image for plenty of high-volume brands — Lunazul and
Espolón among them. It is resumable, so running it daily adds a handful at a
time, but filling 965 bottles that way is not realistic. Treat it as a top-up.

## Running it

Any static server will do:

```
cd docs && python -m http.server 8787
```

Then open `http://localhost:8787`. On a phone, use **Share → Add to Home Screen**
to install it; the service worker caches the whole app so it plays offline.

## A note on the data

`bottles.js` contains every average retail price in the file. Anywhere this app
is hosted, that pricing is readable by anyone who can reach the page — so host
it somewhere that matches how sensitive the underlying data is.
