-- AuctionLedger: developer console (/al x <lua>) used while building and testing
local _, AL = ...

local panel, text
local lines = {}
local MAXLINES = 40

local function ensurePanel()
  if panel then return end
  panel = CreateFrame("Frame", "AuctionLedgerDevPanel", UIParent, "BackdropTemplate")
  panel:SetSize(760, 560)
  panel:SetPoint("TOPLEFT", UIParent, "TOPLEFT", 560, -60)
  panel:SetFrameStrata("TOOLTIP")
  panel:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8x8", edgeFile = "Interface\\Buttons\\WHITE8x8", edgeSize = 1 })
  panel:SetBackdropColor(0, 0, 0, 0.92)
  panel:SetBackdropBorderColor(0.2, 0.8, 1, 1)
  text = panel:CreateFontString(nil, "OVERLAY")
  text:SetFont("Fonts\\ARIALN.TTF", 13, "")
  text:SetPoint("TOPLEFT", 8, -8)
  text:SetPoint("BOTTOMRIGHT", -8, 8)
  text:SetJustifyH("LEFT")
  text:SetJustifyV("TOP")
  text:SetWordWrap(true)
  panel:Hide()
end

local function refresh()
  if not panel then return end
  local rev = {}
  for i = #lines, 1, -1 do rev[#rev + 1] = lines[i] end      -- newest first
  text:SetText(table.concat(rev, "\n"))
end

function AL.DevLog(s)
  for line in tostring(s):gmatch("[^\n]+") do
    table.insert(lines, line)
    if #lines > MAXLINES then table.remove(lines, 1) end
  end
  refresh()
end

local function dump(v, depth, seen)
  depth = depth or 0
  local t = type(v)
  if t == "string" then return string.format("%q", v):gsub("|", "||") end
  if t ~= "table" then return tostring(v) end
  seen = seen or {}
  if seen[v] or depth > 2 then return "{...}" end
  seen[v] = true
  local parts, n = {}, 0
  for k, val in pairs(v) do
    n = n + 1
    if n > 40 then parts[#parts + 1] = "..."; break end
    parts[#parts + 1] = tostring(k) .. "=" .. dump(val, depth + 1, seen)
  end
  return "{" .. table.concat(parts, ", ") .. "}"
end
AL.Dump = dump

local function eval(code)
  local fn, err = loadstring("return " .. code)
  if not fn then fn, err = loadstring(code) end
  if not fn then return "compile error: " .. tostring(err) end
  setfenv(fn, setmetatable({ AL = AL, dump = dump, log = AL.DevLog }, { __index = _G }))
  local res = { pcall(fn) }
  if not res[1] then return "runtime error: " .. tostring(res[2]) end
  local out = {}
  for i = 2, select("#", unpack(res)) do out[#out + 1] = dump(res[i]) end
  return #out > 0 and table.concat(out, "  |  ") or "(no value)"
end

-- test helpers (chat lines are limited to 255 characters, so longer steps live here)
local D = {}
AL.D = D
local A = C_AuctionHouse

function D.watch()
  if D.watching then return "already" end
  D.watching = true
  local f = CreateFrame("Frame")
  for _, e in ipairs({ "AUCTION_HOUSE_THROTTLED_MESSAGE_DROPPED", "AUCTION_HOUSE_THROTTLED_MESSAGE_QUEUED",
    "AUCTION_HOUSE_THROTTLED_MESSAGE_RESPONSE_RECEIVED", "AUCTION_HOUSE_THROTTLED_MESSAGE_SENT",
    "AUCTION_HOUSE_THROTTLED_SYSTEM_READY", "AUCTION_HOUSE_BROWSE_RESULTS_UPDATED", "ITEM_SEARCH_RESULTS_UPDATED",
    "COMMODITY_SEARCH_RESULTS_UPDATED", "AUCTION_HOUSE_PURCHASE_COMPLETED", "ITEM_PURCHASED", "BID_ADDED",
    "AUCTION_HOUSE_SHOW_ERROR", "AUCTION_HOUSE_SHOW_NOTIFICATION", "AUCTION_HOUSE_SHOW_FORMATTED_NOTIFICATION",
    "COMMODITY_PURCHASED", "COMMODITY_PURCHASE_SUCCEEDED", "AUCTION_HOUSE_AUCTION_CREATED", "MAIL_INBOX_UPDATE" }) do
    pcall(f.RegisterEvent, f, e)
  end
  f:SetScript("OnEvent", function(_, e, a, b)
    if e == "MAIL_INBOX_UPDATE" and D.lastMail and GetTime() - D.lastMail < 2 then return end
    if e == "MAIL_INBOX_UPDATE" then D.lastMail = GetTime() end
    AL.DevLog(date("%X ") .. e:gsub("AUCTION_HOUSE_", "AH_") .. " " .. tostring(type(a) == "table" and (a.itemID or "tbl") or a or "") .. " " .. tostring(b or ""))
  end)
  return "watching"
end

-- browse for a name, remember the item key of `itemID`, then item-search it
function D.find(name, itemID)
  D.key = nil
  A.SendBrowseQuery({ searchString = name, sorts = {}, filters = {}, itemClassFilters = {} })
  local tries = 0
  local function poll()
    tries = tries + 1
    for _, r in ipairs(A.GetBrowseResults() or {}) do
      if r.itemKey.itemID == itemID then
        D.key = r.itemKey
        AL.DevLog("key " .. AL.Dump(r.itemKey) .. " min " .. tostring(r.minPrice) .. " qty " .. tostring(r.totalQuantity))
        A.SendSearchQuery(r.itemKey, { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } }, true)
        return
      end
    end
    if tries < 20 then C_Timer.After(0.5, poll) else AL.DevLog("find: no browse result") end
  end
  C_Timer.After(0.5, poll)
  return "searching " .. name
end

-- the cheapest few auctions of the remembered key
function D.list(n)
  if not D.key then return "no key" end
  local out = {}
  for i = 1, math.min(n or 5, A.GetNumItemSearchResults(D.key)) do
    local r = A.GetItemSearchResultInfo(D.key, i)
    out[#out + 1] = string.format("#%d id%d q%d buy %s%s", i, r.auctionID, r.quantity, AL.Money(r.buyoutAmount or 0, true),
      r.containsOwnerItem and " (MINE)" or "")
  end
  return A.GetNumItemSearchResults(D.key) .. " results: " .. table.concat(out, "; ")
end

-- buy result #i of the remembered key at its buyout, if it costs at most maxCopper
function D.buy(i, maxCopper)
  local r = D.key and A.GetItemSearchResultInfo(D.key, i)
  if not r then return "no such result" end
  if r.containsOwnerItem then return "that is your own auction" end
  if not r.buyoutAmount or r.buyoutAmount > maxCopper then return "too expensive: " .. AL.Money(r.buyoutAmount or 0, true) end
  A.PlaceBid(r.auctionID, r.buyoutAmount)
  return "bid placed on " .. r.auctionID .. " for " .. AL.Money(r.buyoutAmount, true)
end

-- temporary sample rows to look at the Ledger/Summary layout; removed again with D.unfake()
function D.fake()
  local now = time()
  local me = AL:Me()
  local rows = {
    { type = "buy", item = 4306, qty = 20, total = 3600, unit = 180, src = "ah", t = now - 7200 },
    { type = "post", item = 4306, qty = 20, total = 6000, unit = 300, deposit = 120, src = "ah", t = now - 7000 },
    { type = "sell", item = 4306, qty = 20, total = 6000, unit = 300, cut = 300, deposit = 120, buyer = "Someone", src = "mail", t = now - 3600 },
    { type = "sell", item = 2318, qty = 5, total = 1500, unit = 300, provisional = true, src = "notice", t = now - 60 },
    { type = "cancel", item = 2318, qty = 5, total = 1500, unit = 300, fee = 0, src = "ah", t = now - 30 },
  }
  for _, r in ipairs(rows) do r.fake = true; r.char = me.name; AL:AddTx(r) end
  table.sort(AL.db.tx, function(a, b) return (a.t or 0) < (b.t or 0) end)
  return "added " .. #rows
end

function D.unfake()
  local n = 0
  for i = #AL.db.tx, 1, -1 do if AL.db.tx[i].fake then table.remove(AL.db.tx, i); n = n + 1 end end
  AL:Fire("AL_TX_ADDED")
  return "removed " .. n
end

AL:Command("x", nil, function(code)
  ensurePanel()
  panel:Show()
  if code == "off" then panel:Hide(); ClearOverrideBindings(panel); return end
  if code == "clear" then wipe(lines); refresh(); return end
  if code == "" then return end
  -- F11 = interact with target while the dev console is open (used to reopen the AH after a reload)
  SetOverrideBinding(panel, true, "F11", "INTERACTTARGET")
  AL.DevLog("> " .. code)
  AL.DevLog(eval(code))
end)
