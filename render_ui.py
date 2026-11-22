"""Offline renderer for UltimateAH's UI.

Runs the addon (TOC order) against a mock of the WoW frame API that records every region's
anchors, size, colours, textures and text, resolves the layout like the client does, and draws it
to PNGs - one per page - so the UI can be reviewed without the game running.

  python render_ui.py [outdir] [page ...]

Approximations: Arial squeezed to 82% width stands in for Arial Narrow; item icons are flat tiles;
no hover/highlight state; coin icons are coloured dots.
"""
import os
import re
import sys

import lupa
from PIL import Image, ImageDraw, ImageFont

ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "UltimateAH")
HERE = os.path.dirname(os.path.abspath(__file__))
SCREEN_W, SCREEN_H = 1600, 900
S = 1.5                      # pixels per UI unit
NARROW = 0.82                # Arial Narrow ~ 82% of Arial's width

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
SlashCmdList, UISpecialFrames, StaticPopupDialogs = {}, {}, {}
function StaticPopup_Show() end
BreakUpLargeNumbers = function(n)
  local s = tostring(math.floor(n))
  local out = s:reverse():gsub("(%d%d%d)", "%1,"):reverse()
  return (out:gsub("^,", ""))
end

OBJS = {}
local M = {}
local MT = { __index = function(t, k)
  local m = M[k]
  if m then return m end
  if type(k) ~= "string" or not k:match("^%u") then return nil end
  if k:match("^Get") or k:match("^Is") or k:match("^Has") then return function() return nil end end
  return function() end
end }
local function new(kind, parent)
  local o = setmetatable({ kind = kind, parent = parent, points = {}, npoints = 0, shown = true, scripts = {},
                           events = {}, alpha = 1, enabled = true, wrap = true }, MT)
  OBJS[#OBJS + 1] = o
  o.idx = #OBJS
  return o
end
NEW = new

function M:SetPoint(p, rel, rp, x, y)
  if type(rel) == "number" then rel, rp, x, y = nil, nil, rel, rp
  elseif type(rp) == "number" then rp, x, y = nil, rp, x end
  if type(rel) == "string" then rel = _G[rel] end
  if not self.points[p] then self.npoints = self.npoints + 1 end
  self.points[p] = { p, rel or false, rp or p, x or 0, y or 0 }
  self.all = nil
end
function M:ClearAllPoints() self.points = {}; self.npoints = 0; self.all = nil end
function M:SetAllPoints(rel) self.all = rel or false end
function M:SetSize(w, h) self.w, self.h = w, h end
function M:SetWidth(w) self.w = w end
function M:SetHeight(h) self.h = h end
function M:GetWidth() return self.w or 100 end
function M:GetHeight() return self.h or 20 end
function M:Show() self.shown = true; if self.scripts.OnShow then self.scripts.OnShow(self) end end
function M:Hide() if self.shown and self.scripts.OnHide then self.shown = false; self.scripts.OnHide(self) end; self.shown = false end
function M:SetShown(v) if v then self:Show() else self:Hide() end end
function M:IsShown() return self.shown end
function M:IsVisible() local o = self; while o do if not o.shown then return false end; o = o.parent end; return true end
function M:SetAlpha(a) self.alpha = a end
function M:SetColorTexture(r, g, b, a) self.color = { r, g, b, a or 1 }; self.tex = nil end
function M:SetTexture(t) self.tex = t; self.color = nil end
function M:SetVertexColor(r, g, b, a) self.vcolor = { r, g, b, a or 1 } end
function M:SetDesaturated(v) self.desat = v end
function M:AddMaskTexture() self.circle = true end
function M:SetText(t)
  if self.fs then self.fs.text = t end
  self.text = t
  -- like the game: setting an edit box's text tells its OnTextChanged script
  if self.kind == "EditBox" and self.scripts and self.scripts.OnTextChanged then self.scripts.OnTextChanged(self, false) end
end
function M:GetText() return self.text or "" end
function M:SetFormattedText(f, ...) self:SetText(string.format(f, ...)) end
function M:SetFontObject(f) self.font = f end
function M:SetFont(path, size, flags) self.fpath, self.fsize = path, size; return true end
function M:GetFont() return self.fpath or "Fonts\\ARIALN.TTF", self.fsize or 12 end
function M:SetTextColor(r, g, b, a) self.tcolor = { r, g, b, a or 1 } end
function M:SetJustifyH(j) self.jh = j end
function M:SetJustifyV(j) self.jv = j end
function M:SetWordWrap(v) self.wrap = v end
function M:SetTextInsets(l, r) self.insetL, self.insetR = l, r end
function M:GetStringWidth() return MEASURE(self) end
function M:SetFrameLevel(n) self.level = n end
function M:GetFrameLevel() if self.level then return self.level end; return self.parent and (self.parent:GetFrameLevel() + 1) or 0 end
function M:SetFrameStrata(s) self.strata = s end
function M:SetStartPoint(p, rel, x, y) self.sp = { p, rel, x or 0, y or 0 } end
function M:SetEndPoint(p, rel, x, y) self.ep = { p, rel, x or 0, y or 0 } end
function M:SetThickness(t) self.thick = t end
function M:SetFontString(fs) self.fs = fs end
function M:GetFontString() return self.fs end
function M:SetNormalFontObject(f) self.nfont = f end
function M:SetDisabledFontObject(f) self.dfont = f end
function M:SetEnabled(v) self.enabled = v and true or false; local s = self.scripts[v and "OnEnable" or "OnDisable"]; if s then s(self) end end
function M:Enable() self:SetEnabled(true) end
function M:Disable() self:SetEnabled(false) end
function M:IsEnabled() return self.enabled end
function M:SetChecked(v) self.checked = v end
function M:GetChecked() return self.checked end
function M:SetScript(s, fn) self.scripts[s] = fn; if s == "OnEvent" then self.OnEvent = fn end end
function M:HookScript(s, fn)
  local old = self.scripts[s]
  self.scripts[s] = old and function(...) old(...); fn(...) end or fn
end
function M:GetScript(s) return self.scripts[s] end
function M:RegisterEvent(e) self.events[e] = true end
function M:UnregisterEvent(e) self.events[e] = nil end
function M:CreateTexture(_, layer, _, sub) local t = new("Texture", self); t.layer = layer or "ARTWORK"; t.sub = sub or 0; return t end
function M:CreateFontString(_, layer, font) local t = new("FontString", self); t.layer = layer or "ARTWORK"; t.sub = 0; t.font = font; return t end
function M:CreateLine(_, layer) local t = new("Line", self); t.layer = layer or "ARTWORK"; t.sub = 0; return t end
function M:CreateMaskTexture() local t = new("Mask", self); return t end
function M:SetThumbTexture(t) if type(t) == "table" then t:ClearAllPoints(); t:SetPoint("TOP", self, "TOP", 0, 0) end end
function M:GetFrameStrata() return self.strata or (self.parent and self.parent:GetFrameStrata()) or "MEDIUM" end
function M:GetEffectiveScale() return 1 end
function M:HasFocus() return false end

FRAMES = {}
FONTS = {}
function CreateFrame(kind, name, parent)
  local f = new(kind or "Frame", parent or UIParent)
  if name then _G[name] = f end
  FRAMES[#FRAMES + 1] = f
  return f
end
function CreateFont(name) local f = new("Font", nil); f.shown = false; FONTS[name] = f; _G[name] = f; return f end
UIParent = new("Frame", nil); UIParent.root = true
Minimap = CreateFrame("Frame", nil, UIParent); Minimap:SetSize(140, 140); Minimap:SetPoint("TOPRIGHT", -20, -20); Minimap.shown = false
GameTooltip = CreateFrame("Frame"); GameTooltip.shown = false
RaidWarningFrame = CreateFrame("Frame")
GameFontHighlight = CreateFont("GameFontHighlight"); GameFontHighlight:SetFont("Fonts\\FRIZQT__.TTF", 12)
function FIRE(e, ...) for _, f in ipairs(FRAMES) do if f.events[e] and f.OnEvent then f.OnEvent(f, e, ...) end end end
TIMERS = {}
C_Timer = { After = function(s, fn) TIMERS[#TIMERS + 1] = fn end, NewTicker = function() return {} end }
function RUNTIMERS() for i = 1, 10 do local l = TIMERS; TIMERS = {}; if #l == 0 then return end; for _, fn in ipairs(l) do pcall(fn) end end end
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
function GetMoney() return 12345678 end
function PlaySound() end
function RaidNotice_AddMessage() end
RAID_CLASS_COLORS = { WARRIOR = { r = 0.78, g = 0.61, b = 0.43 }, SHAMAN = { r = 0, g = 0.44, b = 0.87 }, MAGE = { r = 0.25, g = 0.78, b = 0.92 } }
ITEM_QUALITY_COLORS = { [0] = { hex = "|cff9d9d9d" }, [1] = { hex = "|cffffffff" }, [2] = { hex = "|cff1eff00" }, [3] = { hex = "|cff0070dd" }, [4] = { hex = "|cffa335ee" } }
NAMES = { [4306] = "Silk Cloth", [12359] = "Thorium Bar", [12360] = "Arcanite Bar", [14047] = "Runecloth", [8170] = "Rugged Leather",
          [13463] = "Dreamfoil", [13464] = "Golden Sansam", [7078] = "Essence of Fire", [12811] = "Righteous Orb", [11382] = "Blood of the Mountain",
          [16203] = "Greater Eternal Essence", [14344] = "Large Brilliant Shard", [3577] = "Gold Bar", [2589] = "Linen Cloth", [4338] = "Mageweave Cloth",
          [11991] = "Quicksilver Ring", [9999] = "Black Mageweave Leggings", [2770] = "Copper Ore", [10620] = "Thorium Ore", [8831] = "Purple Lotus" }
QUAL = { [12360] = 2, [12811] = 2, [11382] = 2, [16203] = 2, [14344] = 3, [11991] = 2, [9999] = 2, [2589] = 1 }
C_Item = {
  GetItemNameByID = function(id) return NAMES[id] or ("Item " .. id) end,
  GetItemInfo = function(id) return NAMES[id], nil, QUAL[id] or 1, 1, 1, "x", "y", 20, "", 1, (id % 7) * 120 end,
  GetItemIconByID = function(id) return id end,
  GetItemQualityByID = function(id) return QUAL[id] or 1 end,
  GetItemInfoInstant = function() return nil end,
}
BAG = { [0] = {}, [1] = {} }
C_Container = {
  GetContainerNumSlots = function(b) return BAG[b] and 16 or 0 end,
  GetContainerItemInfo = function(b, s) return BAG[b] and BAG[b][s] end,
  GetContainerNumFreeSlots = function() return 10 end,
  UseContainerItem = function() end,
}
Enum = { AuctionHouseSortOrder = { Price = 0 }, BagIndex = { Bank = -1 }, TooltipDataType = { Item = 0 } }
C_AuctionHouse = setmetatable({}, { __index = function() return function() return nil end end })
C_AuctionHouse.GetOwnedAuctions = function() return {} end
function GetInboxNumItems() return 0 end
TooltipDataProcessor = { AddTooltipPostCall = function(_, fn) TOOLTIPFN = fn end }
"""

DATA = r"""
local A = UltimateAH
local scope = A:Scope()
math.randomseed(7)
local ids = {}
for id in pairs(NAMES) do ids[#ids + 1] = id end
table.sort(ids)
local base = { [4306] = 210, [12359] = 9800, [12360] = 444597, [14047] = 3150, [8170] = 2400, [13463] = 15500, [13464] = 9200,
  [7078] = 31000, [12811] = 52000, [11382] = 48000, [16203] = 98000, [14344] = 61000, [3577] = 5200, [2589] = 45, [4338] = 1450,
  [11991] = 260000, [9999] = 41000, [2770] = 190, [10620] = 3900, [8831] = 6100 }
A.db.prices[scope] = {}
for _, id in ipairs(ids) do
  local b = base[id]
  local h = {}
  for d = 0, 20 do h[20777 - d] = { math.floor(b * (0.9 + 0.2 * math.random())), math.floor(b * (0.8 + 0.15 * math.random())) } end
  A.db.prices[scope][tostring(id)] = { i = id, n = NAMES[id], mkt = b, min = math.floor(b * 0.93), minOther = math.floor(b * 0.95),
    top = math.floor(b * 1.02), qty = math.random(5, 3000), num = math.random(3, 120), t = NOW - math.random(60, 7200), h = h,
    sold = b > 50000 and math.random() * 6 or (b > 5000 and math.random(8, 90) or math.random(200, 4000)), soldT = NOW - 1800 }
end
A.db.prices[scope]["12360"].sold = 0
-- price patterns, as the server scan's history gives them: days, position in the range, trend, weekdays, hours, forecast
local trends = { -22, -8, 0, 0, 4, 12, 31, 0, -14, 6 }
for n, id in ipairs(ids) do
  local e = A.db.prices[scope][tostring(id)]
  local tr = trends[(n - 1) % #trends + 1]
  e.ins = { 30, math.random(5, 95), tr, -1, 0, -1, 0, -1, -1, 0, -1, 0, 0, 0, 0 }
  e.insT = NOW - 1800
end
A.db.prices[scope]["12360"].ins = { 30, 92, 14, 1, -6, 5, 9, 3, 19, 8, 20, 455000, 447000, 431000, 472000 }
A.db.prices[scope]["4306"].ins = { 30, 12, -22, 2, -7, 6, 11, 4, 20, 12, 21, 195, 207, 180, 215 }
A.db.prices[scope]["4306"].minOther = 180
A.db.prices[scope]["12360"].minOther = 401000
A.db.chars = {
  ["Tess Bank"] = { name = "Tess Bank", money = 12345678, class = "WARRIOR", t = NOW },
  ["Alma Farmer"] = { name = "Alma Farmer", money = 4815162, class = "SHAMAN", t = NOW - 3600 },
  ["Otto Bank"] = { name = "Otto Bank", money = 999000, class = "MAGE", t = NOW - 86400 },
}
A.db.tx = {}
local types = { "buy", "sell", "sell", "post", "post", "cancel", "expired", "sell" }
local chars = { "Tess Bank", "Alma Farmer", "Otto Bank" }
for i = 1, 60 do
  local id = ids[(i * 7) % #ids + 1]
  local ty = types[i % #types + 1]
  local q = ({ 1, 5, 20, 1, 10 })[i % 5 + 1]
  local unit = math.floor(base[id] * (0.85 + 0.3 * math.random()))
  A.db.tx[#A.db.tx + 1] = { t = NOW - i * 5200, char = chars[i % 3 + 1], type = ty, item = id, name = NAMES[id], qty = q, unit = unit,
    total = unit * q, cut = ty == "sell" and math.floor(unit * q * 0.05) or nil, deposit = ty == "post" and 150 or nil,
    provisional = (ty == "sell" and i < 8) or nil, buyer = ty == "sell" and "Somebody" or nil, src = "ah" }
end
table.sort(A.db.tx, function(a, b) return a.t < b.t end)
A.db.value = {}
for ci, c in ipairs(chars) do
  local list = {}
  local g, it = 2000000 * ci, 5000000 / ci
  for k = 0, 120 do
    g = g * (0.99 + 0.025 * math.random()); it = it * (0.985 + 0.03 * math.random())
    list[#list + 1] = { NOW - (120 - k) * 6 * 3600, math.floor(g), math.floor(it) }
  end
  A.db.value[c] = list
end
A.db.inv = {}
for ci, c in ipairs(chars) do
  local bags, bank = {}, {}
  for k = 1, 9 do local id = ids[(k * 3 + ci) % #ids + 1]; bags[tostring(id)] = { id, (k * 7) % 40 + 1 } end
  for k = 1, 6 do local id = ids[(k * 5 + ci) % #ids + 1]; bank[tostring(id)] = { id, (k * 11) % 60 + 1 } end
  A.db.inv[c] = { bags = bags, bank = bank, bankT = NOW - ci * 86400, mail = {}, mailMoney = 0 }
end
for k = 1, 9 do
  local id = ids[(k * 3 + 1) % #ids + 1]
  BAG[0][k] = { itemID = id, stackCount = (k * 7) % 40 + 1, hyperlink = "|cffffffff|Hitem:" .. id .. "::::::::1::::::|h[" .. NAMES[id] .. "]|h|r", quality = QUAL[id] or 1 }
end
BAG[0][10] = { itemID = 2589, stackCount = 3, quality = 0, hyperlink = "|cff9d9d9d|Hitem:2589::::::::1::::::|h[Linen Cloth]|h|r" }
for k = 1, 8 do
  local id = ids[(k * 5 + 2) % #ids + 1]
  BAG[1][k] = { itemID = id, stackCount = (k * 13) % 60 + 2, hyperlink = "|cffffffff|Hitem:" .. id .. "::::::::1::::::|h[" .. NAMES[id] .. "]|h|r", quality = QUAL[id] or 1 }
end
-- posting from the Sell page
ItemLocation = { CreateFromBagAndSlot = function(_, b, s) return { b = b, s = s } end }
C_AuctionHouse.GetItemCommodityStatus = function() return 2 end
C_AuctionHouse.CalculateCommodityDeposit = function(_, duration, qty) return 35 * duration * qty end
C_AuctionHouse.IsThrottledMessageSystemReady = function() return true end
function SELL_DEMO()
  A.ahOpen = true
  for key, e in pairs(A.db.prices[scope]) do
    local b = e.minOther or e.min
    A.Sell.live[key] = { t = NOW - 40, list = { { b, 240 }, { math.floor(b * 1.004), 1200 }, { math.floor(b * 0.97), 60, true },
                                               { math.floor(b * 1.02), 900 }, { math.floor(b * 1.05), 3100 } } }
  end
end
A.db.listings = {
  ["Tess Bank"] = { t = NOW - 1800, list = {
    { id = 4306, name = "Silk Cloth", qty = 20, buyout = 4000, left = 40000 },
    { id = 12360, name = "Arcanite Bar", qty = 1, buyout = 439000, left = 80000 },
    { id = 14047, name = "Runecloth", qty = 20, buyout = 61000, left = 9000 },
    { id = 13463, name = "Dreamfoil", qty = 5, buyout = 75000, sold = true },
  } },
  ["Alma Farmer"] = { t = NOW - 7200, list = {
    { id = 7078, name = "Essence of Fire", qty = 2, buyout = 61000, left = 120000 },
    { id = 16203, name = "Greater Eternal Essence", qty = 1, buyout = 99000, left = 30000 },
  } },
}
A.db.watch = {}
A.Watch:Add(12360, "Arcanite Bar", 400000)
A.Watch:Add(14344, "Large Brilliant Shard", 50000)
A.Watch:Add(8831, "Purple Lotus", 5000)
A.Watch:For("12360").hit = { t = NOW - 300, qty = 3, price = 395000, source = "full scan" }
A.db.scans[scope] = { t = NOW - 600, kind = "full", items = 11873 }
local deals = {}
for k = 1, 14 do
  local id = ids[(k * 5) % #ids + 1]
  local ref = base[id]
  local q = (k % 4) + 1
  local cost = math.floor(ref * 0.5) * q
  local relist = math.floor(ref * 0.97)
  local profit = math.floor(relist * q * 0.95 - cost)
  deals[#deals + 1] = { kind = k % 6 == 0 and "vendor" or "flip", key = tostring(id), item = id, name = NAMES[id], n = q, qty = q * 5,
    cost = cost, sellAt = relist, profit = profit, ref = ref, low = math.floor(ref * 0.5), roi = profit / cost, sure = k % 3 ~= 0,
    auctions = 30, listed = 200, above = 12, days = 5 }
end
table.sort(deals, function(a, b) return a.profit > b.profit end)
A.db.deals = { [scope] = { t = NOW - 600, list = deals } }
"""

lua = lupa.LuaRuntime(unpack_returned_tuples=True)

# --- fonts ----------------------------------------------------------------
_fonts = {}


def pil_font(size):
    size = max(6, int(round(size * S)))
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", size)
    return _fonts[size]


COIN = {"Gold": (255, 210, 80), "Silver": (200, 205, 215), "Copper": (215, 130, 75)}


def parse_markup(text, base):
    """-> list of (string, rgb or None for base, kind) ; kind 'text' or 'coin'"""
    out = []
    color = None
    i = 0
    buf = ""
    t = text

    def flush():
        nonlocal buf
        if buf:
            out.append((buf, color, "text"))
            buf = ""
    while i < len(t):
        if t.startswith("||", i):
            buf += "|"; i += 2; continue
        if t.startswith("|c", i) and len(t) >= i + 10:
            flush()
            h = t[i + 4:i + 10]
            try:
                color = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            except ValueError:
                color = None
            i += 10; continue
        if t.startswith("|r", i):
            flush(); color = None; i += 2; continue
        if t.startswith("|T", i):
            flush()
            j = t.find("|t", i)
            path = t[i + 2:j if j > 0 else len(t)]
            kind = next((k for k in COIN if k in path), None)
            out.append(("o", COIN.get(kind, (150, 150, 150)), "coin"))
            i = (j + 2) if j > 0 else len(t); continue
        if t.startswith("|H", i):
            j = t.find("|h", i)
            i = j + 2 if j > 0 else len(t); continue
        if t.startswith("|h", i):
            i += 2; continue
        buf += t[i]; i += 1
    flush()
    return out


def seg_width(segs, font):
    w = 0
    for s, _, kind in segs:
        if kind == "coin":
            w += font.size * 0.85
        else:
            w += font.getlength(s) * NARROW
    return w


def font_info(o, fonts):
    """-> (size, rgb) for a FontString / EditBox"""
    f = o["font"]
    fobj = None
    if isinstance(f, str):
        fobj = fonts.get(f)
    elif f is not None:
        fobj = f
    size, color = 12, (255, 255, 255)
    if fobj is not None:
        size = fobj["fsize"] or 12
        tc = fobj["tcolor"]
        if tc:
            color = tuple(int(tc[i] * 255) for i in (1, 2, 3))
    if o["fsize"]:
        size = o["fsize"]
    tc = o["tcolor"]
    if tc:
        color = tuple(int(tc[i] * 255) for i in (1, 2, 3))
    return size, color


# --- layout ---------------------------------------------------------------
H_OF = {"TOPLEFT": 0, "LEFT": 0, "BOTTOMLEFT": 0, "TOP": .5, "CENTER": .5, "BOTTOM": .5,
        "TOPRIGHT": 1, "RIGHT": 1, "BOTTOMRIGHT": 1}
V_OF = {"TOPLEFT": 0, "TOP": 0, "TOPRIGHT": 0, "LEFT": .5, "CENTER": .5, "RIGHT": .5,
        "BOTTOMLEFT": 1, "BOTTOM": 1, "BOTTOMRIGHT": 1}


class Layout:
    def __init__(self, objs, fonts):
        self.objs = objs
        self.fonts = fonts
        self.memo = {}

    def text_w(self, o):
        size, _ = font_info(o, self.fonts)
        return seg_width(parse_markup(str(o["text"] or ""), None), pil_font(size)) / S

    def rect(self, o):
        key = o["idx"]
        if key in self.memo:
            return self.memo[key]
        self.memo[key] = None             # cycle guard
        r = self._rect(o)
        self.memo[key] = r
        return r

    def relrect(self, o, rel):
        if rel is False or rel is None:
            rel = o["parent"]
        if rel is None:
            return (0, 0, SCREEN_W, SCREEN_H)
        return self.rect(rel)

    def _rect(self, o):
        if o["root"]:
            return (0, 0, SCREEN_W, SCREEN_H)
        if o["all"] is not None:
            return self.relrect(o, o["all"])
        pts = o["points"]
        if not pts or not o["npoints"]:
            return None
        L = R = T = B = CX = CY = None
        for p in pts.values():
            point, rel, rp, x, y = p[1], p[2], p[3], p[4], p[5]
            rr = self.relrect(o, rel)
            if rr is None:
                return None
            ax = rr[0] + (rr[2] - rr[0]) * H_OF[rp] + x
            ay = rr[1] + (rr[3] - rr[1]) * V_OF[rp] - y
            h, v = H_OF[point], V_OF[point]
            if h == 0: L = ax
            elif h == 1: R = ax
            else: CX = ax
            if v == 0: T = ay
            elif v == 1: B = ay
            else: CY = ay
        w, hgt = o["w"], o["h"]
        if o["kind"] == "FontString":
            if w is None or w == 0:
                w = None if (L is not None and R is not None) else self.text_w(o)
            if hgt is None or hgt == 0:
                size, _ = font_info(o, self.fonts)
                hgt = size * 1.25
                ww = w if w is not None else ((R - L) if (L is not None and R is not None) else None)
                if ww and o["wrap"] is not False and o["text"]:
                    segs = parse_markup(str(o["text"]), None)
                    font = pil_font(size)
                    if seg_width(segs, font) > ww * S + 2:
                        hgt = size * 1.22 * len(wrap(segs, font, ww * S))
        w = w if w is not None else 0
        hgt = hgt if hgt is not None else 0
        if L is None and R is None:
            L = (CX if CX is not None else 0) - w / 2; R = L + w
        elif L is None:
            L = R - w
        elif R is None:
            R = L + w
        if T is None and B is None:
            T = (CY if CY is not None else 0) - hgt / 2; B = T + hgt
        elif T is None:
            T = B - hgt
        elif B is None:
            B = T + hgt
        return (L, T, R, B)


LAYERS = {"BACKGROUND": 0, "BORDER": 1, "ARTWORK": 2, "OVERLAY": 3, "HIGHLIGHT": 9}
STRATA = {"BACKGROUND": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "DIALOG": 4, "FULLSCREEN": 5, "FULLSCREEN_DIALOG": 6, "TOOLTIP": 7}


def visible(o):
    while o is not None:
        if not o["shown"]:
            return False
        o = o["parent"]
    return True


def strata(o):
    while o is not None:
        if o["strata"]:
            return o["strata"]
        o = o["parent"]
    return "MEDIUM"


def level(o):
    if o["level"] is not None:
        return o["level"]
    p = o["parent"]
    return 0 if p is None else level(p) + 1


def render(path, crop=None):
    objs = [lua.globals().OBJS[i] for i in range(1, len(lua.globals().OBJS) + 1)]
    fonts = {k: v for k, v in lua.globals().FONTS.items()}
    lay = Layout(objs, fonts)
    items = []
    for o in objs:
        k = o["kind"]
        if k not in ("Texture", "FontString", "Line", "EditBox", "Button"):
            continue
        if k in ("EditBox",):
            pass
        if k == "Button":
            continue
        if not visible(o) or o["layer"] == "HIGHLIGHT":
            continue
        frame = o["parent"]
        items.append(((STRATA.get(strata(frame), 2), level(frame), LAYERS.get(o["layer"] or "ARTWORK", 2),
                       o["sub"] or 0, o["idx"]), o))
    # edit box text
    for o in objs:
        if o["kind"] == "EditBox" and visible(o) and o["text"]:
            items.append(((STRATA.get(strata(o), 2), level(o), 3, 5, o["idx"]), o))
    items.sort(key=lambda x: x[0])
    if os.environ.get("AL_RECT"):             # debugging aid: where did these objects (idx) end up?
        want = {int(x) for x in os.environ["AL_RECT"].split(",")}
        for pos, (key, o) in enumerate(items):
            if o["idx"] in want:
                print("obj", o["idx"], o["kind"], "order", pos, "of", len(items), "key", key, "rect", lay.rect(o))
        for o in objs:
            if o["idx"] in want and o["kind"] not in ("Texture", "FontString", "Line"):
                print("obj", o["idx"], o["kind"], "rect", lay.rect(o), "visible", visible(o))
                pts = o["points"]
                print("   bool(pts)", bool(pts), "npoints", o["npoints"], "all", o["all"], "root", o["root"], "w/h", o["w"], o["h"])
                for p in pts.values():
                    print("   point", [p[i] if i != 2 else (p[i] if p[i] in (False, None) else p[i]["idx"]) for i in range(1, 6)])
    img = Image.new("RGB", (int(SCREEN_W * S), int(SCREEN_H * S)), (40, 44, 52))
    d = ImageDraw.Draw(img, "RGBA")
    for _, o in items:
        k = o["kind"]
        alpha = 1.0
        q = o
        while q is not None:
            alpha *= q["alpha"] or 1
            q = q["parent"]
        if k == "Line":
            pts = []
            for sp in (o["sp"], o["ep"]):
                if not sp:
                    break
                rr = lay.rect(sp[2]) if sp[2] else lay.rect(o["parent"])
                if not rr:
                    break
                pts.append((rr[0] + (rr[2] - rr[0]) * H_OF[sp[1]] + sp[3], rr[1] + (rr[3] - rr[1]) * V_OF[sp[1]] - sp[4]))
            c = o["color"]
            if len(pts) == 2 and c:
                col = tuple(int(c[i] * 255) for i in (1, 2, 3)) + (int(c[4] * 255 * alpha),)
                d.line([(x * S, y * S) for x, y in pts], fill=col, width=max(1, int(round((o["thick"] or 1) * S))))
            continue
        r = lay.rect(o)
        if not r:
            continue
        x0, y0, x1, y1 = (v * S for v in r)
        if k == "Texture":
            c = o["color"]
            vc = o["vcolor"]
            if c:
                col = [c[1], c[2], c[3], c[4]]
            elif o["tex"] is not None:
                col = [0.45, 0.42, 0.36, 1] if not o["desat"] else [0.4, 0.4, 0.4, 1]
            else:
                continue
            if vc:
                col = [col[0] * vc[1], col[1] * vc[2], col[2] * vc[3], col[3] * vc[4]]
            fill = tuple(int(v * 255) for v in col[:3]) + (int(col[3] * 255 * alpha),)
            if x1 - x0 < 0.5 or y1 - y0 < 0.5:
                continue
            if o["circle"]:
                d.ellipse([x0, y0, x1, y1], fill=fill)
            elif o["tex"] is not None and not c and str(o["tex"]).lower().endswith("ultimateah\\logo"):
                logo = Image.open(os.path.join(HERE, "media", "logo.png")).convert("RGBA")
                logo = logo.resize((max(1, int(round(x1 - x0))), max(1, int(round(y1 - y0)))), Image.LANCZOS)
                img.paste(logo, (int(round(x0)), int(round(y0))), logo)
            elif o["tex"] is not None and not c:
                d.rectangle([x0, y0, x1, y1], fill=fill)
                d.rectangle([x0 + 2, y0 + 2, x1 - 2, y1 - 2], outline=(255, 255, 255, 40))
            else:
                d.rectangle([x0, y0, x1 - 1 if x1 - x0 > 1 else x1, y1 - 1 if y1 - y0 > 1 else y1], fill=fill)
            continue
        # text
        text = str(o["text"] or "")
        if not text:
            continue
        size, base = font_info(o, fonts)
        if k == "EditBox":
            x0 += (o["insetL"] or 0) * S
        font = pil_font(size)
        segs = parse_markup(text, base)
        boxw = x1 - x0
        lines = [segs]
        tw = seg_width(segs, font)
        if tw > boxw + 2 and boxw > 4:
            if o["wrap"] is not False and k == "FontString":
                lines = wrap(segs, font, boxw)
            else:
                lines = [truncate(segs, font, boxw)]
        lh = size * 1.22 * S
        total_h = lh * len(lines)
        jv = o["jv"] or "MIDDLE"
        if jv == "TOP":
            ty = y0
        elif jv == "BOTTOM":
            ty = y1 - total_h
        else:
            ty = (y0 + y1) / 2 - total_h / 2
        for line in lines:
            lw = seg_width(line, font)
            jh = o["jh"] or "CENTER"
            if k == "EditBox":
                jh = "LEFT"
            if jh == "LEFT":
                tx = x0
            elif jh == "RIGHT":
                tx = x1 - lw
            else:
                tx = (x0 + x1) / 2 - lw / 2
            draw_line(img, d, line, font, tx, ty, base, alpha)
            ty += lh
    if crop:
        img = img.crop(tuple(int(v * S) for v in crop))
    img.convert("RGB").save(path)


def wrap(segs, font, boxw):
    words = []
    for s, c, kind in segs:
        if kind == "coin":
            words.append([(s, c, kind)])
            continue
        parts = re.split(r"(\s+)", s)
        for p in parts:
            if p:
                words.append([(p, c, kind)])
    lines, cur, cw = [], [], 0
    for w in words:
        ww = seg_width(w, font)
        if cw + ww > boxw and cur:
            lines.append(cur); cur, cw = [], 0
            if w[0][0].isspace():
                continue
        cur += w; cw += ww
    if cur:
        lines.append(cur)
    return lines


def truncate(segs, font, boxw):
    out, w = [], 0
    ell = font.getlength("...") * NARROW
    for s, c, kind in segs:
        sw = seg_width([(s, c, kind)], font)
        if w + sw <= boxw - ell:
            out.append((s, c, kind)); w += sw; continue
        if kind == "text":
            acc = ""
            for ch in s:
                if w + seg_width([(acc + ch, c, kind)], font) > boxw - ell:
                    break
                acc += ch
            out.append((acc + "...", c, kind))
        break
    return out


def draw_line(img, d, segs, font, x, y, base, alpha):
    for s, c, kind in segs:
        col = c or base
        if kind == "coin":
            r = font.size * 0.32
            cx, cy = x + font.size * 0.42, y + font.size * 0.62
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col + (255,))
            x += font.size * 0.85
            continue
        w = int(font.getlength(s)) + 4
        hgt = int(font.size * 1.4)
        tmp = Image.new("RGBA", (max(1, w), hgt), (0, 0, 0, 0))
        td = ImageDraw.Draw(tmp)
        td.text((0, 0), s, font=font, fill=tuple(col) + (int(255 * alpha),))
        nw = max(1, int(w * NARROW))
        tmp = tmp.resize((nw, hgt), Image.LANCZOS)
        img.paste(tmp, (int(x), int(y)), tmp)
        x += font.getlength(s) * NARROW


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "renders")
    pages = sys.argv[2:]
    os.makedirs(outdir, exist_ok=True)
    lua.execute(MOCK)
    G = lua.globals()

    def measure(o):
        size = 12
        f = o.font
        if isinstance(f, str) and G.FONTS[f]:
            size = G.FONTS[f].fsize or 12
        return seg_width(parse_markup(str(o.text or ""), None), pil_font(size)) / S
    G.MEASURE = measure
    AL = lua.table()
    G.UltimateAH = AL
    toc = open(os.path.join(ADDON, "UltimateAH.toc"), encoding="utf-8").read().splitlines()
    loader = lua.eval("function(src, name) return assert(load(src, name)) end")
    for f in [l.strip() for l in toc if l.strip().endswith(".lua")]:
        loader(open(os.path.join(ADDON, f), encoding="utf-8").read(), "@" + f)("UltimateAH", AL)
    G.FIRE("ADDON_LOADED", "UltimateAH")
    G.FIRE("PLAYER_LOGIN")
    G.RUNTIMERS()
    lua.execute(DATA)
    lua.execute("UltimateAH.db.settings.pos = nil")
    names = pages or list(AL.UI.TAB_NAMES.values())
    fw, fh = 1190, 680
    crop = ((SCREEN_W - fw) / 2 - 20, (SCREEN_H - fh) / 2 - 20, (SCREEN_W + fw) / 2 + 20, (SCREEN_H + fh) / 2 + 20)
    for n in names:
        if n == "PriceGraph":
            lua.execute("UltimateAH.UI:Toggle('Prices'); UltimateAH.UI:ShowPriceGraph('12360')")
        elif n == "AHPanel":
            lua.execute("AuctionHouseFrame = CreateFrame('Frame'); AuctionHouseFrame:SetSize(800, 520); AuctionHouseFrame:SetPoint('CENTER', -150, 0)"
                        " ; UltimateAH.ahOpen = true; UltimateAH.UI:AttachToAH(); UltimateAH.UI:UpdateScanStatus()"
                        " ; if UltimateAH.UI.frame then UltimateAH.UI.frame:Hide() end")
        elif n == "Menu":
            lua.execute("UltimateAH.UI:Toggle('Ledger'); local b = UltimateAH.UI.lbar.type; b.scripts.OnClick(b, 'LeftButton')")
        elif n == "Sell":
            lua.execute("SELL_DEMO(); UltimateAH.UI:Toggle('Sell'); UltimateAH.UI:Refresh(); UltimateAH.ahOpen = false")
        else:
            lua.execute("UltimateAH.UI:Toggle(%r); UltimateAH.UI:Refresh()" % n)
        if os.environ.get("AL_LUA"):          # debugging aid: run some Lua after the page is up
            lua.execute(os.environ["AL_LUA"])
        errs = [str(G.UltimateAH.errors[i]) for i in range(1, len(G.UltimateAH.errors) + 1)]
        out = os.path.join(outdir, n + ".png")
        render(out, None if n == "AHPanel" else crop)
        print(out, "errors:" if errs else "", errs[-3:] if errs else "")
        if n == "PriceGraph":
            lua.execute("UltimateAH.UI.pgraph:Hide()")
        if n == "Menu":
            lua.execute("UltimateAH.W.CloseMenu()")


if __name__ == "__main__":
    main()
