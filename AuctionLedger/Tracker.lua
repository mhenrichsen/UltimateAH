-- AuctionLedger: records buys, posts, cancels, sales and expiries
--
-- Buys are recorded at the auction house the moment the server confirms them.
-- Sales are recorded from the "Auction successful" mail invoice (exact price and AH cut),
-- with a provisional entry as soon as the "A buyer has been found" message arrives.
local _, AL = ...
local T = {}
AL.Tracker = T

local AH = C_AuctionHouse

local function now() return time() end
local function itemInfoFromLocation(loc)
  if not loc then return nil end
  local ok, link = pcall(C_Item.GetItemLink, loc)
  local ok2, id = pcall(C_Item.GetItemID, loc)
  return ok2 and id or AL.ItemID(ok and link), ok and link or nil
end

---------------------------------------------------------------------------
-- caches filled from AH results, so a bid/buyout can be tied to an item
---------------------------------------------------------------------------
local auctionCache = {}   -- auctionID -> { itemID, link, qty, buyout(unit for commodities?) }
local cacheCount = 0

local function cacheAuction(id, rec)
  if not id then return end
  if not auctionCache[id] then cacheCount = cacheCount + 1 end
  auctionCache[id] = rec
  if cacheCount > 4000 then wipe(auctionCache); cacheCount = 0 end
end

AL:On("ITEM_SEARCH_RESULTS_UPDATED", function(itemKey)
  if not itemKey then return end
  local n = AH.GetNumItemSearchResults(itemKey) or 0
  for i = 1, n do
    local r = AH.GetItemSearchResultInfo(itemKey, i)
    if r and r.auctionID then
      cacheAuction(r.auctionID, { itemID = itemKey.itemID, link = r.itemLink, qty = r.quantity or 1,
                                   buyout = r.buyoutAmount, bid = r.bidAmount or r.minBid })
    end
  end
end)
AL:On("ITEM_SEARCH_RESULTS_ADDED", function(itemKey) AL:Fire("ITEM_SEARCH_RESULTS_UPDATED", itemKey) end)

local function lookupAuction(auctionID)
  local c = auctionCache[auctionID]
  local ok, info = pcall(AH.GetAuctionInfoByID, auctionID)
  if ok and info then
    c = c or {}
    c.itemID = c.itemID or (info.itemKey and info.itemKey.itemID)
    c.link = c.link or info.itemLink
    c.buyout = c.buyout or info.buyoutAmount
    c.bid = c.bid or info.bidAmount or info.minBid
    c.qty = c.qty or 1
  end
  return c
end

---------------------------------------------------------------------------
-- buying: commodities
---------------------------------------------------------------------------
local pc   -- pending commodity purchase

hooksecurefunc(AH, "StartCommoditiesPurchase", function(itemID, quantity)
  pc = { itemID = itemID, qty = quantity, t = now() }
end)

AL:On("COMMODITY_PRICE_UPDATED", function(unit, total)
  if pc then pc.unit, pc.total = unit, total end
end)

hooksecurefunc(AH, "ConfirmCommoditiesPurchase", function(itemID, quantity)
  if not pc or pc.itemID ~= itemID then pc = { itemID = itemID, qty = quantity, t = now() } end
  pc.qty = quantity
  pc.confirmed = now()
end)

hooksecurefunc(AH, "CancelCommoditiesPurchase", function() if pc and not pc.confirmed then pc = nil end end)

local function recordCommodityBuy(itemID, qty)
  if not pc or pc.done then return end
  if itemID and pc.itemID ~= itemID then return end
  qty = qty or pc.qty
  local total = pc.total
  if total and pc.qty and pc.qty > 0 and qty ~= pc.qty then total = math.floor(total * qty / pc.qty + 0.5) end
  if not total and pc.unit then total = pc.unit * qty end
  pc.done = true
  AL:AddTx({ type = "buy", item = pc.itemID, qty = qty, total = total,
             unit = total and qty > 0 and math.floor(total / qty + 0.5) or nil, src = "ah" })
  AL:Debug("bought", qty, "x", pc.itemID, "for", AL.Money(total or 0, true))
end

AL:On("COMMODITY_PURCHASED", function(itemID, quantity) recordCommodityBuy(itemID, quantity) end)
AL:On("COMMODITY_PURCHASE_SUCCEEDED", function()
  -- COMMODITY_PURCHASED normally carries the exact quantity; give it a moment first
  C_Timer.After(0.5, function() recordCommodityBuy(nil, nil) end)
end)
AL:On("COMMODITY_PURCHASE_FAILED", function() if pc and not pc.done then pc = nil end end)

---------------------------------------------------------------------------
-- buying: items (buyout or bid)
---------------------------------------------------------------------------
local pendingBids = {}    -- auctionID -> info

hooksecurefunc(AH, "PlaceBid", function(auctionID, bidAmount)
  local c = lookupAuction(auctionID) or {}
  local isBuyout = c.buyout and c.buyout > 0 and bidAmount >= c.buyout
  pendingBids[auctionID] = { itemID = c.itemID, link = c.link, qty = c.qty or 1, amount = bidAmount,
                             buyout = isBuyout, t = now() }
end)

local function finishItemBuy(auctionID)
  local p = pendingBids[auctionID]
  if not p or p.done then return end
  p.done = true
  AL:AddTx({ type = "buy", item = p.itemID, link = p.link, qty = p.qty, total = p.amount,
             unit = math.floor(p.amount / math.max(p.qty, 1) + 0.5), src = "ah" })
end

AL:On("AUCTION_HOUSE_PURCHASE_COMPLETED", function(auctionID) finishItemBuy(auctionID) end)

AL:On("ITEM_PURCHASED", function(itemID)
  for id, p in pairs(pendingBids) do
    if p.buyout and not p.done and p.itemID == itemID and now() - p.t < 30 then finishItemBuy(id); return end
  end
end)

-- a plain bid (not a buyout) that the server accepted: note it, the buy itself comes from the "Auction won" mail
AL:On("BID_ADDED", function(bidID)
  local p = pendingBids[bidID]
  if p and not p.buyout and not p.done then
    p.done = true
    AL:AddTx({ type = "bid", item = p.itemID, link = p.link, qty = p.qty, total = p.amount,
               unit = math.floor(p.amount / math.max(p.qty, 1) + 0.5), src = "ah" })
  end
end)

---------------------------------------------------------------------------
-- posting
---------------------------------------------------------------------------
local pp   -- pending post

local function startPost(loc, duration, quantity, unit, total, isCommodity)
  local itemID, link = itemInfoFromLocation(loc)
  local deposit
  pcall(function()
    if isCommodity then deposit = AH.CalculateCommodityDeposit(itemID, duration, quantity)
    else deposit = AH.CalculateItemDeposit(loc, duration, quantity) end
  end)
  pp = { itemID = itemID, link = link, qty = quantity, unit = unit, total = total, duration = duration,
         deposit = deposit, t = now() }
end

hooksecurefunc(AH, "PostCommodity", function(loc, duration, quantity, unitPrice)
  startPost(loc, duration, quantity, unitPrice, unitPrice * quantity, true)
end)
hooksecurefunc(AH, "ConfirmPostCommodity", function(loc, duration, quantity, unitPrice)
  if not pp then startPost(loc, duration, quantity, unitPrice, unitPrice * quantity, true) end
end)
hooksecurefunc(AH, "PostItem", function(loc, duration, quantity, bid, buyout)
  local each = buyout or bid or 0
  startPost(loc, duration, quantity, each, each * quantity, false)
  pp.bid = bid
end)
hooksecurefunc(AH, "ConfirmPostItem", function(loc, duration, quantity, bid, buyout)
  if not pp then
    local each = buyout or bid or 0
    startPost(loc, duration, quantity, each, each * quantity, false)
  end
end)
hooksecurefunc(AH, "CancelSell", function() pp = nil end)

local function recordPost()
  if not pp or now() - pp.t > 60 then pp = nil; return end
  local p = pp
  pp = nil
  AL:AddTx({ type = "post", item = p.itemID, link = p.link, qty = p.qty, unit = p.unit, total = p.total,
             deposit = p.deposit, duration = p.duration, src = "ah" })
end

AL:On("AUCTION_HOUSE_AUCTION_CREATED", function() recordPost() end)
AL:On("AUCTION_HOUSE_POST_ERROR", function() pp = nil end)

---------------------------------------------------------------------------
-- cancelling
---------------------------------------------------------------------------
local pendingCancel = {}

hooksecurefunc(AH, "CancelAuction", function(auctionID)
  local rec
  local ok, list = pcall(AH.GetOwnedAuctions)
  if ok and list then
    for _, a in ipairs(list) do
      if a.auctionID == auctionID then rec = a; break end
    end
  end
  local cost
  pcall(function() cost = AH.GetCancelCost(auctionID) end)
  pendingCancel[auctionID] = { itemID = rec and rec.itemKey and rec.itemKey.itemID, link = rec and rec.itemLink,
                               qty = rec and rec.quantity or 1, buyout = rec and rec.buyoutAmount, fee = cost, t = now() }
end)

AL:On("AUCTION_CANCELED", function(auctionID)
  local p = pendingCancel[auctionID]
  if not p then return end
  pendingCancel[auctionID] = nil
  local q = math.max(p.qty or 1, 1)
  AL:AddTx({ type = "cancel", item = p.itemID, link = p.link, qty = q, total = p.buyout,
             unit = p.buyout and math.floor(p.buyout / q + 0.5), fee = p.fee, src = "ah" })
end)

---------------------------------------------------------------------------
-- my active auctions (shown on the Listings tab for every character)
---------------------------------------------------------------------------
local function snapshotOwned()
  local ok, list = pcall(AH.GetOwnedAuctions)
  if not ok or not list then return end
  -- an empty list only counts when the AH says the list is complete (else it just hasn't arrived)
  if #list == 0 then
    local okFull, full = pcall(AH.HasFullOwnedAuctionResults)
    if not (okFull and full) then return end
  end
  local out = {}
  for _, a in ipairs(list) do
    local id = a.itemKey and a.itemKey.itemID
    -- on Forever buyoutAmount is the price of the whole stack
    local q = a.quantity or 1
    out[#out + 1] = { id = id, aid = a.auctionID, link = a.itemLink, name = AL.ItemName(id, a.itemLink), qty = q,
                      buyout = a.buyoutAmount, unit = a.buyoutAmount and q > 0 and a.buyoutAmount / q or nil,
                      bid = a.bidAmount, sold = (a.status == 1) or nil, left = a.timeLeftSeconds }
  end
  AL.db.listings = AL.db.listings or {}
  AL.db.listings[AL:CharKey()] = { t = now(), list = out }
  -- sold auctions waiting in the mail: make sure each has a provisional sale in the ledger
  -- (one may already exist from the "buyer found" message; it gets this auction's ID)
  AL.db.soldSeen = AL.db.soldSeen or {}
  local me = AL:Me().name
  local added = false
  for i, a in ipairs(list) do
    if a.status == 1 and a.auctionID and not AL.db.soldSeen[a.auctionID] then
      AL.db.soldSeen[a.auctionID] = now()
      local name = out[i].name
      local r
      for j = #AL.db.tx, math.max(1, #AL.db.tx - 2000), -1 do
        local x = AL.db.tx[j]
        if x.type == "sell" and x.provisional and not x.auctionID and x.char == me and x.name == name then r = x; break end
      end
      local q = math.max(a.quantity or 1, 1)
      if r then
        r.auctionID = a.auctionID
        r.qty, r.total = q, a.buyoutAmount or r.total
        r.unit = r.total and math.floor(r.total / q + 0.5)
      else
        AL:AddTx({ type = "sell", provisional = true, name = name, item = out[i].id, link = a.itemLink, qty = q,
                   total = a.buyoutAmount, unit = a.buyoutAmount and math.floor(a.buyoutAmount / q + 0.5),
                   auctionID = a.auctionID, src = "listing" })
        added = true
      end
    end
  end
  local cutoff = now() - 40 * 86400
  for id, t in pairs(AL.db.soldSeen) do if t < cutoff then AL.db.soldSeen[id] = nil end end
  if added then AL:Fire("AL_TX_ADDED") end
  AL:Fire("AL_LISTINGS")
end
AL:On("OWNED_AUCTIONS_UPDATED", snapshotOwned)

-- refresh my auctions when the AH opens (retry for a while if the AH is busy)
AL:On("AUCTION_HOUSE_SHOW", function()
  local tries = 0
  local function ask()
    if not AL.ahOpen then return end
    tries = tries + 1
    if AH.IsThrottledMessageSystemReady() then
      pcall(AH.QueryOwnedAuctions, {})
    elseif tries < 10 then
      C_Timer.After(2, ask)
    end
  end
  C_Timer.After(1.5, ask)
end)

---------------------------------------------------------------------------
-- chat messages: sold / won / expired
---------------------------------------------------------------------------
local P_SOLD = AL.FormatToPattern(ERR_AUCTION_SOLD_S)
local P_EXPIRED = AL.FormatToPattern(ERR_AUCTION_EXPIRED_S)

local function listedUnitPrice(name)
  local mine = AL.db.listings and AL.db.listings[AL:CharKey()]
  if not mine then return nil end
  for _, a in ipairs(mine.list) do
    if a.name == name and not a.sold and a.buyout and a.buyout > 0 then
      return a.buyout / math.max(a.qty or 1, 1), a.qty, a.id
    end
  end
end

AL:On("CHAT_MSG_SYSTEM", function(msg)
  if not msg then return end
  local sold = P_SOLD and msg:match(P_SOLD)
  if sold then
    local unit, qty, id = listedUnitPrice(sold)
    AL:AddTx({ type = "sell", provisional = true, name = sold, item = id, qty = qty,
               unit = unit and math.floor(unit + 0.5), total = unit and qty and math.floor(unit * qty + 0.5) or nil, src = "notice" })
    return
  end
end)

---------------------------------------------------------------------------
-- mail invoices: the authoritative sale price, AH cut, won auctions, expiries
---------------------------------------------------------------------------
local P_EXPIRED_MAIL = AL.FormatToPattern(AUCTION_EXPIRED_MAIL_SUBJECT)
local P_WON_MAIL = AL.FormatToPattern(AUCTION_WON_MAIL_SUBJECT)
local P_SOLD_MAIL = AL.FormatToPattern(AUCTION_SOLD_MAIL_SUBJECT)
local MAIL_DAYS = 30
local SIG_WINDOW = 3 * 3600

local function seen(sig, t)
  local list = AL.db.invoices[sig]
  if list then
    for _, x in ipairs(list) do if math.abs(x - t) < SIG_WINDOW then return true end end
  end
  return false
end

local function remember(sig, t)
  AL.db.invoices[sig] = AL.db.invoices[sig] or {}
  table.insert(AL.db.invoices[sig], t)
end

function T:PruneInvoices()
  local cutoff = now() - 45 * 86400
  for sig, list in pairs(AL.db.invoices) do
    for i = #list, 1, -1 do if list[i] < cutoff then table.remove(list, i) end end
    if #list == 0 then AL.db.invoices[sig] = nil end
  end
end

-- the sale/expiry time from the mail's remaining days
local function mailTime(daysLeft)
  return math.floor(now() - (MAIL_DAYS - (daysLeft or MAIL_DAYS)) * 86400)
end

local function findProvisional(name, char)
  for i = #AL.db.tx, math.max(1, #AL.db.tx - 3000), -1 do
    local r = AL.db.tx[i]
    if r.type == "sell" and r.provisional and r.char == char and r.name == name then return r end
  end
end

-- an "Auction won" mail for something already recorded at the AH (one commodity purchase can
-- arrive as several mails, one per seller, so the mails' amounts are summed against the buy)
local function matchAhBuy(name, char, amount, t)
  amount = amount or 0
  for i = #AL.db.tx, math.max(1, #AL.db.tx - 3000), -1 do
    local r = AL.db.tx[i]
    if r.type == "buy" and r.src == "ah" and r.char == char and r.total and (r.name == name or not r.name)
       and (r.mailedAmt or 0) + amount <= r.total + 1 and math.abs((r.t or 0) - t) < 3 * 86400 then
      r.mailedAmt = (r.mailedAmt or 0) + amount
      return r
    end
  end
end

local function scanInbox()
  if not AL.db then return end
  local me = AL:Me().name
  local n = GetInboxNumItems() or 0
  local added = 0
  for i = 1, n do
    local _, _, sender, subject, money, _, daysLeft = GetInboxHeaderInfo(i)
    local invoiceType, itemName, player, bid, buyout, deposit, consignment, _, _, _, count = GetInboxInvoiceInfo(i)
    local t = mailTime(daysLeft)
    if invoiceType == "seller" and itemName then
      local sig = table.concat({ "S", me, itemName, player or "", bid or 0, count or 1 }, "|")
      if not seen(sig, t) then
        remember(sig, t)
        local total = bid or 0
        local qty = count or 1
        local r = findProvisional(itemName, me)
        if r then
          r.provisional = nil
          r.t = t
        else
          r = AL:AddTx({ type = "sell", name = itemName, t = t })
        end
        r.qty, r.total, r.unit = qty, total, math.floor(total / math.max(qty, 1) + 0.5)
        r.cut, r.deposit, r.buyer, r.src = consignment, deposit, player, "mail"
        r.item = r.item or AL:IdForName(itemName)
        added = added + 1
      end
    elseif invoiceType == "buyer" and itemName then
      local sig = table.concat({ "B", me, itemName, player or "", bid or 0, count or 1 }, "|")
      if not seen(sig, t) then
        remember(sig, t)
        local r = matchAhBuy(itemName, me, bid, t)
        if not r then
          AL:AddTx({ type = "buy", name = itemName, item = AL:IdForName(itemName), qty = count or 1, total = bid,
                     unit = bid and math.floor(bid / math.max(count or 1, 1) + 0.5), seller = player, src = "mail", t = t })
          added = added + 1
        end
      end
    elseif subject and P_EXPIRED_MAIL then
      local name = subject:match(P_EXPIRED_MAIL)
      if name then
        local sig = "E|" .. me .. "|" .. subject
        if not seen(sig, t) then
          remember(sig, t)
          local _, _, _, cnt = GetInboxItem(i, 1)
          AL:AddTx({ type = "expired", name = name, item = AL:IdForName(name), qty = cnt, src = "mail", t = t })
          added = added + 1
        end
      end
    end
  end
  if added > 0 then
    AL:Debug("mail: recorded", added, "auction mails")
    table.sort(AL.db.tx, function(a, b) return (a.t or 0) < (b.t or 0) end)
    AL:Fire("AL_TX_ADDED")
  end
end
T.ScanInbox = scanInbox

local inboxPending
AL:On("MAIL_INBOX_UPDATE", function()
  if inboxPending then return end
  inboxPending = true
  C_Timer.After(0.3, function() inboxPending = false; pcall(scanInbox) end)
end)

AL:On("AL_DB_READY", function() T:PruneInvoices() end)

---------------------------------------------------------------------------
-- name -> itemID (mail invoices carry only the item name)
---------------------------------------------------------------------------
local nameIndex
function AL:IdForName(name)
  if not name then return nil end
  if not nameIndex then
    nameIndex = {}
    for _, r in ipairs(self.db.tx) do if r.item and r.name then nameIndex[r.name] = r.item end end
    for _, scope in pairs(self.db.prices) do
      for _, p in pairs(scope) do if p.n and p.i then nameIndex[p.n] = nameIndex[p.n] or p.i end end
    end
  end
  local id = nameIndex[name]
  if not id and C_Item.GetItemInfoInstant then
    local x = C_Item.GetItemInfoInstant(name)
    if type(x) == "number" then id = x end
  end
  if id then nameIndex[name] = id end
  return id
end
AL:On("AL_TX_ADDED", function(r) if r and r.item and r.name and nameIndex then nameIndex[r.name] = r.item end end)
