"""Offline tests for the learned forecasts (ah_ml.py): made-up markets written straight into the
server scan's database, a training on each, and a server scan that hands the forecasts out.
Needs numpy and scikit-learn (pip install numpy scikit-learn); without them it only checks that the
server scan does not need them."""
import gzip
import json
import math
import os
import random
import sys
import tempfile

import ah_api
import ah_ml
import ah_server

fails = 0


def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (("  -- " + str(info)) if info else ""))
    if not cond:
        fails += 1


tmp = tempfile.mkdtemp(prefix="uahml_")
ah_api.STATE = os.path.join(tmp, "log")
DAY = 20801                                              # the last day of every made-up history


def market(folder, kind, days=30, items=700, houses=(110, 113), seed=1):
    """a database with `days` days of prices. kind "reverting": prices wander around a usual level and
    come back to it; "walk": every day's change is pure chance"""
    db = ah_server.connect(folder)
    rnd = random.Random(seed)
    for hid in houses:
        hk = ah_server.house_key(db, "eu", {"id": hid})
        rows = []
        for item in range(items):
            base = math.log(rnd.choice([120, 900, 4500, 30000, 250000]))
            x = 0.0
            for d in range(DAY - days + 1, DAY + 1):
                x = (0.6 * x + rnd.gauss(0, 0.1)) if kind == "reverting" else (x + rnd.gauss(0, 0.06))
                price = int(round(math.exp(base + x)))
                rows.append((hk, d, str(1000 + item), price * 3, 3, int(price * 0.95), rnd.randint(5, 400), rnd.randint(0, 50)))
        db.executemany("INSERT INTO daily (house, day, key, mkt_sum, n, min, qty, sold) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    db.commit()
    db.close()


if not ah_ml.libs():
    check("without numpy / scikit-learn: nothing is trained, nothing breaks", "note" in ah_ml.train(os.path.join(tmp, "none")))
    print("\nnumpy / scikit-learn are not installed: the other checks were skipped")
    print("%d failure(s)" % fails)
    raise SystemExit(1 if fails else 0)

# 1. prices that come back to their usual level can be learned
A = os.path.join(tmp, "reverting")
market(A, "reverting")
rep = ah_ml.train(A, now=DAY * 86400)
h1, h7 = rep["horizons"]["1"], rep["horizons"]["7"]
check("learnable market: the one-day forecast beats 'unchanged' and is on", h1["on"] and h1["error"] < 0.95 * h1["unchanged"], h1)
check("learnable market: the seven-day forecast beats 'unchanged' and is on", h7["on"] and h7["error"] < 0.9 * h7["unchanged"], h7)
check("learnable market: the 20-80% range catches about 60% of real prices", h7.get("range_on") and 0.45 <= h7["range_caught"] <= 0.75, h7)
check("training: checked on rows it did not learn from", h1["checked_on"] > 1000 and h1["learned_from"] > 5000 and rep["days"] == 30, rep)
check("training: the report is published as ml.json", json.load(open(os.path.join(A, "ml.json")))["horizons"]["7"]["on"] is True)
check("training: the report reads as text", any("7 days ahead: on" in line for line in ah_ml.describe(rep)), ah_ml.describe(rep))

db = ah_server.connect(A)
hk = ah_server.house_key(db, "eu", {"id": 110})
pred = ah_ml.predict_house(A, db, hk, DAY)
now = {k: m / n for k, m, n in db.execute("SELECT key, mkt_sum, n FROM daily WHERE house = ? AND day = ?", (hk, DAY))}
usual = {}
for k, m, n in db.execute("SELECT key, mkt_sum, n FROM daily WHERE house = ?", (hk,)):
    usual.setdefault(k, []).append(m / n)
usual = {k: ah_server.median(v) for k, v in usual.items()}
check("forecasts: one for every item with a price today", len(pred) == 700 and all(p[0] > 0 and p[1] > 0 for p in pred.values()), len(pred))
high = [k for k in now if now[k] > 1.2 * usual[k]]
low = [k for k in now if now[k] < 0.83 * usual[k]]
check("forecasts: a price far above its usual level is expected to fall",
      len(high) > 20 and sum(pred[k][1] < now[k] for k in high) >= 0.9 * len(high), (len(high), sum(pred[k][1] < now[k] for k in high)))
check("forecasts: a price far below its usual level is expected to rise",
      len(low) > 20 and sum(pred[k][1] > now[k] for k in low) >= 0.9 * len(low), (len(low), sum(pred[k][1] > now[k] for k in low)))
check("forecasts: the range holds the forecast", all(p[2] <= p[1] <= p[3] and p[2] > 0 for p in pred.values()))
check("forecasts: nothing moves by more than a factor of two", all(0.49 * now[k] <= p[1] <= 2.05 * now[k] for k, p in pred.items()))
db.close()

# 2. the server scan hands them out
api = type("Api", (), {})()
import io
import re
import urllib.error

HOST = "https://eu.api.blizzard.com"


def fake(req):
    url = req.full_url
    if url.startswith("https://oauth.battle.net/token"):
        return 200, json.dumps({"access_token": "TOKEN"}).encode(), {}
    path = url[len(HOST):].split("?")[0]
    if path.endswith("/commodities"):
        aucs = [{"id": 100000 + i * 10 + k, "item": {"id": 1000 + i}, "unit_price": int(round(now[str(1000 + i)])), "quantity": 5,
                 "time_left": "VERY_LONG"} for i in range(700) for k in range(2)]
        return 200, json.dumps({"auctions": aucs}).encode(), {"Last-Modified": "now"}
    if re.fullmatch(r"/data/wow/ruleset/1/auctions/110", path):
        return 200, json.dumps({"id": 110, "name": "Alliance Auction House", "auctions": [],
                                "commodities": {"href": HOST + path + "/commodities"}}).encode(), {"Last-Modified": "now"}
    raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))


cfg = {"client_id": "id", "client_secret": "secret", "region": "eu"}
db = ah_server.connect(A)
entry = ah_server.scan_house(ah_api.Api(cfg, opener=fake), db, A, {"id": 110, "name": "Alliance Auction House"},
                             now=DAY * 86400 + 20 * 3600)
db.close()
with gzip.open(os.path.join(A, "eu-110.lua.gz"), "rt", encoding="utf-8") as f:
    meta, items, ins = ah_api.parse_file(f.read())
F = {name: j for j, name in enumerate(ah_api.INS_FIELDS)}
x = ins[high[0]]
check("server scan: the data file carries the learned forecasts", len(ins) == 700 and len(x) == len(F) and x[F["in1"]] > 0 and x[F["in7"]] > 0
      and 0 < x[F["lo7"]] <= x[F["in7"]] <= x[F["hi7"]], x)
check("server scan: the week's forecast is the learned one", abs(x[F["in7"]] - ah_api.sig3(pred[high[0]][1])) <= 0.03 * x[F["in7"]], (x[F["in7"]], pred[high[0]][1]))
check("server scan: the index says the learned forecast is on", entry.get("learned") is True, entry)

# 3. prices that move by pure chance cannot be learned, and nothing is handed out
B = os.path.join(tmp, "walk")
market(B, "walk", seed=2)
rep = ah_ml.train(B, now=DAY * 86400)
check("random market: both forecasts stay off", not rep["horizons"]["1"]["on"] and not rep["horizons"]["7"]["on"], rep["horizons"])
check("random market: no model is kept", not os.path.exists(os.path.join(B, "ml.pkl")))
db = ah_server.connect(B)
check("random market: no forecasts", ah_ml.predict_house(B, db, ah_server.house_key(db, "eu", {"id": 110}), DAY) == {})
db.close()

# 4. a market that stops being learnable loses its forecasts at the next training
market(os.path.join(tmp, "turn"), "reverting", seed=3)
T = os.path.join(tmp, "turn")
ah_ml.train(T, now=DAY * 86400)
had = os.path.exists(os.path.join(T, "ml.pkl"))
os.remove(os.path.join(T, "history.db"))
market(T, "walk", seed=4)
ah_ml.train(T, now=DAY * 86400)
check("a market that turns random loses its forecasts", had and not os.path.exists(os.path.join(T, "ml.pkl")))

# 5. too little history: nothing is trained
C = os.path.join(tmp, "young")
market(C, "reverting", days=3, seed=5)
rep = ah_ml.train(C, now=DAY * 86400)
check("three days of history: the one-day forecast waits", rep["horizons"]["1"]["on"] is False and "note" in rep["horizons"]["1"], rep["horizons"]["1"])
check("three days of history: no day has a seven-day answer", rep["horizons"]["7"].get("note") == "no day has an answer yet", rep["horizons"]["7"])
D = os.path.join(tmp, "empty")
check("no database: a note, no crash", "note" in ah_ml.train(D))
E = os.path.join(tmp, "week")
market(E, "reverting", days=7, seed=6)                   # nothing has a change over 7 days yet: an empty column
rep = ah_ml.train(E, now=DAY * 86400)
check("seven days of history: the one-day forecast is trained and judged", "error" in rep["horizons"]["1"], rep["horizons"]["1"])

# 6. hour by hour: the scan's archive, the 1, 6 and 24 hour forecasts
LAST = DAY * 24 + 19                                     # the hour number of the last archived scan


def hourly(folder, kind, hours=80, items=600, houses=(110, 113), seed=1):
    """an hour-by-hour archive of `hours` scans, written the way the scan writes it -> the last
    prices of the first house. kind as in market(): "reverting" or "walk", per hour"""
    db = ah_server.connect(folder)
    hks = [ah_server.house_key(db, "eu", {"id": hid}) for hid in houses]
    db.commit()
    db.close()
    rnd = random.Random(seed)
    first = None
    for hk in hks:
        base = [math.log(rnd.choice([120, 900, 4500, 30000, 250000])) for _ in range(items)]
        x = [0.0] * items
        table = {}
        for i in range(hours):
            table = {}
            for item in range(items):
                x[item] = (0.5 * x[item] + rnd.gauss(0, 0.04)) if kind == "reverting" else (x[item] + rnd.gauss(0, 0.02))
                price = int(round(math.exp(base[item] + x[item])))
                table[str(1000 + item)] = {"mkt": price, "min": max(1, int(price * 0.97)), "qty": rnd.randint(5, 400), "num": rnd.randint(2, 30)}
            ah_server.archive_hour(folder, hk, (LAST - hours + 1 + i) * 3600 + 23 * 60, table, {})
        if first is None:
            first = (hk, {k: p["mkt"] for k, p in table.items()}, dict(zip(table, base)))
    return first


H = os.path.join(tmp, "hours")
hk, last_price, base = hourly(H, "reverting")
rep = ah_ml.train(H, now=DAY * 86400)
hh = rep["hourly"]["horizons"]
check("hour by hour: the report counts the archived hours", rep["hourly"]["hours"] == 80, rep["hourly"]["hours"])
check("hour by hour: the 1, 6 and 24 hour forecasts beat 'unchanged' and are on",
      all(hh[h]["on"] and hh[h]["error"] < 0.9 * hh[h]["unchanged"] for h in ("1", "6", "24")), hh)
check("hour by hour: checked on later hours than it learned from", hh["1"]["checked_on"] > 5000 and hh["1"]["learned_from"] > 20000, hh["1"])
check("hour by hour: the report says how often the direction was right", hh["1"]["calls"] > 100 and hh["1"]["calls_right"] > 0.7, hh["1"])
check("hour by hour: the report reads as text", any(line.startswith("6 hours ahead: on") for line in ah_ml.describe(rep)), ah_ml.describe(rep))
pred = ah_ml.predict_hours(H, hk, LAST)
check("hour by hour: forecasts for every followed item", len(pred) == 600 and all(min(p) > 0 for p in pred.values()), len(pred))
high = [k for k in last_price if last_price[k] > 1.06 * math.exp(base[k])]
low = [k for k in last_price if last_price[k] < 0.94 * math.exp(base[k])]
check("hour by hour: a price above its usual level is expected to come down within 6 hours",
      len(high) > 20 and sum(pred[k][1] < last_price[k] for k in high) >= 0.9 * len(high), (len(high), sum(pred[k][1] < last_price[k] for k in high)))
check("hour by hour: a price below its usual level is expected to rise within 6 hours",
      len(low) > 20 and sum(pred[k][1] > last_price[k] for k in low) >= 0.9 * len(low), (len(low), sum(pred[k][1] > last_price[k] for k in low)))
check("hour by hour: no forecasts from an hour that was not scanned", ah_ml.predict_hours(H, hk, LAST + 1) == {})


def fake_hour(req):
    url = req.full_url
    if url.startswith("https://oauth.battle.net/token"):
        return 200, json.dumps({"access_token": "TOKEN"}).encode(), {}
    path = url[len(HOST):].split("?")[0]
    if path.endswith("/commodities"):
        aucs = [{"id": 100000 + int(k) * 10 + n, "item": {"id": int(k)}, "unit_price": last_price[k], "quantity": 5,
                 "time_left": "VERY_LONG"} for k in last_price for n in range(2)]
        return 200, json.dumps({"auctions": aucs}).encode(), {"Last-Modified": "now"}
    if re.fullmatch(r"/data/wow/ruleset/1/auctions/110", path):
        return 200, json.dumps({"id": 110, "name": "Alliance Auction House", "auctions": [],
                                "commodities": {"href": HOST + path + "/commodities"}}).encode(), {"Last-Modified": "now"}
    raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))


db = ah_server.connect(H)
entry = ah_server.scan_house(ah_api.Api(cfg, opener=fake_hour), db, H, {"id": 110, "name": "Alliance Auction House"},
                             now=(LAST + 1) * 3600 + 23 * 60)
db.close()
with gzip.open(os.path.join(H, "eu-110.lua.gz"), "rt", encoding="utf-8") as f:
    meta, items, ins = ah_api.parse_file(f.read())
x = ins[high[0]]
check("server scan: an item with one day of history still gets its hour-ahead forecasts",
      len(ins) == 600 and len(x) == len(F) and x[F["days"]] == 1 and x[F["trend"]] == 9999 and x[F["in7"]] == 0, x)
check("server scan: the price in 6 hours, and tomorrow's from the 24 hour forecast",
      0 < x[F["in6"]] < last_price[high[0]] and x[F["in1"]] > 0 and x[F["lo7"]] == 0, (x, last_price[high[0]]))
check("server scan: the index says the hour-ahead forecasts are on", entry.get("hourAhead") is True and entry.get("learned") is False
      and entry.get("hours") == 81, entry)

W = os.path.join(tmp, "hours_walk")
hk2 = hourly(W, "walk", seed=2)[0]
rep = ah_ml.train(W, now=DAY * 86400)
hh = rep["hourly"]["horizons"]
check("hour by hour, random market: every forecast stays off", not any(hh[h]["on"] for h in hh) and len(hh) == 3, hh)
check("hour by hour, random market: no model, no forecasts", not os.path.exists(os.path.join(W, "ml.pkl"))
      and ah_ml.predict_hours(W, hk2, LAST) == {})

Y = os.path.join(tmp, "hours_young")
hourly(Y, "reverting", hours=8, seed=3)
hh = ah_ml.train(Y, now=DAY * 86400)["hourly"]["horizons"]
check("eight hours of archive: the forecasts wait", hh["1"]["on"] is False and hh["1"].get("note") == "too little history"
      and hh["24"].get("note") == "no hour has an answer yet", hh)

print()
print("%d failure(s)" % fails)
raise SystemExit(1 if fails else 0)
