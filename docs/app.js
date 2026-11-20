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
  var pct = function (x) { return (x * 100).toFixed(x < 0.1 ? 1 : 0) + '%'; };
  var buzz = function (ms) { if (navigator.vibrate) { try { navigator.vibrate(ms); } catch (e) {} } };

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
  var catFilter = 'All';
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

  // ============================================================
  // ROUND BUILDING
  // ============================================================
  function pool(cat) {
    cat = cat || catFilter;
    return cat === 'All' ? BOTTLES : BOTTLES.filter(function (b) { return b.c === cat; });
  }

  function pickRound(rng, cat) {
    rng = rng || Math.random;
    cat = cat || catFilter;
    var src = pool(cat).slice();
    // Fisher–Yates
    for (var i = src.length - 1; i > 0; i--) {
      var j = Math.floor(rng() * (i + 1));
      var t = src[i]; src[i] = src[j]; src[j] = t;
    }
    var out = [], seenBrand = {}, perCat = {};
    var catCap = cat === 'All' ? 3 : ROUND_LEN;

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
  var VIEWS = ['home', 'round', 'reveal', 'sum', 'stats', 'guide'];
  function show(name) {
    VIEWS.forEach(function (v) { $('view-' + v).hidden = (v !== name); });
    var inGame = (name === 'round' || name === 'reveal' || name === 'sum');
    $('tabs').hidden = inGame;
    var sc = $('view-' + name).querySelector('.scroll');
    if (sc) sc.scrollTop = 0;
  }
  function setTab(name) {
    currentTab = name;
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (t) {
      t.classList.toggle('is-on', t.dataset.tab === name);
    });
    if (name === 'stats') renderStats();
    show(name);
  }

  // ============================================================
  // HOME
  // ============================================================
  function renderHome() {
    var n = pool().length;
    $('hero-eyebrow').textContent = ROUND_LEN + ' bottles · ' + catFilter;
    $('hero-meta').textContent = num(n) + ' bottle' + (n === 1 ? '' : 's') + ' in the book';
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

  function renderChips() {
    var wrap = $('chips');
    wrap.innerHTML = '';
    ['All'].concat(CATS).forEach(function (c) {
      var count = c === 'All' ? BOTTLES.length : catCounts[c];
      var b = document.createElement('button');
      b.className = 'chip' + (c === catFilter ? ' is-on' : '');
      b.innerHTML = '';
      b.appendChild(document.createTextNode(c));
      var s = document.createElement('span');
      s.className = 'chip__n';
      s.textContent = num(count);
      b.appendChild(s);
      b.disabled = count < ROUND_LEN;
      if (count < ROUND_LEN) b.style.opacity = '.4';
      b.addEventListener('click', function () {
        catFilter = c;
        renderChips();
        renderHome();
      });
      wrap.appendChild(b);
    });
  }

  // ============================================================
  // ROUND
  // ============================================================
  function dailyItems(key) {
    return pickRound(mulberry32(seedFrom('price-check|' + key)), 'All');
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
    addSpec(spec, 'Size', b.s);
    if (b.f) addSpec(spec, 'Strength', b.f);
    addSpec(spec, 'Stocked in', num(b.a) + ' accts');

    var card = $('bottle');
    card.style.animation = 'none';
    void card.offsetWidth;
    card.style.animation = '';

    typed = '';
    paintGuess();
  }

  function addSpec(parent, label, value) {
    var w = document.createElement('div');
    w.className = 'spec';
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
    recap.appendChild(document.createTextNode(' on ' + b.n + ', ' + b.s + '.'));

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
  function renderRanks(b) {
    var box = $('v-ranks');
    var list = $('v-ranks-list');
    var all = RANKS[b.c];
    if (!all || !all.length) { box.hidden = true; return; }

    var at = -1;
    for (var i = 0; i < all.length; i++) if (all[i][0] === b.b) { at = i; break; }
    if (at === -1) { box.hidden = true; return; }

    // two either side, sliding inwards at the ends so it is always five rows
    var from = Math.max(0, Math.min(at - 2, all.length - 5));
    var to = Math.min(all.length, from + 5);

    // "of 66 brands in Cordials", not "of 66 cordials brands"
    $('v-ranks-h').textContent = b.b + ' is #' + (at + 1) + ' of ' + all.length +
      ' brands in ' + b.c + ' by volume';

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

      var cs = document.createElement('span');
      cs.className = 'rrow__cases';
      cs.textContent = Math.round(row[1]).toLocaleString('en-US');

      li.appendChild(pos); li.appendChild(nm); li.appendChild(cs);
      list.appendChild(li);
    }
    box.hidden = false;
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
    g.appendChild(document.createTextNode(verdict + ' Best call: ' + best.bottle.n +
      ' at ' + money(best.bottle.p) + '.'));

    var list = $('tally');
    list.innerHTML = '';
    rs.forEach(function (r) {
      var li = document.createElement('li');
      li.className = 'trow';

      var nm = document.createElement('span');
      nm.className = 'trow__name';
      nm.textContent = r.bottle.n;

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
    renderChips();
    renderHome();
    renderGuide();

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
