"""Offline tests for posting from the Sell page (Sell.lua) with a mocked auction house."""
import os
import re
import sys

import lupa

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "UltimateAH")
fails = 0


def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (("  -- " + str(info)) if info else ""))
    if not cond:
        fails += 1


src = open(os.path.join(HERE, "test_tracker.py"), encoding="utf-8").read()
MOCK = re.search(r'MOCK = r"""(.*?)"""', src, re.S).group(1)
lua = lupa.LuaRuntime(unpack_returned_tuples=True)
lua.execute(MOCK)
lua.execute(r"""
ITEMNAMES[11991] = "Quicksilver Ring"
local function link(id, name, bonus) return "|cffffffff|Hitem:" .. id .. "::::::::1:::" .. (bonus or ":") .. ":|h[" .. name .. "]|h|r" end
BAG = {
  [0] = {
    [1] = { itemID = 4306, stackCount = 20, hyperlink = link(4306, "Silk Cloth") },
    [2] = { itemID = 4306, stackCount = 13, hyperlink = link(4306, "Silk Cloth") },
    [3] = { itemID = 4306, stackCount = 20, hyperlink = link(4306, "Silk Cloth"), isBound = true },
    [4] = { itemID = 11991, stackCount = 1, hyperlink = link(11991, "Quicksilver Ring of the Owl", "1:1:12745") },
  },
}
C_Container = {
  GetContainerNumSlots = function(b) return BAG[b] and 8 or 0 end,
  GetContainerItemInfo = function(b, s) return BAG[b] and BAG[b][s] end,
}
ItemLocation = { CreateFromBagAndSlot = function(_, b, s) local i = BAG[b][s]; return { bag = b, slot = s, id = i.itemID, link = i.hyperlink } end }
Enum.ItemCommodityStatus = { Unknown = 0, Item = 1, Commodity = 2 }
CALLS, CONFIRM, READY, POPUPS, QUERIES = {}, false, true, {}, {}
C_AuctionHouse.PostCommodity = function(loc, dur, qty, unit) CALLS[#CALLS + 1] = { "commodity", loc.id, dur, qty, unit }; return CONFIRM end
C_AuctionHouse.PostItem = function(loc, dur, qty, bid, buyout) CALLS[#CALLS + 1] = { "item", loc.id, dur, qty, buyout, bid }; return CONFIRM end
C_AuctionHouse.ConfirmPostCommodity = function(loc, dur, qty, unit) CALLS[#CALLS + 1] = { "confirm", loc.id, dur, qty, unit } end
C_AuctionHouse.GetItemCommodityStatus = function(loc) return loc.id == 4306 and 2 or 1 end
C_AuctionHouse.IsThrottledMessageSystemReady = function() return READY end
C_AuctionHouse.IsSellItemValid = function() return true end
C_AuctionHouse.MakeItemKey = function(id) return { itemID = id } end
C_AuctionHouse.SendSearchQuery = function(key) QUERIES[#QUERIES + 1] = key.itemID end
C_AuctionHouse.CalculateCommodityDeposit = function(id, dur, qty) return 7 * dur * qty end
StaticPopupDialogs = {}
function StaticPopup_Show(which, text) local d = { which = which, text = text }; POPUPS[#POPUPS + 1] = d; return d end
""")
AL = lua.table()
for f in ("Core.lua", "Tracker.lua", "Scanner.lua", "Value.lua", "Deals.lua", "Guild.lua", "Watch.lua", "Sell.lua", "Mail.lua", "Api.lua"):
    chunk = lua.eval("function(src, name) return assert((loadstring or load)(src, name)) end")(
        open(os.path.join(ADDON, f), encoding="utf-8").read(), "@" + f)
    chunk("UltimateAH", AL)
G = lua.globals()
G.FIRE("ADDON_LOADED", "UltimateAH")
G.FIRE("PLAYER_LOGIN")
G.RUNTIMERS()
lua.execute("""
Sl = UltimateAH.Sell
POSTED = {}
UltimateAH:On("AL_SELL_POSTED", function(key, ok) POSTED[#POSTED + 1] = { key, ok } end)
function post(...) local ok, why = Sl:Post(...); return ok, why end
""")
post = G.post


def calls():
    return [tuple(c.values()) for c in G.CALLS.values()]


# 1. pricing modes
pf = lua.eval("function(post, lowest, ref, mode) return Sl.PriceFor({ post = post, lowest = lowest, ref = ref }, mode) end")
check("price: undercut, match and normal", (pf(194, 195, 200, "undercut"), pf(194, 195, 200, "match"), pf(194, 195, 200, "normal")) == (194, 195, 200))
check("price: no matching of an auction far below normal", pf(200, 90, 200, "match") == 200)

# 2. finding the item in the bags
it = lua.eval('Sl:Locate("4306")')
check("locate: counts every unbound stack", it.count == 33 and it.bag == 0 and it.slot == 1 and it.commodity is True, (it.count, it.commodity))
ring = lua.eval('Sl:Locate("11991:b12745")')
check("locate: a variant by its key, as a single item", ring.count == 1 and ring.commodity is False and ring.slot == 4, (ring.count, ring.commodity))
check("locate: not in the bags", lua.eval('Sl:Locate("999")').loc is None)
check("deposit: asked from the game", lua.eval('Sl:Deposit(Sl:Locate("4306"), 2, 33)') == 7 * 2 * 33)

# 3. refusals
ok, why = post("4306", 190, 33, 2)
check("post: refused while the auction house is closed", ok is False and "Open the auction house" in why, why)
lua.execute("UltimateAH.ahOpen = true")
check("post: needs a price", post("4306", None, 33, 2)[0] is False)
ok, why = post("4306", 190, 50, 2)
check("post: not more than you have", ok is False and "only have 33" in why, why)
check("post: item gone", post("999", 190, 1, 2)[0] is False)
lua.execute("READY = false")
ok, why = post("4306", 190, 33, 2)
check("post: waits while the auction house is busy", ok is False and "busy" in why and len(calls()) == 0, why)
lua.execute("READY = true")

# 4. a commodity
ok, why = post("4306", 190.7, 33, 3)
check("post: commodity goes out with unit price, quantity and duration", ok is True and calls() == [("commodity", 4306, 3, 33, 190)], calls())
ok, why = post("4306", 190, 33, 3)
check("post: one at a time", ok is False and "previous" in why and len(calls()) == 1, why)
lua.execute("PRINTS = {}")
n_tx = lua.eval("#UltimateAH.db.tx")
G.FIRE("AUCTION_HOUSE_AUCTION_CREATED", 555)
prints = "\n".join(G.PRINTS.values())
check("post: confirmed by the game", lua.eval("Sl.posting") is None and "posted 33 x" in prints and "1s 90c each" in prints, prints)
check("post: page is told", [tuple(p.values()) for p in G.POSTED.values()] == [("4306", True)])
tx = lua.eval("UltimateAH.db.tx[#UltimateAH.db.tx]")
check("post: lands in the ledger", lua.eval("#UltimateAH.db.tx") == n_tx + 1 and tx.type == "post" and tx.qty == 33 and tx.unit == 190 and tx.total == 6270,
      (tx.type, tx.qty, tx.unit, tx.total))

# 5. a single item
lua.execute("CALLS = {}")
ok, why = post("11991:b12745", 250000, 1, 1)
check("post: a single item goes out with a buyout and no bid", ok is True and calls() == [("item", 11991, 1, 1, 250000)], calls())
lua.execute("PRINTS = {}")
G.FIRE("AUCTION_HOUSE_POST_ERROR")
check("post: a refusal by the game is reported", lua.eval("Sl.posting") is None and "refused" in "\n".join(G.PRINTS.values())
      and tuple(G.POSTED[2].values()) == ("11991:b12745", False))

# 6. the game asks for a confirmation
lua.execute("CALLS = {}; CONFIRM = true")
ok, why = post("4306", 1, 5, 2)
popup = G.POPUPS[1]
check("post: confirmation asked", ok is True and popup is not None and popup.which == "ULTIMATEAH_CONFIRM_POST" and "5 x" in popup.text, popup and popup.text)
lua.execute('StaticPopupDialogs["ULTIMATEAH_CONFIRM_POST"].OnAccept(nil, POPUPS[1].data)')
check("post: confirmed with the same numbers", calls()[-1] == ("confirm", 4306, 2, 5, 1), calls())
G.FIRE("AUCTION_HOUSE_AUCTION_CREATED", 556)
lua.execute("CONFIRM = false; CALLS = {}")
ok, why = post("4306", 1, 5, 2)
lua.execute("CONFIRM = true")
lua.execute('Sl.posting = nil; post("4306", 1, 5, 2); StaticPopupDialogs["ULTIMATEAH_CONFIRM_POST"].OnCancel(nil, POPUPS[#POPUPS].data)')
check("post: saying no to the confirmation frees the page", lua.eval("Sl.posting") is None)
lua.execute("CONFIRM = false")

# 7. live auctions
lua.execute("""
UltimateAH:Fire("AL_PRICE", "4306", { {200, 40}, {195, 100}, {195, 20}, {193, 60, true}, {210, 5}, {220, 9}, {230, 1}, {240, 1} })
COMP, COMP_T = Sl:Competition("4306", 4)
""")
comp = [tuple(c.values()) for c in G.COMP.values()]
check("live: cheapest first, equal prices merged, mine marked", comp == [(193, 60, True), (195, 120, False), (200, 40, False), (210, 5, False)], comp)
check("live: has a time", G.COMP_T is not None)
lua.execute("QUERIES = {}; R1 = Sl:RefreshLive('4306', 4306); R2 = Sl:RefreshLive('11991:b12745', 11991)")
check("live: fresh data is not asked for again", G.R1 is False and list(G.QUERIES.values()) == [11991] and G.R2 is True, list(G.QUERIES.values()))
lua.execute("R3 = Sl:RefreshLive('2589', 2589)")
check("live: at most one search a second", G.R3 is False)
lua.execute("UltimateAH.ahOpen = false; Sl.lastQuery = nil; R4 = Sl:RefreshLive('2589', 2589)")
check("live: nothing is asked while the auction house is closed", G.R4 is False)

# 8. rows for the page
rows = {r.key: r for r in lua.eval("Sl:Rows()").values()}
check("rows: one per item key, bound stacks left out", set(rows) == {"4306", "11991:b12745"} and rows["4306"].count == 33, sorted(rows))

print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
