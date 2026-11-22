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

print()
print("%d failure(s)" % fails)
raise SystemExit(1 if fails else 0)
