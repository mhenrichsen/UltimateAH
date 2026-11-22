# Tests for the v2 features; executed by test_tracker.py in its namespace (exec), before the summary.

# 17. own auctions: name matching, deal finder skips them
lua.execute("""
local set = AuctionLedger:MyNameSet()
MINE = { AuctionLedger.IsMineName(set, "Tess-Bank", nil), AuctionLedger.IsMineName(set, nil, "Tess Bank"),
         AuctionLedger.IsMineName(set, "Someone-Else", "Someone") }
""")
check("own auctions recognised by name", G.MINE[1] and G.MINE[2] and not G.MINE[3], list(G.MINE.values()))
lua.execute("""
local e = { i = 600, n = "Cloth", mkt = 100000, top = 99000, h = {} }
local cfg = { minProfit = 2000, minROI = 0.1, cheap = 0.85, minAuctions = 4, maxShare = 0.5 }
local base = { {20000,2}, {25000,1}, {30000,3}, {95000,5}, {98000,10}, {100000,10}, {101000,20} }
DEAL_OTHERS = AuctionLedger.Deals.Evaluate(600, base, e, cfg)
local mine = { {20000,2,true}, {25000,1,true}, {30000,3,true}, {95000,5}, {98000,10}, {100000,10}, {101000,20} }
DEAL_MINE = AuctionLedger.Deals.Evaluate(600, mine, e, cfg)
""")
check("deal finder: cheap auctions from others are a flip", G.DEAL_OTHERS is not None and G.DEAL_OTHERS.kind == "flip")
check("deal finder: never suggests buying your own auctions", G.DEAL_MINE is None)

# 18. money parsing, watchlist alerts
pm = lua.eval("AuctionLedger.ParseMoney")
got = (pm("40g"), pm("1g 50s"), pm("35s20c"), pm("2.5"), pm("abc"))
check("parse money", got == (400000, 15000, 3520, 25000, None), got)
lua.execute("""
PRINTS = {}
AuctionLedger.Watch:Add(4306, "Silk Cloth", 190)
AuctionLedger.Watch:Check("4306", { {185, 5}, {180, 3, true}, {200, 10} }, "test")
W1 = #PRINTS
AuctionLedger.Watch:Check("4306", { {185, 5} }, "test")
W2 = #PRINTS
AuctionLedger.Watch:Check("4306", { {170, 1} }, "test")
W3 = #PRINTS
AuctionLedger.Watch:Check("4306", { {195, 9}, {191, 1} }, "test")
W4 = #PRINTS
WHIT = AuctionLedger.Watch:For("4306").hit
""")
check("watch: alert for listings at or under the max (own ignored)",
      G.W1 == 1 and "5 listed" in G.PRINTS[1] and "1s 85c" in G.PRINTS[1], G.PRINTS[1])
check("watch: same price again within 10 min is quiet", G.W2 == 1)
check("watch: a cheaper listing alerts again", G.W3 == 2 and G.WHIT.price == 170)
check("watch: nothing under the max, no alert", G.W4 == 2)
lua.execute("""
WR1 = { AuctionLedger.Watch:Resolve("4306") }
WR2 = { AuctionLedger.Watch:Resolve("Silk Cloth") }
""")
check("watch: resolve by ID and by name", G.WR1[1] == 4306 and G.WR2[1] == 4306, (G.WR1[1], G.WR2[1]))

# 19. post suggestion
lua.execute("""
local scope = AuctionLedger:Scope()
AuctionLedger.db.prices[scope]["4306"] = { i = 4306, n = "Silk Cloth", mkt = 199, min = 150, minOther = 192, top = 201, qty = 100, t = NOW, h = {} }
SUG1 = AuctionLedger.Suggest(4306)
AuctionLedger.db.prices[scope]["4306"].minOther = 50
SUG2 = AuctionLedger.Suggest(4306)
AuctionLedger.db.prices[scope]["4306"].minOther = 192
SUG3 = AuctionLedger.Suggest(999999)
""")
check("suggest: undercut the cheapest other auction by 1c", G.SUG1.post == 191 and G.SUG1.advice == "post",
      (G.SUG1.post, G.SUG1.advice))
check("suggest: far-too-cheap competition -> normal price", G.SUG2.post == 201, G.SUG2.post)
check("suggest: no data -> no price", G.SUG3.post is None and G.SUG3.advice == "unknown", G.SUG3.advice)

# 20. guild/whisper upgrades
pq = lua.eval("function(q) return AuctionLedger.Guild.ParseQuery(q) end")
check("parse 'x20'", tuple(pq("Silk Cloth x20")) == ("Silk Cloth", 20) and tuple(pq("20 Silk Cloth")) == ("Silk Cloth", 20)
      and tuple(pq("Silk Cloth 20x")) == ("Silk Cloth", 20) and pq("Silk Cloth")[0] == "Silk Cloth" and pq("Silk Cloth")[1] is None,
      (pq("Silk Cloth 20x"), pq("Silk Cloth")))
lua.execute("""
AuctionLedger.db.settings.guildReply = true
AuctionLedger.Scanner.last = { t = NOW, items = { ["4306"] = { {100, 5, true}, {150, 10}, {190, 20} } } }
""")
G.SENT = lua.table()
guild("AH Silk Cloth x20", "Buyer")
G.RUNTIMERS()
check("guild: x20 prices the 20 cheapest (not your own)", len(sent()) == 1 and "x20 costs 34s now" in sent()[0], sent())
guild("AH help", "Newbie")
G.RUNTIMERS()
check("guild: AH help", len(sent()) == 2 and "AH <item> x20" in sent()[1], sent()[-1:])
G.NOW = G.NOW + 5
G.FIRE("CHAT_MSG_WHISPER", "AH Silk Cloth", "Friend")
G.RUNTIMERS()
check("whisper: replies to the sender", len(sent()) == 3 and sent()[2].startswith("WHISPER>Friend:[AL] [Silk Cloth]"), sent()[-1:])
G.NOW = G.NOW + 5
G.FIRE("CHAT_MSG_WHISPER", "AH Unobtainium Bar", "Friend")
G.RUNTIMERS()
check("whisper: unknown item says so", len(sent()) == 4 and "no AH data for 'Unobtainium Bar'" in sent()[3], sent()[-1:])
G.NOW = G.NOW + 5
G.FIRE("CHAT_MSG_WHISPER", "hey, want to group?", "Friend")
G.RUNTIMERS()
check("whisper: normal whispers are ignored", len(sent()) == 4)
lua.execute("AuctionLedger.db.settings.whisperReply = false")
G.NOW = G.NOW + 30
G.FIRE("CHAT_MSG_WHISPER", "AH Silk Cloth", "Friend")
G.RUNTIMERS()
check("whisper: off switch", len(sent()) == 4)
