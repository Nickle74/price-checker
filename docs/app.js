/* ============================================================
   price check — guess the average retail price
   Data: window.BOTTLES from data/bottles.js
   Keys: i index, c category, b brand, n name, s size,
         p avg retail price, t tier, f proof, a accounts
   ============================================================ */
(function () {
  'use strict';

  var BOTTLES = window.BOTTLES || [];
  var RANKS = window.BRAND_RANKS || {};
  var ROUND_LEN = 10;
  var MAX_PER = 1000;
  var ZERO_AT = 0.60;      // 60% off or worse scores nothing
  var STREAK_AT = 0.15;    // within 15% keeps a streak alive
  var STREAK_STEP = 50;
  var STREAK_CAP = 250;
  var STORE_KEY = 'priceCheck.v1';
  var DAILY_KEY = 'priceCheck.daily.v1';
  var SHARE_URL = 'https://nickle74.github.io/price-checker/';
  // 🟩 within 15%  🟨 within 30%  🟧 within 60%  ⬜ beyond
  var MARKS = [[0.15, '🟩'], [0.30, '🟨'], [0.60, '🟧'], [Infinity, '⬜']];

  var BANDS = [
    { max: 0.03, label: 'Dead on',   tone: 'is-good', line: 'Within 3%. That is a shelf tag, not a guess.' },
    { max: 0.08, label: 'Nailed it', tone: 'is-good', line: 'Inside 8%. You know this shelf.' },
    { max: 0.15, label: 'Close',     tone: 'is-good', line: 'Inside 15%. Good read.' },
    { max: 0.30, label: 'In range',  tone: 'is-mid',  line: 'In the neighbourhood, not on the block.' },
    { max: 0.60, label: 'Off',       tone: 'is-mid',  line: 'The tier was right, the number was not.' },
    { max: Infinity, label: 'Way off', tone: 'is-bad', line: 'Not this one. Reset and go again.' }
  ];

  // ---------- tiny helpers ----------
  var $ = function (id) { return document.getElementById(id); };
  var money = function (n) {
    return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  var moneyShort = function (n) {
    return '$' + (n % 1 === 0 ? n.toLocaleString('en-US')
                              : n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  };
  var num = function (n) { return n.toLocaleString('en-US'); };

  // Account counts in the source file top out at 500 -- Crown Royal Apple 500,
  // Patron Silver 499, Tito's 499 -- so that is the denominator, and a share
  // of the market reads better on a card than a raw count nobody can scale.
  // Clamped, because four rows in the file exceed 500 and all four are bad
  // data: a 200ML Buzzballz 6-pack claims 972. A card must never say 194%.
  var MAX_ACCOUNTS = 500;
  var distPct = function (a) {
    return Math.round(Math.min(a, MAX_ACCOUNTS) / MAX_ACCOUNTS * 100) + '%';
  };
  var pct = function (x) { return (x * 100).toFixed(x < 0.1 ? 1 : 0) + '%'; };
  var buzz = function (ms) { if (navigator.vibrate) { try { navigator.vibrate(ms); } catch (e) {} } };

  // ============================================================
  // BOTTLE ARTWORK
  // A photo when we have one, keyed on the restored UPC; otherwise a drawn
  // bottle so a card is never empty. Coverage grows as images land in
  // docs/img/ — nothing here needs changing when they do.
  // ============================================================
  var IMG_DIR = 'img/';

  // shape + liquid per category. `label` is the paper, `ink` the lettering on
  // it; pale glass gets an outline or it disappears against the card.
  var LOOK = {
    'Whiskey':            { form: 'square', body: '#B5651D', cap: '#3C2A14', label: '#F6EFE0', ink: '#412402' },
    'Cognac':             { form: 'round',  body: '#8C3A12', cap: '#2A1708', label: '#F6EFE0', ink: '#4A1B0C' },
    'Brandy':             { form: 'round',  body: '#9A4718', cap: '#2A1708', label: '#F6EFE0', ink: '#4A1B0C' },
    'Tequila':            { form: 'taper',  body: '#D9B452', cap: '#4A3A12', label: '#FBF7EC', ink: '#412402' },
    'Rum':                { form: 'square', body: '#7A4A22', cap: '#2A1708', label: '#F6EFE2', ink: '#412402' },
    'Vodka':              { form: 'tall',   body: '#C6D6E0', cap: '#2B3A42', label: '#FFFFFF', ink: '#042C53', edge: 1 },
    'Gin':                { form: 'tall',   body: '#BBD3C7', cap: '#1F3A30', label: '#FFFFFF', ink: '#04342C', edge: 1 },
    'Cordials':           { form: 'round',  body: '#A33B5E', cap: '#3A1324', label: '#FBEAF0', ink: '#4B1528' },
    'Grain Alcohol':      { form: 'tall',   body: '#D5DBDE', cap: '#3A3A38', label: '#FFFFFF', ink: '#2C2C2A', edge: 1 },
    'Non-Alcoholic':      { form: 'tall',   body: '#A9CBB6', cap: '#2F4A38', label: '#FFFFFF', ink: '#04342C', edge: 1 },
    'Prepared Cocktails': { form: 'can',    body: '#D85A30', cap: '#B8B6AD', label: '#FBEAE2', ink: '#4A1B0C' }
  };
  var LOOK_FALLBACK = { form: 'tall', body: '#B4B2A9', cap: '#444441', label: '#F1EFE8', ink: '#2C2C2A' };

  function initials(brand) {
    var words = brand.replace(/[^A-Za-z0-9' ]/g, ' ').split(/\s+/).filter(Boolean);
    if (!words.length) return '?';
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return (words[0][0] + words[1][0]).toUpperCase();
  }

  function drawnBottle(b) {
    var L = LOOK[b.c] || LOOK_FALLBACK;
    var edge = L.edge ? ' stroke="rgba(18,18,17,.22)" stroke-width="1.2"' : '';
    var shape, bandX, bandW;

    if (L.form === 'can') {
      shape = '<rect x="36" y="16" width="48" height="126" rx="7" fill="' + L.body + '"' + edge + '/>' +
              '<rect x="36" y="24" width="48" height="6" fill="' + L.cap + '"/>';
      bandX = 36; bandW = 48;
    } else {
      // cap and neck overlap the shoulder so the silhouette reads as one piece
      var head = '<rect x="51" y="8" width="18" height="10" rx="2" fill="' + L.cap + '"/>' +
                 '<rect x="53" y="16" width="14" height="24" fill="' + L.body + '"' + edge + '/>';
      var body;
      if (L.form === 'round') {
        body = '<ellipse cx="60" cy="92" rx="34" ry="50" fill="' + L.body + '"' + edge + '/>';
        bandX = 30; bandW = 60;
      } else if (L.form === 'taper') {
        body = '<path d="M32 140 L38 40 Q38 36 42 36 L78 36 Q82 36 82 40 L88 140 Q88 142 85 142 L35 142 Q32 142 32 140 Z" fill="' + L.body + '"' + edge + '/>';
        bandX = 36; bandW = 48;
      } else if (L.form === 'tall') {
        body = '<rect x="35" y="36" width="50" height="106" rx="5" fill="' + L.body + '"' + edge + '/>';
        bandX = 35; bandW = 50;
      } else {
        body = '<rect x="31" y="38" width="58" height="104" rx="9" fill="' + L.body + '"' + edge + '/>';
        bandX = 31; bandW = 58;
      }
      shape = head + body;
    }

    var bandY = 80;
    return '<svg viewBox="0 0 120 152" role="img" aria-label="' + esc(b.c) + ' bottle">' +
      shape +
      '<rect x="' + bandX + '" y="' + bandY + '" width="' + bandW + '" height="34" fill="' + L.label + '"/>' +
      '<text x="' + (bandX + bandW / 2) + '" y="' + (bandY + 23) + '" text-anchor="middle" ' +
        'font-family="system-ui, -apple-system, sans-serif" font-size="15" font-weight="600" ' +
        'letter-spacing="-0.4" fill="' + L.ink + '">' + esc(initials(b.b)) + '</text>' +
      '</svg>';
  }

  // name plus pack, for lists where two pack sizes would otherwise look identical
  function label(b) {
    return b.k ? b.n + ' ' + b.k + '-pack' : b.n;
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  var shotToken = 0;

  function renderShot(b) {
    var mine = ++shotToken;
    var fig = $('shot');
    fig.innerHTML = drawnBottle(b);
    fig.classList.remove('has-photo');
    if (!b.u) return;

    // Try the photo; keep the drawing until it actually decodes, so a missing
    // file or a dead connection just leaves the drawn bottle in place.
    var img = new Image();
    img.alt = b.n;
    img.decoding = 'async';
    img.loading = 'eager';
    img.onload = function () {
      if (mine !== shotToken) return;   // player already moved to another card
      fig.innerHTML = '';
      fig.appendChild(img);
      fig.classList.add('has-photo');
    };
    img.onerror = function () { /* drawn bottle stays */ };
    img.src = IMG_DIR + b.u + '.webp';
  }

  // ---------- dates ----------
  // Local dates, so the daily turns over at the player's own midnight.
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function dayKey(d) {
    d = d || new Date();
    return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
  }
  function yesterdayKey() {
    var d = new Date();
    d.setDate(d.getDate() - 1);
    return dayKey(d);
  }
  var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  function prettyDay(key) {
    var p = key.split('-');
    return MONTHS[parseInt(p[1], 10) - 1] + ' ' + parseInt(p[2], 10);
  }

  // ---------- seeded randomness ----------
  // FNV-1a over the date string, then mulberry32 — same day, same ten bottles,
  // on every device, with no server involved.
  function seedFrom(str) {
    var h = 2166136261;
    for (var i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ---------- persisted stats ----------
  var stats = loadStats();
  function loadStats() {
    var base = { rounds: 0, bestRound: 0, bestStreak: 0, totalPts: 0, sumPct: 0, nGuess: 0, cat: {},
                 dailyStreak: 0, dailyBest: 0, dailyPlayed: 0, dailyLast: '' };
    try {
      var raw = localStorage.getItem(STORE_KEY);
      if (!raw) return base;
      var s = JSON.parse(raw);
      for (var k in base) if (!(k in s)) s[k] = base[k];
      if (!s.cat || typeof s.cat !== 'object') s.cat = {};
      return s;
    } catch (e) { return base; }
  }
  function saveStats() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(stats)); } catch (e) {}
  }

  // ---------- today's saved attempt ----------
  // Stored as bottle indexes plus guesses, so the whole summary rebuilds from it.
  function loadDaily() {
    try {
      var raw = localStorage.getItem(DAILY_KEY);
      if (!raw) return null;
      var d = JSON.parse(raw);
      if (!d || d.date !== dayKey() || !d.picks || !d.guesses) return null;
      if (d.picks.length !== ROUND_LEN || d.guesses.length !== ROUND_LEN) return null;
      // Regenerating the bank reshuffles the indexes, which would rebuild the
      // round from the wrong bottles — drop the record rather than lie about it.
      var fresh = dailyItems(d.date);
      for (var i = 0; i < ROUND_LEN; i++) {
        if (!BOTTLES[d.picks[i]] || BOTTLES[d.picks[i]] !== fresh[i]) return null;
      }
      return d;
    } catch (e) { return null; }
  }
  function saveDaily(rec) {
    try { localStorage.setItem(DAILY_KEY, JSON.stringify(rec)); } catch (e) {}
  }

  // ---------- state ----------
  // Empty means no constraint on that axis. Arrays rather than single values
  // so a player can line up, say, Cognac + Brandy, or 375mL + 700mL -- which
  // also rescues the thin slices: neither 700mL (6) nor Grain Alcohol (3) can
  // fill a round alone, but they can in company.
  var catSel = [];
  var sizeSel = [];
  // 'all', 'pop' or 'obs'. Single-valued rather than an array: popular and
  // obscure are opposite ends of one axis, so choosing both means choosing
  // neither, and the two sets are built so they never overlap.
  var scopeSel = 'all';

  function toggle(list, v) {
    var i = list.indexOf(v);
    if (i === -1) list.push(v); else list.splice(i, 1);
    return list;
  }
  var game = null;
  var typed = '';
  var currentTab = 'home';

  // ---------- categories ----------
  var catCounts = (function () {
    var m = {};
    BOTTLES.forEach(function (b) { m[b.c] = (m[b.c] || 0) + 1; });
    return m;
  })();
  var CATS = Object.keys(catCounts).sort(function (a, b) { return catCounts[b] - catCounts[a]; });

  // ---------- sizes ----------
  // Ordered biggest-selling format first rather than alphabetically, so the
  // row reads 750mL, 1.75L, ... which is how anyone in the trade thinks about
  // it. 1L is absent because it is held out of the bank entirely -- see
  // EXCLUDE_SIZES in tools/build_bank.py.
  var sizeCounts = (function () {
    var m = {};
    BOTTLES.forEach(function (b) { m[b.s] = (m[b.s] || 0) + 1; });
    return m;
  })();
  var SIZES = Object.keys(sizeCounts).sort(function (a, b) { return sizeCounts[b] - sizeCounts[a]; });

  // ---------- popular / obscure ----------
  // Ranked on `a`, the number of the 500 accounts that stock a bottle -- the
  // same figure the card shows as Distribution, and the only per-item measure
  // of reach the bank carries. Note the floor: every bottle here is already
  // in at least 200 accounts, so "obscure" means a bottle in 200-odd of them,
  // not one nobody has heard of. A Luksusowa or a Maraska Slivovitz, not a
  // garage brand.
  //
  // Top and bottom are taken WITHIN each category. Ranked across the whole
  // bank, "popular" would have been a list of whiskeys and vodkas and
  // "obscure" whatever category happens to be thinly stocked -- the scope has
  // to stay a question about price, not a backdoor category filter.
  var SCOPE_LABEL = { pop: 'Popular', obs: 'Obscure' };
  var scopeSets = (function () {
    var byCat = {};
    BOTTLES.forEach(function (b) { (byCat[b.c] = byCat[b.c] || []).push(b); });
    var top = {}, bot = {};
    Object.keys(byCat).forEach(function (c) {
      var rows = byCat[c].slice().sort(function (x, y) {
        return (y.a - x.a) || (x.i - y.i);   // index breaks ties, so the split is stable
      });
      // Half the category when it holds fewer than 40, so the two ends never
      // meet in the middle: Cognac has 25 bottles and a flat twenty each way
      // would have put 15 of them in BOTH scopes. Anything left over in the
      // middle belongs to neither, which is the point of picking the ends.
      var k = Math.min(20, Math.floor(rows.length / 2));
      rows.slice(0, k).forEach(function (b) { top[b.i] = true; });
      rows.slice(rows.length - k).forEach(function (b) { bot[b.i] = true; });
    });
    return { pop: top, obs: bot };
  })();
  function scopeKey(label) { return label === 'Popular' ? 'pop' : 'obs'; }

  // ============================================================
  // ROUND BUILDING
  // ============================================================
  function pool(cats, sizes, scope) {
    cats = cats || catSel;
    sizes = sizes || sizeSel;
    scope = scope || scopeSel;
    if (!cats.length && !sizes.length && scope === 'all') return BOTTLES;
    var set = scope === 'all' ? null : scopeSets[scope];
    return BOTTLES.filter(function (b) {
      return (!cats.length || cats.indexOf(b.c) !== -1) &&
             (!sizes.length || sizes.indexOf(b.s) !== -1) &&
             (!set || set[b.i]);
    });
  }

  function pickRound(rng, cats, sizes, scope) {
    rng = rng || Math.random;
    cats = cats || catSel;
    sizes = sizes || sizeSel;
    scope = scope || scopeSel;
    var src = pool(cats, sizes, scope).slice();
    // Fisher–Yates
    for (var i = src.length - 1; i > 0; i--) {
      var j = Math.floor(rng() * (i + 1));
      var t = src[i]; src[i] = src[j]; src[j] = t;
    }
    var out = [], seenBrand = {}, perCat = {};
    // With no category chosen, cap any one of them at 3 so a round stays
    // varied. With a selection, share the ten out across what was chosen --
    // pick two categories and you get roughly five of each, not nine and one.
    var catCap = cats.length ? Math.max(3, Math.ceil(ROUND_LEN / cats.length)) : 3;

    for (var pass = 0; pass < 3 && out.length < ROUND_LEN; pass++) {
      for (var k = 0; k < src.length && out.length < ROUND_LEN; k++) {
        var b = src[k];
        if (out.indexOf(b) !== -1) continue;
        if (pass === 0) {
          if (seenBrand[b.b]) continue;
          if ((perCat[b.c] || 0) >= catCap) continue;
        } else if (pass === 1) {
          if (seenBrand[b.b]) continue;        // still no duplicate brands
        }
        out.push(b);
        seenBrand[b.b] = true;
        perCat[b.c] = (perCat[b.c] || 0) + 1;
      }
    }
    // spread the money around: easy-ish first, dearest last
    out.sort(function (a, b) { return a.p - b.p; });
    var cheap = out.slice(0, Math.ceil(out.length / 2));
    var dear = out.slice(Math.ceil(out.length / 2));
    var woven = [];
    for (var n = 0; n < Math.max(cheap.length, dear.length); n++) {
      if (cheap[n]) woven.push(cheap[n]);
      if (dear[n]) woven.push(dear[n]);
    }
    return woven;
  }

  // ============================================================
  // SCORING
  // ============================================================
  function pointsFor(err) {
    if (err >= ZERO_AT) return 0;
    return Math.round(MAX_PER * Math.pow(1 - err / ZERO_AT, 1.5));
  }
  function bandFor(err) {
    // a guess worth nothing always reads "Way off" — the label and the score must agree
    if (pointsFor(err) === 0) return BANDS[BANDS.length - 1];
    for (var i = 0; i < BANDS.length; i++) if (err <= BANDS[i].max) return BANDS[i];
    return BANDS[BANDS.length - 1];
  }
  function maxBonus() {
    var t = 0;
    for (var i = 2; i <= ROUND_LEN; i++) t += Math.min((i - 1) * STREAK_STEP, STREAK_CAP);
    return t;
  }

  // ============================================================
  // VIEWS
  // ============================================================
  var VIEWS = ['home', 'round', 'reveal', 'sum', 'learn', 'card', 'practice', 'stats', 'guide'];
  function show(name) {
    VIEWS.forEach(function (v) { $('view-' + v).hidden = (v !== name); });
    var inGame = (name === 'round' || name === 'reveal' || name === 'sum');
    $('tabs').hidden = inGame;
    var sc = $('view-' + name).querySelector('.scroll');
    if (sc) sc.scrollTop = 0;
    // On every view but the round, it is the WINDOW that scrolls: .view is
    // min-height:100dvh and simply grows, so the line above has never had
    // anything to reset. Switching tabs kept the last page's scroll offset,
    // which put a new page's first screen out of sight -- Practice opened
    // with the tiles already half off the top.
    if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
  }
  function setTab(name) {
    currentTab = name;
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (t) {
      t.classList.toggle('is-on', t.dataset.tab === name);
    });
    if (name === 'stats') renderStats();
    if (name === 'learn') renderLearn();
    if (name === 'practice') renderPractice();
    show(name);
  }

  // ============================================================
  // HOME
  // ============================================================
  function renderHome() {
    var n = pool().length;
    var bits = [];
    bits.push(catSel.length ? catSel.join(', ') : 'All categories');
    if (sizeSel.length) bits.push(sizeSel.join(', '));
    if (scopeSel !== 'all') bits.push(SCOPE_LABEL[scopeSel]);
    $('hero-eyebrow').textContent = ROUND_LEN + ' bottles · ' + bits.join(' · ');
    $('hero-meta').textContent = n < ROUND_LEN
      ? num(n) + ' bottle' + (n === 1 ? '' : 's') + ' — need ' + ROUND_LEN + ', pick more'
      : num(n) + ' bottle' + (n === 1 ? '' : 's') + ' in the book';
    $('btn-play').disabled = n < ROUND_LEN;

    $('st-best').textContent = stats.bestRound ? num(stats.bestRound) : '—';
    $('st-rounds').textContent = num(stats.rounds);
    $('st-acc').textContent = stats.nGuess ? pct(stats.sumPct / stats.nGuess) : '—';
    renderDailyCard();
  }

  function renderDailyCard() {
    var rec = loadDaily();
    var card = $('btn-daily');
    var score = $('daily-score');
    card.classList.toggle('is-done', !!rec);
    $('daily-title').textContent = rec ? 'Today’s bottles — played' : 'Today’s bottles';

    if (rec) {
      var total = scoreGuesses(rec.picks.map(function (i) { return BOTTLES[i]; }), rec.guesses).total;
      $('daily-sub').textContent = prettyDay(rec.date) + ' · tap to see your grid';
      score.hidden = false;
      score.textContent = num(total);
    } else {
      $('daily-sub').textContent = prettyDay(dayKey()) + ' · the same ten for everyone';
      score.hidden = true;
    }
  }

  // One builder for both rows. The count on each chip is the number of
  // bottles you would actually be playing -- it honours the OTHER filter, so
  // picking Tequila and then looking at the size row tells you how many
  // tequilas come in each format, not how many bottles exist in that size.
  // A combination that cannot fill a round is disabled rather than hidden,
  // so the row does not reshuffle under the thumb.
  // One builder for both rows. Chips toggle rather than replace, so the count
  // on each is what that chip adds under the OTHER axis's selection. Nothing
  // is disabled any more: with multi-select a chip too thin to stand alone is
  // still worth picking alongside another, and it is the Start button that
  // reports whether the combination can actually fill a round.
  function buildChips(wrapId, values, selected, countFor, onPick, onClear) {
    var wrap = $(wrapId);
    wrap.innerHTML = '';

    var all = document.createElement('button');
    all.className = 'chip' + (selected.length ? '' : ' is-on');
    all.appendChild(document.createTextNode('All'));
    var an = document.createElement('span');
    an.className = 'chip__n';
    an.textContent = num(countFor(null));
    all.appendChild(an);
    all.addEventListener('click', onClear);
    wrap.appendChild(all);

    values.forEach(function (v) {
      var count = countFor(v);
      var b = document.createElement('button');
      b.className = 'chip' + (selected.indexOf(v) !== -1 ? ' is-on' : '');
      b.appendChild(document.createTextNode(v));
      var sp = document.createElement('span');
      sp.className = 'chip__n';
      sp.textContent = num(count);
      b.appendChild(sp);
      if (!count) b.style.opacity = '.4';
      b.addEventListener('click', function () { onPick(v); });
      wrap.appendChild(b);
    });
  }

  function redraw() { renderChips(); renderSizeChips(); renderScopeChips(); renderHome(); }

  function renderChips() {
    buildChips('chips', CATS, catSel,
      function (c) { return pool(c ? [c] : [], sizeSel).length; },
      function (c) { toggle(catSel, c); redraw(); },
      function () { catSel = []; redraw(); });
  }

  function renderSizeChips() {
    buildChips('size-chips', SIZES, sizeSel,
      function (z) { return pool(catSel, z ? [z] : []).length; },
      function (z) { toggle(sizeSel, z); redraw(); },
      function () { sizeSel = []; redraw(); });
  }

  // Same row, one difference: these two chips replace each other instead of
  // adding up, and tapping the lit one turns it off back to All.
  function renderScopeChips() {
    buildChips('scope-chips', ['Popular', 'Obscure'],
      scopeSel === 'all' ? [] : [SCOPE_LABEL[scopeSel]],
      function (v) { return pool(catSel, sizeSel, v ? scopeKey(v) : 'all').length; },
      function (v) {
        var k = scopeKey(v);
        scopeSel = (scopeSel === k) ? 'all' : k;
        redraw();
      },
      function () { scopeSel = 'all'; redraw(); });
  }

  // ============================================================
  // LEARN + PRACTICE
  // ============================================================
  // Tiers ordered by what they actually cost rather than by hand, so the row
  // cannot drift out of order if the price file renames or adds one.
  var TIERS = (function () {
    var sum = {}, n = {};
    BOTTLES.forEach(function (b) { sum[b.t] = (sum[b.t] || 0) + b.p; n[b.t] = (n[b.t] || 0) + 1; });
    return Object.keys(n).sort(function (a, b) { return sum[a] / n[a] - sum[b] / n[b]; });
  })();

  // 9-litre cases for a brand WITHIN its own category and tier -- the same
  // figure the reveal screen ranks on. A brand can appear in two tiers with
  // two different numbers (E&J is 5,860 in Mid and 1,379 in Premium), so the
  // key has to carry all three parts.
  var volOf = (function () {
    var m = {};
    Object.keys(BRAND_RANKS).forEach(function (k) {
      BRAND_RANKS[k].forEach(function (pair) { m[k + '|' + pair[0]] = pair[1]; });
    });
    return function (b) { return m[b.c + '|' + b.t + '|' + b.b]; };
  })();

  // A tile is about 68px wide on a phone, and every name ends with its own
  // category -- "Hornitos Plata Tequila" in a row of tequilas. Drop it.
  function shortName(b) {
    var tail = b.c.split(' ').pop().replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return b.n.replace(new RegExp('\\s+' + tail + '$', 'i'), '');
  }

  // A chip row where one value is always chosen: no All, nothing to clear.
  function buildPicker(wrapId, values, current, countFor, onPick) {
    var wrap = $(wrapId);
    wrap.innerHTML = '';
    values.forEach(function (v) {
      var count = countFor(v);
      var b = document.createElement('button');
      b.className = 'chip' + (v === current ? ' is-on' : '');
      b.appendChild(document.createTextNode(v));
      var sp = document.createElement('span');
      sp.className = 'chip__n';
      sp.textContent = num(count);
      b.appendChild(sp);
      if (!count) b.style.opacity = '.4';
      b.addEventListener('click', function () { onPick(v); });
      wrap.appendChild(b);
    });
  }

  function miniShot(b) {
    var fig = document.createElement('div');
    fig.className = 'tile__shot';
    fig.innerHTML = drawnBottle(b);
    if (b.u) {
      var img = new Image();
      img.alt = '';
      img.decoding = 'async';
      img.onload = function () { fig.innerHTML = ''; fig.appendChild(img); };
      img.src = IMG_DIR + b.u + '.webp';
    }
    return fig;
  }

  // ---------- Learn ----------
  // One size at a time, and it is required: the same bottle in 375mL and
  // 1.75L would otherwise appear twice in one ladder at two prices, which
  // makes the ladder unreadable rather than richer.
  var lSize = null, lCats = [], lTiers = [];

  function learnPool(size, cats, tiers) {
    size = size || lSize;
    cats = cats || lCats;
    tiers = tiers || lTiers;
    return BOTTLES.filter(function (b) {
      return b.s === size &&
             (!cats.length || cats.indexOf(b.c) !== -1) &&
             (!tiers.length || tiers.indexOf(b.t) !== -1);
    });
  }

  function renderLearn() {
    buildPicker('l-size-chips', SIZES, lSize,
      function (z) { return learnPool(z).length; },
      function (z) { lSize = z; renderLearn(); });
    buildChips('l-cat-chips', CATS, lCats,
      function (c) { return learnPool(lSize, c ? [c] : []).length; },
      function (c) { toggle(lCats, c); renderLearn(); },
      function () { lCats = []; renderLearn(); });
    buildChips('l-tier-chips', TIERS, lTiers,
      function (t) { return learnPool(lSize, lCats, t ? [t] : []).length; },
      function (t) { toggle(lTiers, t); renderLearn(); },
      function () { lTiers = []; renderLearn(); });
    renderLadder();
  }

  function renderLadder() {
    var rows = learnPool().slice().sort(function (a, b) {
      return (a.p - b.p) || a.n.localeCompare(b.n);
    });
    var box = $('ladder');
    box.innerHTML = '';
    $('l-count').textContent = rows.length
      ? 'The ladder · ' + num(rows.length) + ' at ' + lSize
      : 'The ladder';

    if (!rows.length) {
      var e = document.createElement('p');
      e.className = 'empty';
      e.textContent = 'Nothing at ' + lSize + ' in that selection. Try another size, or clear a filter.';
      box.appendChild(e);
      return;
    }

    // The category-and-tier caveat that used to live here is gone with the
    // figure it applied to. A brand total only compared with other brands in
    // the same segment; an item's own cases compare with any other item's,
    // whatever the ladder is filtered to.
    //
    // the item's OWN cases. volOf() is the brand total, which is the right
    // figure for the rank card below and the wrong one here -- it printed
    // 31,114 against every Mom Water and 26,929 against every New Mix, so a
    // column of items was repeating one number down the page.
    var topVol = 0;
    rows.forEach(function (b) { topVol = Math.max(topVol, b.v || 0); });

    var head = document.createElement('div');
    head.className = 'ladder__head';
    ['', 'Bottle', 'Price', '9L cases'].forEach(function (t) {
      var sp = document.createElement('span');
      sp.textContent = t;
      head.appendChild(sp);
    });
    box.appendChild(head);

    rows.forEach(function (b, i) {
      var r = document.createElement('button');
      r.type = 'button';
      r.className = 'lrow';
      r.addEventListener('click', function () { openCard(b); });
      var vol = b.v;
      // the ladder's own leader, which needs no category-and-tier caveat now
      // that the figure belongs to the item rather than to its brand
      if (vol && vol === topVol) r.classList.add('is-top');

      var pos = document.createElement('span');
      pos.className = 'lrow__pos';
      pos.textContent = String(i + 1);
      r.appendChild(pos);

      var body = document.createElement('div');
      body.className = 'lrow__body';
      var nm = document.createElement('span');
      nm.className = 'lrow__name';
      nm.textContent = b.n;
      body.appendChild(nm);
      var br = document.createElement('span');
      br.className = 'lrow__brand';
      br.textContent = b.t + ' · ' + b.c;
      body.appendChild(br);
      r.appendChild(body);

      var pr = document.createElement('span');
      pr.className = 'lrow__price';
      pr.textContent = money(b.p);
      r.appendChild(pr);

      var vl = document.createElement('span');
      vl.className = 'lrow__vol';
      vl.textContent = vol ? num(Math.round(vol)) : '—';
      r.appendChild(vl);

      box.appendChild(r);
    });

    var foot = document.createElement('div');
    foot.className = 'ladder__foot';
    foot.textContent = '9-litre cases over 52 weeks, for the item itself';
    box.appendChild(foot);
  }

  // ---------- the bottle card ----------
  // Reached by tapping a ladder row. Where the ladder answers "what does the
  // shelf cost", this answers "what is this one and how big is it" -- the
  // photograph large enough to recognise, the price on its own, and the
  // volume both as a number and as a position in its segment.
  var cardScroll = 0;

  function openCard(b) {
    // remember where the ladder was: coming back to the top of fifty rows,
    // having tapped row forty, is its own small punishment
    cardScroll = document.scrollingElement ? document.scrollingElement.scrollTop : 0;
    renderCard(b);
    show('card');
  }

  function closeCard() {
    show('learn');
    // show() zeroes the window scroll, so this has to come after it
    if (document.scrollingElement) document.scrollingElement.scrollTop = cardScroll;
  }

  function addFig(parent, label, value, note, mod) {
    var d = document.createElement('div');
    d.className = 'fig' + (mod ? ' ' + mod : '');
    var l = document.createElement('span');
    l.className = 'fig__l';
    l.textContent = label;
    var v = document.createElement('span');
    v.className = 'fig__v';
    v.textContent = value;
    d.appendChild(l);
    d.appendChild(v);
    if (note) {
      var n = document.createElement('span');
      n.className = 'fig__n';
      n.textContent = note;
      d.appendChild(n);
    }
    parent.appendChild(d);
    return d;
  }

  function renderCard(b) {
    $('c-brand').textContent = b.b;
    $('c-name').textContent = b.n;

    // the big shot: the drawn bottle first, swapped for the photograph when
    // one decodes, exactly as the round does it
    var fig = $('c-shot');
    fig.innerHTML = drawnBottle(b);
    fig.classList.remove('has-photo');
    if (b.u) {
      var img = new Image();
      img.alt = b.n;
      img.decoding = 'async';
      img.onload = function () {
        fig.innerHTML = '';
        fig.appendChild(img);
        fig.classList.add('has-photo');
      };
      img.src = IMG_DIR + b.u + '.webp';
    }

    var tags = $('c-tags');
    tags.innerHTML = '';
    [['tag tag--cat', b.c], ['tag', b.t], ['tag', b.s + (b.k ? ' · ' + b.k + '-pack' : '')]]
      .forEach(function (t) {
        var sp = document.createElement('span');
        sp.className = t[0];
        sp.textContent = t[1];
        tags.appendChild(sp);
      });

    var figs = $('c-figures');
    figs.innerHTML = '';
    addFig(figs, b.k ? 'Average retail, per ' + b.k + '-pack' : 'Average retail',
      money(b.p), null, 'fig--lead');

    var vol = volOf(b);
    addFig(figs, '9-litre cases, 52 weeks', b.v ? num(b.v) : '—',
      vol ? 'this item; ' + b.b + ' is ' + num(Math.round(vol)) + ' in ' + b.t + ' ' + b.c
          : 'this item');
    addFig(figs, 'Distribution', distPct(b.a), 'of ' + num(MAX_ACCOUNTS) + ' accounts');
    if (b.f) addFig(figs, 'Strength', b.f);
    addFig(figs, 'Size', b.s);

    fillRanks(b, { box: 'c-ranks', head: 'c-ranks-h', sub: 'c-ranks-sub', list: 'c-ranks-list' },
      true, 'Average retail in ' + b.t + ' at ' + b.s +
            ' · a dash means that brand sells nothing there');

    renderAlso(b);
  }

  // Everything else the brand sells, whatever the size -- the one question a
  // single ladder row cannot answer, since the ladder is pinned to one format.
  function renderAlso(b) {
    var box = $('c-also'), head = $('c-also-h');
    var rest = BOTTLES.filter(function (x) { return x.b === b.b && x !== b; })
      .sort(function (x, y) { return x.p - y.p; });

    box.innerHTML = '';
    if (!rest.length) {
      box.hidden = head.hidden = true;
      return;
    }
    box.hidden = head.hidden = false;
    head.textContent = 'The rest of ' + b.b;

    rest.forEach(function (x) {
      var r = document.createElement('button');
      r.className = 'lrow';
      r.type = 'button';

      var body = document.createElement('div');
      body.className = 'lrow__body';
      var nm = document.createElement('span');
      nm.className = 'lrow__name';
      nm.textContent = x.n;
      body.appendChild(nm);
      var sub = document.createElement('span');
      sub.className = 'lrow__brand';
      sub.textContent = x.s + (x.k ? ' · ' + x.k + '-pack' : '') + ' · ' + x.t;
      body.appendChild(sub);
      r.appendChild(body);

      var pr = document.createElement('span');
      pr.className = 'lrow__price';
      pr.textContent = money(x.p);
      r.appendChild(pr);

      // staying on the card rather than pushing another one, so Back always
      // means the ladder and never a chain of cards to climb out of
      r.addEventListener('click', function () {
        renderCard(x);
        if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
      });
      box.appendChild(r);
    });
  }

  // ---------- Practice ----------
  // One category and one size, both required. Several tiers is fine and makes
  // the drill readable: inside a single tier the five prices can sit within a
  // couple of dollars of each other, which is a memory test rather than a
  // judgement of where a bottle belongs.
  var pSize = null, pCat = null, pTiers = [];
  var DRILL_N = 5;
  var drill = null;

  function practicePool(size, cat, tiers) {
    size = size || pSize;
    cat = cat || pCat;
    tiers = tiers || pTiers;
    return BOTTLES.filter(function (b) {
      return b.s === size && b.c === cat &&
             (!tiers.length || tiers.indexOf(b.t) !== -1);
    });
  }

  function renderPractice() {
    buildPicker('p-size-chips', SIZES, pSize,
      function (z) { return practicePool(z).length; },
      function (z) { pSize = z; drill = null; renderPractice(); });
    buildPicker('p-cat-chips', CATS, pCat,
      function (c) { return practicePool(pSize, c).length; },
      function (c) { pCat = c; drill = null; renderPractice(); });
    buildChips('p-tier-chips', TIERS, pTiers,
      function (t) { return practicePool(pSize, pCat, t ? [t] : []).length; },
      function (t) { toggle(pTiers, t); drill = null; renderPractice(); },
      function () { pTiers = []; drill = null; renderPractice(); });

    if (!drill) newDrill();
    renderDrill();
  }

  // Five bottles at five DIFFERENT prices. Two at $26.99 would leave the
  // drill with no single right answer, and the player marked wrong for an
  // order every bit as correct as the one being checked against.
  function newDrill() {
    var pool = practicePool();
    var byPrice = {};
    pool.forEach(function (b) { (byPrice[b.p] = byPrice[b.p] || []).push(b); });

    var prices = Object.keys(byPrice);
    for (var i = prices.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = prices[i]; prices[i] = prices[j]; prices[j] = t;
    }

    var picked = [], usedBrand = {};
    prices.forEach(function (pr) {
      if (picked.length >= DRILL_N) return;
      var opts = byPrice[pr];
      // a different brand each time where the shelf allows it, so the drill
      // is five decisions and not one brand's own line-up
      var fresh = opts.filter(function (b) { return !usedBrand[b.b]; });
      var from = fresh.length ? fresh : opts;
      var b = from[Math.floor(Math.random() * from.length)];
      usedBrand[b.b] = true;
      picked.push(b);
    });

    if (picked.length < DRILL_N) {
      drill = { short: picked.length };
      return;
    }

    var order = picked.slice();
    do {
      for (var k = order.length - 1; k > 0; k--) {
        var m = Math.floor(Math.random() * (k + 1));
        var tmp = order[k]; order[k] = order[m]; order[m] = tmp;
      }
      // never hand the player a drill that is already solved
    } while (isSorted(order));

    drill = { items: picked, order: order, checked: false };
  }

  function isSorted(list) {
    for (var i = 1; i < list.length; i++) if (list[i].p < list[i - 1].p) return false;
    return true;
  }

  function renderDrill() {
    var box = $('drill'), empty = $('drill-empty');
    var check = $('btn-drill-check');

    if (!drill || drill.short !== undefined) {
      box.hidden = true;
      empty.hidden = false;
      var have = drill ? drill.short : 0;
      empty.textContent = 'Only ' + have + ' bottle' + (have === 1 ? '' : 's') +
        ' at a price of its own in ' + (pCat || '—') + ' at ' + (pSize || '—') +
        '. Five are needed — add a price tier, or try another size.';
      check.disabled = true;
      return;
    }
    empty.hidden = true;
    box.hidden = false;
    check.disabled = drill.checked;

    var correct = drill.items.slice().sort(function (a, b) { return a.p - b.p; });
    var tiles = $('tiles');
    tiles.innerHTML = '';

    drill.order.forEach(function (b, i) {
      var el = document.createElement('div');
      el.className = 'tile';
      el.tabIndex = 0;
      // which slot of the CURRENT order this tile came from; commitOrder reads
      // it back after a drag has rearranged the row
      el.dataset.k = String(i);
      el.setAttribute('aria-label', shortName(b) + ', ' + b.s +
        (drill.checked ? ', ' + money(b.p) : ''));
      el.appendChild(miniShot(b));

      var nm = document.createElement('span');
      nm.className = 'tile__name';
      nm.textContent = shortName(b);
      el.appendChild(nm);

      // A drill is one size throughout -- practicePool filters on it -- so
      // this repeats down the row. It earns the line anyway: while you are
      // dragging you are looking at the tiles, not back up at the chip that
      // set the size, and what a bottle costs is meaningless without it.
      var sz = document.createElement('span');
      sz.className = 'tile__size';
      sz.textContent = b.s;
      el.appendChild(sz);

      var pr = document.createElement('span');
      pr.className = 'tile__price';
      pr.textContent = money(b.p);
      pr.hidden = !drill.checked;
      el.appendChild(pr);

      if (drill.checked) el.classList.add(correct[i] === b ? 'is-right' : 'is-wrong');
      tiles.appendChild(el);
    });

    var v = $('drill-verdict');
    if (drill.checked) {
      var hits = 0;
      drill.order.forEach(function (b, i) { if (correct[i] === b) hits++; });
      v.innerHTML = '';
      var strong = document.createElement('b');
      strong.textContent = hits + ' of ' + DRILL_N;
      v.appendChild(strong);
      v.appendChild(document.createTextNode(hits === DRILL_N
        ? ' — the whole ladder, in order.'
        : ' in the right place. Cheapest to most expensive runs ' +
          correct.map(function (b) { return shortName(b); }).join(' → ') + '.'));
      v.hidden = false;
    } else {
      v.hidden = true;
    }
  }

  function checkDrill() {
    if (!drill || drill.short !== undefined || drill.checked) return;
    drill.checked = true;
    renderDrill();
  }

  // ---------- dragging the tiles ----------
  // Pointer events, not HTML5 drag-and-drop: dragstart and drop never fire on
  // iOS Safari, which is most of the phones this gets played on. touch-action
  // is none on a tile (see the CSS) so a drag is not read as a page scroll.
  function wireDrag() {
    var tiles = $('tiles');
    var el = null, startX = 0, originLeft = 0, moved = false;

    tiles.addEventListener('pointerdown', function (e) {
      var t = e.target.closest ? e.target.closest('.tile') : null;
      if (!t || !tiles.contains(t)) return;
      el = t;
      moved = false;
      startX = e.clientX;
      originLeft = t.offsetLeft;
      t.setPointerCapture(e.pointerId);
      t.classList.add('is-drag');
      e.preventDefault();
    });

    tiles.addEventListener('pointermove', function (e) {
      if (!el) return;
      var dx = e.clientX - startX;
      if (Math.abs(dx) > 3) moved = true;

      // Keep swapping while the tile's centre is still past a neighbour's.
      // One swap per move event would be enough for a finger, which reports
      // a move every few pixels, but a flick -- or a mouse dragged fast --
      // can arrive as a single jump of three tiles, and the row has to
      // follow all of it.
      var swapped = true, guard = 0;
      while (swapped && guard++ < 16) {
        swapped = false;
        var centre = originLeft + dx + el.offsetWidth / 2;
        var sibs = Array.prototype.slice.call(tiles.children);
        for (var i = 0; i < sibs.length; i++) {
          var s = sibs[i];
          if (s === el) continue;
          var mid = s.offsetLeft + s.offsetWidth / 2;
          var elIsAfter = !!(s.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
          if ((elIsAfter && centre < mid) || (!elIsAfter && centre > mid)) {
            // Where the tile should stay on screen while the row relays out
            // underneath it. Without this correction it jumps out from under
            // the finger by a tile's width on every swap.
            var visualLeft = originLeft + dx;
            tiles.insertBefore(el, elIsAfter ? s : s.nextSibling);
            originLeft = el.offsetLeft;
            startX = e.clientX - (visualLeft - originLeft);
            dx = e.clientX - startX;
            swapped = true;
            break;
          }
        }
      }
      el.style.transform = 'translateX(' + dx + 'px)';
    });

    function end() {
      if (!el) return;
      el.style.transform = '';
      el.classList.remove('is-drag');
      var didMove = moved;
      el = null;
      if (didMove) commitOrder();
    }
    tiles.addEventListener('pointerup', end);
    tiles.addEventListener('pointercancel', end);

    // Arrows move a focused tile, so the drill is playable without a drag at
    // all -- and a way out if a pointer ever gets stuck mid-gesture.
    tiles.addEventListener('keydown', function (e) {
      var t = e.target.closest ? e.target.closest('.tile') : null;
      if (!t) return;
      var sibs = Array.prototype.slice.call(tiles.children);
      var i = sibs.indexOf(t);
      if (e.key === 'ArrowLeft' && i > 0) {
        tiles.insertBefore(t, sibs[i - 1]);
      } else if (e.key === 'ArrowRight' && i < sibs.length - 1) {
        tiles.insertBefore(t, sibs[i + 1].nextSibling);
      } else {
        return;
      }
      e.preventDefault();
      var at = Array.prototype.slice.call(tiles.children).indexOf(t);
      commitOrder(at);
    });
  }

  // The DOM is the source of truth while a drag is in flight; this reads the
  // arrangement back into the model once the finger lifts. Matching on the
  // element's position in the previous order rather than on its text, because
  // two bottles in a drill can share a short name.
  function commitOrder(focusAt) {
    if (!drill || !drill.items) return;
    var tiles = Array.prototype.slice.call($('tiles').children);
    if (tiles.length !== drill.order.length) return;
    var next = tiles.map(function (el) { return drill.order[+el.dataset.k]; });
    if (next.indexOf(undefined) !== -1) return;
    drill.order = next;
    // a rearrangement after a check is a new answer, not a corrected one
    drill.checked = false;
    renderDrill();
    if (focusAt !== undefined) {
      var again = $('tiles').children[focusAt];
      if (again) again.focus();
    }
  }

  // ============================================================
  // ROUND
  // ============================================================
  function dailyItems(key) {
    // 'All' on every axis deliberately: the daily is the same ten bottles for
    // everyone, so a player's own category, size or popularity choice must not
    // touch it.
    return pickRound(mulberry32(seedFrom('price-check|' + key)), [], [], 'all');
  }

  function startRound(mode) {
    var items = mode === 'daily' ? dailyItems(dayKey()) : pickRound();
    if (items.length < ROUND_LEN) return;
    game = { mode: mode || 'free', items: items, idx: 0, results: [],
             total: 0, streak: 0, bestStreak: 0 };
    typed = '';
    renderBottle();
    show('round');
  }

  // Replay a set of guesses through the same scoring the live round uses, so a
  // stored daily and a freshly played one can never disagree.
  function scoreGuesses(items, guesses) {
    var out = { results: [], total: 0, streak: 0, bestStreak: 0 };
    guesses.forEach(function (g, n) {
      var b = items[n];
      var err = Math.abs(g - b.p) / b.p;
      var base = pointsFor(err), bonus = 0;
      if (err <= STREAK_AT) {
        out.streak += 1;
        if (out.streak > 1) bonus = Math.min((out.streak - 1) * STREAK_STEP, STREAK_CAP);
        if (out.streak > out.bestStreak) out.bestStreak = out.streak;
      } else {
        out.streak = 0;
      }
      out.total += base + bonus;
      out.results.push({ bottle: b, guess: g, err: err, pts: base + bonus,
                         base: base, bonus: bonus, band: bandFor(err) });
    });
    return out;
  }

  // Rebuild a finished daily from its stored guesses, so revisiting it shows
  // the same summary instead of letting the round be played twice.
  function replayDaily(rec) {
    var items = rec.picks.map(function (i) { return BOTTLES[i]; });
    var scored = scoreGuesses(items, rec.guesses);
    game = { mode: 'daily', idx: ROUND_LEN - 1, items: items,
             results: scored.results, total: scored.total,
             streak: scored.streak, bestStreak: scored.bestStreak };
    renderSummary();
    show('sum');
  }

  function renderPips(done) {
    ['pips', 'pips2'].forEach(function (id) {
      var p = $(id);
      p.innerHTML = '';
      for (var i = 0; i < ROUND_LEN; i++) {
        var state = i < game.idx ? ' is-done' : i === game.idx ? (done ? ' is-done' : ' is-now') : '';
        var d = document.createElement('span');
        d.className = 'pip' + state;
        p.appendChild(d);
      }
      p.setAttribute('aria-valuenow', String(game.idx + 1));
      p.setAttribute('aria-valuemax', String(ROUND_LEN));
    });
    $('running').textContent = num(game.total);
    $('running2').textContent = num(game.total);
  }

  function renderBottle() {
    var b = game.items[game.idx];
    renderPips(false);
    renderShot(b);
    $('b-cat').textContent = b.c;
    $('b-tier').textContent = b.t;
    $('b-name').textContent = b.n;
    // the item name usually already opens with the brand — only show it when it adds something
    var redundant = b.n.toLowerCase().indexOf(b.b.toLowerCase()) === 0;
    $('b-brand').textContent = b.b;
    $('b-brand').hidden = redundant;
    $('b-name').classList.toggle('is-solo', redundant);

    var spec = $('b-spec');
    spec.innerHTML = '';
    // size is the one spec the guess actually hinges on -- a 1.75L and a 375mL
    // of the same thing are different questions -- so it is set larger
    addSpec(spec, 'Size', b.s, 'spec--lead');
    if (b.k) addSpec(spec, 'Pack', b.k + '-pack');
    if (b.f) addSpec(spec, 'Strength', b.f);
    addSpec(spec, 'Distribution', distPct(b.a));

    // a multipack is priced as a pack, so say so rather than letting the
    // player guess the price of one can
    $('g-hint').textContent = b.k
      ? 'Average retail, per ' + b.k + '-pack'
      : 'Average retail, per bottle';

    var card = $('bottle');
    card.style.animation = 'none';
    void card.offsetWidth;
    card.style.animation = '';

    typed = '';
    paintGuess();
  }

  function addSpec(parent, label, value, mod) {
    var w = document.createElement('div');
    w.className = 'spec' + (mod ? ' ' + mod : '');
    var l = document.createElement('span'); l.className = 'spec__l'; l.textContent = label;
    var v = document.createElement('span'); v.className = 'spec__v'; v.textContent = value;
    w.appendChild(l); w.appendChild(v);
    parent.appendChild(w);
  }

  function guessValue() { return typed === '' ? NaN : parseFloat(typed); }

  function paintGuess() {
    var amt = $('g-amount');
    $('g-digits').textContent = typed === '' ? '0' : typed;
    amt.classList.toggle('is-empty', typed === '');
    var v = guessValue();
    $('btn-lock').disabled = !(isFinite(v) && v > 0);
  }

  function press(k) {
    if (k === 'del') {
      typed = typed.slice(0, -1);
    } else if (k === '.') {
      if (typed.indexOf('.') === -1 && typed !== '') typed += '.';
    } else {
      var dot = typed.indexOf('.');
      if (dot !== -1 && typed.length - dot > 2) return;      // 2 decimals max
      if (dot === -1 && typed.replace('.', '').length >= 4) return; // $9999 max
      if (typed === '0') typed = '';
      typed += k;
    }
    buzz(4);
    paintGuess();
  }

  function buildKeys() {
    var keys = $('keys');
    keys.innerHTML = '';
    ['1','2','3','4','5','6','7','8','9','.','0','del'].forEach(function (k) {
      var b = document.createElement('button');
      b.className = 'key' + (k === '.' || k === 'del' ? ' key--fn' : '');
      b.type = 'button';
      if (k === 'del') {
        b.setAttribute('aria-label', 'Delete');
        b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6H9.5L4 12l5.5 6H20a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1z"/><path d="M15 10l-4 4M11 10l4 4"/></svg>';
      } else {
        b.textContent = k;
      }
      b.addEventListener('click', function () { press(k); });
      keys.appendChild(b);
    });
  }

  // ============================================================
  // REVEAL
  // ============================================================
  function lockIn() {
    var v = guessValue();
    if (!(isFinite(v) && v > 0)) return;
    var b = game.items[game.idx];
    var err = Math.abs(v - b.p) / b.p;
    var band = bandFor(err);
    var base = pointsFor(err);

    var bonus = 0;
    if (err <= STREAK_AT) {
      game.streak += 1;
      if (game.streak > 1) bonus = Math.min((game.streak - 1) * STREAK_STEP, STREAK_CAP);
      if (game.streak > game.bestStreak) game.bestStreak = game.streak;
    } else {
      game.streak = 0;
    }

    var pts = base + bonus;
    game.total += pts;
    game.results.push({ bottle: b, guess: v, err: err, pts: pts, base: base, bonus: bonus, band: band });

    // running stats
    stats.sumPct += err;
    stats.nGuess += 1;
    var c = stats.cat[b.c] || { sum: 0, n: 0 };
    c.sum += err; c.n += 1;
    stats.cat[b.c] = c;
    saveStats();

    buzz(err <= STREAK_AT ? [8, 40, 12] : 10);
    renderReveal(game.results[game.results.length - 1]);
    show('reveal');
  }

  function renderReveal(r) {
    var b = r.bottle;
    renderPips(true);
    var v = $('verdict');
    v.className = 'verdict ' + r.band.tone;
    $('v-band').textContent = r.band.label;
    $('v-pts').textContent = '+' + num(r.pts);
    $('v-sub').textContent = r.err < 0.005 ? 'Exact' :
      pct(r.err) + ' ' + (r.guess > b.p ? 'high' : 'low');

    $('v-guess').textContent = moneyShort(r.guess);
    $('v-actual').textContent = money(b.p);

    var fill = $('v-fill');
    fill.style.width = '0%';
    var closeness = Math.max(0, 1 - r.err / ZERO_AT);
    setTimeout(function () { fill.style.width = Math.round(closeness * 100) + '%'; }, 40);

    var diff = Math.abs(r.guess - b.p);
    var recap = $('v-recap');
    recap.innerHTML = '';
    recap.appendChild(document.createTextNode(r.band.line + ' '));
    var strong = document.createElement('b');
    strong.textContent = money(diff) + (r.guess > b.p ? ' over' : ' under');
    recap.appendChild(strong);
    recap.appendChild(document.createTextNode(' on ' + label(b) + ', ' + b.s + '.'));

    renderSizes(b);
    renderRanks(b);

    var st = $('v-streak');
    if (r.bonus > 0) {
      st.hidden = false;
      st.textContent = '🔥 ' + game.streak + ' in a row · +' + r.bonus + ' bonus';
    } else {
      st.hidden = true;
    }

    $('btn-next').textContent = (game.idx + 1 >= ROUND_LEN) ? 'See your round' : 'Next bottle';
  }

  // Where this bottle's brand sits on volume in its category, with the two
  // brands immediately above and below it.
  // Average shelf price for a brand at one category and size. Built lazily and
  // cached, because the reveal screen draws five of these per bottle.
  var compCache = {};
  // Scoped to the TIER as well as the size, because the list it feeds is a
  // tier segment. Without the tier, Crown Royal showed $44.37 in a table of
  // Super Premium whiskeys -- its five Super Premium 750mLs are all $25.99,
  // and the average was being dragged up by an Ultra XO, an Ultra 12 Year and
  // a $140.99 Luxury 18 Year that are not in that segment at all. It read as
  // the dearest brand on the list when it is the same price as the rest.
  // Costs about four points more dashes (29% of rank rows to 33%), which is
  // the right trade for a column that means what the heading above it says.
  function compPrice(brand, cat, size, tier) {
    var key = brand + '|' + cat + '|' + size + '|' + (tier || '');
    if (compCache.hasOwnProperty(key)) return compCache[key];
    var sum = 0, n = 0;
    for (var i = 0; i < BOTTLES.length; i++) {
      var x = BOTTLES[i];
      if (x.b === brand && x.c === cat && x.s === size &&
          (!tier || x.t === tier)) { sum += x.p; n++; }
    }
    compCache[key] = n ? sum / n : null;
    return compCache[key];
  }

  // The reveal screen and the bottle card both want this list, so it takes
  // the element ids rather than owning them. `full` is the difference between
  // them: mid-round you get the two brands either side, which is a comparison;
  // on a card you get the whole segment, which is a map.
  function fillRanks(b, ids, full, subText) {
    var box = $(ids.box);
    var list = $(ids.list);
    // same category AND same price segment: comps a rep would actually make
    var all = RANKS[b.c + '|' + b.t];
    if (!all || all.length < 2) { box.hidden = true; return; }

    var at = -1;
    for (var i = 0; i < all.length; i++) if (all[i][0] === b.b) { at = i; break; }
    if (at === -1) { box.hidden = true; return; }

    var from, to;
    if (full) {
      from = 0;
      to = all.length;
    } else {
      // One either side, sliding inwards at the ends; a thin segment shows
      // fewer. Three rather than five since the by-size card joined this
      // screen: the comparison a player reads mid-round is the brand just
      // above and just below, and the whole segment is on the bottle's card
      // in Learn for anyone who wants it.
      var span = Math.min(ids.span || 5, all.length);
      from = Math.max(0, Math.min(at - 2, all.length - span));
      to = Math.min(all.length, from + span);
    }

    $(ids.head).textContent = b.b + ' is #' + (at + 1) + ' of ' + all.length +
      ' ' + b.t + ' ' + b.c + ' brands by volume';
    $(ids.sub).textContent = subText;

    list.innerHTML = '';
    for (var k = from; k < to; k++) {
      var row = all[k];
      var li = document.createElement('li');
      li.className = 'rrow' + (k === at ? ' is-me' : '');

      var pos = document.createElement('span');
      pos.className = 'rrow__pos';
      pos.textContent = k + 1;

      var nm = document.createElement('span');
      nm.className = 'rrow__name';
      nm.textContent = row[0];

      var pr = document.createElement('span');
      pr.className = 'rrow__price';
      var avg = compPrice(row[0], b.c, b.s, b.t);
      // the comp's price is only a fair comparison at the SAME size, so where
      // that brand has nothing in this format say so rather than quietly
      // averaging a 1.75L into a 750mL line-up
      pr.textContent = avg === null ? '—' : money(avg);
      if (avg === null) pr.classList.add('is-none');

      var cs = document.createElement('span');
      cs.className = 'rrow__cases';
      cs.textContent = Math.round(row[1]).toLocaleString('en-US');

      li.appendChild(pos); li.appendChild(nm); li.appendChild(pr); li.appendChild(cs);
      list.appendChild(li);
    }
    box.hidden = false;
  }

  // ---------- the same bottle in its other formats ----------
  // Asked on the reveal because that is where the player has just committed
  // to a number and is most willing to be told what the rest of the shelf
  // costs. 56% of the bank shares a name with another size, and never more
  // than three others, so this stays short.
  var SIZE_ML = { "50mL": 50, "100mL": 100, "200mL": 200, "250mL": 250,
                  "355mL": 355, "375mL": 375, "500mL": 500, "700mL": 700,
                  "750mL": 750, "1L": 1000, "1.75L": 1750 };

  function mlOf(b) {
    if (SIZE_ML[b.s]) return SIZE_ML[b.s] * (b.k || 1);
    var m = /^([\d.]+)\s*(mL|L)$/i.exec(b.s || "");
    if (!m) return null;
    var v = parseFloat(m[1]);
    return (m[2].toLowerCase() === "l" ? v * 1000 : v) * (b.k || 1);
  }

  var sizeKin = (function () {
    var m = {};
    BOTTLES.forEach(function (b) {
      var k = b.b + "\u0000" + b.n;
      (m[k] = m[k] || []).push(b);
    });
    return function (b) {
      var all = m[b.b + "\u0000" + b.n] || [];
      // one row per size: the same name at the same size twice is the
      // duplicate the bank already resolves, not a format to compare against
      var seen = {}, out = [];
      all.forEach(function (x) {
        if (seen[x.s]) return;
        seen[x.s] = 1;
        out.push(x);
      });
      return out.length > 1 ? out : [];
    };
  })();

  function renderSizes(b) {
    var box = $('v-sizes'), list = $('v-sizes-list');
    var kin = sizeKin(b);
    if (kin.length < 2) { box.hidden = true; return; }

    kin = kin.slice().sort(function (x, y) { return (mlOf(x) || 0) - (mlOf(y) || 0); });
    $('v-sizes-h').textContent = label(b) + ' by size';

    // cheapest per litre, which is not reliably the biggest bottle
    var best = null;
    kin.forEach(function (x) {
      var ml = mlOf(x);
      if (!ml) return;
      var per = x.p / (ml / 1000);
      if (best === null || per < best) best = per;
    });

    list.innerHTML = '';
    kin.forEach(function (x) {
      var row = document.createElement('div');
      row.className = 'srow' + (x === b ? ' is-me' : '');

      var sz = document.createElement('span');
      sz.className = 'srow__size';
      sz.textContent = x.s + (x.k ? ' · ' + x.k + 'pk' : '');
      row.appendChild(sz);

      var pr = document.createElement('span');
      pr.className = 'srow__price';
      pr.textContent = money(x.p);
      row.appendChild(pr);

      var per = document.createElement('span');
      per.className = 'srow__per';
      var ml = mlOf(x);
      if (ml) {
        var v = x.p / (ml / 1000);
        per.textContent = money(v) + '/L';
        if (best !== null && Math.abs(v - best) < 0.005) row.classList.add('is-best');
      } else {
        per.textContent = '—';
      }
      row.appendChild(per);

      list.appendChild(row);
    });
    box.hidden = false;
  }

  function renderRanks(b) {
    fillRanks(b, { box: 'v-ranks', head: 'v-ranks-h', sub: 'v-ranks-sub',
                   list: 'v-ranks-list', span: 3 },
      false, 'Average retail in ' + b.t + ' at ' + b.s + ' \u00b7 this one went for ' + money(b.p));
  }

  function nextStep() {
    if (game.idx + 1 >= ROUND_LEN) { finishRound(); return; }
    game.idx += 1;
    renderBottle();
    show('round');
  }

  // ============================================================
  // SUMMARY
  // ============================================================
  function finishRound() {
    stats.rounds += 1;
    stats.totalPts += game.total;
    if (game.total > stats.bestRound) stats.bestRound = game.total;
    if (game.bestStreak > stats.bestStreak) stats.bestStreak = game.bestStreak;

    if (game.mode === 'daily') {
      var today = dayKey();
      if (stats.dailyLast !== today) {
        stats.dailyStreak = (stats.dailyLast === yesterdayKey()) ? stats.dailyStreak + 1 : 1;
        stats.dailyLast = today;
        stats.dailyPlayed += 1;
      }
      if (game.total > stats.dailyBest) stats.dailyBest = game.total;
      saveDaily({
        date: today,
        picks: game.items.map(function (b) { return b.i; }),
        guesses: game.results.map(function (r) { return r.guess; })
      });
    }

    saveStats();
    renderSummary();
    show('sum');
  }

  function markFor(err) {
    for (var i = 0; i < MARKS.length; i++) if (err <= MARKS[i][0]) return MARKS[i][1];
    return MARKS[MARKS.length - 1][1];
  }

  function shareText() {
    var grid = game.results.map(function (r) { return markFor(r.err); }).join('');
    var avg = game.results.reduce(function (a, r) { return a + r.err; }, 0) / game.results.length;
    return 'price check · ' + prettyDay(dayKey()) + '\n' +
           num(game.total) + ' pts · ' + pct(avg) + ' off\n' +
           grid + '\n' + SHARE_URL;
  }

  function shareResult() {
    var text = shareText();
    var done = function (msg) {
      var btn = $('btn-share');
      var was = btn.textContent;
      btn.textContent = msg;
      setTimeout(function () { btn.textContent = was; }, 1800);
    };
    if (navigator.share) {
      navigator.share({ text: text }).catch(function () {});
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done('Copied'); },
                                               function () { done('Copy failed'); });
      return;
    }
    // last resort for older mobile browsers
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    try { done(document.execCommand('copy') ? 'Copied' : 'Copy failed'); }
    catch (e) { done('Copy failed'); }
    document.body.removeChild(ta);
  }

  function renderSummary() {
    var rs = game.results;
    var avgErr = rs.reduce(function (a, r) { return a + r.err; }, 0) / rs.length;
    var best = rs.reduce(function (a, r) { return r.err < a.err ? r : a; }, rs[0]);

    var isDaily = game.mode === 'daily';
    $('s-score').textContent = num(game.total);
    $('s-of').textContent = 'out of ' + num(ROUND_LEN * MAX_PER) + ', before streak bonuses';
    $('s-eyebrow').textContent = isDaily
      ? 'Daily · ' + prettyDay(dayKey())
      : (game.total >= stats.bestRound && game.total > 0 ? 'New personal best' : 'Round complete');

    $('btn-share').hidden = !isDaily;
    $('btn-again').hidden = isDaily;
    var marks = $('s-marks');
    marks.hidden = !isDaily;
    if (isDaily) marks.textContent = rs.map(function (r) { return markFor(r.err); }).join('');

    $('s-acc').textContent = pct(avgErr);
    $('s-best').textContent = pct(best.err);
    $('s-streak').textContent = num(game.bestStreak);

    var pctScore = game.total / (ROUND_LEN * MAX_PER);
    var verdict;
    if (pctScore >= 0.85) verdict = 'You are pricing like you set the shelf tags.';
    else if (pctScore >= 0.65) verdict = 'Strong round. The misses were on the odd sizes.';
    else if (pctScore >= 0.45) verdict = 'Middling. The tier reads are landing, the dollars are not.';
    else verdict = 'Rough round. Try one category at a time and build the feel.';

    var g = $('s-grade');
    g.innerHTML = '';
    var bb = document.createElement('b');
    bb.textContent = 'Average miss ' + pct(avgErr) + '. ';
    g.appendChild(bb);
    g.appendChild(document.createTextNode(verdict + ' Best call: ' + label(best.bottle) +
      ' at ' + money(best.bottle.p) + '.'));

    var list = $('tally');
    list.innerHTML = '';
    rs.forEach(function (r) {
      var li = document.createElement('li');
      li.className = 'trow';

      var nm = document.createElement('span');
      nm.className = 'trow__name';
      nm.textContent = label(r.bottle);

      var meta = document.createElement('span');
      meta.className = 'trow__meta';
      meta.appendChild(document.createTextNode(moneyShort(r.guess) + ' → ' + money(r.bottle.p) + ' · '));
      var sp = document.createElement('span');
      sp.className = r.err <= STREAK_AT ? 'hit' : r.err >= ZERO_AT ? 'miss' : '';
      sp.textContent = r.err < 0.005 ? 'exact' : pct(r.err) + (r.guess > r.bottle.p ? ' high' : ' low');
      meta.appendChild(sp);

      var pt = document.createElement('span');
      pt.className = 'trow__pts';
      pt.textContent = num(r.pts);

      li.appendChild(nm); li.appendChild(pt); li.appendChild(meta);
      list.appendChild(li);
    });
  }

  // ============================================================
  // STATS
  // ============================================================
  function renderStats() {
    $('x-rounds').textContent = num(stats.rounds);
    $('x-best').textContent = stats.bestRound ? num(stats.bestRound) : '—';
    $('x-streak').textContent = num(stats.bestStreak);

    // a streak only counts while it is current — yesterday or today
    var live = (stats.dailyLast === dayKey() || stats.dailyLast === yesterdayKey())
      ? stats.dailyStreak : 0;
    $('x-dstreak').textContent = num(live);
    $('x-dplayed').textContent = num(stats.dailyPlayed);
    var rec = loadDaily();
    $('x-dtoday').textContent = rec
      ? num(scoreGuesses(rec.picks.map(function (i) { return BOTTLES[i]; }), rec.guesses).total)
      : '—';

    var wrap = $('cat-bars');
    wrap.innerHTML = '';
    var keys = Object.keys(stats.cat).sort(function (a, b) {
      return (stats.cat[a].sum / stats.cat[a].n) - (stats.cat[b].sum / stats.cat[b].n);
    });
    if (!keys.length) {
      var e = document.createElement('p');
      e.className = 'empty';
      e.textContent = 'Play a round and your category accuracy shows up here.';
      wrap.appendChild(e);
      return;
    }
    keys.forEach(function (k) {
      var c = stats.cat[k];
      var avg = c.sum / c.n;
      var acc = Math.max(0, 1 - avg / ZERO_AT);

      var row = document.createElement('div'); row.className = 'barrow';
      var top = document.createElement('div'); top.className = 'barrow__top';
      var nm = document.createElement('span'); nm.textContent = k;
      var vn = document.createElement('span'); vn.className = 'barrow__n';
      vn.textContent = pct(avg) + ' off · ' + c.n + ' guess' + (c.n === 1 ? '' : 'es');
      top.appendChild(nm); top.appendChild(vn);

      var track = document.createElement('div'); track.className = 'barrow__track';
      var fill = document.createElement('span'); fill.className = 'barrow__fill';
      fill.style.width = Math.round(acc * 100) + '%';
      track.appendChild(fill);

      row.appendChild(top); row.appendChild(track);
      wrap.appendChild(row);
    });
  }

  // ============================================================
  // GUIDE
  // ============================================================
  function renderGuide() {
    var ul = $('band-list');
    ul.innerHTML = '';
    var edges = [0, 0.03, 0.08, 0.15, 0.30, 0.60];
    ['Dead on', 'Nailed it', 'Close', 'In range', 'Off'].forEach(function (label, i) {
      var hi = pointsFor(edges[i]);                 // best you can do in this band
      var lo = pointsFor(Math.min(edges[i + 1], ZERO_AT - 0.0001)); // worst
      var li = document.createElement('li');
      var b = document.createElement('b'); b.textContent = label;
      var s = document.createElement('span');
      s.textContent = 'within ' + Math.round(edges[i + 1] * 100) + '%  ·  ' +
        num(lo) + '–' + num(hi) + ' pts';
      li.appendChild(b); li.appendChild(s);
      ul.appendChild(li);
    });
    $('guide-source').textContent =
      'Average retail price per item, taken straight from your distribution file. ' +
      'Only bottles stocked in 10 or more accounts are in play, so the average is a real ' +
      'shelf price and not a one-store fluke. ' + num(BOTTLES.length) + ' bottles qualify.';
  }

  // ============================================================
  // WIRING
  // ============================================================
  function quitRound() {
    game = null;
    setTab('home');
    renderHome();
  }

  function init() {
    if (!BOTTLES.length) {
      document.body.innerHTML =
        '<p style="padding:40px;font-family:system-ui">No bottle data loaded. ' +
        'Run <code>tools/build_bank.py</code> to regenerate <code>app/data/bottles.js</code>.</p>';
      return;
    }

    buildKeys();
    // one call rather than three: a row added to the setup screen and not
    // added here is a row that silently never draws
    redraw();
    renderGuide();

    // Learn and Practice both require a size, and Practice a category, so
    // they open on the biggest-selling format rather than on an empty screen.
    // SIZES and CATS are ordered by how much of the bank sits in each.
    lSize = pSize = SIZES[0];
    pCat = CATS[0];
    // Learn opens on ONE category rather than All. Every category at once is
    // 255 rows at 750mL, which is a long scroll before the screen tells you
    // anything; one is a shelf you could stand in front of. All is still a
    // tap away on the row.
    lCats = [CATS[0]];
    wireDrag();
    $('btn-drill-new').addEventListener('click', function () {
      newDrill();
      renderDrill();
    });
    $('btn-drill-check').addEventListener('click', checkDrill);
    $('btn-card-back').addEventListener('click', closeCard);

    $('btn-play').addEventListener('click', function () { startRound('free'); });
    $('btn-again').addEventListener('click', function () { startRound('free'); });
    $('btn-share').addEventListener('click', shareResult);
    $('btn-daily').addEventListener('click', function () {
      var rec = loadDaily();
      if (rec) replayDaily(rec); else startRound('daily');
    });
    $('btn-lock').addEventListener('click', lockIn);
    $('btn-next').addEventListener('click', nextStep);
    $('btn-quit').addEventListener('click', quitRound);
    $('btn-home').addEventListener('click', quitRound);
    $('btn-guide-top').addEventListener('click', function () { setTab('guide'); });

    $('btn-reset').addEventListener('click', function () {
      if (!confirm('Clear every round, score and streak on this device?')) return;
      try { localStorage.removeItem(STORE_KEY); } catch (e) {}
      stats = loadStats();
      renderStats();
      renderHome();
    });

    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (t) {
      t.addEventListener('click', function () {
        if (t.dataset.tab === 'home') renderHome();
        setTab(t.dataset.tab);
      });
    });

    // hardware keyboard, for desktop play
    document.addEventListener('keydown', function (e) {
      if ($('view-round').hidden) {
        if (e.key === 'Enter' && !$('view-reveal').hidden) { e.preventDefault(); nextStep(); }
        return;
      }
      if (e.key >= '0' && e.key <= '9') { press(e.key); e.preventDefault(); }
      else if (e.key === '.') { press('.'); e.preventDefault(); }
      else if (e.key === 'Backspace') { press('del'); e.preventDefault(); }
      else if (e.key === 'Enter') { lockIn(); e.preventDefault(); }
    });

    setTab('home');

    if ('serviceWorker' in navigator && location.protocol.indexOf('http') === 0) {
      window.addEventListener('load', function () {
        navigator.serviceWorker.register('sw.js').catch(function () {});
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
