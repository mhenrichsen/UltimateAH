"""Offline UI smoke test: load every addon file in TOC order against a permissive mock of the
WoW frame API, then build and refresh every page. Catches nil calls, typos and bad arithmetic
in UI code without the game running."""
import os
import sys

import lupa

ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "UltimateAH")

MOCK = r"""
NOW = 1795300000
function time(t) if t then return os.time(t) end return NOW end
date = os.date
function GetTime() return NOW end
function debugprofilestop() return os.clock() * 1000 end
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
StaticPopupDialogs = {}
function StaticPopup_Show() end
BreakUpLargeNumbers = function(n) return tostring(n) end
CALLS = 0

-- a widget: known getters return sensible values, every other method is a no-op returning nil
local VALUES = {
  GetFrameLevel = 1, GetWidth = 100, GetHeight = 20, GetStringWidth = 10, GetText = "", GetLeft = 0,
  GetEffectiveScale = 1, IsShown = false, IsVisible = false, HasFocus = false, IsEnabled = true,
  IsMouseOver = false, GetNumPoints = 1, GetChecked = false,
}
local FRAMEMT
local function widget()
  local o = { events = {}, scripts = {}, shown = false }
  return setmetatable(o, FRAMEMT)
end
FRAMEMT = { __index = function(t, k)
  if type(k) ~= "string" or not k:match("^%u") then return nil end
  if k == "RegisterEvent" then return function(self, e) self.events[e] = true end end
  if k == "UnregisterEvent" then return function(self, e) self.events[e] = nil end end
  if k == "SetScript" then return function(self, s, fn) self.scripts[s] = fn; if s == "OnEvent" then self.OnEvent = fn end end end
  if k == "HookScript" then return function(self, s, fn) self.scripts[s] = fn end end
  if k == "GetScript" then return function(self, s) return self.scripts[s] end end
  if k == "Show" then return function(self) self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end end
  if k == "Hide" then return function(self) self.shown = false end end
  if k == "SetShown" then return function(self, v) self.shown = v and true or false end end
  if k == "IsShown" or k == "IsVisible" then return function(self) return self.shown end end
  if k == "SetText" then return function(self, v) self.text = v end end
  if k == "GetText" then return function(self) return self.text or "" end end
  if k == "GetFont" then return function() return "Fonts\\ARIALN.TTF", 12 end end
  if k:match("^Create") then return function() CALLS = CALLS + 1; return widget() end end
  if k == "GetFontString" then return function() return widget() end end
  if VALUES[k] ~= nil then local v = VALUES[k]; return function() return v end end
  if k:match("^Get") then return function() return nil end end
  return function() CALLS = CALLS + 1 end
end }
FRAMES = {}
function CreateFrame() local f = widget(); FRAMES[#FRAMES + 1] = f; return f end
function CreateFont() return widget() end
UIParent, Minimap, GameTooltip, RaidWarningFrame = widget(), widget(), widget(), widget()
GameFontHighlight = widget()
function FIRE(e, ...)
  for _, f in ipairs(FRAMES) do if f.events[e] and f.OnEvent then f.OnEvent(f, e, ...) end end
end
TIMERS = {}
C_Timer = { After = function(s, fn) TIMERS[#TIMERS + 1] = fn end, NewTicker = function() return {} end }
function RUNTIMERS() for i = 1, 10 do local l = TIMERS; TIMERS = {}; if #l == 0 then return end; for _, fn in ipairs(l) do fn() end end end
function hooksecurefunc(t, name, fn)
  if type(t) == "string" then t, name, fn = _G, t, name end
  local orig = t[name] or function() end
  t[name] = function(...) local r = { orig(...) }; fn(...); return table.unpack(r) end
end
function ChatEdit_InsertLink() end
function IsModifiedClick() return false end
function IsShiftKeyDown() return false end
function GetCursorPosition() return 0, 0 end
function UnitName() return "Tess", "Bank" end
function GetRealmName() return "" end
function UnitFactionGroup() return "Alliance" end
function UnitClass() return "Warrior", "WARRIOR" end
function GetMoney() return 500000 end
function PlaySound() end
function RaidNotice_AddMessage() end
ITEM_QUALITY_COLORS = { [1] = { hex = "|cffffffff" } }
C_Item = {
  GetItemNameByID = function(id) return "Item " .. id end,
  GetItemInfo = function(id) return "Item " .. id, nil, 1, 1, 1, "x", "y", 20, "", 1, 50 end,
  GetItemIconByID = function() return 1 end,
  GetItemQualityByID = function() return 1 end,
  GetItemInfoInstant = function() return nil end,
}
BAG = { [0] = { [1] = { itemID = 4306, stackCount = 20, hyperlink = "|cffffffff|Hitem:4306::::::::1::::::|h[Silk Cloth]|h|r", quality = 1 } } }
C_Container = {
  GetContainerNumSlots = function(b) return BAG[b] and 4 or 0 end,
  GetContainerItemInfo = function(b, s) return BAG[b] and BAG[b][s] end,
  GetContainerNumFreeSlots = function() return 10 end,
  UseContainerItem = function() end,
}
Enum = { AuctionHouseSortOrder = { Price = 0 }, BagIndex = { Bank = -1 } }
C_AuctionHouse = setmetatable({}, { __index = function() return function() return nil end end })
C_AuctionHouse.GetOwnedAuctions = function() return {} end
function GetInboxNumItems() return 0 end
TooltipDataProcessor = { AddTooltipPostCall = function(_, fn) TOOLTIPFN = fn end }
Enum.TooltipDataType = { Item = 0 }
"""

lua = lupa.LuaRuntime(unpack_returned_tuples=True)
lua.execute(MOCK)
AL = lua.table()
toc = open(os.path.join(ADDON, "UltimateAH.toc"), encoding="utf-8").read().splitlines()
files = [l.strip() for l in toc if l.strip().endswith(".lua")]
loader = lua.eval("function(src, name) return assert(load(src, name)) end")
for f in files:
    loader(open(os.path.join(ADDON, f), encoding="utf-8").read(), "@" + f)("UltimateAH", AL)
G = lua.globals()
G.FIRE("ADDON_LOADED", "UltimateAH")
G.FIRE("PLAYER_LOGIN")
G.RUNTIMERS()

fails = 0


def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + (("  -- " + str(info)) if info else ""))
    if not cond:
        fails += 1


# some data so every page has rows
lua.execute("""
local A = UltimateAH
local scope = A:Scope()
A.db.prices[scope] = A.db.prices[scope] or {}
A.db.prices[scope]["4306"] = { i = 4306, n = "Silk Cloth", mkt = 199, min = 150, minOther = 160, top = 201, qty = 100, num = 9, t = NOW, h = { [20777] = { 200, 150 }, [20778] = { 199, 151 } } }
A:AddTx({ type = "buy", item = 4306, name = "Silk Cloth", qty = 20, unit = 190, total = 3800 })
A:AddTx({ type = "sell", item = 4306, name = "Silk Cloth", qty = 10, unit = 300, total = 3000, cut = 150 })
A:AddTx({ type = "sell", item = 4306, name = "Silk Cloth", qty = 5, unit = 300, total = 1500, provisional = true })
A.db.listings = { ["Tess Bank"] = { t = NOW, list = { { id = 4306, name = "Silk Cloth", qty = 20, buyout = 4000, left = 3600 }, { id = 4306, name = "Silk Cloth", qty = 5, buyout = 900, sold = true } } } }
A.Watch:Add(4306, "Silk Cloth", 170)
A.Watch:For("4306").hit = { t = NOW - 60, qty = 4, price = 160, source = "test" }
A.db.deals = { [scope] = { t = NOW, list = { { kind = "flip", key = "4306", item = 4306, name = "Silk Cloth", n = 2, qty = 30, cost = 3000, sellAt = 199, profit = 40000, ref = 201, low = 90, roi = 1.2, sure = true, auctions = 12, listed = 200, above = 8, days = 3 } } } }
""")

for tab in list(G.UltimateAH.UI.TAB_NAMES.values()):
    try:
        lua.execute("UltimateAH.UI:Toggle(%r)" % tab)
        lua.execute("UltimateAH.UI:Refresh()")
        errs = lua.eval("#UltimateAH.errors")
        check("page %s builds and refreshes" % tab, True)
    except Exception as e:  # noqa: BLE001
        check("page %s builds and refreshes" % tab, False, e)

lua.execute("ERRS = {} for _, e in ipairs(UltimateAH.errors or {}) do ERRS[#ERRS + 1] = tostring(e) end")
errs = [G.ERRS[i] for i in range(1, len(G.ERRS) + 1)]
check("no errors caught by the addon's own error handler", not errs, errs[:5])

for name, code in [
    ("price graph popup", "UltimateAH.UI:ShowPriceGraph('4306')"),
    ("AH side panel", "AuctionHouseFrame = CreateFrame(); UltimateAH.ahOpen = true; UltimateAH.UI:AttachToAH(); UltimateAH.UI:UpdateScanStatus()"),
    ("minimap button", "UltimateAH.UI.mmb = nil; UltimateAH.UI:MinimapButton()"),
    ("sidebar badges", "UltimateAH.UI:UpdateChrome()"),
    ("dropdown menu opens", "local d = UltimateAH.UI.vperiod; d.scripts.OnClick(d, 'LeftButton')"),
    ("dropdown right-click steps back", "local d = UltimateAH.UI.vperiod; d.scripts.OnClick(d, 'RightButton')"),
    ("toggle switch flips a setting", "local c = UltimateAH.UI.checks[1]; local before = UltimateAH.db.settings.tooltip; c.scripts.OnClick(c); assert(UltimateAH.db.settings.tooltip ~= before)"),
    ("table sort by header", "local t = UltimateAH.UI.ltable; t.headers[7].scripts.OnClick(); t.headers[7].scripts.OnClick()"),
    ("item tooltip lines", "local tt = CreateFrame(); GameTooltip = tt; tt.GetItem = function() return 'Silk Cloth', '|cffffffff|Hitem:4306::::::::1::::::|h[Silk Cloth]|h|r' end; TOOLTIPFN(tt, { id = 4306 })"),
    ("prices right-click -> watch", "UltimateAH.UI:Toggle('Prices'); UltimateAH.UI.ptable.onClick({ itemID = 4306, key = '4306' }, 'RightButton'); assert(UltimateAH.UI.current == 'Watch')"),
]:
    try:
        lua.execute(code)
        check(name, True)
    except Exception as e:  # noqa: BLE001
        check(name, False, e)

lua.execute("ERRS = {} for _, e in ipairs(UltimateAH.errors or {}) do ERRS[#ERRS + 1] = tostring(e) end")
errs = [G.ERRS[i] for i in range(1, len(G.ERRS) + 1)]
check("still no handler errors", not errs, errs[:5])
print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
