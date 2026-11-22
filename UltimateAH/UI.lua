-- Ultimate AH: main window (Ledger / Summary / Listings / Prices), AH side panel, tooltips
local _, AL = ...
local W = AL.W
local UI = {}
AL.UI = UI

local WIDTH = 982          -- page width + 40 (the page area is 942 wide)
UI.WIDTH = WIDTH
UI.TAB_NAMES = { "Ledger", "Summary", "Value", "Inventory", "Listings", "Prices", "Deals", "Watch", "Sell", "Settings" }

local TYPE_LABEL = { buy = "Bought", sell = "Sold", post = "Posted", cancel = "Cancelled", expired = "Expired", bid = "Bid" }
local TYPE_COLOR = {
  buy = W.C.red, sell = W.C.green, post = W.C.blue,
  cancel = { 1, 0.62, 0.3 }, expired = W.C.muted, bid = W.C.gold,
}
local GRAY = { 0.6, 0.6, 0.6 }

local function ago(t)
  if not t then return "never" end
  local s = time() - t
  if s < 90 then return "just now" end
  if s < 3600 then return math.floor(s / 60) .. "m ago" end
  if s < 86400 * 2 then return math.floor(s / 3600) .. "h ago" end
  return math.floor(s / 86400) .. "d ago"
end
UI.Ago = ago

local function qualityColorText(name, itemID, link)
  local q = AL.ItemQuality(itemID, link)
  if q and ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[q] then
    return ITEM_QUALITY_COLORS[q].hex .. (name or "?") .. "|r"
  end
  return name or (itemID and ("item:" .. itemID)) or "?"
end

---------------------------------------------------------------------------
-- per-item buy/sell averages from the ledger (all characters)
---------------------------------------------------------------------------
local itemStats
function AL:ItemStats(itemID)
  if not itemStats then
    itemStats = {}
    for _, r in ipairs(self.db.tx) do
      local id = r.item or self:IdForName(r.name)
      if id and r.total and r.qty and r.qty > 0 and not r.provisional then
        local s = itemStats[id] or { bq = 0, bt = 0, sq = 0, st = 0, cut = 0 }
        if r.type == "buy" then s.bq, s.bt = s.bq + r.qty, s.bt + r.total
        elseif r.type == "sell" then s.sq, s.st, s.cut = s.sq + r.qty, s.st + r.total, s.cut + (r.cut or 0) end
        itemStats[id] = s
      end
    end
  end
  return itemStats[itemID]
end
AL:On("AL_TX_ADDED", function() itemStats = nil end)

---------------------------------------------------------------------------
-- filters shared by Ledger and Summary
---------------------------------------------------------------------------
UI.filter = { char = "ALL", type = "ALL", period = 0, search = "" }

local function charOptions()
  local opts, seen = { { "ALL", "All characters" } }, {}
  local names = {}
  for k in pairs(AL.db.chars) do if not seen[k] then seen[k] = true; names[#names + 1] = k end end
  for _, r in ipairs(AL.db.tx) do if r.char and not seen[r.char] then seen[r.char] = true; names[#names + 1] = r.char end end
  table.sort(names)
  for _, n in ipairs(names) do opts[#opts + 1] = { n, n } end
  return opts
end

local PERIODS = { { 0, "All time" }, { 1, "Today" }, { 7, "7 days" }, { 30, "30 days" }, { 90, "90 days" } }
local TYPES = { { "ALL", "All" }, { "buy", "Buys" }, { "sell", "Sales" }, { "post", "Posts" },
                { "cancel", "Cancels" }, { "expired", "Expired" }, { "bid", "Bids" } }

local function periodStart(days)
  if not days or days == 0 then return 0 end
  if days == 1 then
    local d = date("*t")
    d.hour, d.min, d.sec = 0, 0, 0
    return time(d)
  end
  return time() - days * 86400
end

local function passes(r, f, ignoreType)
  if f.char ~= "ALL" and r.char ~= f.char then return false end
  if not ignoreType and f.type ~= "ALL" and r.type ~= f.type then return false end
  if (r.t or 0) < periodStart(f.period) then return false end
  if f.search ~= "" then
    local n = (r.name or AL.ItemName(r.item, r.link) or ""):lower()
    if not n:find(f.search:lower(), 1, true) then return false end
  end
  return true
end

-- totals for a set of transactions
local function totals(list)
  local t = { bought = 0, nb = 0, sold = 0, ns = 0, cut = 0, pending = 0, np = 0, deposits = 0, fees = 0 }
  for _, r in ipairs(list) do
    if r.type == "buy" then t.bought = t.bought + (r.total or 0); t.nb = t.nb + 1
    elseif r.type == "sell" and r.provisional then t.pending = t.pending + (r.total or 0); t.np = t.np + 1
    elseif r.type == "sell" then t.sold = t.sold + (r.total or 0); t.cut = t.cut + (r.cut or 0); t.ns = t.ns + 1
    elseif r.type == "post" then t.deposits = t.deposits + (r.deposit or 0)
    elseif r.type == "cancel" then t.fees = t.fees + (r.fee or 0) end
  end
  t.net = t.sold - t.cut - t.bought
  return t
end
UI.Totals = totals

-- a character name in its class colour (when we know the class)
function UI.CharText(name)
  local c = name and AL.db.chars[name]
  local col = c and c.class and RAID_CLASS_COLORS and RAID_CLASS_COLORS[c.class]
  if col then return string.format("|cff%02x%02x%02x%s|r", math.floor(col.r * 255), math.floor(col.g * 255), math.floor(col.b * 255), name) end
  return name or "?"
end
local charText = UI.CharText
UI.QualityText = qualityColorText

---------------------------------------------------------------------------
-- main frame: sidebar navigation + page
---------------------------------------------------------------------------
local FRAME_W, FRAME_H, SIDE_W = 1190, 680, 196
local PAGES = {
  Ledger    = { "INV_Misc_Note_01", "Every auction house buy, sale, post and cancel on all your characters." },
  Summary   = { "INV_Scroll_03", "Profit per character and per item." },
  Value     = { "INV_Misc_Coin_04", "Gold plus what your items are worth, over time." },
  Inventory = { "INV_Misc_Bag_08", "Every tradeable item on every character, valued at market price." },
  Listings  = { "INV_Scroll_05", "Your auctions on every character, and who undercuts them." },
  Prices    = { "INV_Misc_Spyglass_02", "Scanned auction house prices. Click an item for its price history." },
  Deals     = { "INV_Misc_Coin_06", "Auctions listed below their normal price: buy and relist, or vendor." },
  Watch     = { "Spell_Holy_MindVision", "Get alerted when an item is listed at or under your price." },
  Sell      = { "INV_Misc_Coin_03", "What the items in your bags are worth, and what to post them for." },
  Settings  = { "INV_Misc_Gear_01", "Options and stored data." },
}

function UI:Create()
  if self.frame then return end
  local C = W.C
  local f = CreateFrame("Frame", "UltimateAHFrame", UIParent)
  f:SetSize(FRAME_W, FRAME_H)
  f:SetPoint("CENTER")
  f:SetFrameStrata("HIGH")
  f:SetToplevel(true)
  W.Fill(f, C.bg)
  W.Border(f)
  W.Shadow(f)
  f:EnableMouse(true)
  f:SetMovable(true)
  f:SetClampedToScreen(true)
  f:RegisterForDrag("LeftButton")
  f:SetScript("OnDragStart", f.StartMoving)
  f:SetScript("OnDragStop", function(s)
    s:StopMovingOrSizing()
    local p, _, rp, x, y = s:GetPoint()
    AL.db.settings.pos = { p, rp, x, y }
  end)
  f:Hide()
  tinsert(UISpecialFrames, "UltimateAHFrame")
  self.frame = f

  -- sidebar
  local side = W.Panel(f, C.side, true)
  side:SetPoint("TOPLEFT", 1, -1)
  side:SetPoint("BOTTOMLEFT", 1, 1)
  side:SetWidth(SIDE_W)
  local edge = side:CreateTexture(nil, "BORDER")
  edge:SetPoint("TOPRIGHT"); edge:SetPoint("BOTTOMRIGHT")
  edge:SetWidth(1)
  edge:SetColorTexture(C.border[1], C.border[2], C.border[3], 1)

  local logo = W.Logo(side, 32)
  logo:SetPoint("TOPLEFT", 16, -18)
  local title = W.Label(side, "Ultimate AH", "UAHFontH2")
  title:SetPoint("LEFT", logo, "RIGHT", 10, 6)
  local ver = W.Label(side, "Auction house toolkit", "UAHFontLabel")
  ver:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -2)

  self.views, self.tabs = {}, {}
  local y = -74
  for _, n in ipairs(UI.TAB_NAMES) do
    if n == "Ledger" or n == "Watch" then
      if n == "Watch" then y = y - 10 end
      local sep = W.Label(side, n == "Ledger" and "OVERVIEW" or "TOOLS", "UAHFontLabel")
      sep:SetPoint("TOPLEFT", 22, y)
      y = y - 18
    end
    local b = CreateFrame("Button", nil, side)
    b:SetSize(SIDE_W - 16, 32)
    b:SetPoint("TOPLEFT", 8, y)
    y = y - 34
    b.sel = W.Fill(b, C.panel2)
    b.sel:Hide()
    local hl = b:CreateTexture(nil, "HIGHLIGHT")
    hl:SetAllPoints()
    hl:SetColorTexture(1, 1, 1, 0.035)
    b.bar = b:CreateTexture(nil, "ARTWORK")
    b.bar:SetPoint("TOPLEFT"); b.bar:SetPoint("BOTTOMLEFT")
    b.bar:SetWidth(3)
    b.bar:SetColorTexture(C.accent[1], C.accent[2], C.accent[3], 1)
    b.bar:Hide()
    b.icon = b:CreateTexture(nil, "ARTWORK")
    b.icon:SetSize(18, 18)
    b.icon:SetPoint("LEFT", 14, 0)
    b.icon:SetTexture("Interface\\Icons\\" .. PAGES[n][1])
    b.icon:SetTexCoord(0.08, 0.92, 0.08, 0.92)
    b.text = W.Label(b, n, "UAHFontBody")
    b.text:SetPoint("LEFT", b.icon, "RIGHT", 12, 0)
    -- badge (counts: undercut auctions, watch alerts, deals)
    b.badge = CreateFrame("Frame", nil, b)
    b.badge:SetSize(26, 16)
    b.badge:SetPoint("RIGHT", -10, 0)
    b.badge.bg = W.Fill(b.badge, C.accent)
    b.badge.fs = W.Label(b.badge, "", "UAHFontLabel")
    b.badge.fs:SetPoint("CENTER", 0, 0)
    b.badge.fs:SetTextColor(1, 1, 1)
    b.badge:Hide()
    b:SetScript("OnClick", function() UI:Select(n) end)
    self.tabs[n] = b

    local v = CreateFrame("Frame", nil, f)
    v:SetPoint("TOPLEFT", SIDE_W + 24, -88)
    v:SetPoint("BOTTOMRIGHT", -24, 16)
    v:Hide()
    self.views[n] = v
  end

  -- account card at the bottom of the sidebar
  local card = W.Panel(side, C.panel)
  card:SetPoint("BOTTOMLEFT", 10, 10)
  card:SetPoint("BOTTOMRIGHT", -11, 10)
  card:SetHeight(74)
  local cl = W.Label(card, "ACCOUNT VALUE", "UAHFontLabel")
  cl:SetPoint("TOPLEFT", 12, -10)
  self.acctValue = W.Label(card, "", "UAHFontH2")
  self.acctValue:SetPoint("TOPLEFT", 12, -26)
  self.acctNote = W.Label(card, "", "UAHFontMuted")
  self.acctNote:SetPoint("TOPLEFT", 12, -50)

  -- page header
  self.pageTitle = W.Label(f, "", "UAHFontH1")
  self.pageTitle:SetPoint("TOPLEFT", SIDE_W + 24, -22)
  self.pageDesc = W.Label(f, "", "UAHFontMuted")
  self.pageDesc:SetPoint("TOPLEFT", SIDE_W + 24, -52)
  self.subtitle = W.Label(f, "", "UAHFontMuted")
  self.subtitle:SetPoint("TOPRIGHT", -52, -30)
  self.subtitle:SetJustifyH("RIGHT")
  local close = W.Close(f, function() f:Hide() end)
  close:SetPoint("TOPRIGHT", -10, -10)
  local hline = f:CreateTexture(nil, "BORDER")
  hline:SetPoint("TOPLEFT", SIDE_W + 1, -74)
  hline:SetPoint("TOPRIGHT", -1, -74)
  hline:SetHeight(1)
  hline:SetColorTexture(C.border[1], C.border[2], C.border[3], 0.6)

  for _, n in ipairs(UI.TAB_NAMES) do self["Build" .. n](self, self.views[n]) end

  local pos = AL.db.settings.pos
  if pos then f:ClearAllPoints(); f:SetPoint(pos[1], UIParent, pos[2], pos[3], pos[4]) end
  f:SetScript("OnShow", function() UI:Refresh() end)
  f:SetScript("OnHide", function() W.CloseMenu() end)
end

function UI:Select(name)
  self.current = name
  local C = W.C
  for n, v in pairs(self.views) do
    local on = n == name
    v:SetShown(on)
    local b = self.tabs[n]
    b.sel:SetShown(on)
    b.bar:SetShown(on)
    b.icon:SetDesaturated(not on)
    b.icon:SetAlpha(on and 1 or 0.6)
    local c = on and { 1, 1, 1 } or C.muted
    b.text:SetTextColor(c[1], c[2], c[3])
  end
  self.pageTitle:SetText(name)
  self.pageDesc:SetText(PAGES[name] and PAGES[name][2] or "")
  AL.db.settings.tab = name
  W.CloseMenu()
  self:Refresh()
end

-- sidebar badges and the account card
function UI:UpdateChrome()
  local C = W.C
  local function badge(n, count, color)
    local b = self.tabs[n] and self.tabs[n].badge
    if not b then return end
    if count and count > 0 then
      b.fs:SetText(count > 99 and "99+" or tostring(count))
      b:SetWidth(math.max(20, b.fs:GetStringWidth() + 12))
      b.bg:SetColorTexture(color[1], color[2], color[3], 1)
      b:Show()
    else
      b:Hide()
    end
  end
  badge("Listings", #AL:Undercuts(), C.red)
  local hits = 0
  for _, w in pairs(AL.Watch and AL.Watch:List() or {}) do if w.hit and time() - w.hit.t < 3600 then hits = hits + 1 end end
  badge("Watch", hits, C.green)
  local nd = 0
  if AL.Deals then
    local cfg = AL.Deals:Settings()
    for _, d in ipairs((AL.Deals:Saved())) do if d.profit >= cfg.minProfit and d.roi >= cfg.minROI then nd = nd + 1 end end
  end
  badge("Deals", nd, C.accent)

  local tot = 0
  for ck in pairs(AL.db.chars) do
    local ok, b = pcall(AL.Value.Breakdown, AL.Value, ck)
    if ok and b then tot = tot + b.total end
  end
  self.acctValue:SetText(AL.Money(tot))
  local l, from = {}, time() - 7 * 86400
  for _, r in ipairs(AL.db.tx) do if (r.t or 0) >= from then l[#l + 1] = r end end
  local t = totals(l)
  self.acctNote:SetText("AH net, 7 days   " .. (t.net >= 0 and (W.GREEN .. "+") or W.RED) .. AL.Money(t.net, "short") .. "|r")
end

function UI:Toggle(tab)
  self:Create()
  if self.frame:IsShown() and not tab then self.frame:Hide(); return end
  self.frame:Show()
  tab = tab or self.current or AL.db.settings.tab
  if not self.views[tab] then tab = "Ledger" end
  self:Select(tab)
end

function UI:Refresh()
  if not self.frame or not self.frame:IsShown() then return end
  local n = 0
  for _ in pairs(AL.db.chars) do n = n + 1 end
  local sc = AL.db.scans[AL:Scope()]
  local fresh = sc and sc.t and (time() - sc.t < 3600)
  self.subtitle:SetText(string.format("%s transactions  \194\183  %d characters  \194\183  %sscanned %s|r",
    BreakUpLargeNumbers and BreakUpLargeNumbers(#AL.db.tx) or #AL.db.tx, n,
    fresh and W.GREEN or W.MUTED, sc and sc.t and ago(sc.t) or "never"))
  pcall(self.UpdateChrome, self)
  local v = self.current or "Ledger"
  local fn = self["Refresh" .. v]
  if fn then
    local ok, err = pcall(fn, self)
    if not ok then AL:Error("refresh " .. v, err) end
  end
end

local pendingRefresh
local function queueRefresh()
  if pendingRefresh then return end
  pendingRefresh = true
  C_Timer.After(0.2, function() pendingRefresh = false; UI:Refresh() end)
end
AL:On("AL_TX_ADDED", queueRefresh)
AL:On("AL_SCAN_DONE", queueRefresh)
AL:On("AL_LISTINGS", queueRefresh)

-- filter bar used by Ledger and Summary
function UI:FilterBar(parent, withType)
  local bar = {}
  bar.char = W.Cycle(parent, "Character", 220, charOptions(), function(v) UI.filter.char = v; UI:Refresh() end)
  bar.char:SetPoint("TOPLEFT", 0, 0)
  local last = bar.char
  if withType then
    bar.type = W.Cycle(parent, "Type", 150, TYPES, function(v) UI.filter.type = v; UI:Refresh() end)
    bar.type:SetPoint("LEFT", last, "RIGHT", 8, 0)
    last = bar.type
  end
  bar.period = W.Cycle(parent, "Period", 160, PERIODS, function(v) UI.filter.period = v; UI:Refresh() end)
  bar.period:SetPoint("LEFT", last, "RIGHT", 8, 0)
  bar.search = W.Edit(parent, 240, "Search items", function(txt) UI.filter.search = txt or ""; UI:Refresh() end)
  bar.search:SetPoint("TOPRIGHT", -16, 0)
  function bar:Sync()
    self.char:SetOptions(charOptions())
    for i, o in ipairs(self.char.opts) do if o[1] == UI.filter.char then self.char.i = i end end
    self.char:Refresh()
    if self.type then
      for i, o in ipairs(TYPES) do if o[1] == UI.filter.type then self.type.i = i end end
      self.type:Refresh()
    end
    for i, o in ipairs(PERIODS) do if o[1] == UI.filter.period then self.period.i = i end end
    self.period:Refresh()
    if self.search:GetText() ~= UI.filter.search then self.search:SetText(UI.filter.search) end
  end
  return bar
end

---------------------------------------------------------------------------
-- Ledger tab
---------------------------------------------------------------------------
function UI:BuildLedger(v)
  self.lbar = self:FilterBar(v, true)
  local cards = CreateFrame("Frame", nil, v)
  cards:SetPoint("TOPLEFT", 0, -40)
  cards:SetSize(WIDTH - 56, 60)
  self.lcards = W.StatRow(cards, WIDTH - 56, { "Bought", "Sold", "AH cut", "Net profit", "Awaiting mail" })
  self.ltable = W.Table(v, {
    { title = "Date", width = 104 },
    { title = "Character", width = 120 },
    { title = "Type", width = 80, pill = true },
    { title = "Item", width = 240, icon = true },
    { title = "Qty", width = 44, justify = "RIGHT" },
    { title = "Each", width = 104, justify = "RIGHT" },
    { title = "Total", width = 116, justify = "RIGHT" },
    { title = "Note", width = 92 },
  }, 21)
  self.ltable:SetPoint("TOPLEFT", 0, -114)
  self.ltable.emptyText = "No transactions yet. Buy or sell something on the auction house and it shows up here."
  -- right-click: delete a wrong entry (asks first)
  StaticPopupDialogs.ULTIMATEAH_DELETE = {
    text = "Delete this ledger entry?\n\n%s",
    button1 = DELETE or "Delete", button2 = CANCEL or "Cancel",
    OnAccept = function(_, rec)
      for i = #AL.db.tx, 1, -1 do if AL.db.tx[i] == rec then table.remove(AL.db.tx, i); break end end
      AL:Fire("AL_TX_ADDED")
    end,
    timeout = 0, whileDead = true, hideOnEscape = true, preferredIndex = 3,
  }
  self.ltable.onClick = function(d, btn)
    if btn == "RightButton" and d.rec then
      local r = d.rec
      local desc = string.format("%s %s x%s (%s)", TYPE_LABEL[r.type] or r.type, r.name or AL.ItemName(r.item, r.link) or "?", tostring(r.qty or "?"), AL.Money(r.total or 0, true))
      StaticPopup_Show("ULTIMATEAH_DELETE", desc, nil, r)
    end
  end
end

function UI:RefreshLedger()
  self.lbar:Sync()
  local rows, list = {}, {}
  local tx = AL.db.tx
  for i = #tx, 1, -1 do
    local r = tx[i]
    if passes(r, self.filter) then
      list[#list + 1] = r
      local name = r.name or AL.ItemName(r.item, r.link)
      local label = TYPE_LABEL[r.type] or r.type
      local note = ""
      if r.type == "sell" then
        if r.provisional then label = "Pending"; note = "awaiting mail"
        elseif r.cut then note = "cut " .. AL.Money(r.cut, "short") end
      elseif r.type == "post" and r.deposit then note = "deposit " .. AL.Money(r.deposit, "short")
      elseif r.type == "cancel" and r.fee and r.fee > 0 then note = "fee " .. AL.Money(r.fee, "short")
      elseif r.type == "buy" and r.src == "mail" then note = "from mail" end
      local tip = {}
      if r.buyer then tip[#tip + 1] = "Buyer: " .. r.buyer end
      if r.seller then tip[#tip + 1] = "Seller: " .. r.seller end
      if r.cut then tip[#tip + 1] = "AH cut: " .. AL.Money(r.cut) end
      if r.type == "sell" and r.total and not r.provisional then
        tip[#tip + 1] = "You received: " .. AL.Money(r.total - (r.cut or 0))
      end
      if r.provisional then tip[#tip + 1] = "Estimated from your listing; the exact amount is read from the mail." end
      rows[#rows + 1] = {
        cells = { date("%d %b %H:%M", r.t), charText(r.char), label, qualityColorText(name, r.item, r.link),
                  r.qty or "", r.unit and AL.Money(r.unit) or "", r.total and AL.Money(r.total) or "", note },
        sort = { r.t, r.char, label, name or "", r.qty or 0, r.unit or 0, r.total or 0, note },
        colors = { nil, nil, r.provisional and W.C.gold or TYPE_COLOR[r.type], nil, nil, nil, nil, GRAY },
        icon = AL.ItemIcon(r.item), link = r.link or AL.ItemLink(r.item), itemID = r.item, tip = tip, rec = r,
      }
      tip[#tip + 1] = "|cff999999Right-click to delete this entry.|r"
    end
  end
  self.ltable:SetData(rows, true)
  local t = totals(list)
  local C, c = W.C, self.lcards
  c[1]:Set(AL.Money(t.bought), nil, t.nb .. " buys", C.red)
  c[2]:Set(AL.Money(t.sold), nil, t.ns .. " sales", C.green)
  c[3]:Set(AL.Money(t.cut), nil, "5% of sales")
  c[4]:Set(AL.Money(t.net), t.net >= 0 and C.green or C.red, "sold - cut - bought", t.net >= 0 and C.green or C.red)
  c[5]:Set(t.np > 0 and AL.Money(t.pending) or "-", t.np > 0 and C.gold or C.muted, t.np > 0 and (t.np .. " sales") or "none")
end

---------------------------------------------------------------------------
-- Summary tab
---------------------------------------------------------------------------
function UI:BuildSummary(v)
  self.sbar = self:FilterBar(v, false)
  local nChars = 0
  for _ in pairs(AL.db.chars) do nChars = nChars + 1 end
  local charRows = math.max(2, math.min(nChars + 1, 6))
  local h1 = W.Label(v, "PER CHARACTER", "UAHFontLabel")
  h1:SetPoint("TOPLEFT", 0, -42)
  self.stable = W.Table(v, {
    { title = "Character", width = 150 },
    { title = "Bought", width = 120, justify = "RIGHT" },
    { title = "Sold", width = 120, justify = "RIGHT" },
    { title = "AH cut", width = 100, justify = "RIGHT" },
    { title = "Net", width = 130, justify = "RIGHT" },
    { title = "Buys", width = 50, justify = "RIGHT" },
    { title = "Sales", width = 50, justify = "RIGHT" },
    { title = "Gold now", width = 130, justify = "RIGHT" },
  }, charRows)
  self.stable:SetPoint("TOPLEFT", 0, -58)
  local h2 = W.Label(v, "ITEMS  -  PROFIT = SOLD AFTER CUT - BOUGHT", "UAHFontLabel")
  local itemsTop = -58 - (charRows + 1) * W.ROW_H - 28
  h2:SetPoint("TOPLEFT", 0, itemsTop)
  self.sitems = W.Table(v, {
    { title = "Item", width = 230, icon = true },
    { title = "Bought", width = 60, justify = "RIGHT" },
    { title = "Avg buy", width = 105, justify = "RIGHT" },
    { title = "Sold", width = 60, justify = "RIGHT" },
    { title = "Avg sell", width = 105, justify = "RIGHT" },
    { title = "Profit", width = 125, justify = "RIGHT" },
    { title = "Market now", width = 110, justify = "RIGHT" },
  }, math.floor((576 + itemsTop - 16 - 30) / W.ROW_H) - 1)
  self.sitems:SetPoint("TOPLEFT", 0, itemsTop - 16)
  self.sitems.sortCol, self.sitems.sortAsc = 6, false
end

function UI:RefreshSummary()
  self.sbar:Sync()
  local byChar, byItem, all = {}, {}, {}
  for _, r in ipairs(AL.db.tx) do
    if passes(r, self.filter, true) then
      all[#all + 1] = r
      local c = r.char or "?"
      byChar[c] = byChar[c] or {}
      table.insert(byChar[c], r)
      if (r.type == "buy" or (r.type == "sell" and not r.provisional)) and r.total then
        local id = r.item or AL:IdForName(r.name) or r.name
        local s = byItem[id] or { name = r.name, id = r.item, link = r.link, bq = 0, bt = 0, sq = 0, st = 0, cut = 0 }
        s.name = s.name or r.name
        s.link = s.link or r.link
        if r.type == "buy" then s.bq, s.bt = s.bq + (r.qty or 0), s.bt + r.total
        else s.sq, s.st, s.cut = s.sq + (r.qty or 0), s.st + r.total, s.cut + (r.cut or 0) end
        byItem[id] = s
      end
    end
  end
  local rows = {}
  local function addRow(name, list, gold, bold)
    local t = totals(list)
    rows[#rows + 1] = {
      cells = { bold and (W.ACCENT .. name .. "|r") or charText(name), AL.Money(t.bought), AL.Money(t.sold), AL.Money(t.cut),
                AL.Money(t.net), t.nb, t.ns, gold and AL.Money(gold) or "" },
      sort = { bold and "~" or name, t.bought, t.sold, t.cut, t.net, t.nb, t.ns, gold or 0 },
      colors = { nil, nil, nil, nil, t.net >= 0 and W.C.green or W.C.red },
    }
  end
  local names, goldAll = {}, 0
  for c in pairs(byChar) do names[#names + 1] = c end
  for c, info in pairs(AL.db.chars) do
    if not byChar[c] then names[#names + 1] = c; byChar[c] = {} end
    goldAll = goldAll + (info.money or 0)
  end
  table.sort(names)
  for _, c in ipairs(names) do
    local info = AL.db.chars[c]
    addRow(c, byChar[c], info and info.money)
  end
  if self.filter.char == "ALL" then addRow("All characters", all, goldAll, true) end
  self.stable:SetData(rows)

  local irows = {}
  for id, s in pairs(byItem) do
    local itemID = type(id) == "number" and id or s.id
    local profit = (s.st - s.cut) - s.bt
    local p = itemID and AL.Scanner:ForItem(itemID)
    irows[#irows + 1] = {
      cells = { qualityColorText(s.name or AL.ItemName(itemID), itemID, s.link), s.bq,
                s.bq > 0 and AL.Money(s.bt / s.bq) or "", s.sq, s.sq > 0 and AL.Money(s.st / s.sq) or "",
                AL.Money(profit), p and AL.Money(p.mkt) or "" },
      colors = { nil, nil, nil, nil, nil, profit >= 0 and W.C.green or W.C.red },
      sort = { s.name or "", s.bq, s.bq > 0 and s.bt / s.bq or 0, s.sq, s.sq > 0 and s.st / s.sq or 0, profit, p and p.mkt or 0 },
      icon = AL.ItemIcon(itemID), itemID = itemID, link = s.link,
    }
  end
  self.sitems:SetData(irows)
end

---------------------------------------------------------------------------
-- Value tab: gold + item worth over time, per character or the whole account
---------------------------------------------------------------------------
local function shortMoney(v)
  local g = v / 10000
  if g >= 1000000 then return string.format("%.1fM g", g / 1000000) end
  if g >= 1 then return (BreakUpLargeNumbers and BreakUpLargeNumbers(math.floor(g + 0.5)) or math.floor(g + 0.5)) .. " g" end
  return string.format("%d s", math.floor(v / 100))
end

local VPERIODS = { { 1, "24 hours" }, { 7, "7 days" }, { 30, "30 days" }, { 90, "90 days" }, { 0, "All time" } }

function UI:BuildValue(v)
  self.vchar = W.Cycle(v, "Show", 220, { { "ACCOUNT", "Account" } }, function() UI:Refresh() end)
  self.vchar:SetPoint("TOPLEFT", 0, 0)
  self.vperiod = W.Cycle(v, "Period", 150, VPERIODS, function() UI:Refresh() end)
  self.vperiod:SetPoint("LEFT", self.vchar, "RIGHT", 8, 0)
  self.vperiod.i = 2
  self.vperiod:Refresh()
  local cards = CreateFrame("Frame", nil, v)
  cards:SetPoint("TOPLEFT", 0, -40)
  cards:SetSize(WIDTH - 56, 60)
  self.vcards = W.StatRow(cards, WIDTH - 56, { "Total value", "Gold", "Bags + bank", "Mail", "On the AH" })
  self.vgraph = W.Graph(v, WIDTH - 56, 230, shortMoney)
  self.vgraph:SetPoint("TOPLEFT", 0, -112)
  local legend = W.Label(v, W.ACCENT .. "——|r  Total        " .. W.GOLD .. "——|r  Gold        " .. W.GREEN .. "——|r  Items", "UAHFontMuted")
  legend:SetPoint("TOPRIGHT", self.vgraph, "BOTTOMRIGHT", 0, -6)
  self.vtable = W.Table(v, {
    { title = "Character", width = 150 },
    { title = "Gold", width = 110, justify = "RIGHT" },
    { title = "Bags", width = 100, justify = "RIGHT" },
    { title = "Bank", width = 100, justify = "RIGHT" },
    { title = "Mail", width = 100, justify = "RIGHT" },
    { title = "Auctions", width = 100, justify = "RIGHT" },
    { title = "Total", width = 120, justify = "RIGHT" },
    { title = "Bank seen", width = 90, justify = "RIGHT" },
  }, 8)
  self.vtable:SetPoint("TOPLEFT", 0, -112 - 230 - 26)
  self.vtable.sortCol, self.vtable.sortAsc = 7, false
  self.vtable.onClick = function(d) if d.char then UI:ShowValueFor(d.char) end end
end

function UI:ShowValueFor(char)
  for i, o in ipairs(self.vchar.opts) do if o[1] == char then self.vchar.i = i end end
  self.vchar:Refresh()
  self:Refresh()
end

function UI:RefreshValue()
  local V = AL.Value
  local opts = { { "ACCOUNT", "Account" } }
  local names = {}
  for k in pairs(AL.db.chars) do names[#names + 1] = k end
  table.sort(names)
  for _, n in ipairs(names) do opts[#opts + 1] = { n, n } end
  self.vchar:SetOptions(opts)
  local who = self.vchar:Value()
  local days = self.vperiod:Value()
  local from = days > 0 and (time() - days * 86400) or 0

  local pts
  if who == "ACCOUNT" then pts = V:AccountSeries(0)
  else pts = V:Series(who) end
  local total, gold, items = {}, {}, {}
  local startV
  for _, p in ipairs(pts) do
    if p[1] >= from then
      total[#total + 1] = { p[1], p[2] + p[3] }
      gold[#gold + 1] = { p[1], p[2] }
      items[#items + 1] = { p[1], p[3] }
      startV = startV or (p[2] + p[3])
    end
  end
  self.vgraph:SetData({
    { name = "Items", color = W.C.green, points = items, thick = 1.5, alpha = 0.75 },
    { name = "Gold", color = W.C.gold, points = gold, thick = 1.5, alpha = 0.75 },
    { name = "Total", color = W.C.accent, points = total, thick = 2.5 },
  }, days > 0 and from or nil, time())

  -- current breakdown
  local cur = { gold = 0, bags = 0, bank = 0, mail = 0, ah = 0, total = 0 }
  local rows = {}
  for _, n in ipairs(names) do
    local b = V:Breakdown(n)
    if who == "ACCOUNT" or who == n then
      for k in pairs(cur) do cur[k] = cur[k] + (b[k] or 0) end
    end
    local inv = AL.db.inv and AL.db.inv[n] or {}
    rows[#rows + 1] = {
      cells = { charText(n), AL.Money(b.gold), AL.Money(b.bags), AL.Money(b.bank), AL.Money(b.mail), AL.Money(b.ah),
                AL.Money(b.total), inv.bankT and ago(inv.bankT) or "never" },
      sort = { n, b.gold, b.bags, b.bank, b.mail, b.ah, b.total, inv.bankT or 0 },
      colors = { nil, nil, nil, nil, nil, nil, nil, not inv.bankT and W.C.muted or nil },
      char = n,
      tip = { n, "Click to graph this character.", "Bank contents are remembered from the last time you opened the bank." },
    }
  end
  self.vtable:SetData(rows, true)
  local C, c = W.C, self.vcards
  c[1]:Set(AL.Money(cur.total), nil, (who == "ACCOUNT" and "account" or who), C.accent)
  if startV then
    local d = cur.total - startV
    local ccol = d >= 0 and C.green or C.red
    c[1].note:SetText((d >= 0 and "+" or "-") .. AL.Money(math.abs(d), "short") .. "  " .. self.vperiod.opts[self.vperiod.i][2])
    c[1].note:SetTextColor(ccol[1], ccol[2], ccol[3])
  else
    c[1].note:SetTextColor(C.muted[1], C.muted[2], C.muted[3])
  end
  c[2]:Set(AL.Money(cur.gold), nil, nil, C.gold)
  c[3]:Set(AL.Money(cur.bags + cur.bank), nil, "bank " .. AL.Money(cur.bank, "short"), C.green)
  c[4]:Set(AL.Money(cur.mail))
  c[5]:Set(AL.Money(cur.ah), nil, nil, C.green)
end

AL:On("AL_VALUE", queueRefresh)

---------------------------------------------------------------------------
-- Inventory tab: every tradeable item of every character and what it is worth
---------------------------------------------------------------------------
local WHERE = { bags = "Bags", bank = "Bank", mail = "Mail" }

function UI:BuildInventory(v)
  self.ichar = W.Cycle(v, "Character", 240, { { "ALL", "All characters" } }, function() UI:Refresh() end)
  self.ichar:SetPoint("TOPLEFT", 0, 0)
  self.isearch = W.Edit(v, 240, "Search items", function(t) UI.invSearch = (t or ""):lower(); UI:Refresh() end)
  self.isearch:SetPoint("LEFT", self.ichar, "RIGHT", 8, 0)
  self.itot = W.Label(v, "", "UAHFontH2")
  self.itot:SetPoint("TOPRIGHT", -16, -4)
  self.itot:SetJustifyH("RIGHT")
  local note = W.Label(v, "Tradeable items only, valued at the scanned market price. The bank is remembered from the last visit.", "GameFontDisableSmall")
  note:SetPoint("TOPLEFT", 0, -36)
  self.itable = W.Table(v, {
    { title = "Character", width = 140 },
    { title = "Item", width = 260, icon = true },
    { title = "Where", width = 70, pill = true },
    { title = "Qty", width = 60, justify = "RIGHT" },
    { title = "Value each", width = 120, justify = "RIGHT" },
    { title = "Total value", width = 130, justify = "RIGHT" },
    { title = "Market seen", width = 90, justify = "RIGHT" },
  }, 24)
  self.itable:SetPoint("TOPLEFT", 0, -62)
  self.itable.sortCol, self.itable.sortAsc = 6, false
  self.itable.emptyText = "No items recorded yet."
end

function UI:RefreshInventory()
  local opts, names = { { "ALL", "All characters" } }, {}
  for k in pairs(AL.db.inv or {}) do names[#names + 1] = k end
  table.sort(names)
  for _, n in ipairs(names) do opts[#opts + 1] = { n, n } end
  self.ichar:SetOptions(opts)
  local who = self.ichar:Value()
  local q = self.invSearch or ""
  local rows, total = {}, 0
  for _, char in ipairs(names) do
    if who == "ALL" or who == char then
      local inv = AL.db.inv[char]
      for where, label in pairs(WHERE) do
        for _, it in pairs(inv[where] or {}) do
          local id, count, link = it[1], it[2], it[3]
          local name = (link and link:match("|h%[(.-)%]|h")) or AL.ItemName(id) or ("item " .. tostring(id))
          if q == "" or name:lower():find(q, 1, true) then
            local unit = AL.Value.UnitValue(id, link)
            local e = AL.Scanner:ForItem(link or id)
            total = total + unit * count
            rows[#rows + 1] = {
              cells = { charText(char), qualityColorText(name, id, link), label, count, unit > 0 and AL.Money(unit) or "|cff999999no price|r",
                        unit > 0 and AL.Money(unit * count) or "", e and ago(e.t) or "" },
              sort = { char, name, label, count, unit, unit * count, -(e and e.t or 0) },
              icon = AL.ItemIcon(id), itemID = id, link = link,
            }
          end
        end
      end
    end
  end
  self.itable:SetData(rows, true)
  self.itot:SetText(string.format("%s%d stacks|r   %s", W.MUTED, #rows, AL.Money(total)))
end

---------------------------------------------------------------------------
-- Listings tab (active auctions of every character, as of their last AH visit)
---------------------------------------------------------------------------
function UI:BuildListings(v)
  local cards = CreateFrame("Frame", nil, v)
  cards:SetPoint("TOPLEFT", 0, 0)
  cards:SetSize(WIDTH - 56, 60)
  self.listCards = W.StatRow(cards, WIDTH - 56, { "Active auctions", "Worth at buyout", "Undercut", "Sold - in the mail" })
  local info = W.Label(v, "As seen the last time each character opened the auction house; undercuts come from the latest scan.", "UAHFontMuted")
  info:SetPoint("TOPLEFT", 0, -72)
  self.ltab2 = W.Table(v, {
    { title = "Character", width = 136 },
    { title = "Item", width = 226, icon = true },
    { title = "Qty", width = 46, justify = "RIGHT" },
    { title = "Your price", width = 100, justify = "RIGHT" },
    { title = "Lowest other", width = 106, justify = "RIGHT" },
    { title = "Stack total", width = 104, justify = "RIGHT" },
    { title = "Left", width = 60, justify = "RIGHT" },
    { title = "Status", width = 132, pill = true },
  }, 22)
  self.ltab2:SetPoint("TOPLEFT", 0, -96)
  self.ltab2.emptyText = "No listings recorded yet - open the auction house on each character."
  self.ltab2.sortCol, self.ltab2.sortAsc = 8, true
end

-- my active auctions that someone else now undercuts (from the latest scan data)
function AL:Undercuts()
  local out = {}
  for char, snap in pairs(self.db.listings or {}) do
    for _, a in ipairs(snap.list or {}) do
      if not a.sold and a.buyout and a.buyout > 0 then
        local each = a.buyout / math.max(a.qty or 1, 1)
        local p = a.id and AL.Scanner:ForItem(a.link or a.id)
        if p and p.minOther and p.minOther < each - 0.5 and (p.t or 0) >= (snap.t or 0) - 86400 then
          out[#out + 1] = { char = char, a = a, each = each, lowest = p.minOther }
        end
      end
    end
  end
  return out
end

function UI:RefreshListings()
  local rows, total, n, under, sold, soldV = {}, 0, 0, 0, 0, 0
  for char, snap in pairs(AL.db.listings or {}) do
    for _, a in ipairs(snap.list or {}) do
      local tot = a.buyout or a.bid or 0            -- the whole stack
      local each = tot / math.max(a.qty or 1, 1)
      local status, scol, rank
      local p = a.id and AL.Scanner:ForItem(a.link or a.id)
      local tip = { "Recorded " .. ago(snap.t) }
      local left, leftS = "", 0
      local lowCol
      if a.sold then
        status, scol, rank = "Sold, in the mail", W.C.gold, 1
        sold = sold + 1; soldV = soldV + tot * 0.95
      else
        if a.left then
          leftS = a.left - (time() - snap.t)
          left = leftS > 0 and (leftS >= 3600 and string.format("%dh", math.ceil(leftS / 3600)) or string.format("%dm", math.ceil(leftS / 60))) or "ended?"
        end
        if p and p.minOther and p.minOther < each - 0.5 then
          status, scol, rank, lowCol = "Undercut", W.C.red, 0, W.C.red
          under = under + 1
          tip[#tip + 1] = "Lowest from someone else: " .. AL.Money(p.minOther) .. " (yours " .. AL.Money(each) .. ")"
          tip[#tip + 1] = "Cancel and repost at " .. AL.Money(math.max(1, p.minOther - 1)) .. " to be cheapest."
        elseif p and p.minOther then
          status, scol, rank = "Lowest", W.C.green, 2
          tip[#tip + 1] = "Next cheapest from someone else: " .. AL.Money(p.minOther)
        else
          status, scol, rank = "Active", W.C.muted, 3
        end
      end
      if not a.sold then total = total + tot; n = n + 1 end
      rows[#rows + 1] = {
        cells = { charText(char), qualityColorText(a.name or AL.ItemName(a.id, a.link), a.id, a.link), a.qty or 1, AL.Money(each),
                  p and p.minOther and AL.Money(p.minOther) or "", AL.Money(tot), left, status },
        sort = { char, a.name or "", a.qty or 1, each, p and p.minOther or 0, tot, leftS, rank },
        colors = { nil, nil, nil, nil, lowCol, nil, (leftS > 0 and leftS < 7200) and W.C.gold or W.C.muted, scol },
        icon = AL.ItemIcon(a.id), link = a.link, itemID = a.id, tip = tip,
      }
    end
  end
  self.ltab2:SetData(rows, true)
  local C, c = W.C, self.listCards
  c[1]:Set(tostring(n), nil, nil, C.accent)
  c[2]:Set(AL.Money(total))
  c[3]:Set(tostring(under), under > 0 and C.red or C.green, under > 0 and "repost cheaper" or "all lowest", under > 0 and C.red or nil)
  c[4]:Set(tostring(sold), sold > 0 and C.gold or nil, sold > 0 and ("about " .. AL.Money(soldV, "short")) or nil)
end

-- after a scan: tell me which auctions got undercut
AL:On("AL_SCAN_DONE", function(kind)
  if (kind ~= "full" and kind ~= "api") or AL.db.settings.undercutNotice == false then return end
  if kind == "api" then
    local info = AL.Api and AL.Api:Info()
    if not info or time() - info.t > 2 * 3600 then return end        -- old news
  end
  C_Timer.After(1, function()
    local u = AL:Undercuts()
    if #u == 0 then return end
    local names = {}
    for i = 1, math.min(5, #u) do
      names[#names + 1] = string.format("%s (%s < %s)", u[i].a.name or "?", AL.Money(u[i].lowest, true), AL.Money(u[i].each, true))
    end
    AL:Print(string.format("|cffff7373%d of your auctions are undercut|r: %s%s - see Listings", #u,
      table.concat(names, ", "), #u > 5 and ", ..." or ""))
  end)
end)

---------------------------------------------------------------------------
-- Prices tab
---------------------------------------------------------------------------
function UI:BuildPrices(v)
  self.psearch = W.Edit(v, 240, "Search scanned items", function(txt) UI.priceSearch = (txt or ""):lower(); UI:Refresh() end)
  self.psearch:SetPoint("TOPLEFT", 0, 0)
  self.pfull = W.Button(v, "Full Scan", 100, function() AL.Scanner:Full() end, "primary")
  self.pfull:SetPoint("LEFT", self.psearch, "RIGHT", 12, 0)
  self.pquick = W.Button(v, "Quick Scan", 100, function() AL.Scanner:Quick() end)
  self.pquick:SetPoint("LEFT", self.pfull, "RIGHT", 8, 0)
  self.pdeep = W.Button(v, "Deep Scan", 100, function() AL.Scanner:Deep() end)
  self.pdeep:SetPoint("LEFT", self.pquick, "RIGHT", 8, 0)
  self.pstatus = W.Label(v, "", "UAHFontMuted")
  self.pstatus:SetPoint("LEFT", self.pdeep, "RIGHT", 14, 0)
  self.pstatus:SetWidth(340)               -- one anchor: a second one on the page's edge fights over the height
  self.pstatus:SetJustifyH("LEFT")
  self.pstatus:SetWordWrap(false)
  self.ptable = W.Table(v, {
    { title = "Item", width = 196, icon = true },
    { title = "Min buyout", width = 80, justify = "RIGHT" },
    { title = "Market", width = 80, justify = "RIGHT" },
    { title = "Top 100", width = 80, justify = "RIGHT" },
    { title = "14d avg", width = 80, justify = "RIGHT" },
    { title = "Trend/day", width = 64, justify = "RIGHT" },
    { title = "Qty", width = 52, justify = "RIGHT" },
    { title = "Sold/day", width = 64, justify = "RIGHT" },
    { title = "Scanned", width = 66, justify = "RIGHT" },
    { title = "My avg buy", width = 78, justify = "RIGHT" },
    { title = "My avg sell", width = 78, justify = "RIGHT" },
  }, 25)
  self.ptable:SetPoint("TOPLEFT", 0, -40)
  self.ptable.sortCol, self.ptable.sortAsc = 1, true
  self.ptable.onClick = function(d, btn)
    if btn == "RightButton" and d.itemID then
      -- watch it: prefill the Watch tab with 80% of the normal price
      local e = AL.db.prices[AL:Scope()][d.key]
      local ref = e and AL.Sell.Reference(e)
      UI:Select("Watch")
      UI.witem:SetText(tostring(d.itemID))
      UI.wmax:SetText(ref and AL.Money(math.floor(ref * 0.8), true):gsub(" ", "") or "")
      UI.wmax:SetFocus()
    elseif d.key then UI:ShowPriceGraph(d.key) end
  end
  self.ptable.emptyText = "No prices yet - open the auction house and press Full Scan (or Quick Scan)."
end

function UI:RefreshPrices()
  local prices = AL.db.prices[AL:Scope()] or {}
  local q = self.priceSearch or ""
  local rows = {}
  local count = 0
  for key, e in pairs(prices) do
    count = count + 1
    local name = e.n or AL.ItemName(e.i)
    if not e.n and name then e.n = name end
    if q == "" or (name and name:lower():find(q, 1, true)) then
      local st = e.i and AL:ItemStats(e.i)
      local avg = AL.Scanner.HistoryAvg(e)
      local sold = AL.Api and AL.Api.SoldPerDay(e)
      local trend = AL.Api and AL.Api.Trend(e)
      local tip = { "Click: price history graph.", "Right-click: add to the watchlist." }
      if sold then tip[#tip + 1] = "Sold/day is an estimate: units that left the auction house between hourly API scans." end
      if trend then tip[#tip + 1] = "Trend/day: how the price moved over the last week (from the server scan's history)." end
      rows[#rows + 1] = {
        cells = { qualityColorText(name or ("item " .. key), e.i), AL.Money(e.min), AL.Money(e.mkt), e.top and AL.Money(e.top) or "",
                  avg and AL.Money(avg) or "", trend and AL.Api.TrendText(trend) or "", e.qty or "",
                  sold and AL.Api.SoldText(sold) or "", ago(e.t),
                  st and st.bq > 0 and AL.Money(st.bt / st.bq) or "", st and st.sq > 0 and AL.Money(st.st / st.sq) or "" },
        sort = { name or "~", e.min or 0, e.mkt or 0, e.top or 0, avg or 0, trend or -9999, e.qty or 0, sold or -1, -(e.t or 0),
                 st and st.bq > 0 and st.bt / st.bq or 0, st and st.sq > 0 and st.st / st.sq or 0 },
        colors = { nil, nil, nil, nil, nil, nil, nil, nil, (time() - (e.t or 0) > 86400) and W.C.muted or nil },
        icon = AL.ItemIcon(e.i), itemID = e.i, key = key, tip = tip,
      }
    end
  end
  self.ptable:SetData(rows, true)
  self:UpdateScanStatus()
end

-- price history of one item (daily market value and lowest buyout)
function UI:ShowPriceGraph(key)
  local e = AL.db.prices[AL:Scope()] and AL.db.prices[AL:Scope()][key]
  if not e then return end
  if not self.pgraph then
    local f = W.Panel(self.frame, W.C.bg)
    f:SetSize(680, 416)
    f:SetPoint("CENTER", self.frame, "CENTER", 90, -10)
    f:SetFrameLevel(self.frame:GetFrameLevel() + 20)
    W.Shadow(f)
    f:EnableMouse(true)
    local close = W.Close(f)
    close:SetPoint("TOPRIGHT", -8, -8)
    f.icon = f:CreateTexture(nil, "ARTWORK")
    f.icon:SetSize(32, 32)
    f.icon:SetPoint("TOPLEFT", 18, -18)
    f.icon:SetTexCoord(0.08, 0.92, 0.08, 0.92)
    f.title = W.Label(f, "", "UAHFontH2")
    f.title:SetPoint("TOPLEFT", 60, -18)
    f.sub = W.Label(f, "", "UAHFontMuted")
    f.sub:SetPoint("TOPLEFT", 60, -38)
    f.graph = W.Graph(f, 644, 280, shortMoney)
    f.graph:SetPoint("TOPLEFT", 18, -62)
    local legend = W.Label(f, W.ACCENT .. "——|r  Market        " .. W.GOLD .. "——|r  Lowest buyout", "UAHFontMuted")
    legend:SetPoint("BOTTOMRIGHT", -18, 12)
    -- what the server scan's history says: trend and weekdays, hours, forecast (next to the legend)
    f.patterns = {}
    for i = 1, 3 do
      local l = W.Label(f, "", "UAHFontMuted")
      l:SetPoint("BOTTOMLEFT", 18, 48 - (i - 1) * 18)
      l:SetWidth(i == 3 and 400 or 640)
      l:SetJustifyH("LEFT")
      l:SetWordWrap(false)
      f.patterns[i] = l
    end
    self.pgraph = f
  end
  local f = self.pgraph
  local mk, mn = {}, {}
  local days = {}
  for d in pairs(e.h or {}) do days[#days + 1] = d end
  table.sort(days)
  for _, d in ipairs(days) do
    local h = e.h[d]
    local t = d * 86400 + 43200
    mk[#mk + 1] = { t, h[1] }
    mn[#mn + 1] = { t, h[2] }
  end
  f.title:SetText(qualityColorText(e.n or AL.ItemName(e.i), e.i))
  f.icon:SetTexture(AL.ItemIcon(e.i))
  f.sub:SetText(string.format("Now: market %s, lowest %s, %d listed (%s).  %d day(s) of history.",
    AL.Money(e.mkt), AL.Money(e.min), e.qty or 0, ago(e.t), #days))
  f.graph:SetData({
    { name = "Lowest", color = W.C.gold, points = mn, thick = 1.5, alpha = 0.75 },
    { name = "Market", color = W.C.accent, points = mk, thick = 2.5 },
  })
  local rows = { {}, {}, {} }
  for _, l in ipairs(AL.Api and AL.Api.InsightLines(e) or {}) do
    if l[1] == "Trend" then table.insert(rows[1], "Trend " .. l[2])
    elseif l[1] == "Usually" then table.insert(rows[1], "usually " .. l[2])
    elseif l[1] == "By hour" then table.insert(rows[2], "By hour: " .. l[2])
    else table.insert(rows[3], l[1] .. ": " .. l[2]) end
  end
  local n = 0
  for i = 1, 3 do f.patterns[i]:SetText("") end
  for _, r in ipairs(rows) do                      -- no gaps: the lines that have something, from the top
    if #r > 0 then n = n + 1; f.patterns[n]:SetText(table.concat(r, "  \194\183  ")) end
  end
  f:Show()
end

function UI:UpdateScanStatus()
  local sc = AL.db.scans[AL:Scope()]
  local s = AL.Scanner
  local txt
  if s.state ~= "idle" and s.msg then
    txt = s.msg
  elseif sc and sc.t then
    txt = string.format("Last %s scan %s: %d items.", sc.kind or "", ago(sc.t), sc.items or 0)
  else
    txt = "Never scanned."
  end
  local wait = s:ReplicateReadyIn()
  if wait > 0 and s.state == "idle" then
    txt = txt .. string.format("  Full scan again in %d:%02d.", math.floor(wait / 60), wait % 60)
  end
  if self.pstatus then self.pstatus:SetText(txt) end
  if self.ahStatus then
    local deals = AL.Deals and AL.Deals:Saved()
    local cfg = AL.Deals and AL.Deals:Settings()
    local n, best = 0, nil
    for _, d in ipairs(deals or {}) do
      if d.profit >= cfg.minProfit and d.roi >= cfg.minROI then n = n + 1; best = best or d end
    end
    local C = W.C
    local under = #AL:Undercuts()
    local r = self.ahRows
    r[1]:SetText(sc and sc.t and ago(sc.t) or "never")
    r[2]:SetText(tostring(n)); r[2]:SetTextColor(n > 0 and C.green[1] or C.text[1], n > 0 and C.green[2] or C.text[2], n > 0 and C.green[3] or C.text[3])
    r[3]:SetText(best and AL.Money(best.profit) or "-")
    r[4]:SetText(tostring(under)); r[4]:SetTextColor(under > 0 and C.red[1] or C.text[1], under > 0 and C.red[2] or C.text[2], under > 0 and C.red[3] or C.text[3])
    local status
    if s.state ~= "idle" and s.msg then status = s.msg
    elseif wait > 0 then status = string.format("Full scan ready in %d:%02d", math.floor(wait / 60), wait % 60)
    else status = AL.ahOpen and "Full scan ready" or "" end
    self.ahStatus:SetText(status)
  end
  local enable = AL.ahOpen and s.state == "idle"
  for _, b in ipairs({ self.pfull, self.pquick, self.pdeep, self.ahFull, self.ahQuick, self.ahDeep }) do
    if b then b:SetEnabled(enable) end
  end
  if self.pfull then self.pfull:SetEnabled(enable and wait == 0) end
  if self.ahFull then self.ahFull:SetEnabled(enable and wait == 0) end
end

AL:On("AL_SCAN_STATUS", function() UI:UpdateScanStatus() end)

---------------------------------------------------------------------------
-- Deals tab: buy cheap auctions, relist higher
---------------------------------------------------------------------------
local PROFITS = { { 2000, "20s" }, { 10000, "1g" }, { 50000, "5g" }, { 100000, "10g" }, { 500000, "50g" } }
local ROIS = { { 0.1, "10%" }, { 0.25, "25%" }, { 0.5, "50%" }, { 1, "100%" } }

function UI:BuildDeals(v)
  local cfg = AL.Deals:Settings()
  self.dprofit = W.Cycle(v, "Min profit", 160, PROFITS, function(x) cfg.minProfit = x; UI:Refresh() end)
  self.dprofit:SetPoint("TOPLEFT", 0, 0)
  self.droi = W.Cycle(v, "Min ROI", 140, ROIS, function(x) cfg.minROI = x; UI:Refresh() end)
  self.droi:SetPoint("LEFT", self.dprofit, "RIGHT", 8, 0)
  self.dafford = W.Cycle(v, "Show", 190, { { false, "All deals" }, { true, "Affordable now" }, { "sure", "Confident only" } }, function() UI:Refresh() end)
  self.dafford:SetPoint("LEFT", self.droi, "RIGHT", 8, 0)
  self.dinfo = W.Label(v, "", "UAHFontH2")
  self.dinfo:SetPoint("TOPRIGHT", -16, -4)
  self.dinfo:SetJustifyH("RIGHT")
  local help = W.Label(v, "Flip: buy the auctions listed below the normal price and relist just under it (profit after the 5% AH cut). " ..
    "Vendor: cheaper than a vendor pays. Click a row to search it in the auction house.", "GameFontDisableSmall")
  help:SetPoint("TOPLEFT", 0, -36)
  help:SetWidth(WIDTH - 56)
  self.dtable = W.Table(v, {
    { title = "Item", width = 206, icon = true },
    { title = "Kind", width = 56, pill = true },
    { title = "Buy", width = 78, justify = "RIGHT" },
    { title = "Cost", width = 108, justify = "RIGHT" },
    { title = "Cheapest", width = 70, justify = "RIGHT" },
    { title = "Relist at", width = 100, justify = "RIGHT" },
    { title = "Normal price", width = 100, justify = "RIGHT" },
    { title = "Profit", width = 112, justify = "RIGHT" },
    { title = "ROI", width = 54, justify = "RIGHT" },
  }, 24)
  self.dtable:SetPoint("TOPLEFT", 0, -62)
  self.dtable.sortCol, self.dtable.sortAsc = 8, false
  self.dtable.emptyText = "No deals with these settings. Deals are worked out after each Full Scan."
  self.dtable.onClick = function(d)
    if not AL.Deals.SearchInAH(d.name) then AL:Print("open the auction house to search for", d.name or "?") end
  end
end

function UI:RefreshDeals()
  local cfg = AL.Deals:Settings()
  for i, o in ipairs(PROFITS) do if o[1] == cfg.minProfit then self.dprofit.i = i end end
  self.dprofit:Refresh()
  for i, o in ipairs(ROIS) do if o[1] == cfg.minROI then self.droi.i = i end end
  self.droi:Refresh()
  local list, t = AL.Deals:Saved()
  local money = GetMoney()
  local afford = self.dafford:Value()
  local rows, sum = {}, 0
  for _, d in ipairs(list) do
    local show = (afford == false) or (afford == true and d.cost <= money) or (afford == "sure" and (d.sure or d.kind == "vendor"))
    if d.profit >= cfg.minProfit and d.roi >= cfg.minROI and show then
      sum = sum + d.profit
      local pct = d.ref > 0 and math.floor(d.low / d.ref * 100 + 0.5) or 0
      rows[#rows + 1] = {
        cells = { qualityColorText(d.name or AL.ItemName(d.item), d.item), d.kind == "vendor" and "Vendor" or (d.sure and "Flip" or "Flip?"),
                  d.kind == "flip" and string.format("%d (%d)", d.n, d.qty) or tostring(d.qty), AL.Money(d.cost),
                  pct .. "%", AL.Money(d.sellAt), AL.Money(d.ref),
                  AL.Money(d.profit), math.floor(d.roi * 100 + 0.5) .. "%" },
        sort = { d.name or "", d.kind, d.qty, d.cost, pct, d.sellAt, d.ref, d.profit, d.roi },
        colors = { nil, d.kind == "vendor" and W.C.gold or (d.sure and W.C.accent or GRAY), nil,
                   d.cost > money and W.C.red or nil, nil, nil, nil, W.C.green },
        icon = AL.ItemIcon(d.item), itemID = d.item, name = AL.ItemName(d.item) or d.name,   -- base name searches best
        tip = { d.kind == "flip"
          and string.format("Buy the %d cheapest auctions (%d items) for %s, relist each at %s.", d.n, d.qty, AL.Money(d.cost), AL.Money(d.sellAt))
          or string.format("Buy %d below the vendor price and sell to a vendor for %s each.", d.qty, AL.Money(d.sellAt)),
          string.format("Cheapest is %d%% of the normal price (%s).", pct, AL.Money(d.ref)),
          d.auctions and string.format("Market: %d auctions (%d items) listed, %d at or above the relist price; %s.",
            d.auctions, d.listed or 0, d.above or 0,
            (d.days or 0) >= 2 and ((d.days) .. " days of price history") or "normal price from this scan only (no history yet)") or nil,
          (d.kind == "flip" and not d.sure)
            and "|cffaaaaaaFlip? = less certain: under 3 days of price history, a thin market, or a suspiciously low price. Check the live listings before buying.|r"
            or "Prices can move: check the live listings before buying." },
      }
    end
  end
  self.dtable:SetData(rows, true)
  self.dinfo:SetText(t and string.format("%s%d deals  \194\183  scan %s  \194\183|r  %s", W.MUTED, #rows, ago(t), AL.Money(sum))
    or (W.MUTED .. "Run a Full Scan to find deals.|r"))
end

AL:On("AL_DEALS", queueRefresh)

---------------------------------------------------------------------------
-- minimap button (drag to move around the minimap)
---------------------------------------------------------------------------
function UI:MinimapButton()
  if self.mmb or not Minimap then return end
  local b = CreateFrame("Button", "UltimateAHMinimapButton", Minimap)
  b:SetSize(32, 32)
  b:SetFrameStrata("MEDIUM")
  b:SetFrameLevel(8)
  b:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  b:RegisterForDrag("LeftButton")
  local icon = b:CreateTexture(nil, "BACKGROUND")
  icon:SetTexture(W.LOGO)
  icon:SetSize(20, 20)
  icon:SetPoint("CENTER", 0, 1)
  local border = b:CreateTexture(nil, "OVERLAY")
  border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
  border:SetSize(54, 54)
  border:SetPoint("TOPLEFT")
  b:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
  local function place()
    local a = math.rad(AL.db.settings.mmAngle or 200)
    local r = (Minimap:GetWidth() / 2) + 6
    b:ClearAllPoints()
    b:SetPoint("CENTER", Minimap, "CENTER", math.cos(a) * r, math.sin(a) * r)
  end
  b:SetScript("OnDragStart", function(self)
    self:SetScript("OnUpdate", function()
      local mx, my = Minimap:GetCenter()
      local cx, cy = GetCursorPosition()
      local s = Minimap:GetEffectiveScale()
      AL.db.settings.mmAngle = math.deg(math.atan2(cy / s - my, cx / s - mx))
      place()
    end)
  end)
  b:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)
  b:SetScript("OnClick", function(_, btn)
    if btn == "RightButton" then UI:Toggle("Value") else UI:Toggle() end
  end)
  b:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:AddLine("|cff33ccffAuction|rLedger")
    local tot = 0
    for ck in pairs(AL.db.chars) do tot = tot + AL.Value:Breakdown(ck).total end
    GameTooltip:AddDoubleLine("Account value", AL.Money(tot), 1, 1, 1, 1, 1, 1)
    local t = UI.Totals((function()
      local l, from = {}, time() - 7 * 86400
      for _, r in ipairs(AL.db.tx) do if (r.t or 0) >= from then l[#l + 1] = r end end
      return l
    end)())
    GameTooltip:AddDoubleLine("AH net, 7 days", AL.Money(t.net), 1, 1, 1, 1, 1, 1)
    GameTooltip:AddLine("Left-click: ledger   Right-click: value graph", 0.6, 0.6, 0.6)
    GameTooltip:Show()
  end)
  b:SetScript("OnLeave", function() GameTooltip:Hide() end)
  place()
  b:SetShown(not AL.db.settings.hideMinimap)
  self.mmb = b
end

AL:On("AL_LOGIN", function() UI:MinimapButton() end)
AL:Command("minimap", "show/hide the minimap button", function()
  AL.db.settings.hideMinimap = not AL.db.settings.hideMinimap
  if UI.mmb then UI.mmb:SetShown(not AL.db.settings.hideMinimap) end
end)

---------------------------------------------------------------------------
-- auction house side panel
---------------------------------------------------------------------------
function UI:AttachToAH()
  if self.ahPanel or not AuctionHouseFrame then return end
  local p = W.Panel(AuctionHouseFrame, W.C.bg)
  p:SetSize(210, 304)
  p:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPRIGHT", 6, -24)
  W.Shadow(p)
  local logo = W.Logo(p, 22)
  logo:SetPoint("TOPLEFT", 14, -11)
  local title = W.Label(p, "Ultimate AH", "UAHFontH2")
  title:SetPoint("LEFT", logo, "RIGHT", 8, 0)
  self.ahFull = W.Button(p, "Full Scan", 172, function() AL.Scanner:Full() end, "primary")
  self.ahFull:SetPoint("TOP", 0, -44)
  self.ahQuick = W.Button(p, "Quick Scan", 172, function() AL.Scanner:Quick() end)
  self.ahQuick:SetPoint("TOP", self.ahFull, "BOTTOM", 0, -6)
  self.ahDeep = W.Button(p, "Deep Scan (my items)", 172, function() AL.Scanner:Deep() end)
  self.ahDeep:SetPoint("TOP", self.ahQuick, "BOTTOM", 0, -6)
  local open = W.Button(p, "Open Ultimate AH", 172, function() UI:Toggle() end)
  open:SetPoint("TOP", self.ahDeep, "BOTTOM", 0, -6)
  local sep = p:CreateTexture(nil, "BORDER")
  sep:SetColorTexture(W.C.border[1], W.C.border[2], W.C.border[3], 1)
  sep:SetPoint("TOPLEFT", 14, -170)
  sep:SetPoint("TOPRIGHT", -14, -170)
  sep:SetHeight(1)
  self.ahRows = {}
  for i, l in ipairs({ "Last scan", "Deals", "Best deal", "Undercut" }) do
    local k = W.Label(p, l, "UAHFontMuted")
    k:SetPoint("TOPLEFT", 14, -164 - i * 21)
    local val = W.Label(p, "", "UAHFontBody")
    val:SetPoint("TOPRIGHT", -14, -164 - i * 21)
    val:SetJustifyH("RIGHT")
    self.ahRows[i] = val
  end
  local st = W.Label(p, "", "UAHFontMuted")
  st:SetPoint("TOPLEFT", 14, -278)
  -- hover help for the three scan kinds
  local tips = {
    [self.ahFull] = { "Full Scan", "Downloads every auction at once and computes market values. The server allows one every 15 minutes." },
    [self.ahQuick] = { "Quick Scan", "Pages through the browse list: the lowest buyout and quantity of every item. No cooldown." },
    [self.ahDeep] = { "Deep Scan", "Searches each item you have bought, sold, listed or carry, and prices it from its cheapest 100 auctions." },
  }
  for b, tip in pairs(tips) do
    b:SetMotionScriptsWhileDisabled(true)
    b:SetScript("OnEnter", function(self)
      GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
      GameTooltip:AddLine(tip[1])
      GameTooltip:AddLine(tip[2], 1, 1, 1, true)
      GameTooltip:Show()
    end)
    b:SetScript("OnLeave", function() GameTooltip:Hide() end)
  end
  st:SetPoint("BOTTOMRIGHT", -14, 10)
  st:SetJustifyV("TOP")
  self.ahStatus = st
  self.ahPanel = p
  p:SetScript("OnShow", function() UI:UpdateScanStatus() end)
  -- the full-scan cooldown counts down while the panel is open
  local acc = 0
  p:SetScript("OnUpdate", function(_, el)
    acc = acc + el
    if acc > 1 then acc = 0; UI:UpdateScanStatus() end
  end)
end

AL:On("AUCTION_HOUSE_SHOW", function()
  C_Timer.After(0, function() UI:AttachToAH(); UI:UpdateScanStatus() end)
end)
AL:On("AUCTION_HOUSE_CLOSED", function() UI:UpdateScanStatus() end)

---------------------------------------------------------------------------
-- tooltips
---------------------------------------------------------------------------
local function addTooltip(tt, link)
  if not AL.db or not AL.db.settings.tooltip or not link then return end
  local id = AL.ItemID(link)
  if not id then return end
  local e = AL.Scanner:ForItem(link)
  local st = AL:ItemStats(id)
  if not e and not st then return end
  tt:AddLine(" ")
  if e then
    tt:AddDoubleLine("|cff33ccffUAH|r Market / Min", AL.Money(e.mkt) .. " / " .. AL.Money(e.min), 1, 1, 1, 1, 1, 1)
    local avg = AL.Scanner.HistoryAvg(e)
    if e.top then tt:AddDoubleLine("|cff33ccffUAH|r Top-100 avg", AL.Money(e.top), 1, 1, 1, 1, 1, 1) end
    local sold = AL.Api and AL.Api.SoldPerDay(e)
    if sold then
      tt:AddDoubleLine("|cff33ccffUAH|r Sold per day", sold > 0 and ("~" .. AL.Api.SoldText(sold)) or "|cff999999none seen|r", 1, 1, 1, 1, 1, 1)
    end
    tt:AddDoubleLine("|cff33ccffUAH|r 14-day avg", (avg and AL.Money(avg) or "-") .. "  |cff999999(" .. ago(e.t) .. ", " .. (e.qty or 0) .. " up)|r", 1, 1, 1, 1, 1, 1)
    if AL.db.settings.tooltipPatterns ~= false and AL.Api then
      for _, l in ipairs(AL.Api.InsightLines(e) or {}) do
        tt:AddDoubleLine("|cff33ccffUAH|r " .. l[1], l[2], 1, 1, 1, 1, 1, 1)
      end
    end
    if AL.db.settings.tooltipPost ~= false and AL.Suggest then
      local s = AL.Suggest(id, link)
      if s.post then
        local count = 1
        local owner = tt.GetOwner and tt:GetOwner()
        -- a bag slot: value the whole stack
        if owner and owner.GetBagID and owner.GetID then
          local ok, info = pcall(C_Container.GetContainerItemInfo, owner:GetBagID(), owner:GetID())
          if ok and info and info.stackCount then count = info.stackCount end
        end
        tt:AddDoubleLine("|cff33ccffUAH|r Post at", AL.Money(s.post) .. (count > 1 and ("  |cff999999(x" .. count .. " = " ..
          AL.Money(math.floor(s.post * count * 0.95)) .. " after cut)|r") or ""), 1, 1, 1, 1, 1, 1)
        if s.advice == "vendor" then tt:AddLine("|cff33ccffUAH|r |cffffd100A vendor pays more than the AH|r") end
      end
    end
    local w = AL.Watch and AL.Watch:For(AL.KeyFromLink(link, id) or id)
    if w then tt:AddDoubleLine("|cff33ccffUAH|r Watching at", AL.Money(w.max), 1, 1, 1, 0.35, 1, 0.35) end
  end
  if st and (st.bq > 0 or st.sq > 0) then
    local parts = {}
    if st.bq > 0 then parts[#parts + 1] = string.format("bought %d @ %s", st.bq, AL.Money(st.bt / st.bq)) end
    if st.sq > 0 then parts[#parts + 1] = string.format("sold %d @ %s", st.sq, AL.Money(st.st / st.sq)) end
    tt:AddDoubleLine("|cff33ccffUAH|r You", table.concat(parts, ", "), 1, 1, 1, 1, 1, 1)
  end
end

if TooltipDataProcessor and Enum.TooltipDataType then
  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tt, data)
    if tt ~= GameTooltip and tt ~= ItemRefTooltip then return end
    local link
    if tt.GetItem then link = select(2, tt:GetItem()) end
    if not link and data and data.id then link = "item:" .. data.id end
    pcall(addTooltip, tt, link)
  end)
end

---------------------------------------------------------------------------
-- slash commands
---------------------------------------------------------------------------
AL:Command("show", "open the ledger window", function(arg)
  local tab = arg ~= "" and (arg:sub(1, 1):upper() .. arg:sub(2):lower()) or nil
  if tab and not UI.views then UI:Create() end
  if tab and not (UI.views and UI.views[tab]) then tab = nil end
  UI:Toggle(tab)
end)
AL:Command("prices", "open the prices tab", function() UI:Toggle("Prices") end)
AL:Command("tooltip", "toggle price lines in item tooltips", function()
  AL.db.settings.tooltip = not AL.db.settings.tooltip
  AL:Print("tooltip lines", AL.db.settings.tooltip and "on" or "off")
end)
AL:Command("price", "print the price of an item: /uah price <item link or name>", function(arg)
  local key = AL.ItemID(arg) or AL:IdForName(arg)
  local e = key and AL.Scanner:ForItem(arg:find("|H") and arg or key)
  if not e then
    -- search by name
    for _, p in pairs(AL.db.prices[AL:Scope()] or {}) do
      if p.n and p.n:lower() == arg:lower() then e = p; break end
    end
  end
  if not e then AL:Print("no price for", arg); return end
  AL:Print(string.format("%s: market %s, min %s, %d up (%s)", e.n or arg, AL.Money(e.mkt), AL.Money(e.min), e.qty or 0, ago(e.t)))
end)
