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
- **Form** tracks rounds, best round, best streak and accuracy per category,
  in `localStorage` on the device. Nothing leaves the phone.

## Layout

```
Price Checker/
├─ Average Price Checker.csv     source data (not read at runtime)
├─ app/                          everything that gets deployed
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

Then bump `CACHE` in `app/sw.js` so installed copies pick up the new data.

**What the builder keeps.** Of 1,320 rows in the file, 1,130 become playable:

| Dropped | Rows | Why |
|---|---|---|
| Odd sizes | 79 | 50 mL, 100 mL, 200 mL, "REM SIZE" etc. — unguessable |
| Thin distribution | 95 | stocked in fewer than 10 accounts, so the average is a one-store fluke |
| Price outliers | 16 | under $4 or over $400, including a $1,305 Hennessy 700 mL |

It also expands the trade abbreviations in `item` into something readable —
`MACALLAN 12YR DBL CASK SCT WSK GLASS 86 PROOF 750ML` becomes
*Macallan 12 Year Double Cask Scotch Whiskey* — and strips the packaging, proof
and size out of the name, since those are shown as their own fields.

## Running it

Any static server will do:

```
cd app && python -m http.server 8787
```

Then open `http://localhost:8787`. On a phone, use **Share → Add to Home Screen**
to install it; the service worker caches the whole app so it plays offline.

## A note on the data

`bottles.js` contains every average retail price in the file. Anywhere this app
is hosted, that pricing is readable by anyone who can reach the page — so host
it somewhere that matches how sensitive the underlying data is.
