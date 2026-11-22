"""Ultimate AH: price forecasts learned from the server scan's history.

The server scan (ah_server.py) keeps 30 days of daily prices for every item of every auction house.
This module learns from all of them at once what usually happens next:

    python ah_ml.py train --dir DIR     learn, check on the latest days, save the models (ml.pkl, ml.json)
    python ah_ml.py info  --dir DIR     how the last training went

One row of training data is one item on one day: how its price moved over the last days, where it
sits in its range, how much is listed and sold, the weekday. The answer to learn is how the price
changed one day and seven days later. The models are gradient-boosted trees (scikit-learn's
HistGradientBoostingRegressor), one for the price in a day, one for the price in a week, and two
more for the range the price in a week will most likely be in.

The scan also keeps 14 days of prices hour by hour (hourly.db). From those the same kind of model
learns the price in 1, 6 and 24 hours; one row is one item at one scan.

Every training holds back the latest days (or hours), forecasts them with a model that has not seen
them, and compares the result with the plainest forecast there is: "the price stays the same". A
forecast is only handed out while it beats that. With too little history nothing is trained and nothing is
handed out; the server scan works the same without this module or without numpy / scikit-learn.
"""
import argparse
import json
import math
import os
import pickle
import sqlite3
import sys
import time
import warnings
import zlib

KEEP_DAYS = 30            # the server's history (Blizzard's limit for stored API data)
MIN_DAYS = 3              # days with a price before an item's day is used
MAX_ROWS = 300000         # rows a training uses at most (a random pick beyond that)
PART_ROWS = 4000          # rows kept of one house's one day: 150,000 items x 30 days would not fit in memory
MIN_ROWS = 2000           # rows needed to train at all
MIN_GAIN = 0.97           # a forecast is handed out while its error is under 97% of "unchanged"
COVER = (0.45, 0.75)      # share of real prices the 20%..80% range must have caught on the held-back days
CLAMP = 0.7               # no forecast moves a price by more than a factor of two
HORIZONS = (1, 7)
FEATURES = ("r1", "r2", "r3", "r7", "dev7", "dev30", "vol7", "pos", "slope7", "spread", "level",
            "qty", "qty_vs_week", "sold", "sold_week", "turnover", "days", "weekday")

# the hour-ahead forecasts, from the scan's hour-by-hour archive
H_KEEP = 240              # hours of the archive a training looks at
H_BACK = 72               # hours a forecast looks back
H_MIN = 3                 # prices in the last 24 hours before an item's hour is used
H_TRAIN = 6               # different hours a model must have learned from before it is judged
H_HORIZONS = (1, 6, 24)
H_FEATURES = ("r1", "r2", "r3", "r6", "r12", "r24", "dev6", "dev24", "dev72", "vol12", "pos24", "spread",
              "spread_vs_6", "level", "qty", "qty_1", "qty_6", "auctions", "sold", "sold_6", "seen24", "hour", "weekday")
CALL = 0.05               # the report counts how often a forecast of a move this big had the direction right

_cache = {}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def libs():
    """-> (numpy, HistGradientBoostingRegressor) or None when they are not installed"""
    try:
        import numpy as np
        from sklearn.ensemble import HistGradientBoostingRegressor
    except Exception:
        return None
    return np, HistGradientBoostingRegressor


def weekday(day):
    return (day + 3) % 7                                  # 0 = Monday


def load_house(np, db, hk, day):
    """-> (keys, log market price, log lowest buyout, log quantity, units sold): arrays of
    items x KEEP_DAYS, column KEEP_DAYS-1 is `day`, NaN where the item had no price that day"""
    first = day - KEEP_DAYS + 1
    where = "FROM daily WHERE house = ? AND day >= ? AND day <= ? AND n > 0 AND mkt_sum > 0"
    index = {}
    for (key,) in db.execute("SELECT DISTINCT key " + where, (hk, first, day)):
        index[key] = len(index)
    shape = (len(index), KEEP_DAYS)
    m, mn, q, s = (np.full(shape, np.nan, dtype=np.float32) for _ in range(4))
    # row by row from the database: a big house has 800,000 of them, too many to hold as a list
    for key, d, mkt, low, qty, sold in db.execute("SELECT key, day, mkt_sum * 1.0 / n, min, qty, sold " + where, (hk, first, day)):
        i, j = index[key], d - first
        m[i, j] = math.log(mkt)
        mn[i, j] = math.log(low) if low and low > 0 else math.log(mkt)
        q[i, j] = math.log1p(qty or 0)
        s[i, j] = sold or 0
    return list(index), m, mn, q, s


def features(np, m, mn, q, s, j, day_of_j):
    """the FEATURES of every item on the day in column j, from that day and the days before it"""
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        x = m[:, j]
        nan = np.full(x.shape, np.nan, dtype=np.float32)

        def back(k):
            return x - m[:, j - k] if j - k >= 0 else nan

        week = m[:, max(0, j - 6):j + 1]
        seen = m[:, :j + 1]
        lo, hi = np.nanmin(seen, axis=1), np.nanmax(seen, axis=1)
        steps = np.diff(m[:, max(0, j - 7):j + 1], axis=1)
        vol = np.nanstd(steps, axis=1) if steps.shape[1] else nan
        t = np.arange(week.shape[1], dtype=np.float32)
        ok = np.isfinite(week)
        n = ok.sum(axis=1).astype(np.float32)
        st, sx = (ok * t).sum(axis=1), np.where(ok, week, 0).sum(axis=1)
        stx, stt = (np.where(ok, week, 0) * t).sum(axis=1), (ok * t * t).sum(axis=1)
        den = n * stt - st * st
        slope = np.where((n >= 3) & (den > 0), (n * stx - st * sx) / np.where(den > 0, den, 1), np.nan)
        qweek = np.nanmean(q[:, max(0, j - 6):j + 1], axis=1)
        sweek = np.log1p(np.nanmean(s[:, max(0, j - 6):j + 1], axis=1))
        cols = [back(1), back(2), back(3), back(7), x - np.nanmedian(week, axis=1), x - np.nanmedian(seen, axis=1), vol,
                np.where(hi > lo, (x - lo) / np.where(hi > lo, hi - lo, 1), np.nan), slope, x - mn[:, j], x,
                q[:, j], q[:, j] - qweek, np.log1p(s[:, j]), sweek, sweek - q[:, j],
                np.isfinite(seen).sum(axis=1).astype(np.float32), np.full(x.shape, weekday(day_of_j), dtype=np.float32)]
        return np.stack(cols, axis=1).astype(np.float32)


def usable(np, m, j):
    return np.isfinite(m[:, j]) & (np.isfinite(m[:, :j + 1]).sum(axis=1) >= MIN_DAYS)


def dataset(np, db, day):
    """every item-day of every house -> {horizon: (X, y, column of the day)} for the days that have an answer"""
    parts = {h: ([], [], []) for h in HORIZONS}
    last = KEEP_DAYS - 1
    rng = np.random.default_rng(1)
    for (hk,) in db.execute("SELECT hk FROM house ORDER BY hk").fetchall():
        keys, m, mn, q, s = load_house(np, db, hk, day)
        if not keys:
            continue
        for j in range(MIN_DAYS - 1, last):
            good = usable(np, m, j)
            if not good.any():
                continue
            X = None
            for h in HORIZONS:
                if j + h > last:
                    continue
                pick = np.flatnonzero(good & np.isfinite(m[:, j + h]))
                if not len(pick):
                    continue
                if len(pick) > PART_ROWS:
                    pick = rng.choice(pick, PART_ROWS, replace=False)
                if X is None:
                    X = features(np, m, mn, q, s, j, day - last + j)
                parts[h][0].append(X[pick])
                parts[h][1].append((m[:, j + h] - m[:, j])[pick])
                parts[h][2].append(np.full(len(pick), j, dtype=np.int16))
    out = {}
    for h, (xs, ys, js) in parts.items():
        if xs:
            out[h] = (np.concatenate(xs), np.concatenate(ys), np.concatenate(js))
    return out


def split(np, cols, horizon, need=2):
    """hold back the latest days (or hours). -> (rows to learn from, rows to check on) as masks, or None.
    A row is only learned from when its answer was known before the first held-back day."""
    days = np.unique(cols)
    held = max(1, int(math.ceil(len(days) * 0.2)))
    first_held = days[-held]
    train = cols + horizon < first_held
    check = cols >= first_held
    if len(np.unique(cols[train])) < need or not check.any():
        return None
    return train, check


def sample(np, mask, rng, limit):
    idx = np.flatnonzero(mask)
    if len(idx) > limit:
        idx = rng.choice(idx, limit, replace=False)
    return idx


def model(HGB, **kw):
    return HGB(max_iter=120, learning_rate=0.08, max_leaf_nodes=31, min_samples_leaf=100,
               l2_regularization=1.0, random_state=0, **kw)


def fit(np, HGB, X, y, **kw):
    """a model on X -> y. A column without a single value yet (the change over 24 hours on the first
    day) is set to 0: the library cannot take such a column, and nothing can be learned from it"""
    empty = ~np.isfinite(X).any(axis=0)
    if empty.any():
        X = X.copy()
        X[:, empty] = 0.0
    return model(HGB, **kw).fit(X, y)


def judge(np, HGB, data, h, r, rng, unit, need=2):
    """train on the early part, forecast the held-back end, fill the report `r`.
    -> (X, y, rows learned from, rows checked on) when the forecast beat "unchanged", else None"""
    if h not in data:
        r["note"] = "no %s has an answer yet" % unit
        return None
    X, y, cols = data[h]
    r["rows"] = int(len(y))
    parts = split(np, cols, h, need)
    if not parts or parts[0].sum() < MIN_ROWS:
        r["note"] = "too little history"
        return None
    tr, ck = sample(np, parts[0], rng, MAX_ROWS), sample(np, parts[1], rng, MAX_ROWS)
    r["learned_from"], r["checked_on"] = int(len(tr)), int(len(ck))
    guess = np.clip(fit(np, HGB, X[tr], y[tr], loss="absolute_error").predict(X[ck]), -CLAMP, CLAMP)
    r["error"] = round(float(np.mean(np.abs(y[ck] - guess))), 4)
    r["unchanged"] = round(float(np.mean(np.abs(y[ck]))), 4)
    r["on"] = bool(r["error"] <= MIN_GAIN * r["unchanged"])
    calls = np.abs(guess) >= CALL                         # where it expected a real move: was the direction right?
    r["calls"] = int(calls.sum())
    if r["calls"]:
        r["calls_right"] = round(float(np.mean(np.sign(guess[calls]) == np.sign(y[ck][calls]))), 3)
    return (X, y, tr, ck) if r["on"] else None


def train_daily(np, HGB, folder, report, models):
    db = sqlite3.connect(os.path.join(folder, "history.db"))
    day = db.execute("SELECT MAX(day) FROM daily").fetchone()[0]
    if day is None:
        db.close()
        report["note"] = "no prices yet"
        return
    report["days"] = db.execute("SELECT COUNT(DISTINCT day) FROM daily WHERE day > ?", (day - KEEP_DAYS,)).fetchone()[0]
    data = dataset(np, db, day)
    db.close()
    rng = np.random.default_rng(0)
    models["features"] = FEATURES
    for h in HORIZONS:
        r = report["horizons"][str(h)] = {"on": False, "rows": 0}
        got = judge(np, HGB, data, h, r, rng, "day")
        if not got:
            continue
        X, y, tr, ck = got
        everything = sample(np, np.ones(len(y), dtype=bool), rng, MAX_ROWS)
        models["h%d" % h] = fit(np, HGB, X[everything], y[everything], loss="absolute_error")
        if h == 7:                                        # the range the price will most likely be in
            low = fit(np, HGB, X[tr], y[tr], loss="quantile", quantile=0.2).predict(X[ck])
            high = fit(np, HGB, X[tr], y[tr], loss="quantile", quantile=0.8).predict(X[ck])
            r["range_caught"] = round(float(np.mean((y[ck] >= low) & (y[ck] <= high))), 3)
            r["range_on"] = bool(COVER[0] <= r["range_caught"] <= COVER[1])
            if r["range_on"]:
                models["lo7"] = fit(np, HGB, X[everything], y[everything], loss="quantile", quantile=0.2)
                models["hi7"] = fit(np, HGB, X[everything], y[everything], loss="quantile", quantile=0.8)


# ---------------------------------------------------------------------------
# hour-ahead forecasts from the hour-by-hour archive
# ---------------------------------------------------------------------------
def unpack(np, n, v):
    """one archived scan -> 6 rows of n numbers: ids, market price, lowest buyout, units, auctions, sold"""
    return np.frombuffer(zlib.decompress(v), dtype="<i4").reshape(6, n)


def load_hours(np, db, hk, last, width):
    """the house's last `width` hours up to hour `last` -> (item ids, log market price, log of market
    price over lowest buyout, log units listed, log auctions, log units sold): arrays of
    items x width, the last column is `last`, NaN where the item was not followed that hour"""
    first = last - width + 1
    rows = db.execute("SELECT hour, n, v FROM hour WHERE house = ? AND hour >= ? AND hour <= ? AND n > 0 ORDER BY hour",
                      (hk, first, last)).fetchall()
    if not rows:
        return (np.zeros(0, dtype=np.int64),) + tuple(np.zeros((0, width), dtype=np.float32) for _ in range(5))
    ids = np.unique(np.concatenate([unpack(np, n, v)[0] for _, n, v in rows]))
    m, sp, q, nm, s = (np.full((len(ids), width), np.nan, dtype=np.float32) for _ in range(5))
    for hour, n, v in rows:
        a = unpack(np, n, v)
        i, j = np.searchsorted(ids, a[0]), hour - first
        mkt = np.maximum(a[1], 1).astype(np.float64)
        m[i, j] = np.log(mkt)
        sp[i, j] = np.log(mkt / np.where(a[2] > 0, a[2], mkt))
        q[i, j] = np.log1p(a[3])
        nm[i, j] = np.log1p(a[4])
        s[i, j] = np.log1p(a[5])
    return ids, m, sp, q, nm, s


def husable(np, m, j):
    return np.isfinite(m[:, j]) & (np.isfinite(m[:, max(0, j - 23):j + 1]).sum(axis=1) >= H_MIN)


def hfeatures(np, m, sp, q, nm, s, rows, j, hour):
    """the H_FEATURES of the items `rows` at the scan in column j (hour number `hour`), from that
    scan and the H_BACK hours before it"""
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        lo = max(0, j - H_BACK + 1)
        M, S, Q, D = m[rows, lo:j + 1], sp[rows, lo:j + 1], q[rows, lo:j + 1], s[rows, lo:j + 1]
        x = M[:, -1]
        nan = np.full(x.shape, np.nan, dtype=np.float32)

        def back(a, k):
            return a[:, -1] - a[:, -1 - k] if a.shape[1] > k else nan

        def mean(a, k):
            return np.nanmean(a[:, -k:], axis=1)

        day = M[:, -24:]
        low, high = np.nanmin(day, axis=1), np.nanmax(day, axis=1)
        steps = np.diff(M[:, -13:], axis=1)
        vol = np.nanstd(steps, axis=1) if steps.shape[1] else nan
        full = np.ones(x.shape, dtype=np.float32)
        cols = [back(M, 1), back(M, 2), back(M, 3), back(M, 6), back(M, 12), back(M, 24),
                x - mean(M, 6), x - mean(M, 24), x - mean(M, 72), vol,
                np.where(high > low, (x - low) / np.where(high > low, high - low, 1), np.nan),
                S[:, -1], S[:, -1] - mean(S, 6), x, Q[:, -1], back(Q, 1), back(Q, 6), nm[rows, j],
                D[:, -1], mean(D, 6), np.isfinite(day).sum(axis=1).astype(np.float32),
                full * (hour % 24), full * weekday(hour // 24)]
        return np.stack(cols, axis=1).astype(np.float32)


def hourly_dataset(np, db, last):
    """every followed item at every archived scan -> {horizon: (X, y, column of the hour)}"""
    since = last - H_KEEP
    scans = db.execute("SELECT COUNT(*) FROM hour WHERE hour > ?", (since,)).fetchone()[0]
    part = int(min(PART_ROWS, max(200, 1.5 * MAX_ROWS / max(1, scans))))      # rows kept of one house's one hour
    parts = {h: ([], [], []) for h in H_HORIZONS}
    rng = np.random.default_rng(2)
    for (hk,) in db.execute("SELECT DISTINCT house FROM hour WHERE hour > ? ORDER BY house", (since,)).fetchall():
        ids, m, sp, q, nm, s = load_hours(np, db, hk, last, H_KEEP)
        if not len(ids):
            continue
        scanned = np.isfinite(m).any(axis=0)
        for j in range(H_KEEP - 1):
            if not scanned[j]:
                continue
            rows = np.flatnonzero(husable(np, m, j))
            if len(rows) > part:
                rows = rng.choice(rows, part, replace=False)
            X = None
            for h in H_HORIZONS:
                if j + h >= H_KEEP or not scanned[j + h] or not len(rows):
                    continue
                y = m[rows, j + h] - m[rows, j]
                ok = np.isfinite(y)
                if not ok.any():
                    continue
                if X is None:
                    X = hfeatures(np, m, sp, q, nm, s, rows, j, last - (H_KEEP - 1 - j))
                parts[h][0].append(X[ok])
                parts[h][1].append(y[ok])
                parts[h][2].append(np.full(int(ok.sum()), j, dtype=np.int16))
    out = {}
    for h, (xs, ys, js) in parts.items():
        if xs:
            out[h] = (np.concatenate(xs), np.concatenate(ys), np.concatenate(js))
    return out


def train_hourly(np, HGB, folder, report, models):
    path = os.path.join(folder, "hourly.db")
    r0 = report["hourly"] = {"hours": 0, "horizons": {}}
    if not os.path.exists(path):
        r0["note"] = "no hour-by-hour archive yet"
        return
    db = sqlite3.connect(path)
    try:
        last = db.execute("SELECT MAX(hour) FROM hour").fetchone()[0]
        if last is None:
            r0["note"] = "no hour-by-hour archive yet"
            return
        r0["hours"] = db.execute("SELECT COUNT(DISTINCT hour) FROM hour WHERE hour > ?", (last - H_KEEP,)).fetchone()[0]
        data = hourly_dataset(np, db, last)
    finally:
        db.close()
    rng = np.random.default_rng(0)
    models["hfeatures"] = H_FEATURES
    for h in H_HORIZONS:
        r = r0["horizons"][str(h)] = {"on": False, "rows": 0}
        got = judge(np, HGB, data, h, r, rng, "hour", H_TRAIN)
        if got:
            X, y = got[0], got[1]
            everything = sample(np, np.ones(len(y), dtype=bool), rng, MAX_ROWS)
            models["g%d" % h] = fit(np, HGB, X[everything], y[everything], loss="absolute_error")


def train(folder, now=None):
    """learn from the databases in `folder` -> the report (also written to ml.json)"""
    got = libs()
    report = {"t": int(now or time.time()), "horizons": {}}
    if not got or not os.path.exists(os.path.join(folder, "history.db")):
        report["note"] = "numpy and scikit-learn are not installed" if not got else "no database yet"
        return finish(folder, report, None)
    np, HGB = got
    started = time.time()
    models = {"t": report["t"]}
    train_daily(np, HGB, folder, report, models)
    train_hourly(np, HGB, folder, report, models)
    report["seconds"] = round(time.time() - started, 1)
    return finish(folder, report, models if any(k[:1] in "hg" and k[1:].isdigit() for k in models) else None)


def finish(folder, report, models):
    os.makedirs(folder, exist_ok=True)
    pkl = os.path.join(folder, "ml.pkl")
    if models:
        with open(pkl + ".tmp", "wb") as f:
            pickle.dump(models, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(pkl + ".tmp", pkl)
    elif os.path.exists(pkl):
        os.remove(pkl)                                    # no forecast that beats "unchanged": hand out none
    with open(os.path.join(folder, "ml.json.tmp"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    os.replace(os.path.join(folder, "ml.json.tmp"), os.path.join(folder, "ml.json"))
    return report


def describe(report):
    out = []
    hourly = report.get("hourly") or {}
    for unit, part in (("day", report), ("hour", hourly)):
        for h, r in sorted((part.get("horizons") or {}).items(), key=lambda kv: int(kv[0])):
            name = "%s %s%s ahead" % (h, unit, "" if h == "1" else "s")
            if "error" in r:
                line = "%s: %s, error %.2f%% against %.2f%% for an unchanged price (learned from %d rows, checked on %d)" % (
                    name, "on" if r["on"] else "off", r["error"] * 100, r["unchanged"] * 100, r["learned_from"], r["checked_on"])
                if r.get("calls"):
                    line += "; direction right in %.0f%% of %d forecasts of a move over %d%%" % (
                        r.get("calls_right", 0) * 100, r["calls"], CALL * 100)
                if "range_caught" in r:
                    line += "; the 20-80%% range caught %.0f%%, %s" % (r["range_caught"] * 100, "on" if r["range_on"] else "off")
            else:
                line = "%s: off, %s" % (name, r.get("note", "?"))
            out.append(line)
        if part.get("note"):
            out.append(part["note"])
    return out


def load_models(folder):
    path = os.path.join(folder, "ml.pkl")
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    if _cache.get("key") != (path, stamp):
        try:
            with open(path, "rb") as f:
                _cache["models"] = pickle.load(f)
        except Exception:
            return None
        _cache["key"] = (path, stamp)
    return _cache["models"]


def predict_house(folder, db, hk, day):
    """forecasts for every item of a house that has a price today.
    -> {key: (price in a day, price in a week, low end, high end of the week's range)}; 0 = no forecast"""
    got = libs()
    models = load_models(folder) if got else None
    if not models or tuple(models.get("features") or ()) != FEATURES or not ("h1" in models or "h7" in models):
        return {}
    np = got[0]
    keys, m, mn, q, s = load_house(np, db, hk, day)
    if not keys:
        return {}
    j = KEEP_DAYS - 1
    good = usable(np, m, j)
    if not good.any():
        return {}
    X = features(np, m, mn, q, s, j, day)[good]
    base = m[good, j].astype(np.float64)

    def price(name):
        if name not in models:
            return np.zeros(len(base))
        return np.exp(base + np.clip(models[name].predict(X), -CLAMP, CLAMP))

    p1, p7, lo, hi = price("h1"), price("h7"), price("lo7"), price("hi7")
    if "h7" in models and "lo7" in models:                # a range that does not hold its own forecast is no use
        lo, hi = np.minimum(lo, p7), np.maximum(hi, p7)
    else:
        lo, hi = np.zeros(len(base)), np.zeros(len(base))
    names = [k for k, g in zip(keys, good) if g]
    return {k: (int(round(a)), int(round(b)), int(round(c)), int(round(d)))
            for k, a, b, c, d in zip(names, p1.tolist(), p7.tolist(), lo.tolist(), hi.tolist())}


def predict_hours(folder, hk, hour):
    """hour-ahead forecasts for every followed item of a house, from the scan of hour number `hour`.
    -> {key: (price in 1 hour, in 6 hours, in 24 hours)}; 0 = no forecast"""
    got = libs()
    models = load_models(folder) if got else None
    path = os.path.join(folder, "hourly.db")
    if not models or tuple(models.get("hfeatures") or ()) != H_FEATURES or not os.path.exists(path) \
            or not any("g%d" % h in models for h in H_HORIZONS):
        return {}
    np = got[0]
    db = sqlite3.connect(path)
    try:
        if not db.execute("SELECT 1 FROM hour WHERE house = ? AND hour = ?", (hk, hour)).fetchone():
            return {}
        ids, m, sp, q, nm, s = load_hours(np, db, hk, hour, H_BACK)
        names = dict(db.execute("SELECT id, key FROM item WHERE house = ?", (hk,)))
    finally:
        db.close()
    j = H_BACK - 1
    rows = np.flatnonzero(husable(np, m, j))
    if not len(rows):
        return {}
    X = hfeatures(np, m, sp, q, nm, s, rows, j, hour)
    base = m[rows, j].astype(np.float64)
    cols = []
    for h in H_HORIZONS:
        name = "g%d" % h
        cols.append(np.exp(base + np.clip(models[name].predict(X), -CLAMP, CLAMP)).tolist() if name in models
                    else [0.0] * len(rows))
    return {names[i]: tuple(int(round(c[n])) for c in cols) for n, i in enumerate(ids[rows].tolist())}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ultimate AH: forecasts learned from the server scan's history")
    ap.add_argument("command", choices=["train", "info"])
    ap.add_argument("--dir", default=os.environ.get("AH_DATA", "server_data"), help="the server scan's data folder")
    args = ap.parse_args(argv)
    if args.command == "train":
        report = train(args.dir)
        for line in describe(report):
            log("forecast " + line)
        log("training took %s s" % report.get("seconds", 0))
        return 0
    try:
        with open(os.path.join(args.dir, "ml.json"), encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, ValueError):
        print("no training yet")
        return 0
    print("trained", time.strftime("%Y-%m-%d %H:%M", time.localtime(report.get("t", 0))), "from", report.get("days", 0),
          "day(s) and", (report.get("hourly") or {}).get("hours", 0), "hour(s) of history")
    for line in describe(report):
        print(" ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
