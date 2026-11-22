"""Ultimate AH server scan: every Forever auction house, every hour, into a small database.

The PC script (ah_api.py) only scans while that PC is on. This one is meant for a machine that is
always there (the Docker image, or any server with Python):

    python ah_server.py probe --dir DIR     has Blizzard published new data? (a few small requests)
    python ah_server.py run   --dir DIR     scan every house, update the database, write the data files
    python ah_server.py info  --dir DIR     what the database holds
    python ah_server.py serve --dir DIR     stay running: scan whenever Blizzard has new data and
                                            hand out the data files over HTTP (this is what the
                                            Docker image runs; put HTTPS in front of it)

Everything lives in DIR:

    history.db                      SQLite: one row per auction house, item and day (30 days)
    history.db.gz                   the same, packed for publishing
    state-<region>-<house>.json.gz  the previous snapshot of a house: needed to see what was sold
    <region>-<house>.lua.gz         what the addon loads (the ApiData.lua format); ah_api.py downloads it
    index.json                      the list of houses with the time of their last scan

Credentials: the environment variables BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET (or blizzard_api.json).

Blizzard's API terms allow keeping API data for 30 days at most, so nothing older stays in the
database. Auction data: Blizzard Entertainment, through the Battle.net Game Data API.
"""
import argparse
import array
import collections
import email.utils
import gzip
import http.server
import importlib.util
import itertools
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import zlib

import ah_api
import ah_ml
from ah_api import ApiError, log

REGION = os.environ.get("AH_REGION", "eu")
RULESET = int(os.environ.get("AH_RULESET", "1"))     # every ruleset lists the same houses
FACTIONS = ("Alliance", "Horde")
KEEP_DAYS = 30                                        # Blizzard's limit for stored API data
SOURCE = "Blizzard Entertainment, Battle.net Game Data API"

SCHEMA = """
CREATE TABLE IF NOT EXISTS house (
  hk INTEGER PRIMARY KEY, region TEXT NOT NULL, id INTEGER NOT NULL, ruleset INTEGER, faction TEXT, name TEXT,
  t INTEGER, modified TEXT, auctions INTEGER, items INTEGER, UNIQUE (region, id));
-- one row per house, day and item (or item variant "id:b<bonus ids>"):
--   mkt_sum / n = the day's mean market price, min = the day's lowest buyout (copper per unit)
--   qty = units listed at the last scan of the day, sold / sold_n = units and auctions counted as sold
CREATE TABLE IF NOT EXISTS daily (
  house INTEGER NOT NULL, day INTEGER NOT NULL, key TEXT NOT NULL,
  mkt_sum INTEGER NOT NULL DEFAULT 0, n INTEGER NOT NULL DEFAULT 0, min INTEGER,
  qty INTEGER NOT NULL DEFAULT 0, sold INTEGER NOT NULL DEFAULT 0, sold_n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (house, day, key)) WITHOUT ROWID;
-- seconds of each day covered by two scans that could be compared (the base of the sale rates)
CREATE TABLE IF NOT EXISTS cover (house INTEGER NOT NULL, day INTEGER NOT NULL, seconds INTEGER NOT NULL,
  PRIMARY KEY (house, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS scan (house INTEGER NOT NULL, t INTEGER NOT NULL, auctions INTEGER, items INTEGER,
  sold_units INTEGER, PRIMARY KEY (house, t)) WITHOUT ROWID;
-- prices and sales by hour of the day (UTC), one row per item. v = 96 float32: for each hour the sum of
-- log(price / the item's weekly mean), the number of prices, the units sold, and the sum of the squared
-- logs. Everything fades by PROFILE_DECAY per day; day = the last day the row was touched
CREATE TABLE IF NOT EXISTS hours (house INTEGER NOT NULL, key TEXT NOT NULL, day INTEGER NOT NULL, v BLOB NOT NULL,
  PRIMARY KEY (house, key)) WITHOUT ROWID;
-- the forecast's two weights per house, fitted once a day on what the prices of the last weeks did:
-- n checks, err = its mean error, naive = the error of "the price stays the same" (both in log price)
CREATE TABLE IF NOT EXISTS model (house INTEGER PRIMARY KEY, day INTEGER, a REAL, b REAL, n INTEGER,
  err REAL, naive REAL, ok INTEGER);
"""


HOURLY_DAYS = 14                                      # hour-by-hour prices kept for the hour-ahead forecasts
HOURLY_MIN = 2                                        # auctions an item needs for its hour to be kept
# a file of its own (hourly.db), not handed out: the scan writes it, ah_ml.py learns from it
HOURLY_SCHEMA = """
-- a small number per house and item, so that an hour is six columns of numbers
CREATE TABLE IF NOT EXISTS item (house INTEGER NOT NULL, key TEXT NOT NULL, id INTEGER NOT NULL,
  PRIMARY KEY (house, key)) WITHOUT ROWID;
-- one row per house and scan. hour = t / 3600; v = zlib of 6 x n little-endian int32: the items' ids,
-- market price, lowest buyout, units listed, auctions, units sold since the scan before
CREATE TABLE IF NOT EXISTS hour (house INTEGER NOT NULL, hour INTEGER NOT NULL, t INTEGER NOT NULL,
  n INTEGER NOT NULL, v BLOB NOT NULL, PRIMARY KEY (house, hour)) WITHOUT ROWID;
"""
HOURLY_FIELDS = ("mkt", "min", "qty", "num")


def archive_hour(folder, hk, t, table, sold):
    """keep this scan's prices in the hour-by-hour archive -> (items kept, hours the house has there)"""
    db = sqlite3.connect(os.path.join(folder, "hourly.db"))
    try:
        db.executescript(HOURLY_SCHEMA)
        ids = dict(db.execute("SELECT key, id FROM item WHERE house = ?", (hk,)))
        keys = [k for k, p in table.items() if p["num"] >= HOURLY_MIN and p["mkt"] > 0]
        new = sorted(k for k in keys if k not in ids)
        first = max(ids.values(), default=-1) + 1
        for i, k in enumerate(new):
            ids[k] = first + i
        db.executemany("INSERT INTO item (house, key, id) VALUES (?, ?, ?)", [(hk, k, ids[k]) for k in new])
        keys.sort(key=ids.get)
        top = 2 ** 31 - 1
        a = array.array("i", [ids[k] for k in keys])
        for f in HOURLY_FIELDS:
            a.extend(min(int(table[k][f]), top) for k in keys)
        a.extend(min(int(sold[k][0]), top) if k in sold else 0 for k in keys)
        if sys.byteorder == "big":
            a.byteswap()
        hour = int(t // 3600)
        db.execute("INSERT OR REPLACE INTO hour (house, hour, t, n, v) VALUES (?, ?, ?, ?, ?)",
                   (hk, hour, int(t), len(keys), zlib.compress(a.tobytes(), 6)))
        db.execute("DELETE FROM hour WHERE house = ? AND hour <= ?", (hk, hour - HOURLY_DAYS * 24))
        hours = db.execute("SELECT COUNT(*) FROM hour WHERE house = ?", (hk,)).fetchone()[0]
        db.commit()
    finally:
        db.close()
    return len(keys), hours


def connect(folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "history.db")
    packed = path + ".gz"
    if not os.path.exists(path) and os.path.exists(packed):      # a fresh machine gets the published copy
        with gzip.open(packed, "rb") as src, open(path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def house_key(db, region, h):
    db.execute("INSERT OR IGNORE INTO house (region, id) VALUES (?, ?)", (region, h["id"]))
    return db.execute("SELECT hk FROM house WHERE region = ? AND id = ?", (region, h["id"])).fetchone()[0]


def read_gz(path, default=None):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, EOFError):
        return default


def write_gz(path, data):
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=5) as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, path)


def build_items(db, hk, day, table, folder=None, hour=None):
    """the addon's item rows from today's prices plus the database's history, sale counts and price
    patterns -> (items, hours of compared scans behind the sale rates, the house's forecast check)"""
    hist, ins, samples = {}, {}, []
    learned = ah_ml.predict_house(folder, db, hk, day) if folder else {}      # {} until a training beat "unchanged"
    ahead = ah_ml.predict_hours(folder, hk, hour) if folder and hour is not None else {}      # the same, hour by hour
    row = db.execute("SELECT day, a, b, n, err, naive, ok FROM model WHERE house = ?", (hk,)).fetchone()
    model = (row[1], row[2]) if row and row[6] else None
    refit = not row or row[0] < day                      # once a day
    profs = dict(db.execute("SELECT key, v FROM hours WHERE house = ?", (hk,)))
    cur = db.execute("SELECT key, day, mkt_sum, n, min FROM daily WHERE house = ? AND day > ? AND n > 0 ORDER BY key, day",
                     (hk, day - KEEP_DAYS))
    for key, rows in itertools.groupby(cur, key=lambda r: r[0]):
        days, logs, h = [], [], []
        for _, dd, s, n, mn in rows:
            if dd > day - ah_api.HISTORY_DAYS:
                h += [dd, ah_api.sig3(int(round(s / n))), ah_api.sig3(mn)]
            if s > 0:
                days.append(dd)
                logs.append(math.log(s / n))
        if h:
            hist[key] = h
        p, g = table.get(key), ahead.get(key)
        old = len(days) >= INSIGHT_DAYS
        if p and p["mkt"] > 0 and (old or (g and max(g[1], g[2]) > 0)):
            # an item too young for patterns still gets its hour-ahead forecasts: a row without patterns
            pat = insight(days, logs, day, p["mkt"], profs.get(key), model) if old else \
                [len(days), 50, 9999, -1, 0, -1, 0, -1, -1, 0, -1, 0]
            f = learned.get(key)
            if f and f[1] > 0:
                pat[-1] = ah_api.sig3(f[1])               # the learned week ahead replaces the plain one
            pat += [ah_api.sig3(f[0]), ah_api.sig3(f[2]), ah_api.sig3(f[3])] if f else [0, 0, 0]
            if g and pat[-3] == 0:
                pat[-3] = ah_api.sig3(g[2])               # "tomorrow" from the hours while the days cannot say
            ins[key] = pat + [ah_api.sig3(g[1]) if g else 0]
        if old and refit and zlib.crc32(key.encode("utf-8")) % FIT_SAMPLE == 0:
            samples.extend(fit_samples(days, logs))
    if refit:
        row = (day,) + fit(samples)
        db.execute("INSERT OR REPLACE INTO model (house, day, a, b, n, err, naive, ok) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (hk,) + row)
    check = {"checks": row[3], "error": round(row[4], 4), "unchanged": round(row[5], 4), "on": bool(row[6]),
             "learned": bool(learned), "hours": bool(ahead)}
    since = day - ah_api.SOLD_DAYS
    cover = db.execute("SELECT COALESCE(SUM(seconds), 0) FROM cover WHERE house = ? AND day > ?", (hk, since)).fetchone()[0]
    rates = cover >= ah_api.MIN_COVER
    sold = {}
    if rates:
        sold = dict(db.execute("SELECT key, SUM(sold) FROM daily WHERE house = ? AND day > ? GROUP BY key HAVING SUM(sold) > 0",
                               (hk, since)))
    items = {}
    for key, p in table.items():
        items[key] = dict(p, h=hist.get(key, []), sold=(sold.get(key, 0) / cover * 86400) if rates else None,
                          ins=ins.get(key))
    for key, units in sold.items():                     # sold out completely: the sale rate is still worth keeping
        if key not in items:
            items[key] = {"min": 0, "mkt": 0, "qty": 0, "num": 0, "top": 0, "other": 0, "h": [],
                          "sold": units / cover * 86400}
    # the addon reads sale rates only when soldHours >= 1, so this must agree with `rates`
    return items, (max(1.0, round(cover / 3600.0, 1)) if rates else 0.0), check


# ---------------------------------------------------------------------------
# price patterns: what up to 30 days of history say about one item
# ---------------------------------------------------------------------------
INSIGHT_DAYS = 7          # days with a price before an item gets price patterns
PROFILE_MIN = 5           # auctions an item needs before its prices by hour of the day are followed
PROFILE_DECAY = 0.9       # per day: the hour-of-day figures fade, a month-old hour weighs 4%
HORIZON = 7               # the forecast looks this many days ahead
DRIFT = sum(0.8 ** j for j in range(1, HORIZON + 1))     # a trend is expected to fade out
FIT_SAMPLE = 5            # every n-th item checks the forecast against what really happened
FIT_MIN = 300             # such checks needed before a house gets forecasts at all
KENDALL = {5: 8, 6: 11, 7: 13, 8: 16}                    # agreeing minus disagreeing pairs needed (p < 0.05)


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def weekday(day):
    return (day + 3) % 7                                  # 0 = Monday; day 0 (1 January 1970) was a Thursday


def pct(x):
    return int(round((math.exp(x) - 1) * 100))


def trend(days, logs, upto):
    """the direction of the week before `upto` -> change of the log price per day (the median slope
    between all pairs of days), 0.0 when the days do not agree on a direction, None when fewer than
    five of the last eight days have a price"""
    pts = [(d, x) for d, x in zip(days, logs) if upto - 8 < d <= upto]
    if len(pts) < 5:
        return None
    slopes, agree = [], 0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            s = (pts[j][1] - pts[i][1]) / (pts[j][0] - pts[i][0])
            slopes.append(s)
            agree += (s > 0) - (s < 0)
    if abs(agree) < KENDALL[len(pts)]:
        return 0.0
    return median(slopes)


def weekday_effect(days, logs):
    """-> [cheapest weekday, percent, dearest weekday, percent]; -1 where no weekday stands out.
    Each day is compared with the median of the week around it. A weekday counts when it was on the
    same side at least four times and its distance is large against the item's day-to-day noise."""
    idx = dict(zip(days, logs))
    by, resid = {}, []
    for d, x in idx.items():
        around = [idx[y] for y in range(d - 3, d + 4) if y in idx]
        if len(around) >= 5:
            r = x - median(around)
            by.setdefault(weekday(d), []).append(r)
            resid.append(r)
    out = [-1, 0, -1, 0]
    if len(resid) < 14:
        return out
    noise = 1.4826 * median([abs(r) for r in resid])
    lo = hi = None
    for wd, xs in by.items():
        if len(xs) < 4:
            continue
        m = median(xs)
        if abs(m) * math.sqrt(len(xs)) < 3.6 * noise:
            continue
        if max(xs) < 0 and (lo is None or m < lo[1]):
            lo = (wd, m)
        if min(xs) > 0 and (hi is None or m > hi[1]):
            hi = (wd, m)
    if lo and pct(lo[1]) <= -3:
        out[0:2] = [lo[0], pct(lo[1])]
    if hi and pct(hi[1]) >= 3:
        out[2:4] = [hi[0], pct(hi[1])]
    return out


def hour_effect(v):
    """-> [cheapest hour, dearest hour, spread in percent, hour most units sell]; hours in UTC, -1 = none.
    v: the item's row of the hours table"""
    out = [-1, -1, 0, -1]
    if not v:
        return out
    a = array.array("f")
    a.frombytes(v)
    mean = [a[h] / a[24 + h] if a[24 + h] >= 4 else None for h in range(24)]       # 4 = five days of that hour
    known = [h for h in range(24) if mean[h] is not None]
    if len(known) >= 20:
        base = sum(mean[h] for h in known) / len(known)
        m = [mean[h] - base if mean[h] is not None else 0.0 for h in range(24)]
        sm = [(m[h - 1] + m[h] + m[(h + 1) % 24]) / 3 for h in range(24)]           # neighbouring hours count too
        var = sum(max(a[72 + h] / a[24 + h] - mean[h] ** 2, 0.0) for h in known) / len(known)
        weight = sum(a[24 + h] for h in known) / len(known)
        noise = math.sqrt(var / (3 * weight))                                      # of one smoothed hour
        lo = min(range(24), key=sm.__getitem__)
        hi = max(range(24), key=sm.__getitem__)
        # the extremes of 24 noisy hours lie about three noise widths apart by chance alone
        if sm[hi] - sm[lo] >= 4.5 * noise and pct(sm[hi] - sm[lo]) >= 4:
            out[0:3] = [lo, hi, pct(sm[hi] - sm[lo])]
    q = a[48:72]
    total = sum(q)
    if total >= 20 and sum(1 for x in q if x > 0) >= 8:
        sm = [(q[h - 1] + q[h] + q[(h + 1) % 24]) / 3 for h in range(24)]
        peak = max(range(24), key=sm.__getitem__)
        if sm[peak] >= 1.5 * total / 24:
            out[3] = peak
    return out


def features(days, logs, upto):
    """what the forecast looks at on day `upto` -> (level of the last three days, the week's trend
    carried forward, distance of the month's median from that level), or None with too little history"""
    seen = [x for d, x in zip(days, logs) if upto - KEEP_DAYS < d <= upto]
    recent = [x for d, x in zip(days, logs) if upto - 3 < d <= upto]
    if len(seen) < INSIGHT_DAYS or not recent:
        return None
    level = median(recent)
    return level, (trend(days, logs, upto) or 0.0) * DRIFT, median(seen) - level


def fit_samples(days, logs):
    """every day of the history that has a price HORIZON days later: (trend, reversion, what happened)"""
    idx = dict(zip(days, logs))
    out = []
    for d in days:
        later = idx.get(d + HORIZON)
        f = features(days, logs, d) if later is not None else None
        if f:
            out.append((f[1], f[2], later - f[0]))
    return out


def fit(samples):
    """least squares for  change = a * trend + b * reversion  -> (a, b, n, error, error of "the price
    stays the same", ok). ok only when the forecast was the better of the two on these samples."""
    n = len(samples)
    if n < FIT_MIN:
        return 0.0, 0.0, n, 0.0, 0.0, 0
    s11 = sum(x1 * x1 for x1, x2, y in samples)
    s22 = sum(x2 * x2 for x1, x2, y in samples)
    s12 = sum(x1 * x2 for x1, x2, y in samples)
    s1y = sum(x1 * y for x1, x2, y in samples)
    s2y = sum(x2 * y for x1, x2, y in samples)
    det = s11 * s22 - s12 * s12
    a = b = 0.0
    if det > 1e-12:
        a, b = (s1y * s22 - s2y * s12) / det, (s2y * s11 - s1y * s12) / det
    elif s22 > 1e-12:
        b = s2y / s22
    a, b = min(max(a, 0.0), 1.5), min(max(b, 0.0), 1.0)
    err = sum(abs(y - a * x1 - b * x2) for x1, x2, y in samples) / n
    naive = sum(abs(y) for x1, x2, y in samples) / n
    return a, b, n, err, naive, int((a > 0 or b > 0) and err <= 0.97 * naive)


def insight(days, logs, day, price, prof, model):
    """the INS_FIELDS numbers of one item. days/logs: its daily prices (log), price: today's market price"""
    now = math.log(price)
    pos = int(round(100.0 * (sum(1 for x in logs if x < now) + 0.5 * sum(1 for x in logs if x == now)) / len(logs)))
    tr = trend(days, logs, day)
    in7 = 0
    f = features(days, logs, day) if model else None
    if f:
        guess = f[0] + model[0] * f[1] + model[1] * f[2]
        guess = min(max(guess, min(logs) - 0.2), max(logs) + 0.2)
        in7 = ah_api.sig3(int(round(math.exp(guess))))
    return [len(days), pos, 9999 if tr is None else int(round((math.exp(tr) - 1) * 1000))] + \
        weekday_effect(days, logs) + hour_effect(prof) + [in7]


def update_hours(db, hk, day, hour, table, sold):
    """add this scan to the items' prices and sales by hour of the day"""
    ref = dict(db.execute("SELECT key, SUM(mkt_sum) * 1.0 / SUM(n) FROM daily WHERE house = ? AND day > ? AND n > 0 GROUP BY key",
                          (hk, day - 7)))
    old = {key: (d, v) for key, d, v in db.execute("SELECT key, day, v FROM hours WHERE house = ?", (hk,))}
    rows = []
    for key, p in table.items():
        have = old.get(key)
        if not have and p["num"] < PROFILE_MIN:
            continue
        a = array.array("f")
        if have:
            a.frombytes(have[1])
            if have[0] < day:                             # a new day: everything before fades
                k = PROFILE_DECAY ** (day - have[0])
                a = array.array("f", [x * k for x in a])
        else:
            a.extend([0.0] * 96)
        base = ref.get(key)
        if base and p["mkt"] > 0:
            r = math.log(p["mkt"] / base)
            a[hour] += r
            a[24 + hour] += 1
            a[72 + hour] += r * r
        if key in sold:
            a[48 + hour] += sold[key][0]
        rows.append((hk, key, day, a.tobytes()))
    db.executemany("INSERT OR REPLACE INTO hours (house, key, day, v) VALUES (?, ?, ?, ?)", rows)
    db.execute("DELETE FROM hours WHERE house = ? AND day <= ?", (hk, day - KEEP_DAYS))


def scan_house(api, db, folder, h, now=None, force=False):
    """-> index entry of the house, None when it is empty, or "same" when Blizzard has nothing newer"""
    region, hid = api.region, h["id"]
    name = "%s-%s" % (region, hid)
    state = os.path.join(folder, "state-%s.json.gz" % name)
    prev = read_gz(state)
    since = prev.get("modified") if prev and not force else None
    snap = ah_api.fetch_house(api, RULESET, hid, True, since=since)
    if snap is None or (prev and not force and prev.get("modified") and prev["modified"] == snap.get("modified")):
        return "same"
    aucs = snap["auctions"]
    if not aucs:
        return None
    if now:
        snap["t"] = now
    t, day = snap["t"], ah_api.day_of(snap["t"])
    hk = house_key(db, region, h)
    table = ah_api.price_table(aucs)

    n_sold, sold = 0, {}
    if prev and prev.get("auctions"):
        dt = t - prev["t"]
        if 0 < dt <= ah_api.MAX_GAP:
            sold = ah_api.sold_between(prev["auctions"], aucs, dt, prev.get("prices") or {})
            db.executemany(
                "INSERT INTO daily (house, day, key, sold, sold_n) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (house, day, key) DO UPDATE SET sold = sold + excluded.sold, sold_n = sold_n + excluded.sold_n",
                [(hk, day, key, units, cnt) for key, (units, cnt) in sold.items()])
            n_sold = sum(units for key, (units, cnt) in sold.items() if ":" not in key)
            db.execute("INSERT INTO cover (house, day, seconds) VALUES (?, ?, ?) "
                       "ON CONFLICT (house, day) DO UPDATE SET seconds = seconds + excluded.seconds", (hk, day, dt))
    db.executemany(
        "INSERT INTO daily (house, day, key, mkt_sum, n, min, qty) VALUES (?, ?, ?, ?, 1, ?, ?) "
        "ON CONFLICT (house, day, key) DO UPDATE SET mkt_sum = mkt_sum + excluded.mkt_sum, n = n + 1, "
        "min = CASE WHEN min IS NULL OR excluded.min < min THEN excluded.min ELSE min END, qty = excluded.qty",
        [(hk, day, key, p["mkt"], p["min"], p["qty"]) for key, p in table.items()])
    update_hours(db, hk, day, int(t % 86400 // 3600), table, sold)
    n_kept, n_hours = archive_hour(folder, hk, t, table, sold)
    for tbl in ("daily", "cover"):
        db.execute("DELETE FROM %s WHERE house = ? AND day <= ?" % tbl, (hk, day - KEEP_DAYS))
    db.execute("DELETE FROM scan WHERE house = ? AND t <= ?", (hk, t - KEEP_DAYS * 86400))
    db.execute("INSERT OR REPLACE INTO scan (house, t, auctions, items, sold_units) VALUES (?, ?, ?, ?, ?)",
               (hk, t, len(aucs), len(table), n_sold))
    faction = ah_api.faction_of(snap.get("name") or h.get("name"))
    db.execute("UPDATE house SET ruleset = ?, faction = ?, name = ?, t = ?, modified = ?, auctions = ?, items = ? WHERE hk = ?",
               (RULESET, faction, snap.get("name") or h.get("name"), t, snap.get("modified"), len(aucs), len(table), hk))

    items, sold_hours, check = build_items(db, hk, day, table, folder, int(t // 3600))
    n_days = db.execute("SELECT COUNT(DISTINCT t / 86400) FROM scan WHERE house = ?", (hk,)).fetchone()[0]
    n_ins = sum(1 for it in items.values() if it.get("ins"))
    meta = collections.OrderedDict(v=1, t=t, region=region, house=hid, faction=faction,
                                   auctions=len(aucs), soldHours=sold_hours, insDays=n_days)
    lua = os.path.join(folder, name + ".lua")
    ah_api.write_lua(lua, meta, items)
    with open(lua, "rb") as src, gzip.open(lua + ".gz.tmp", "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    os.replace(lua + ".gz.tmp", lua + ".gz")
    os.remove(lua)
    write_gz(state, {"t": t, "modified": snap.get("modified"), "auctions": aucs,
                     "prices": {k: {"mkt": v["mkt"]} for k, v in table.items()}})
    db.commit()
    log("house %s %s: %d auctions, %d items, %d units sold since the last scan, sale rates from %.1f h; "
        "%d day(s) and %d hour(s) of history, price patterns for %d items, forecast %s" % (
            name, faction, len(aucs), len(table), n_sold, sold_hours, n_days, n_hours, n_ins,
            ("learned" if check["learned"] else "on" if check["on"] else "off") + (
                " (error %.1f%% against %.1f%% for an unchanged price, %d checks)" % (
                    check["error"] * 100, check["unchanged"] * 100, check["checks"]) if check["checks"] >= FIT_MIN else "")
            + ", hour-ahead forecasts " + ("on" if check["hours"] else "off")))
    return {"region": region, "house": hid, "ruleset": RULESET, "faction": faction, "t": t,
            "modified": snap.get("modified"), "auctions": len(aucs), "items": len(table),
            "soldHours": sold_hours, "days": n_days, "hours": n_hours, "patterns": n_ins, "forecast": check,
            "learned": check["learned"], "hourAhead": check["hours"], "file": name + ".lua.gz"}


def read_index(folder):
    try:
        with open(os.path.join(folder, "index.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"houses": []}


def cmd_run(folder, opener=None, cfg=None, now=None, force=False):
    cfg = cfg or dict(ah_api.load_config(), region=REGION)
    api = ah_api.Api(cfg, opener)
    db = connect(folder)
    index = {(e["region"], e["house"]): e for e in read_index(folder).get("houses", [])}
    new = failed = 0
    for h in ah_api.houses(api, RULESET):
        if ah_api.faction_of(h["name"]) not in FACTIONS:
            continue
        try:
            entry = scan_house(api, db, folder, h, now=now, force=force)
        except ApiError as e:
            db.rollback()
            failed += 1
            log("house %s-%s failed: %s" % (api.region, h["id"], e))
            continue
        if isinstance(entry, dict):
            index[(entry["region"], entry["house"])] = entry
            new += 1
    db.execute("PRAGMA optimize")
    db.commit()
    db.close()
    houses = [index[k] for k in sorted(index)]
    tmp = os.path.join(folder, "index.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "updated": max([e["t"] for e in houses] or [0]), "source": SOURCE, "houses": houses}, f, indent=1)
    os.replace(tmp, os.path.join(folder, "index.json"))
    if new:
        path = os.path.join(folder, "history.db")
        with open(path, "rb") as src, gzip.open(path + ".gz.tmp", "wb", compresslevel=5) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        os.replace(path + ".gz.tmp", path + ".gz")
    log("server scan done: %d house(s) with new data, %d failed, %d in the index" % (new, failed, len(houses)))
    return 1 if failed and not new else 0


def cmd_probe(folder, opener=None, cfg=None):
    """-> True when at least one house has data newer than index.json knows"""
    cfg = cfg or dict(ah_api.load_config(), region=REGION)
    known = read_index(folder).get("houses", [])
    changed = not known
    if known:
        api = ah_api.Api(cfg, opener)
        for e in known:
            if e.get("region") != api.region:
                continue
            status, _, _ = api.get("/data/wow/ruleset/%s/auctions/%s" % (e.get("ruleset") or RULESET, e["house"]),
                                   since=e.get("modified"))
            if status != 304:
                changed = True
                break
    log("new data: %s" % ("yes" if changed else "no"))
    return changed


def cmd_info(folder):
    db = connect(folder)
    for hk, region, hid, faction, t, auctions, items in db.execute(
            "SELECT hk, region, id, faction, t, auctions, items FROM house ORDER BY region, id"):
        days, rows = db.execute("SELECT COUNT(DISTINCT day), COUNT(*) FROM daily WHERE house = ?", (hk,)).fetchone()
        cover = db.execute("SELECT COALESCE(SUM(seconds), 0) FROM cover WHERE house = ?", (hk,)).fetchone()[0]
        scans = db.execute("SELECT COUNT(*) FROM scan WHERE house = ?", (hk,)).fetchone()[0]
        print("%s-%s %-8s last scan %s, %s auctions, %s items; %d day(s), %d rows, %d scans, %.1f h compared" % (
            region, hid, faction, time.strftime("%Y-%m-%d %H:%M", time.localtime(t or 0)), auctions, items,
            days, rows, scans, cover / 3600.0))
    db.close()
    return 0


# ---------------------------------------------------------------------------
# serve: the scan loop plus a small read-only file server
# ---------------------------------------------------------------------------
# only these leave the folder: the snapshots (state-*) and the log stay private
PUBLIC = re.compile(r"^(index\.json|ml\.json|[a-z]{2}-\d+\.lua\.gz|history\.db\.gz)$")
TYPES = {".json": "application/json", ".gz": "application/gzip"}


def host_line():
    """one log line about the machine: how much room this service has"""
    parts = ["%s cpus" % os.cpu_count()]
    try:
        parts.append("load %s" % " ".join("%.2f" % x for x in os.getloadavg()))
    except (OSError, AttributeError):
        pass
    try:
        mem = {}
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                k, _, v = line.partition(":")
                mem[k] = int(v.split()[0])
        parts.append("memory %d of %d MB free" % (mem["MemAvailable"] // 1024, mem["MemTotal"] // 1024))
    except (OSError, KeyError, ValueError, IndexError):
        pass
    return ", ".join(parts)


def make_handler(folder):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "UltimateAH"
        timeout = 30                                      # a stalled client must not hold a thread forever

        def answer(self, send_body=True):
            name = self.path.split("?", 1)[0].lstrip("/") or "index.json"
            if name == "healthz":
                idx = read_index(folder)
                body = json.dumps({"ok": True, "updated": idx.get("updated", 0), "houses": len(idx.get("houses", []))}).encode()
                return self.reply(200, body, "application/json", send_body)
            try:
                f = open(os.path.join(folder, name), "rb") if PUBLIC.match(name) else None
            except OSError:
                f = None
            if not f:
                return self.reply(404, b"not found\n", "text/plain", send_body)
            with f:                                       # an open file stays whole while a scan replaces it
                st = os.fstat(f.fileno())
                mtime = int(st.st_mtime)
                modified = email.utils.formatdate(mtime, usegmt=True)
                try:
                    since = email.utils.parsedate_to_datetime(self.headers.get("If-Modified-Since") or "").timestamp()
                except (TypeError, ValueError, IndexError):
                    since = None
                if since is not None and mtime <= since:
                    return self.head(304, None, None, modified)
                self.head(200, st.st_size, TYPES.get(os.path.splitext(name)[1], "application/octet-stream"), modified)
                if send_body:
                    shutil.copyfileobj(f, self.wfile)     # streamed: the database file grows to tens of MB

        def head(self, status, length, ctype, modified=None):
            self.send_response(status)
            if ctype:
                self.send_header("Content-Type", ctype)
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "public, max-age=300")
            self.send_header("X-Data-Source", SOURCE)
            if modified:
                self.send_header("Last-Modified", modified)
            self.end_headers()

        def reply(self, status, body, ctype, send_body):
            self.head(status, len(body), ctype)
            if send_body:
                self.wfile.write(body)

        def do_GET(self):
            self.answer(True)

        def do_HEAD(self):
            self.answer(False)

        def log_message(self, fmt, *args):
            pass                                          # the scan log is the log

    return Handler


def work(script, command, folder):
    """one piece of the hour's work in a process of its own: a scan holds half a gigabyte for a
    few seconds, and this way it goes back to the machine instead of staying with the service"""
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        return subprocess.run([sys.executable, os.path.join(here, script), command, "--dir", folder], timeout=1800).returncode
    except (OSError, subprocess.SubprocessError) as e:
        log("error:", repr(e))
        return 1


def cmd_serve(folder, port, interval=300, rounds=None):
    os.makedirs(folder, exist_ok=True)
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), make_handler(folder))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log("serving %s on port %d; this machine: %s" % (folder, httpd.server_address[1], host_line()))
    # a restarted service trains at its first quiet moment: the scan before the restart was never learned from
    n, scanned = 0, True
    log("learned forecasts: %s" % ("numpy and scikit-learn found, training after every scan"
                                   if importlib.util.find_spec("numpy") and importlib.util.find_spec("sklearn")
                                   else "numpy / scikit-learn are not installed, so none"))
    while rounds is None or n < rounds:
        n += 1
        cfg = dict(ah_api.load_config(), region=REGION)
        if not (cfg["client_id"] and cfg["client_secret"]):
            log("no API keys: set BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET")
        else:
            try:
                if cmd_probe(folder, cfg=cfg):
                    work("ah_server.py", "run", folder)
                    scanned = True
                    log("this machine: %s" % host_line())
                elif scanned:                             # every house is in: learn from the new hour
                    scanned = False
                    work("ah_ml.py", "train", folder)
                    log("this machine: %s" % host_line())
            except ApiError as e:
                log("failed:", e)
            except Exception as e:                         # a bad hour must not end the service
                log("error:", repr(e))
        if rounds is None or n < rounds:
            time.sleep(interval)
    return httpd


def main(argv=None):
    ap = argparse.ArgumentParser(description="UltimateAH server scan: all Forever auction houses into a database")
    ap.add_argument("command", choices=["probe", "run", "info", "serve"])
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")), help="serve: the HTTP port")
    ap.add_argument("--interval", type=int, default=300, help="serve: seconds between checks for new data")
    ap.add_argument("--dir", default=os.path.join(ah_api.HERE, "server_data"), help="folder for the database and the files")
    ap.add_argument("--force", action="store_true", help="run: scan even if Blizzard's data is unchanged")
    args = ap.parse_args(argv)
    ah_api.STATE = args.dir                       # the log goes next to the data
    try:
        if args.command == "probe":
            cmd_probe(args.dir)
            return 0
        if args.command == "info":
            return cmd_info(args.dir)
        if args.command == "serve":
            cmd_serve(args.dir, args.port, args.interval)
            return 0
        return cmd_run(args.dir, force=args.force)
    except ApiError as e:
        log("failed:", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
