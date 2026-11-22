"""Offline tests: run Core.lua + Tracker.lua (+ Scanner/Deals maths) in lupa with a mocked WoW API."""
import os
import sys

import lupa

ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AuctionLedger")

MOCK = r"""
NOW = 1795300000
function time(t) if t then return os.time(t) end return NOW end
date = os.date
function GetTime() return NOW end
function debugprofilestop() return os.clock() * 1000 end
loadstring = loadstring or load
unpack = unpack or table.unpack
strsplit = function(sep, s)
  local out = {}
  for piece in (s .. sep):gmatch("(.-)" .. sep:gsub("%p", "%%%0")) do out[#out + 1] = piece end
  return table.unpack(out)
end
function CopyTable(t) local o = {} for k, v in pairs(t) do o[k] = type(v) == "table" and CopyTable(v) or v end return o end
function wipe(t) for k in pairs(t) do t[k] = nil end return t end
tinsert = table.insert
PRINTS = {}
DEFAULT_CHAT_FRAME = { AddMessage = function(_, m) PRINTS[#PRINTS + 1] = m end }
SlashCmdList = {}
UISpecialFrames = {}
FRAMES = {}
function CreateFrame()
  local f = { events = {} }
  function f:RegisterEvent(e) self.events[e] = true end
  function f:UnregisterEvent(e) self.events[e] = nil end
  function f:SetScript(k, fn) self[k] = fn end
  FRAMES[#FRAMES + 1] = f
  return f
end
function FIRE(e, ...)
  for _, f in ipairs(FRAMES) do if f.events[e] and f.OnEvent then f.OnEvent(f, e, ...) end end
end
TIMERS = {}
C_Timer = { After = function(s, fn) TIMERS[#TIMERS + 1] = fn end, NewTicker = function() return {} end }
SENT = {}
function SendChatMessage(msg, chan, _, target) SENT[#SENT + 1] = chan .. (target and (">" .. target) or "") .. ":" .. msg end
function RUNTIMERS() for i = 1, 20 do local l = TIMERS; TIMERS = {}; if #l == 0 then return end; for _, fn in ipairs(l) do fn() end end end
function hooksecurefunc(t, name, fn)
  if type(t) == "string" then t, name, fn = _G, t, name end
  local orig = t[name]
  t[name] = function(...) local r = { orig(...) }; fn(...); return table.unpack(r) end
end
function UnitName() return "Tess", "Bank" end
function GetRealmName() return "" end
function UnitFactionGroup() return "Alliance" end
function UnitClass() return "Warrior", "WARRIOR" end
MONEY = 500000
function GetMoney() return MONEY end
ITEMNAMES = { [4306] = "Silk Cloth", [2318] = "Light Leather", [11991] = "Quicksilver Ring" }
C_Item = {
  GetItemNameByID = function(id) return ITEMNAMES[id] end,
  GetItemInfo = function(id) return ITEMNAMES[id], nil end,
  GetItemIconByID = function() return 1 end,
  GetItemQualityByID = function() return 1 end,
  GetItemLink = function(loc) return loc.link end,
  GetItemID = function(loc) return loc.id end,
  GetItemInfoInstant = function(name) for id, n in pairs(ITEMNAMES) do if n == name then return id end end end,
}
C_Container = { GetContainerNumSlots = function() return 0 end }
Enum = { AuctionHouseSortOrder = { Price = 0 } }
ERR_AUCTION_SOLD_S = "A buyer has been found for your auction of %s."
ERR_AUCTION_EXPIRED_S = "Your auction of %s has expired."
AUCTION_EXPIRED_MAIL_SUBJECT = "Auction expired: %s"
AUCTION_WON_MAIL_SUBJECT = "Auction won: %s"
AUCTION_SOLD_MAIL_SUBJECT = "Auction successful: %s"
-- auction house
SEARCH = {}
OWNED = {}
C_AuctionHouse = {
  StartCommoditiesPurchase = function() end, ConfirmCommoditiesPurchase = function() end,
  CancelCommoditiesPurchase = function() end, PlaceBid = function() end,
  PostCommodity = function() return false end, ConfirmPostCommodity = function() end,
  PostItem = function() return false end, ConfirmPostItem = function() end, CancelSell = function() end,
  CancelAuction = function() end, GetCancelCost = function() return 0 end,
  CalculateCommodityDeposit = function() return 100 end, CalculateItemDeposit = function() return 60 end,
  GetOwnedAuctions = function() return OWNED end, QueryOwnedAuctions = function() end,
  IsThrottledMessageSystemReady = function() return true end, ReplicateItems = function() end,
  GetNumItemSearchResults = function() return #SEARCH end,
  GetItemSearchResultInfo = function(_, i) return SEARCH[i] end,
  HasFullOwnedAuctionResults = function() return OWNED_FULL end,
  GetAuctionInfoByID = function() return nil end,
}
-- mail
INBOX = {}
function GetInboxNumItems() return #INBOX end
function GetInboxHeaderInfo(i) local m = INBOX[i]; return nil, nil, m.sender, m.subject, m.money or 0, 0, m.daysLeft or 30 end
function GetInboxInvoiceInfo(i) local m = INBOX[i]
  if not m.inv then return nil end
  return m.inv.type, m.inv.item, m.inv.player, m.inv.bid, m.inv.buyout, m.inv.deposit, m.inv.cut, 0, 0, 0, m.inv.count
end
function GetInboxItem(i, a) local m = INBOX[i]; if m.item and a == 1 then return m.item.name, m.item.id, 1, m.item.count end end
"""

lua = lupa.LuaRuntime(unpack_returned_tuples=True)
lua.execute(MOCK)
AL = lua.table()
for f in ("Core.lua", "Tracker.lua", "Scanner.lua", "Deals.lua", "Guild.lua", "Watch.lua", "Sell.lua", "Mail.lua"):
    chunk = lua.eval("function(src, name) return assert((loadstring or load)(src, name)) end")(
        open(os.path.join(ADDON, f), encoding="utf-8").read(), "@" + f)
    chunk("AuctionLedger", AL)
G = lua.globals()
G.FIRE("ADDON_LOADED", "AuctionLedger")
G.FIRE("PLAYER_LOGIN")
G.RUNTIMERS()

fails = 0


def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (("  -- " + str(info)) if info else ""))
    if not cond:
        fails += 1


def txs():
    t = AL.db.tx
    return [dict(t[i].items()) for i in range(1, len(t) + 1)]


AH = G.C_AuctionHouse
check("character key is first+last name", AL.CharKey(AL) == "Tess Bank", AL.CharKey(AL))

# 1. commodity purchase
AH.StartCommoditiesPurchase(4306, 20)
G.FIRE("COMMODITY_PRICE_UPDATED", 200, 4000)
AH.ConfirmCommoditiesPurchase(4306, 20)
G.FIRE("COMMODITY_PURCHASED", 4306, 20)
G.FIRE("COMMODITY_PURCHASE_SUCCEEDED")
G.RUNTIMERS()
t = txs()
check("commodity buy recorded once", len(t) == 1 and t[0]["type"] == "buy" and t[0]["total"] == 4000 and t[0]["qty"] == 20
      and t[0]["unit"] == 200 and t[0]["name"] == "Silk Cloth", t)

# 2. item buyout (Forever: buyoutAmount is for the whole stack)
key = lua.eval("{ itemID = 2318, itemLevel = 0, itemSuffix = 0 }")
G.SEARCH = lua.eval("{ { auctionID = 77, quantity = 5, buyoutAmount = 1500, itemLink = '|cff|Hitem:2318::::::::1::::::|h[Light Leather]|h|r' } }")
G.FIRE("ITEM_SEARCH_RESULTS_UPDATED", key)
AH.PlaceBid(77, 1500)
G.FIRE("AUCTION_HOUSE_PURCHASE_COMPLETED", 77)
G.FIRE("ITEM_PURCHASED", 2318)
t = txs()
check("item buyout recorded once", len(t) == 2 and t[1]["total"] == 1500 and t[1]["qty"] == 5 and t[1]["unit"] == 300, t[1:])

# 3. the "Auction won" mails for those buys must not add buys (commodity arrives as 2 mails)
G.INBOX = lua.eval("""{
  { sender = 'Alliance Auction House', subject = 'Auction won: Silk Cloth', daysLeft = 29.99, inv = { type = 'buyer', item = 'Silk Cloth', player = 'Seller A', bid = 2500, count = 12 } },
  { sender = 'Alliance Auction House', subject = 'Auction won: Silk Cloth', daysLeft = 29.99, inv = { type = 'buyer', item = 'Silk Cloth', player = 'Seller B', bid = 1500, count = 8 } },
  { sender = 'Alliance Auction House', subject = 'Auction won: Light Leather', daysLeft = 29.99, inv = { type = 'buyer', item = 'Light Leather', player = 'Seller C', bid = 1500, count = 5 } },
}""")
G.FIRE("MAIL_INBOX_UPDATE")
G.RUNTIMERS()
check("won-auction mails matched to AH buys (no duplicates)", len(txs()) == 2, len(txs()))

# 4. a bid won later only arrives by mail -> recorded from the mail
G.INBOX = lua.eval("""{ { sender = 'AH', subject = 'Auction won: Quicksilver Ring', daysLeft = 29.5,
  inv = { type = 'buyer', item = 'Quicksilver Ring', player = 'Seller D', bid = 90000, count = 1 } } }""")
G.FIRE("MAIL_INBOX_UPDATE"); G.RUNTIMERS()
t = txs()
ring = [r for r in t if r.get("item") == 11991]
check("bid won by mail recorded as buy", len(t) == 3 and len(ring) == 1 and ring[0]["type"] == "buy" and ring[0]["src"] == "mail"
      and ring[0]["total"] == 90000, ring)

# 5. sold notice -> provisional sale estimated from my listing; then the invoice fills in the real amount
G.OWNED = lua.eval("{ { auctionID = 5, itemKey = { itemID = 4306 }, itemLink = '|Hitem:4306::::::::1::::::|h[Silk Cloth]|h', status = 0, quantity = 10, buyoutAmount = 3000, timeLeftSeconds = 3600 } }")
G.FIRE("OWNED_AUCTIONS_UPDATED")
G.FIRE("CHAT_MSG_SYSTEM", "A buyer has been found for your auction of Silk Cloth.")
t = txs()
check("sold notice -> provisional sale with stack-price estimate", t[-1]["type"] == "sell" and t[-1].get("provisional") and t[-1]["total"] == 3000
      and t[-1]["unit"] == 300, t[-1])
G.NOW = G.NOW + 3600
G.INBOX = lua.eval("""{ { sender = 'AH', subject = 'Auction successful: Silk Cloth', money = 2950, daysLeft = 30,
  inv = { type = 'seller', item = 'Silk Cloth', player = 'Buyer X', bid = 3000, deposit = 100, cut = 150, count = 10 } } }""")
G.FIRE("MAIL_INBOX_UPDATE"); G.RUNTIMERS()
t = txs()
sells = [r for r in t if r["type"] == "sell"]
check("invoice replaces the provisional sale", len(sells) == 1 and not sells[0].get("provisional") and sells[0]["total"] == 3000
      and sells[0]["cut"] == 150 and sells[0]["buyer"] == "Buyer X", sells)

# 6. opening the mailbox again (mail older by now) must not add it again
G.NOW = G.NOW + 600
G.INBOX[1].daysLeft = 30 - 600 / 86400
G.FIRE("MAIL_INBOX_UPDATE"); G.RUNTIMERS()
check("re-reading the same invoice adds nothing", len([r for r in txs() if r["type"] == "sell"]) == 1)

# 7. invoice without a notice (sold while offline) -> new sale
G.INBOX = lua.eval("""{ { sender = 'AH', subject = 'Auction successful: Light Leather', money = 950, daysLeft = 29,
  inv = { type = 'seller', item = 'Light Leather', player = 'Buyer Y', bid = 1000, deposit = 0, cut = 50, count = 4 } } }""")
G.FIRE("MAIL_INBOX_UPDATE"); G.RUNTIMERS()
s = [r for r in txs() if r["type"] == "sell"]
ll = [r for r in s if r.get("item") == 2318]
check("offline sale recorded from mail (dated by the mail)", len(s) == 2 and len(ll) == 1 and ll[0]["unit"] == 250
      and abs(ll[0]["t"] - (G.NOW - 86400)) < 5, ll)

# 8. expired auction mail
G.INBOX = lua.eval("{ { sender = 'AH', subject = 'Auction expired: Silk Cloth', daysLeft = 30, item = { name = 'Silk Cloth', id = 4306, count = 7 } } }")
G.FIRE("MAIL_INBOX_UPDATE"); G.RUNTIMERS()
t = txs()
check("expired mail recorded", t[-1]["type"] == "expired" and t[-1]["qty"] == 7, t[-1])

# 9. posting
loc = lua.eval("{ id = 4306, link = '|Hitem:4306::::::::1::::::|h[Silk Cloth]|h' }")
AH.PostItem(loc, 2, 20, 0, 4000)
G.FIRE("AUCTION_HOUSE_AUCTION_CREATED", 99)
t = txs()
check("post recorded with deposit", t[-1]["type"] == "post" and t[-1]["qty"] == 20 and t[-1]["deposit"] == 60, t[-1])

# 10. ledger is time-ordered after mail inserts
ts = [r["t"] for r in txs()]
check("ledger sorted by time", ts == sorted(ts))

# 11. price maths
st = lua.eval("function(l) return AuctionLedger.Scanner.Stats(l) end")
mn, mkt, qty, num, top = st(lua.eval("{ {100,5}, {110,5}, {120,10}, {500,1}, {130,20}, {140,30} }"))
check("market value ignores the outlier", mn == 100 and 100 <= mkt <= 125 and qty == 71 and num == 6, (mn, mkt, qty, num, top))

# 12. deal finder: 3 cheap stacks under a normal price of ~10g
ev = lua.eval("function(id, l, e) return AuctionLedger.Deals.Evaluate(id, l, e, AuctionLedger.Deals:Settings()) end")
entries = lua.eval("{ {20000,2}, {25000,1}, {30000,3}, {95000,5}, {98000,10}, {100000,10}, {101000,20} }")
e = lua.eval("{ mkt = 100000, top = 99000, h = {} }")
d = ev(9999, entries, e)
check("flip found", d is not None and d.kind == "flip" and d.n == 3 and d.qty == 6 and d.sellAt == 94999
      and abs(d.profit - (6 * 94999 * 0.95 - (40000 + 25000 + 90000))) < 1, d and dict(d.items()))
d2 = ev(9999, lua.eval("{ {98000,2}, {99000,1}, {100000,3}, {101000,5} }"), e)
check("no flip when nothing is cheap", d2 is None)

# 14. sold auctions in the owned list -> provisional sale once; a chat notice is matched, not doubled
G.OWNED = lua.eval("""{
  { auctionID = 501, itemKey = { itemID = 2318 }, itemLink = '|Hitem:2318::::::::1::::::|h[Light Leather]|h', status = 1, quantity = 6, buyoutAmount = 1800 },
  { auctionID = 502, itemKey = { itemID = 4306 }, itemLink = '|Hitem:4306::::::::1::::::|h[Silk Cloth]|h', status = 1, quantity = 4, buyoutAmount = 900 } }""")
G.FIRE("CHAT_MSG_SYSTEM", "A buyer has been found for your auction of Light Leather.")
n_before = len(txs())
G.FIRE("OWNED_AUCTIONS_UPDATED")
G.FIRE("OWNED_AUCTIONS_UPDATED")
prov = [r for r in txs() if r.get("provisional")]
check("owned sold auctions -> one provisional each, chat notice matched",
      len(prov) == 2 and len(txs()) == n_before + 1 and sorted(r.get("auctionID") for r in prov) == [501, 502]
      and [r for r in prov if r.get("auctionID") == 501][0]["total"] == 1800, prov)

# 15. an empty owned list that is not complete must not wipe the listings snapshot
G.OWNED = lua.eval("{}")
G.OWNED_FULL = False
G.FIRE("OWNED_AUCTIONS_UPDATED")
snap = AL.db.listings["Tess Bank"]
check("incomplete empty owned list keeps the snapshot", len(snap.list) == 2, len(snap.list))
G.OWNED_FULL = True
G.FIRE("OWNED_AUCTIONS_UPDATED")
check("complete empty owned list clears it", len(AL.db.listings["Tess Bank"].list) == 0)

# 13. deal finder judges suffix gear per variant, not against the all-variants list
lua.execute("""
local S, scope = AuctionLedger.Scanner, AuctionLedger:Scope()
AuctionLedger.db.prices[scope] = {
  ["500"] = { i = 500, n = "Leggings", mkt = 100000, top = 100000, h = {} },
  ["500:b1"] = { i = 500, n = "Leggings of the Eagle", mkt = 20000, top = 20000, h = {} },
  ["600"] = { i = 600, n = "Cloth", mkt = 100000, top = 99000, h = {} },
}
S.last = { t = NOW, items = {
  ["500"] = { {20000,1}, {21000,1}, {22000,1}, {100000,1}, {100000,1}, {100000,1}, {101000,1} },
  ["500:b1"] = { {20000,1}, {21000,1}, {22000,1}, {23000,1} },
  ["600"] = { {20000,2}, {25000,1}, {30000,3}, {95000,5}, {98000,10}, {100000,10}, {101000,20} },
} }
DEALS = AuctionLedger.Deals:Find()
""")
keys = sorted(d.key for d in G.DEALS.values())
check("suffix gear judged per variant (no false flip)", keys == ["600"], keys)

# 16. guild chat "AH <item>" replies
lua.execute("""
AuctionLedger.UI = { Ago = function(t) return math.floor((NOW - t) / 60) .. 'm ago' end }
local scope = AuctionLedger:Scope()
AuctionLedger.db.prices[scope] = {
  ["4306"] = { i = 4306, n = "Silk Cloth", mkt = 199, min = 192, top = 201, qty = 22280, t = NOW - 720, h = {} },
  ["500"] = { i = 500, n = "Leggings", mkt = 50000, min = 40000, qty = 9, t = NOW - 60, h = {} },
  ["500:b1"] = { i = 500, n = "Leggings", mkt = 20000, min = 19000, qty = 3, t = NOW - 60, h = {} },
  ["501"] = { i = 501, n = "Silk Bandage", mkt = 900, min = 800, qty = 40, t = NOW - 60, h = {} },
}
""")


def guild(text, sender="Guildie"):
    G.NOW = G.NOW + 5          # past the 2 s gap between replies
    G.FIRE("CHAT_MSG_GUILD", text, sender)


def sent():
    s = G.SENT
    return [s[i] for i in range(1, len(s) + 1)]


guild("AH Silk Cloth")
G.RUNTIMERS()
s = sent()
check("guild: reply with market data", len(s) == 1 and s[0].startswith("GUILD:[AL] [Silk Cloth]: market 1s 99c, lowest 1s 92c")
      and "22280 listed" in s[0] and "scanned 12m ago" in s[0], s)
guild("AH Silk Cloth")
G.RUNTIMERS()
check("guild: same asker, same item again is throttled", len(sent()) == 1, sent())
guild("ah ok"); guild("AH is busy right now"); G.RUNTIMERS()
check("guild: 'ah ok' and plain words are ignored", len(sent()) == 1, sent())
guild("AH Leggings", "Other")
G.FIRE("CHAT_MSG_GUILD", "[AL] [Leggings]: market 5g, lowest 4g (scanned 1m ago)", "AnotherAddonUser")
G.RUNTIMERS()
check("guild: stays quiet when another addon user answered first", len(sent()) == 1, sent())
guild("AH leggings", "Third")
G.RUNTIMERS()
check("guild: exact name uses the all-variants price", len(sent()) == 2 and "market 5g, lowest 4g," in sent()[1], sent()[-1:])
guild("AH silk", "Fourth")
G.RUNTIMERS()
check("guild: partial name answers the shortest match and says there are more", len(sent()) == 3
      and "[Silk Cloth]" in sent()[2] and "2 matches" in sent()[2], sent()[-1:])
guild("AH |cffffffff|Hitem:4306::::::::1::::::|h[Silk Cloth]|h|r", "Fifth")
G.RUNTIMERS()
check("guild: item link query", len(sent()) == 4 and "[Silk Cloth]" in sent()[3], sent()[-1:])
guild("[AL] [Silk Cloth]: market 1s", "Me")
G.RUNTIMERS()
check("guild: never answers [AL] lines", len(sent()) == 4)
lua.execute("AuctionLedger.db.settings.guildReply = false")
guild("AH Silk Bandage", "Sixth")
G.RUNTIMERS()
check("guild: off switch", len(sent()) == 4)

exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests_v2.py"), encoding="utf-8").read())

print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)

