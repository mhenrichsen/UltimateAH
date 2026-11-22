-- Ultimate AH: Watch, Sell and Settings pages
local _, AL = ...
local W, UI = AL.W, AL.UI
local WIDTH = UI.WIDTH
local PAGE_W = WIDTH - 56
local qtext = function(...) return UI.QualityText(...) end
local ago = function(t) return UI.Ago(t) end

-- typing into one of our edit boxes: shift-clicked item links go there instead of chat
local linkTargets = {}
if ChatEdit_InsertLink then
  hooksecurefunc("ChatEdit_InsertLink", function(link)
    for _, e in ipairs(linkTargets) do
      if e:IsVisible() and e:HasFocus() then e:SetText(link); return end
    end
  end)
end

---------------------------------------------------------------------------
-- Watch
---------------------------------------------------------------------------
function UI:BuildWatch(v)
  self.witem = W.Edit(v, 300, "Item name, ID or shift-click a link")
  self.witem:SetPoint("TOPLEFT", 0, 0)
  linkTargets[#linkTargets + 1] = self.witem
  self.wmax = W.Edit(v, 150, "Max price, e.g. 40g")
  self.wmax:SetPoint("LEFT", self.witem, "RIGHT", 8, 0)
  local function add()
    local id, name = AL.Watch:Resolve(self.witem:GetText())
    local max = AL.ParseMoney(self.wmax:GetText())
    if not id then AL:Print("unknown item - type its exact name, an ID, or shift-click it"); return end
    if not max then
      local e = AL.Scanner:ForItem(id)
      local ref = e and AL.Sell.Reference(e)
      if not ref then AL:Print("type a max price, e.g. 40g"); return end
      max = math.floor(ref * 0.8)
    end
    AL.Watch:Add(id, name, max)
    self.witem:SetText(""); self.wmax:SetText("")
    self.witem:ClearFocus(); self.wmax:ClearFocus()
  end
  self.wmax:SetScript("OnEnterPressed", add)
  self.witem:SetScript("OnEnterPressed", function() self.wmax:SetFocus() end)
  local b = W.Button(v, "Add to watchlist", 140, add, "primary")
  b:SetPoint("LEFT", self.wmax, "RIGHT", 8, 0)
  self.winfo = W.Label(v, "", "UAHFontH2")
  self.winfo:SetPoint("TOPRIGHT", -16, -4)
  self.winfo:SetJustifyH("RIGHT")
  local help = W.Label(v, "Alerts come as a chat line, a raid warning and a sound - after a scan or while you search the AH. " ..
    "No price = 80% of normal.  Left-click a row: search it.  Right-click: remove.", "UAHFontMuted")
  help:SetPoint("TOPLEFT", 0, -36)
  help:SetWidth(PAGE_W)
  self.wtable = W.Table(v, {
    { title = "Item", width = 250, icon = true },
    { title = "Max price", width = 110, justify = "RIGHT" },
    { title = "Normal", width = 110, justify = "RIGHT" },
    { title = "Lowest now", width = 110, justify = "RIGHT" },
    { title = "Max / normal", width = 90, justify = "RIGHT" },
    { title = "Last alert", width = 250 },
  }, 24)
  self.wtable:SetPoint("TOPLEFT", 0, -62)
  self.wtable.sortCol, self.wtable.sortAsc = 1, true
  self.wtable.emptyText = "Nothing watched yet. Add an item above, or right-click a row on the Prices page."
  self.wtable.onClick = function(d, btn)
    if btn == "RightButton" then
      AL.Watch:Remove(d.itemID)
      AL:Print("stopped watching", d.name or "?")
    elseif not AL.Deals.SearchInAH(d.name) then
      AL:Print("open the auction house to search for", d.name or "?")
    end
  end
end

function UI:RefreshWatch()
  local C = W.C
  local rows, hits = {}, 0
  for _, w in pairs(AL.Watch:List()) do
    local e = AL.Scanner:ForItem(w.id)
    local ref = e and AL.Sell.Reference(e)
    local low = e and (e.minOther or e.min)
    local hit = w.hit and time() - w.hit.t < 3600
    if hit then hits = hits + 1 end
    local name = w.name or AL.ItemName(w.id)
    rows[#rows + 1] = {
      cells = { qtext(name, w.id), AL.Money(w.max), ref and AL.Money(ref) or "", low and AL.Money(low) or "",
                ref and (math.floor(w.max / ref * 100 + 0.5) .. "%") or "",
                w.hit and string.format("%s  -  %s at %s (%s)", ago(w.hit.t), w.hit.qty and (w.hit.qty .. " listed") or "listed",
                  AL.Money(w.hit.price, "short"), w.hit.source or "") or (W.MUTED .. "none yet|r") },
      sort = { name or "", w.max, ref or 0, low or 0, ref and w.max / ref or 0, -(w.hit and w.hit.t or 0) },
      colors = { nil, nil, nil, (low and low <= w.max) and C.green or nil, nil, hit and C.green or nil },
      icon = AL.ItemIcon(w.id), itemID = w.id, name = name,
      tip = { "Left-click: search in the auction house.", "Right-click: stop watching." },
    }
  end
  self.wtable:SetData(rows, true)
  self.winfo:SetText(string.format("%s%d watched|r%s", W.MUTED, #rows,
    hits > 0 and string.format("  %s\194\183|r  %s%d alert%s this hour|r", W.MUTED, W.GREEN, hits, hits == 1 and "" or "s") or ""))
end

AL:On("AL_WATCH", function() if UI.current == "Watch" then UI:Refresh() end end)

---------------------------------------------------------------------------
-- Sell: the bags on the left, the auction you are about to post on the right
---------------------------------------------------------------------------
local SELL_PANEL_X = 580
local SELL_ROWS = 23

local function sellSettings()
  local s = AL.db.settings
  if s.sellDuration == nil then s.sellDuration = 2 end
  if s.sellMode == nil then s.sellMode = "undercut" end
  return s
end

function UI:BuildSell(v)
  local C, Sl = W.C, AL.Sell
  local cards = CreateFrame("Frame", nil, v)
  cards:SetPoint("TOPLEFT", 0, 0)
  cards:SetSize(PAGE_W - 176, 60)
  self.sellCards = W.StatRow(cards, PAGE_W - 176, { "Worth posting", "AH value after cut", "Vendor the rest" })
  self.sjunk = W.Button(v, "Sell junk to vendor", 160, function()
    local n, total = AL.Sell:VendorJunk()
    if n > 0 then AL:Print(string.format("sold %d item stacks to the vendor for %s", n, AL.Money(total))) end
    C_Timer.After(1, function() UI:Refresh() end)
  end)
  self.sjunk:SetPoint("TOPRIGHT", -16, 0)
  self.sjunk:SetHeight(60)
  self.sjunk:SetMotionScriptsWhileDisabled(true)
  W.Tip(self.sjunk, "Sell junk to vendor", "Sells grey items and the items marked Vendor below. A vendor window must be open.")

  -- what is in the bags
  self.selltable = W.Table(v, {
    { title = "Item", width = 200, icon = true },
    { title = "Qty", width = 44, justify = "RIGHT" },
    { title = "Post at", width = 84, justify = "RIGHT" },
    { title = "AH value", width = 92, justify = "RIGHT" },
    { title = "Sold/day", width = 62, justify = "RIGHT" },
    { title = "Do", width = 68, pill = true },
  }, SELL_ROWS)
  self.selltable:SetPoint("TOPLEFT", 0, -72)
  self.selltable.sortCol, self.selltable.sortAsc = 4, false
  self.selltable.emptyText = "No tradeable items in your bags."
  self.selltable.isSelected = function(d) return d.key == UI.sellKey end
  self.selltable.onClick = function(d, btn)
    if btn == "RightButton" then
      if not AL.Deals.SearchInAH(d.name) then AL:Print("open the auction house to search for", d.name or "?") end
    else
      UI:SellSelect(d.key)
    end
  end

  -- the auction being prepared
  local PW = PAGE_W - SELL_PANEL_X + 4          -- lines up with the button above it
  local p = W.Panel(v, C.panel)
  p:SetPoint("TOPLEFT", SELL_PANEL_X, -72)
  p:SetSize(PW, (SELL_ROWS + 1) * W.ROW_H + 6)
  self.sellPanel = p
  p.icon = p:CreateTexture(nil, "ARTWORK")
  p.icon:SetSize(36, 36)
  p.icon:SetPoint("TOPLEFT", 16, -16)
  p.icon:SetTexCoord(0.08, 0.92, 0.08, 0.92)
  p.name = W.Label(p, "", "UAHFontH2")
  p.name:SetPoint("TOPLEFT", 62, -17)
  p.name:SetWidth(PW - 78)
  p.name:SetWordWrap(false)
  p.sub = W.Label(p, "", "UAHFontMuted")
  p.sub:SetPoint("TOPLEFT", 62, -38)
  p.sub:SetWidth(PW - 78)
  p.sub:SetWordWrap(false)

  local function divider(y)
    local d = p:CreateTexture(nil, "ARTWORK")
    d:SetColorTexture(C.border[1], C.border[2], C.border[3], 1)
    d:SetPoint("TOPLEFT", 16, y)
    d:SetSize(PW - 32, 1)
  end
  local function section(y, text)
    local l = W.Label(p, text, "UAHFontLabel")
    l:SetPoint("TOPLEFT", 16, y)
    return l
  end
  local function kv(y, label)
    local l = W.Label(p, label, "UAHFontMuted")
    l:SetPoint("TOPLEFT", 16, y)
    local val = W.Label(p, "", "UAHFontBody")
    val:SetPoint("TOPRIGHT", -16, y)
    val:SetJustifyH("RIGHT")
    return val
  end

  divider(-62)
  section(-72, "MARKET")
  p.lowest = kv(-90, "Cheapest from others")
  p.normal = kv(-109, "Normal price")
  p.sold = kv(-128, "Sold per day")
  p.vendor = kv(-147, "A vendor pays")

  divider(-170)
  section(-180, "CHEAPEST AUCTIONS")
  p.compAge = W.Label(p, "", "UAHFontMuted")
  p.compAge:SetPoint("TOPRIGHT", -16, -180)
  p.compAge:SetJustifyH("RIGHT")
  p.comp = {}
  for i = 1, 4 do
    local y = -198 - (i - 1) * 17
    local price = W.Label(p, "", "UAHFontBody")
    price:SetPoint("TOPLEFT", 16, y)
    price:SetWidth(PW - 150)
    price:SetWordWrap(false)
    local qty = W.Label(p, "", "UAHFontMuted")
    qty:SetPoint("TOPRIGHT", -16, y)
    qty:SetJustifyH("RIGHT")
    p.comp[i] = { price = price, qty = qty }
  end

  divider(-272)
  section(-282, "YOUR AUCTION")
  local cfg = sellSettings()
  p.price = W.Edit(p, 150, "Price each, e.g. 1g 50s", function()
    if UI.sellSetting then return end
    UI.sellEdited, UI.sellMsg = true, nil
    UI:SellSummary()
  end)
  p.price:SetPoint("TOPLEFT", 16, -300)
  p.qty = W.Edit(p, 84, "Quantity", function()
    if UI.sellSetting then return end
    UI.sellQtyEdited, UI.sellMsg = true, nil
    UI:SellSummary()
  end)
  p.qty:SetPoint("TOPLEFT", 174, -300)
  p.qty:SetNumeric(true)
  p.allBtn = W.Button(p, "All", PW - 282, function()
    UI.sellQtyEdited = false
    UI:SellPanel()
  end)
  p.allBtn:SetPoint("TOPLEFT", 266, -300)
  p.mode = W.Cycle(p, "Price", 176, Sl.MODES, function(val)
    sellSettings().sellMode = val
    UI.sellEdited = false
    UI:SellPanel()
  end)
  p.mode:SetPoint("TOPLEFT", 16, -334)
  p.time = W.Cycle(p, "Runs", PW - 216, Sl.DURATIONS, function(val)
    sellSettings().sellDuration = val
    UI:SellSummary()
  end)
  p.time:SetPoint("TOPLEFT", 200, -334)
  for i, o in ipairs(Sl.MODES) do if o[1] == cfg.sellMode then p.mode.i = i end end
  for i, o in ipairs(Sl.DURATIONS) do if o[1] == cfg.sellDuration then p.time.i = i end end
  p.mode:Refresh()
  p.time:Refresh()

  p.total = kv(-370, "Buyout")
  p.deposit = kv(-388, "Deposit")
  p.receive = kv(-406, "You receive after the 5% cut")
  p.status = W.Label(p, "", "UAHFontMuted")
  p.status:SetPoint("TOPLEFT", 16, -427)
  p.status:SetWidth(PW - 32)
  p.status:SetWordWrap(false)
  p.post = W.Button(p, "Post", PW - 32, function()
    local key = UI.sellKey
    if not key then return end
    local ok, why = Sl:Post(key, AL.ParseMoney(p.price:GetText()), tonumber(p.qty:GetText()), p.time:Value())
    UI.sellMsg = (not ok) and { why, C.red } or nil
    p.price:ClearFocus()
    p.qty:ClearFocus()
    UI:SellSummary()
  end, "primary")
  p.post:SetPoint("BOTTOMLEFT", 16, 10)
  p.post:SetHeight(30)
  p.post:SetMotionScriptsWhileDisabled(true)
  p.price:SetScript("OnEnterPressed", function(e) e:ClearFocus() end)
  p.price:SetScript("OnTabPressed", function() p.qty:SetFocus() end)
  p.qty:SetScript("OnTabPressed", function() p.price:SetFocus() end)
end

-- pick an item to post
function UI:SellSelect(key)
  if self.sellKey ~= key then
    self.sellEdited, self.sellQtyEdited, self.sellMsg = false, false, nil
  end
  self.sellKey = key
  local r = self.sellRows and self.sellRows[key]
  if r then AL.Sell:RefreshLive(key, r.id) end
  for i, d in ipairs(self.selltable.data) do if d.key == key then self.sellIdx = i end end
  self:SellPanel()
  self.selltable:Refresh()
end

local function setText(edit, text)
  UI.sellSetting = true
  edit:SetText(text or "")
  UI.sellSetting = false
end

-- fill the right-hand panel for the selected item
function UI:SellPanel()
  local p, C, Sl = self.sellPanel, W.C, AL.Sell
  if not p then return end
  local r = self.sellKey and self.sellRows and self.sellRows[self.sellKey]
  if not r then
    p.icon:Hide()
    p.name:SetText("Nothing selected")
    p.sub:SetText("Pick an item from your bags on the left.")
    for _, f in ipairs({ p.lowest, p.normal, p.sold, p.vendor, p.compAge, p.total, p.deposit, p.receive, p.status }) do f:SetText("") end
    for _, c in ipairs(p.comp) do c.price:SetText(""); c.qty:SetText("") end
    setText(p.price, ""); setText(p.qty, "")
    p.post:SetText("Post")
    p.post:SetEnabled(false)
    return
  end
  local s = AL.Suggest(r.id, r.link)
  self.sellSuggest = s
  p.icon:SetTexture(AL.ItemIcon(r.id))
  p.icon:Show()
  p.name:SetText(qtext(r.name, r.id, r.link))
  p.sub:SetText(string.format("%d in your bags", r.count))
  p.lowest:SetText(s.lowest and AL.Money(s.lowest) or (W.MUTED .. "none listed|r"))
  p.normal:SetText(s.ref and AL.Money(s.ref) or AL.Money(0))
  local sold = AL.Api and AL.Api.SoldPerDay(s.e)
  p.sold:SetText(sold and (sold > 0 and ("about " .. AL.Api.SoldText(sold)) or (W.MUTED .. "none seen|r")) or AL.Money(0))
  p.vendor:SetText(AL.Money(s.vendor or 0))

  local list, t = Sl:Competition(self.sellKey, #p.comp)
  local live = Sl.live[self.sellKey]
  p.compAge:SetText(t and ((live and "live, " or "full scan, ") .. ago(t)) or "")
  for i, c in ipairs(p.comp) do
    local x = list[i]
    if x then
      c.price:SetText(AL.Money(x[1]) .. (x[3] and ("  " .. W.ACCENT .. "yours|r") or ""))
      c.qty:SetText("x " .. (BreakUpLargeNumbers and BreakUpLargeNumbers(x[2]) or x[2]))
    else
      c.price:SetText(i == 1 and (W.MUTED .. (AL.ahOpen and "Looking up the current auctions..." or "Open the auction house for live prices.") .. "|r") or "")
      c.qty:SetText("")
    end
  end

  if not self.sellEdited then
    local price = Sl.PriceFor(s, sellSettings().sellMode)
    setText(p.price, price and AL.Money(price, true) or "")
  end
  if not self.sellQtyEdited then setText(p.qty, tostring(r.count)) end
  self:SellSummary()
end

-- totals, warnings and the Post button, from what is typed
function UI:SellSummary()
  local p, C, Sl = self.sellPanel, W.C, AL.Sell
  local r = self.sellKey and self.sellRows and self.sellRows[self.sellKey]
  if not p or not r then return end
  local s = self.sellSuggest or AL.Suggest(r.id, r.link)
  local price = AL.ParseMoney(p.price:GetText())
  local qty = tonumber(p.qty:GetText())
  local valid = price and price >= 1 and qty and qty >= 1 and qty <= r.count
  local total = valid and price * qty or nil
  p.total:SetText(total and AL.Money(total) or AL.Money(0))
  local deposit
  if valid and AL.ahOpen then deposit = Sl:Deposit(Sl:Locate(self.sellKey), p.time:Value(), qty) end
  p.deposit:SetText(deposit and AL.Money(deposit) or AL.Money(0))
  p.receive:SetText(total and AL.Money(math.floor(total * Sl.CUT), nil, W.GREEN) or AL.Money(0))
  if total then p.receive:SetTextColor(C.green[1], C.green[2], C.green[3]) else p.receive:SetTextColor(C.text[1], C.text[2], C.text[3]) end

  local msg, col, can = nil, C.muted, valid and AL.ahOpen and not Sl.posting
  if Sl.posting then msg = "Posting..."
  elseif self.sellMsg then msg, col = self.sellMsg[1], self.sellMsg[2]
  elseif not price then msg = "Type a price, e.g. 1g 50s."
  elseif not qty or qty < 1 then msg = "Type a quantity."
  elseif qty > r.count then msg, col = "You only have " .. r.count .. ".", C.red
  elseif s.lowest and price < s.lowest * 0.5 then
    msg, col = "Far below the cheapest auction (" .. AL.Money(s.lowest, "short") .. "). Check the price.", C.red
  elseif (s.vendor or 0) > 0 and price * Sl.CUT <= s.vendor then
    msg, col = "A vendor pays more: " .. AL.Money(s.vendor, "short") .. " each.", C.gold
  elseif not AL.ahOpen then msg = "Open the auction house to post."
  elseif s.reason and not self.sellEdited then msg = s.reason:sub(1, 1):upper() .. s.reason:sub(2) .. "."
  end
  p.status:SetText(msg or "")
  p.status:SetTextColor(col[1], col[2], col[3])
  p.post:SetText(total and string.format("Post %d for %s", qty, AL.Money(total, "short")) or "Post")
  p.post:SetEnabled(can and true or false)
end

function UI:RefreshSell()
  local C = W.C
  local ADVICE = { post = { "Post", C.green }, vendor = { "Vendor", C.gold }, unknown = { "No data", C.muted } }
  local rows, ah, vend, nPost, nVend = {}, 0, 0, 0, 0
  local mode = sellSettings().sellMode
  self.sellRows = {}
  for _, r in ipairs(AL.Sell:Rows()) do
    local s = r.s
    local name = (r.link and r.link:match("|h%[(.-)%]|h")) or AL.ItemName(r.id, r.link) or ("item " .. r.id)
    r.name = name
    self.sellRows[r.key] = r
    local adv = ADVICE[s.advice] or ADVICE.unknown
    local post = AL.Sell.PriceFor(s, mode)
    local proceeds = post and post * r.count * AL.Sell.CUT or 0
    if s.advice == "post" then ah = ah + proceeds; nPost = nPost + 1
    else vend = vend + r.vendorTotal; if r.vendorTotal > 0 then nVend = nVend + 1 end end
    local sold = AL.Api and AL.Api.SoldPerDay(s.e)
    local tip = { s.reason and ("Post at: " .. s.reason) or "No auction data." }
    if post then tip[#tip + 1] = string.format("%d at %s each: %s after the cut.", r.count, AL.Money(post), AL.Money(proceeds)) end
    if (s.vendor or 0) > 0 then tip[#tip + 1] = "A vendor pays " .. AL.Money(s.vendor) .. " each." end
    tip[#tip + 1] = "Click: prepare the auction.  Right-click: search in the auction house."
    rows[#rows + 1] = {
      cells = { qtext(name, r.id, r.link), r.count, post and AL.Money(post) or "", post and AL.Money(proceeds) or "",
                sold and AL.Api.SoldText(sold) or "", adv[1] },
      sort = { name, r.count, post or 0, proceeds, sold or -1, adv[1] },
      colors = { nil, nil, C.accent, nil, nil, adv[2] },
      icon = AL.ItemIcon(r.id), itemID = r.id, link = r.link, name = AL.ItemName(r.id) or name, key = r.key, tip = tip,
    }
  end
  self.selltable:SetData(rows, true)
  local c = self.sellCards
  c[1]:Set(tostring(nPost), nil, "of " .. #rows .. " stacks", C.accent)
  c[2]:Set(AL.Money(ah), C.green, nil, C.green)
  c[3]:Set(AL.Money(vend), nil, nVend .. " stacks", C.gold)
  self.sjunk:SetEnabled(MerchantFrame and MerchantFrame:IsShown() or false)
  -- keep the selection; when the item is gone (posted), move to the row that took its place
  local data = self.selltable.data
  if not (self.sellKey and self.sellRows[self.sellKey]) then
    local d = data[math.min(self.sellIdx or 1, #data)]
    self.sellKey, self.sellEdited, self.sellQtyEdited, self.sellMsg = d and d.key or nil, false, false, nil
    if d then AL.Sell:RefreshLive(d.key, d.itemID) end
  end
  for i, d in ipairs(data) do if d.key == self.sellKey then self.sellIdx = i end end
  self.selltable:Refresh()
  self:SellPanel()
end

local function sellShown() return UI.current == "Sell" and UI.frame and UI.frame:IsShown() end
AL:On("BAG_UPDATE_DELAYED", function() if sellShown() then UI:Refresh() end end)
AL:On("MERCHANT_SHOW", function() if UI.current == "Sell" then UI:Refresh() end end)
AL:On("MERCHANT_CLOSED", function() if UI.current == "Sell" then UI:Refresh() end end)
AL:On("AL_SELL_LIVE", function(key) if sellShown() and key == UI.sellKey then UI:Refresh() end end)
AL:On("AL_SELL_POSTED", function(key, ok)
  UI.sellQtyEdited = false
  UI.sellMsg = ok and { "Posted.", W.C.green } or { "Not posted. The auction house did not confirm it.", W.C.red }
  if sellShown() then UI:Refresh() end
end)
AL:On("AUCTION_HOUSE_SHOW", function()
  if not sellShown() then return end
  C_Timer.After(0.5, function()
    local r = UI.sellKey and UI.sellRows and UI.sellRows[UI.sellKey]
    if r then AL.Sell:RefreshLive(UI.sellKey, r.id) end
    UI:Refresh()
  end)
end)
AL:On("AUCTION_HOUSE_CLOSED", function() if sellShown() then UI:Refresh() end end)

---------------------------------------------------------------------------
-- Settings
---------------------------------------------------------------------------
local function S() return AL.db.settings end

function UI:BuildSettings(v)
  local groups = {
    { "TOOLTIPS", {
      { "Price lines", "Market, lowest, top-100 and 14-day averages, and what you paid / got.",
        function() return S().tooltip end, function(x) S().tooltip = x end },
      { "Post-price suggestion", "What to post an item for, and what your stack is worth.",
        function() return S().tooltipPost ~= false end, function(x) S().tooltipPost = x end },
    } },
    { "CHAT", {
      { "Answer 'AH <item>' in guild chat", "Replies with our prices. Several addon users never answer twice.",
        function() return AL.Guild:Enabled() end, function(x) S().guildReply = x end },
      { "Answer 'AH <item>' whispers", "'AH Silk Cloth x20' whispered to you gets the price and the cost of 20.",
        function() return AL.Guild:WhisperEnabled() end, function(x) S().whisperReply = x end },
    } },
    { "AUCTION HOUSE", {
      { "Full Scan when I open the AH", "Only when the 15-minute cooldown allows it.",
        function() return S().autoScan end, function(x) S().autoScan = x end },
      { "Tell me about undercut auctions", "After each Full Scan: which of your auctions someone listed cheaper.",
        function() return S().undercutNotice ~= false end, function(x) S().undercutNotice = x end },
      { "Watchlist: raid warning and sound", "Off = only a chat line when a watched item is cheap.",
        function() return S().watchAlert ~= false end, function(x) S().watchAlert = x end },
      { "Sell junk when I open a vendor", "Grey items, and items a vendor pays more for than the AH would.",
        function() return S().autoJunk end, function(x) S().autoJunk = x end },
    } },
    { "OTHER", {
      { "Minimap button", "Left-click opens this window, right-click the value graph.",
        function() return not S().hideMinimap end, function(x) S().hideMinimap = not x; if UI.mmb then UI.mmb:SetShown(x) end end },
      { "Debug messages", "For troubleshooting.", function() return S().debug end, function(x) S().debug = x end },
    } },
  }
  self.checks = {}
  local y = 0
  for _, g in ipairs(groups) do
    local h = W.Label(v, g[1], "UAHFontLabel")
    h:SetPoint("TOPLEFT", 0, y)
    y = y - 18
    for _, o in ipairs(g[2]) do
      local c = W.Toggle(v, o[1], o[2], o[3], o[4], 460)
      c:SetPoint("TOPLEFT", 0, y)
      y = y - 42
      self.checks[#self.checks + 1] = c
    end
    y = y - 8
  end

  -- right column: stored data
  local x = 520
  local panel = W.Panel(v, W.C.panel)
  panel:SetPoint("TOPLEFT", x, 0)
  panel:SetSize(PAGE_W - x - 16, 252)
  local h = W.Label(panel, "STORED DATA", "UAHFontLabel")
  h:SetPoint("TOPLEFT", 16, -14)
  self.sstats = {}
  local labels = { "Ledger rows", "Characters", "Priced items", "Daily price points", "Value snapshots", "Watched items", "Last scan" }
  for i, l in ipairs(labels) do
    local k = W.Label(panel, l, "UAHFontMuted")
    k:SetPoint("TOPLEFT", 16, -16 - i * 26)
    local val = W.Label(panel, "", "UAHFontBody")
    val:SetPoint("TOPRIGHT", -16, -16 - i * 26)
    val:SetJustifyH("RIGHT")
    self.sstats[i] = val
    if i < #labels then
      local ln = panel:CreateTexture(nil, "BORDER")
      ln:SetColorTexture(1, 1, 1, 0.04)
      ln:SetPoint("TOPLEFT", 16, -16 - i * 26 - 18)
      ln:SetPoint("TOPRIGHT", -16, -16 - i * 26 - 18)
      ln:SetHeight(1)
    end
  end
  local clear = W.Button(panel, "Clear price data", 150, function()
    StaticPopup_Show("ULTIMATEAH_CONFIRM", "all scanned prices and price history", nil,
      function() AL.db.prices[AL:Scope()] = {}; AL.db.deals = {}; AL:Print("price data cleared"); UI:Refresh() end)
  end)
  clear:SetPoint("BOTTOMLEFT", 16, 14)
  local reset = W.Button(panel, "Clear watch alerts", 150, function()
    for _, w in pairs(AL.Watch:List()) do w.hit, w.lastAlert = nil, nil end
    UI:Refresh()
  end)
  reset:SetPoint("LEFT", clear, "RIGHT", 8, 0)
  local note = W.Label(v, "Data is shared by all characters on this WoW account. Characters on another account can be merged " ..
    "with sync_accounts.py (see the README).", "UAHFontMuted")
  note:SetPoint("TOPLEFT", panel, "BOTTOMLEFT", 0, -12)
  note:SetWidth(PAGE_W - x - 16)
  local cmds = W.Label(v, "Commands  /uah  /uah scan [quick|deep]  /uah watch <item> <price>  /uah sell  /uah junk  /uah deals  " ..
    "/uah value  /uah price <item>  /uah ah <item> [x20]  /uah help", "UAHFontMuted")
  cmds:SetPoint("TOPLEFT", note, "BOTTOMLEFT", 0, -10)
  cmds:SetWidth(PAGE_W - x - 16)
end

function UI:RefreshSettings()
  for _, c in ipairs(self.checks) do c:Sync() end
  local nPrices, nHist = 0, 0
  for _, e in pairs(AL.db.prices[AL:Scope()] or {}) do
    nPrices = nPrices + 1
    for _ in pairs(e.h or {}) do nHist = nHist + 1 end
  end
  local nChars, nSnaps = 0, 0
  for _ in pairs(AL.db.chars) do nChars = nChars + 1 end
  for _, list in pairs(AL.db.value or {}) do nSnaps = nSnaps + #list end
  local nWatch = 0
  for _ in pairs(AL.Watch:List()) do nWatch = nWatch + 1 end
  local sc = AL.db.scans[AL:Scope()]
  local vals = { #AL.db.tx, nChars, nPrices, nHist, nSnaps, nWatch, sc and ((sc.kind or "") .. ", " .. ago(sc.t)) or "never" }
  for i, v in ipairs(vals) do
    self.sstats[i]:SetText(type(v) == "number" and (BreakUpLargeNumbers and BreakUpLargeNumbers(v) or tostring(v)) or v)
  end
end

StaticPopupDialogs["ULTIMATEAH_CONFIRM"] = {
  text = "Ultimate AH: delete %s?\n\nThis cannot be undone.",
  button1 = YES or "Yes", button2 = NO or "No",
  OnAccept = function(_, fn) if type(fn) == "function" then fn() end end,
  timeout = 0, whileDead = true, hideOnEscape = true, preferredIndex = 3,
}
