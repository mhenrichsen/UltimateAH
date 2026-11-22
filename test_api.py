"""Offline tests for the API auto scan: ah_api.py against a fake Blizzard API, then the addon's
import of the file it writes (Api.lua in lupa with the mocked WoW API of test_tracker.py)."""
import io
import json
import os
import random
import re
import sys
import tempfile
import urllib.error

import lupa

import ah_api

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, "AuctionLedger")
fails = 0


def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (("  -- " + str(info)) if info else ""))
    if not cond:
        fails += 1


# ---------------------------------------------------------------------------
# a fake API
# ---------------------------------------------------------------------------
HOST = "https://eu.api.blizzard.com"


class Fake:
    def __init__(self):
        self.regular = []
        self.commodities = []
        self.modified = "Sun, 22 Nov 2026 12:00:00 GMT"
        self.calls = []
        self.auth = []

    def __call__(self, req):
        url = req.full_url
        self.calls.append(url)
        self.auth.append(req.get_header("Authorization"))
        if url.startswith("https://oauth.battle.net/token"):
            return 200, json.dumps({"access_token": "TOKEN", "expires_in": 86399}).encode(), {}
        path = url[len(HOST):].split("?")[0]
        if "namespace=dynamic-forever-eu" not in url:
            raise urllib.error.HTTPError(url, 403, "bad namespace", {}, io.BytesIO(b""))
        if path == "/data/wow/ruleset/index":
            body = {"rulesets": [{"id": 1, "name": "PvP"}, {"id": 2, "name": "Normal"}]}
        elif path in ("/data/wow/ruleset/1/auctions/", "/data/wow/ruleset/2/auctions/"):
            r = path.split("/")[4]
            body = {"auctions": [
                {"id": 113, "name": "Alliance Auction House", "key": {"href": "%s/data/wow/ruleset/%s/auctions/113" % (HOST, r)}},
                {"id": 114, "name": {"en_US": "Horde Auction House"}, "key": {"href": "%s/data/wow/ruleset/%s/auctions/114" % (HOST, r)}},
                {"id": 112, "name": "Alliance Auction House", "key": {"href": "%s/data/wow/ruleset/%s/auctions/112" % (HOST, r)}}]}
        elif re.fullmatch(r"/data/wow/ruleset/\d/auctions/113", path):
            body = {"id": 113, "name": "Alliance Auction House", "auctions": self.regular,
                    "commodities": {"href": HOST + path + "/commodities?namespace=dynamic-forever-eu"}}
        elif re.fullmatch(r"/data/wow/ruleset/\d/auctions/112", path):
            body = {"id": 112, "name": "Alliance Auction House"}          # empty house: no auctions field
        elif re.fullmatch(r"/data/wow/ruleset/\d/auctions/113/commodities", path):
            body = {"auctions": self.commodities}
        else:
            raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))
        return 200, json.dumps(body).encode(), {"Last-Modified": self.modified}


def reg(aid, item, buyout, qty=1, tl="VERY_LONG", bonus=None):
    it = {"id": item}
    if bonus:
        it["bonus_lists"] = bonus
    return {"id": aid, "item": it, "buyout": buyout, "quantity": qty, "time_left": tl}


def com(aid, item, unit, qty, tl="VERY_LONG"):
    return {"id": aid, "item": {"id": item}, "unit_price": unit, "quantity": qty, "time_left": tl}


def items_of(d):
    """ApiData items ("min,mkt,...,day,mkt,min,...") as {key: {1: min, ..., 7: sold, 8: [history]}}"""
    out = {}
    for key, s in d["items"].items():
        v = [float(x) if "." in x else int(x) for x in s.split(",")]
        out[key] = {i + 1: x for i, x in enumerate(v[:7])}
        out[key][8] = v[7:]
    return out


tmp = tempfile.mkdtemp(prefix="altest_")
ah_api.STATE = os.path.join(tmp, "state")
ah_api.saved_variables = lambda: None
OUT = os.path.join(tmp, "ApiData.lua")
cfg = {"client_id": "id", "client_secret": "secret", "region": "eu", "ruleset": 1, "house": 113,
       "buyout_is_total": True, "faction": "Alliance"}
fake = Fake()
api = ah_api.Api(cfg, opener=fake)

# 1. discovery
rs = ah_api.rulesets(api)
check("api: rulesets listed", [r["id"] for r in rs] == [1, 2], rs)
hs = ah_api.houses(api, 1)
check("api: house list found on the fallback path", [h["id"] for h in hs] == [113, 114, 112], hs)
check("api: faction from the house name", [ah_api.faction_of(h["name"]) for h in hs] == ["Alliance", "Horde", "Alliance"])
check("api: token only sent to Blizzard", all(u.startswith(("https://oauth.battle.net/", HOST + "/")) for u in fake.calls))
try:
    api.get("https://evil.example.com/data/wow/ruleset/index")
    check("api: refuses links to other hosts", False)
except ah_api.ApiError:
    check("api: refuses links to other hosts", True)
check("api: empty house has no auctions", ah_api.fetch_house(api, 1, 112)["auctions"] == {})

# 2. the price maths is the same as the addon's (Scanner.lua S.Stats)
src = open(os.path.join(HERE, "test_tracker.py"), encoding="utf-8").read()
MOCK = re.search(r'MOCK = r"""(.*?)"""', src, re.S).group(1)
lua = lupa.LuaRuntime(unpack_returned_tuples=True)
lua.execute(MOCK)
AL = lua.table()
for f in ("Core.lua", "Tracker.lua", "Scanner.lua", "Deals.lua", "Guild.lua", "Watch.lua", "Sell.lua", "Mail.lua", "Api.lua"):
    chunk = lua.eval("function(src, name) return assert((loadstring or load)(src, name)) end")(
        open(os.path.join(ADDON, f), encoding="utf-8").read(), "@" + f)
    chunk("AuctionLedger", AL)
G = lua.globals()
G.FIRE("ADDON_LOADED", "AuctionLedger")
G.FIRE("PLAYER_LOGIN")
G.RUNTIMERS()
lua_stats = lua.eval("""function(flat)
  local e = {}
  for i = 1, #flat, 2 do e[#e + 1] = { flat[i], flat[i + 1] } end
  return AuctionLedger.Scanner.Stats(e)
end""")
random.seed(7)
same = True
for _ in range(200):
    n = random.randint(1, 60)
    base = random.choice([35, 480, 12000, 950000])
    ent = [[base * random.choice([1, 1, 1.02, 1.1, 1.5, 4]) + random.randint(0, 9), random.choice([1, 1, 5, 20, 200])] for _ in range(n)]
    flat = lua.table_from([x for e in ent for x in e])
    a = ah_api.stats([list(e) for e in ent])
    b = lua_stats(flat)
    if (round(a[0], 4), a[1], a[2], a[3], a[4]) != (round(b[0], 4), b[1], b[2], b[3], b[4]):
        same = False
        info = (a, b)
        break
check("stats: same min / market / top-100 as the in-game scan", same, "" if same else info)

# 3. keys match the addon's link keys
key = lua.eval('AuctionLedger.KeyFromLink("|cff1eff00|Hitem:11991::::::::1:1491::1:2:12745:777:|h[Ring of the Owl]|h|r", 11991)')
check("keys: bonus ids give the addon's variant key", ah_api.item_key({"id": 11991, "bonus_lists": [12745, 777]}) == key, key)
check("keys: plain item", ah_api.item_key({"id": 4306}) == "4306")

# 4. first scan
fake.regular = [
    reg(1, 11991, 50000, bonus=[12745]),                 # variant, cheapest
    reg(2, 11991, 80000, bonus=[12745]),
    reg(3, 11991, 60000, bonus=[900]),                   # another variant
    reg(4, 2589, 2000, qty=20),                          # stack: buyout is for the whole stack
    reg(5, 2589, 2400, qty=20, tl="SHORT"),
    reg(6, 2589, 9000, qty=20),                          # overpriced
    {"id": 7, "item": {"id": 2589}, "bid": 100, "quantity": 20, "time_left": "LONG"},   # bid only
    reg(8, 7005, 1000),                                  # the only one of its kind
    reg(9, 7005, 1100, tl="MEDIUM"),
]
fake.commodities = [com(100, 4306, 150, 200), com(101, 4306, 160, 500), com(102, 4306, 155, 40), com(103, 4306, 400, 10)]
T0 = 1795300000 - 3600
ah_api.cmd_scan(api, cfg, out=OUT, now=T0)
G.AuctionLedger_ApiData = None
lua.execute(open(OUT, encoding="utf-8").read())
d = G.AuctionLedger_ApiData
check("scan: file loads in Lua", d is not None and d.t == T0 and d.house == 113 and d.faction == "Alliance" and d.auctions == 12,
      (d.t, d.house, d.auctions) if d else None)
it = items_of(d)
check("scan: stack buyout becomes a unit price", it["2589"][1] == 100 and it["2589"][3] == 60 and it["2589"][4] == 3, it["2589"])
check("scan: commodity price", it["4306"][1] == 150 and it["4306"][3] == 750 and it["4306"][4] == 4, it["4306"])
check("scan: variant has its own price and counts for the plain item",
      it["11991:b12745"][1] == 50000 and it["11991:b900"][1] == 60000 and it["11991"][1] == 50000 and it["11991"][4] == 3)
check("scan: no sale rate from a single scan", d.soldHours == 0 and it["4306"][7] == 0)
check("scan: today's price history", it["4306"][8] == [T0 // 86400, it["4306"][2], 150], it["4306"][8])
check("scan: history keeps three significant digits", ah_api.sig3(123456) == 123000 and ah_api.sig3(999) == 999 and ah_api.sig3(50049) == 50000)

# 5. second scan one hour later
fake.modified = "Sun, 22 Nov 2026 13:00:00 GMT"
fake.regular = [
    # 1 gone (cheapest of its variant, lots of time left)      -> sold
    reg(2, 11991, 80000, bonus=[12745]),
    reg(3, 11991, 60000, bonus=[900]),
    # 4 gone (cheapest stack)                                  -> 20 sold
    # 5 gone, but it was SHORT                                 -> expired, not counted
    # 6 gone, overpriced and nothing cheaper left              -> cancelled, not counted
    # 8 gone while 9 survives at a higher price                -> sold
    reg(9, 7005, 1100, tl="SHORT"),
    reg(20, 2589, 2200, qty=20),                         # new
]
fake.commodities = [
    com(100, 4306, 150, 80),       # 120 of 200 bought
    com(101, 4306, 160, 500),
    # 102 gone at 155: cheaper than the surviving 160 but dearer than the surviving 150 -> cancelled
    # 103 gone at 400 -> cancelled
]
T1 = T0 + 3600
ah_api.cmd_scan(api, cfg, out=OUT, now=T1)
G.AuctionLedger_ApiData = None
lua.execute(open(OUT, encoding="utf-8").read())
d = G.AuctionLedger_ApiData
it = items_of(d)
check("sold: one hour of data", d.soldHours == 1, d.soldHours)
check("sold: partly bought commodity, cancelled ones ignored", it["4306"][7] == 120 * 24, it["4306"][7])
check("sold: cheapest stack sold; expired and overpriced ones ignored", it["2589"][7] == 20 * 24, it["2589"][7])
check("sold: variant sale counts for the variant and the plain item",
      it["11991:b12745"][7] == 24 and it["11991"][7] == 24 and it["11991:b900"][7] == 0, (it["11991:b12745"][7], it["11991"][7]))
check("sold: gone while a dearer one stayed", it["7005"][7] == 24, it["7005"][7])
check("scan: new prices", it["2589"][1] == 110 and it["4306"][3] == 580)

# unchanged data is not scanned twice; a long gap is not compared
n_before = len(fake.calls)
ah_api.cmd_scan(api, cfg, out=OUT, now=T1 + 600)
check("scan: unchanged data is skipped", ah_api.read_state("last.json", {})["t"] == T1)
gap = ah_api.sold_between({"1": ["5", 3, 100, 3, 0]}, {}, 5 * 3600, {})
check("sold: scans too far apart are not compared", dict(gap) == {})
late = ah_api.sold_between({"1": ["5", 3, 100, 2, 0]}, {}, 2.5 * 3600, {})
check("sold: an auction that may have run out is not counted", dict(late) == {})

# own auctions (ids from the game's saved data) are not "others"
mine_db = lua.eval('{ listings = { ["Tess Bank"] = { list = { { aid = 100 } } } } }')
check("own auctions: ids read from the saved data", ah_api.my_auction_ids(mine_db) == {"100"})
tbl = ah_api.price_table({"100": ["4306", 80, 150, 3, 1], "101": ["4306", 500, 160, 3, 1]}, {"100"})
check("own auctions: lowest other skips mine", tbl["4306"]["min"] == 150 and tbl["4306"]["other"] == 160, tbl["4306"])

# 6. the addon's import
lua.execute("""
NOW = %d + 900
local S = AuctionLedger.Scanner
S:Store("4306", 4306, "Silk Cloth", 999, 999, 5, 1, NOW - 86400)           -- old in-game price
S:Store("2589", 2589, "Linen Cloth", 105, 107, 40, 2, NOW - 60)            -- fresher than the API scan
AuctionLedger.Watch:Add(4306, "Silk Cloth", 155)
PRINTS = {}
IMPORT = { AuctionLedger.Api:Import() }
RUNTIMERS()
""" % T1)
p = lua.eval('AuctionLedger.db.prices[AuctionLedger:Scope()]')
check("import: started", G.IMPORT[1] is True, list(G.IMPORT.values()))
e = p["4306"]
check("import: API price replaces an older in-game price", e.min == 150 and e.qty == 580 and e.t == T1 and e.src == "api" and e.n == "Silk Cloth",
      (e.min, e.qty, e.t, e.src))
check("import: a newer in-game price is kept, the sale rate still arrives",
      p["2589"].min == 105 and p["2589"].sold == 480 and p["2589"].soldT == T1, (p["2589"].min, p["2589"].sold))
check("import: new items and variants", p["7005"] is not None and p["11991:b12745"].min == 80000 and p["11991:b12745"].i == 11991)
check("import: lowest other", p["4306"].minOther == 150)
check("import: history merged", p["4306"].h[T1 // 86400][2] == 150, list(p["4306"].h.keys()))
check("import: sale rate helper", lua.eval('AuctionLedger.Api.SoldPerDay(AuctionLedger.db.prices[AuctionLedger:Scope()]["4306"])') == 2880)
sc = lua.eval('AuctionLedger.db.scans[AuctionLedger:Scope()]')
check("import: scan status", sc.kind == "API" and sc.t == T1 and sc.api.house == 113 and sc.api.soldHours == 1, (sc.kind, sc.t))
prints = "\n".join(G.PRINTS.values())
check("import: watchlist alert from API data", "Watchlist:" in prints and "Silk Cloth" in prints, prints[:200])
check("import: one summary line", "API scan from" in prints and "sale rates from 1 h" in prints, prints[-200:])
check("import: data table freed", G.AuctionLedger_ApiData is None)
lua.execute(open(OUT, encoding="utf-8").read())
lua.execute("IMPORT = { AuctionLedger.Api:Import() }")
check("import: the same scan is not loaded twice", G.IMPORT[1] is False and G.IMPORT[2] == "already loaded", list(G.IMPORT.values()))
lua.execute("AuctionLedger_ApiData.t = AuctionLedger_ApiData.t + 1; AuctionLedger_ApiData.faction = 'Horde'; IMPORT = { AuctionLedger.Api:Import() }")
check("import: data of the other faction is refused", G.IMPORT[1] is False, list(G.IMPORT.values()))
check("import: sold text", (lua.eval('AuctionLedger.Api.SoldText(2880)'), lua.eval('AuctionLedger.Api.SoldText(2.44)')) == ("2880", "2.4"))

# 7. detect: picks the house whose prices match the in-game scan, and the buyout convention
ah_api.CONFIG = os.path.join(tmp, "cfg.json")
game = lua.eval("""(function()
  local p = {}
  for i = 1, 80 do p[tostring(1000 + i)] = { min = 100 + i, t = os.time() } end
  return { prices = { ["Forever Alliance"] = p }, listings = {} }
end)()""")
ah_api.saved_variables = lambda: game
fake.regular = [reg(1000 + i, 1000 + i, (100 + i) * 5, qty=5) for i in range(1, 81)]
fake.commodities = []
cfg2 = {"client_id": "id", "client_secret": "secret", "region": "eu", "ruleset": None, "house": None, "buyout_is_total": False}
ah_api.cmd_detect(ah_api.Api(cfg2, opener=fake), cfg2)
check("detect: finds the house and that buyout is per stack",
      cfg2["house"] == 113 and cfg2["buyout_is_total"] is True and cfg2["faction"] == "Alliance", cfg2)
saved = json.load(open(ah_api.CONFIG))
check("detect: choice saved", saved["house"] == 113 and saved["ruleset"] == 1)

print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
