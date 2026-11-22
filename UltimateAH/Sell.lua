-- Ultimate AH: what to do with the things in your bags
--
-- For every tradeable item: what it would fetch on the AH (after the 5% cut) versus a vendor, and
-- a suggested buyout price. The suggestion undercuts the cheapest auction from someone else by
-- 1 copper, unless that auction is far below the normal price - then racing it to the bottom is a
-- loss, and the normal price is suggested instead (it sells once the cheap ones are gone).
local _, AL = ...
local Sl = {}
AL.Sell = Sl

local CUT = 0.95
local FLOOR = 0.8          -- don't undercut below 80% of the normal price

local function vendorPrice(itemID)
  local ok, _, _, _, _, _, _, _, _, _, _, sell = pcall(C_Item.GetItemInfo, itemID)
  return ok and sell or 0
end
Sl.VendorPrice = vendorPrice

-- the normal price of an item: 14-day average, else the top-100 average, else market
function Sl.Reference(e)
  if not e then return nil end
  local days = 0
  for _ in pairs(e.h or {}) do days = days + 1 end
  local avg = AL.Scanner.HistoryAvg(e, 14)
  if avg and days >= 2 then return avg end
  return e.top or e.mkt or e.min
end

-- -> { post, reason, ref, lowest, vendor, advice ("post" / "vendor" / "hold"), e }
function AL.Suggest(itemID, link)
  local e = AL.Scanner:ForItem(link or itemID)
  local vendor = vendorPrice(itemID)
  local out = { vendor = vendor, e = e }
  if not e then
    out.advice = vendor > 0 and "vendor" or "unknown"
    out.reason = "no auction data - scan the AH"
    return out
  end
  local ref = Sl.Reference(e)
  local lowest = e.minOther or e.min
  out.ref, out.lowest = ref, lowest
  if lowest and ref and lowest >= ref * FLOOR then
    out.post = math.max(1, math.floor(lowest) - 1)
    out.reason = "1c under the cheapest auction"
  elseif ref then
    out.post = math.floor(ref)
    out.reason = string.format("cheapest is only %d%% of normal - post at the normal price", math.floor((lowest or 0) / ref * 100 + 0.5))
  elseif lowest then
    out.post = math.max(1, math.floor(lowest) - 1)
    out.reason = "1c under the cheapest auction"
  end
  if out.post then
    if vendor > 0 and vendor >= out.post * CUT then out.advice = "vendor"
    else out.advice = "post" end
  else
    out.advice = vendor > 0 and "vendor" or "unknown"
  end
  return out
end

-- every sellable stack in this character's bags, grouped by price key
function Sl:Rows()
  AL.Value:ReadBags()
  local bags = AL.Value:Inv().bags or {}
  local out = {}
  for key, it in pairs(bags) do
    local id, count, link = it[1], it[2], it[3]
    local s = AL.Suggest(id, link)
    local proceeds = s.post and s.post * count * CUT or 0
    out[#out + 1] = { key = key, id = id, count = count, link = link, s = s, proceeds = proceeds,
                      vendorTotal = (s.vendor or 0) * count }
  end
  return out
end

-- one-click vendoring of everything whose advice is "vendor" (merchant must be open)
function Sl:VendorJunk(dry)
  if not (MerchantFrame and MerchantFrame:IsShown()) and not dry then
    AL:Print("open a vendor first")
    return 0, 0
  end
  local n, total = 0, 0
  for b = 0, (NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4) do
    for slot = 1, C_Container.GetContainerNumSlots(b) or 0 do
      local info = C_Container.GetContainerItemInfo(b, slot)
      if info and info.itemID and not info.isLocked then
        local v = vendorPrice(info.itemID)
        local junk = info.quality == 0
        local s = not junk and not info.isBound and AL.Suggest(info.itemID, info.hyperlink)
        -- grey items, plus tradeable items where a vendor pays more than the AH would (with data)
        if v > 0 and (junk or (s and s.advice == "vendor" and s.post)) then
          n, total = n + 1, total + v * (info.stackCount or 1)
          if not dry then C_Container.UseContainerItem(b, slot) end
        end
      end
    end
  end
  return n, total
end

AL:On("MERCHANT_SHOW", function()
  if not AL.db.settings.autoJunk then return end
  C_Timer.After(0.3, function()
    local n, total = Sl:VendorJunk()
    if n > 0 then AL:Print(string.format("sold %d item stacks to the vendor for %s", n, AL.Money(total))) end
  end)
end)

---------------------------------------------------------------------------
-- posting from the Sell page
---------------------------------------------------------------------------
local AH = C_AuctionHouse

Sl.DURATIONS = { { 1, "12 hours" }, { 2, "24 hours" }, { 3, "48 hours" } }
Sl.MODES = { { "undercut", "Undercut by 1c" }, { "match", "Match the cheapest" }, { "normal", "Normal price" } }
Sl.CUT = CUT

-- the unit price for a pricing mode, from an AL.Suggest result
function Sl.PriceFor(s, mode)
  if not s then return nil end
  if mode == "normal" and s.ref then return math.max(1, math.floor(s.ref)) end
  if mode == "match" and s.lowest and (not s.ref or s.lowest >= s.ref * FLOOR) then
    return math.max(1, math.floor(s.lowest))
  end
  return s.post
end

-- live auctions of an item, straight from an AH search: [key] = { t, list = { {unit, qty, mine}, ... } }
Sl.live = {}
AL:On("AL_PRICE", function(key, list)
  if type(list) ~= "table" then return end
  Sl.live[key] = { t = time(), list = list }
  AL:Fire("AL_SELL_LIVE", key)
end)

-- the cheapest auctions to show: equal prices merged, cheapest first -> { {unit, qty, mine}, ... }, source time
function Sl:Competition(key, max)
  local l = self.live[key]
  local src = l and l.list or (AL.Scanner.last and AL.Scanner.last.items[key])
  local t = l and l.t or (AL.Scanner.last and AL.Scanner.last.items[key] and AL.Scanner.last.t)
  local out = {}
  if not src then return out, nil end
  local sorted = {}
  for i, x in ipairs(src) do sorted[i] = x end
  table.sort(sorted, function(a, b) return a[1] < b[1] end)
  for _, x in ipairs(sorted) do
    local unit = math.floor(x[1] + 0.5)
    local last = out[#out]
    if last and last[1] == unit and (last[3] or false) == (x[3] or false) then
      last[2] = last[2] + x[2]
    else
      if #out >= (max or 5) then break end
      out[#out + 1] = { unit, x[2], x[3] or false }
    end
  end
  return out, t
end

-- ask the AH for the item's current auctions (the answer arrives as AL_PRICE)
function Sl:RefreshLive(key, itemID)
  if not AL.ahOpen or not itemID or AL.Scanner.state ~= "idle" then return false end
  local l = self.live[key]
  if l and time() - l.t < 30 then return false end
  if self.lastQuery and GetTime() - self.lastQuery < 1 then return false end
  if AH.IsThrottledMessageSystemReady and not AH.IsThrottledMessageSystemReady() then return false end
  self.lastQuery = GetTime()
  local ok = pcall(AH.SendSearchQuery, AH.MakeItemKey(itemID),
    { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } }, true)
  return ok
end

-- where an item is in the bags -> { loc, count, commodity, bag, slot } (loc nil when it is gone)
function Sl:Locate(key)
  local out = { count = 0 }
  for b = 0, (NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4) do
    local ok, n = pcall(C_Container.GetContainerNumSlots, b)
    for slot = 1, (ok and n or 0) do
      local info = C_Container.GetContainerItemInfo(b, slot)
      if info and info.itemID and not info.isBound and AL.KeyFromLink(info.hyperlink, info.itemID) == key then
        out.count = out.count + (info.stackCount or 1)
        if not out.loc and not info.isLocked and ItemLocation then
          out.loc, out.bag, out.slot = ItemLocation:CreateFromBagAndSlot(b, slot), b, slot
          out.id, out.link = info.itemID, info.hyperlink
        end
      end
    end
  end
  if out.loc and AH.GetItemCommodityStatus then
    local ok, st = pcall(AH.GetItemCommodityStatus, out.loc)
    out.commodity = ok and st == ((Enum.ItemCommodityStatus and Enum.ItemCommodityStatus.Commodity) or 2)
  end
  return out
end

function Sl:Deposit(it, duration, qty)
  if not it or not it.loc or not qty or qty < 1 then return nil end
  local ok, d
  if it.commodity then ok, d = pcall(AH.CalculateCommodityDeposit, it.id, duration, qty)
  else ok, d = pcall(AH.CalculateItemDeposit, it.loc, duration, qty) end
  return ok and d or nil
end

local function describe(p)
  return string.format("%d x %s at %s each", p.qty, p.link or AL.ItemName(p.id) or "item", AL.Money(p.unit, true))
end

-- post `qty` of the item at `unit` copper each. The game only accepts this from a click.
-- -> true, or false + why not
function Sl:Post(key, unit, qty, duration)
  if not AL.ahOpen then return false, "Open the auction house to post." end
  if self.posting and GetTime() - self.posting.t < 10 then return false, "Still posting the previous auction." end
  unit, qty = math.floor(tonumber(unit) or 0), math.floor(tonumber(qty) or 0)
  if unit < 1 then return false, "Set a price first." end
  local it = self:Locate(key)
  if not it.loc then return false, "That item is not in your bags any more." end
  if qty < 1 then return false, "Set a quantity first." end
  if qty > it.count then return false, "You only have " .. it.count .. "." end
  if AH.IsThrottledMessageSystemReady and not AH.IsThrottledMessageSystemReady() then
    return false, "The auction house is busy. Try again in a moment."
  end
  if AH.IsSellItemValid then
    local ok, valid = pcall(AH.IsSellItemValid, it.loc, false)
    if ok and valid == false then return false, "The auction house does not accept this item." end
  end
  duration = duration or 2
  local ok, confirm
  if it.commodity then ok, confirm = pcall(AH.PostCommodity, it.loc, duration, qty, unit)
  else ok, confirm = pcall(AH.PostItem, it.loc, duration, qty, nil, unit) end
  if not ok then return false, "The game refused the post: " .. tostring(confirm) end
  local p = { key = key, id = it.id, link = it.link, unit = unit, qty = qty, duration = duration,
              commodity = it.commodity, loc = it.loc, t = GetTime() }
  self.posting = p
  if confirm then
    -- the game wants a second yes (it does that for prices it finds suspicious)
    local d = StaticPopup_Show and StaticPopup_Show("ULTIMATEAH_CONFIRM_POST", describe(p))
    if d then d.data = p else self.posting = nil; return false, "The game asked for a confirmation that could not be shown." end
  end
  C_Timer.After(10, function() if self.posting == p then self.posting = nil; AL:Fire("AL_SELL_POSTED", key, false) end end)
  return true
end

if StaticPopupDialogs then
  StaticPopupDialogs["ULTIMATEAH_CONFIRM_POST"] = {
    text = "Ultimate AH: the auction house asks you to confirm this price.\n\nPost %s?",
    button1 = YES or "Yes", button2 = NO or "No",
    OnAccept = function(_, p)
      if type(p) ~= "table" then return end
      if p.commodity then pcall(AH.ConfirmPostCommodity, p.loc, p.duration, p.qty, p.unit)
      else pcall(AH.ConfirmPostItem, p.loc, p.duration, p.qty, nil, p.unit) end
    end,
    OnCancel = function(_, p)
      if Sl.posting == p then Sl.posting = nil; AL:Fire("AL_SELL_POSTED", p and p.key, false) end
    end,
    timeout = 0, whileDead = true, hideOnEscape = true, preferredIndex = 3,
  }
end

AL:On("AUCTION_HOUSE_AUCTION_CREATED", function()
  local p = Sl.posting
  if not p then return end
  Sl.posting = nil
  Sl.live[p.key] = nil                       -- my new auction changed the picture
  AL:Print("posted " .. describe(p))
  AL:Fire("AL_SELL_POSTED", p.key, true)
end)
AL:On("AUCTION_HOUSE_POST_ERROR", function()
  local p = Sl.posting
  if not p then return end
  Sl.posting = nil
  AL:Print("|cffff7373the auction house refused the post|r of " .. describe(p))
  AL:Fire("AL_SELL_POSTED", p.key, false)
end)

AL:Command("sell", "what to sell and for how much (Sell tab)", function() AL.UI:Toggle("Sell") end)
AL:Command("junk", "sell grey items and items a vendor pays more for than the AH (vendor must be open)", function()
  local n, total = Sl:VendorJunk()
  AL:Print(string.format("sold %d item stacks to the vendor for %s", n, AL.Money(total)))
end)
