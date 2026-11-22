-- Ultimate AH: deal finder
--
-- After a Full Scan every auction of every item is known. For each item a reference price is taken
-- (the 14-day average market value; without history, the average of the cheapest 100 auctions).
-- * Flip: auctions listed well below the reference are bought out and relisted just under the first
--   "normal" price. Profit counts the 5% AH cut; ROI = profit / cost.
-- * Vendor: auctions cheaper than what a vendor pays for the item.
local _, AL = ...
local Dl = {}
AL.Deals = Dl

local CUT = 0.95

function Dl:Settings()
  local s = AL.db.settings
  s.deals = s.deals or {}
  local d = s.deals
  if d.minProfit == nil then d.minProfit = 10000 end       -- 1g
  if d.minROI == nil then d.minROI = 0.25 end
  if d.cheap == nil then d.cheap = 0.85 end                 -- "normal" price = at least 85% of the reference
  if d.minAuctions == nil then d.minAuctions = 4 end        -- skip items that hardly trade
  if d.maxShare == nil then d.maxShare = 0.5 end            -- never buy more than half of what is listed
  return d
end

local function vendorPrice(itemID)
  local ok, _, _, _, _, _, _, _, _, _, _, sell = pcall(C_Item.GetItemInfo, itemID)
  return ok and sell or nil
end

-- entries: sorted { unit, qty } of one item ; e: its price entry
function Dl.Evaluate(itemID, entries, e, cfg)
  if not entries then return nil end
  -- never suggest buying your own auctions
  local others = {}
  for _, x in ipairs(entries) do if not x[3] then others[#others + 1] = x end end
  entries = others
  if #entries < cfg.minAuctions then return nil end
  local ref = AL.Scanner.HistoryAvg(e, 14)
  local days = 0
  for _ in pairs(e.h or {}) do days = days + 1 end
  if not ref or days < 2 then ref = e.top or e.mkt end
  if not ref or ref <= 0 then return nil end
  local total = 0
  for _, x in ipairs(entries) do total = total + x[2] end

  -- vendor deal: below what a vendor pays
  local vendor = vendorPrice(itemID)
  local best
  if vendor and vendor > 0 then
    local q, cost = 0, 0
    for _, x in ipairs(entries) do
      if x[1] < vendor then q, cost = q + x[2], cost + x[1] * x[2] else break end
    end
    local profit = q * vendor - cost
    if q > 0 and profit >= cfg.minProfit * 0.25 then
      best = { kind = "vendor", n = 0, qty = q, cost = cost, sellAt = vendor, profit = profit, ref = ref,
               low = entries[1][1], roi = profit / cost }
    end
  end

  -- flip: the cheap auctions below the first normal price
  local n, q, cost, sellAt = 0, 0, 0, nil
  for _, x in ipairs(entries) do
    if x[1] >= cfg.cheap * ref then sellAt = x[1]; break end
    n, q, cost = n + 1, q + x[2], cost + x[1] * x[2]
  end
  -- a real market at the relist price: at least 3 auctions at or above it
  local above = 0
  for _, x in ipairs(entries) do if sellAt and x[1] >= sellAt then above = above + 1 end end
  if n > 0 and sellAt and above >= 3 and q <= total * cfg.maxShare then
    -- undercut the next listing by 1 copper, but never ask more than the normal price
    -- (a lone overpriced listing is not what the item sells for)
    local relist = math.max(1, math.min(math.floor(sellAt) - 1, math.floor(ref)))
    local profit = q * relist * CUT - cost
    local roi = profit / cost
    if profit >= cfg.minProfit and roi >= cfg.minROI then
      local flip = { kind = "flip", n = n, qty = q, cost = cost, sellAt = relist, profit = profit, ref = ref,
                     low = entries[1][1], roi = roi, listed = total, auctions = #entries, above = above, days = days,
                     -- confident: a few days of price history and a market with some depth
                     sure = days >= 3 and #entries >= 10 and entries[1][1] >= ref * 0.05 }
      if not best or flip.profit > best.profit then best = flip end
    end
  end
  return best
end

function Dl:Find()
  local last = AL.Scanner.last
  if not last then return nil, "Run a Full Scan first - the deal finder needs every auction." end
  -- compute with the loosest filter values; the Deals tab narrows the saved list down, so the
  -- filters keep working after a reload (the raw scan is only kept in memory)
  local cfg = CopyTable(self:Settings())
  cfg.minProfit, cfg.minROI = 2000, 0.1
  local prices = AL.Scanner:Prices()
  local out = {}
  -- items with variants (random-suffix gear) are judged per variant: "of the Eagle" is not a cheap
  -- "of the Monkey"
  local hasVariants = {}
  for key in pairs(last.items) do
    local id = key:match("^(%d+):")
    if id then hasVariants[id] = true end
  end
  for key, entries in pairs(last.items) do
    local e = prices[key]
    if e and not hasVariants[key] then
      local ok, d = pcall(Dl.Evaluate, e.i, entries, e, cfg)
      if ok and d then
        d.key, d.item, d.name = key, e.i, e.n
        out[#out + 1] = d
      end
    end
  end
  table.sort(out, function(a, b) return a.profit > b.profit end)
  while #out > 300 do table.remove(out) end
  AL.db.deals = AL.db.deals or {}
  AL.db.deals[AL:Scope()] = { t = last.t, list = out }
  AL:Fire("AL_DEALS")
  return out
end

function Dl:Saved()
  local d = AL.db.deals and AL.db.deals[AL:Scope()]
  return d and d.list or {}, d and d.t
end

-- search an item in the open auction house (Blizzard UI)
function Dl.SearchInAH(name)
  if not name or not AL.ahOpen or not AuctionHouseFrame then return false end
  local ok = pcall(function()
    local bar = AuctionHouseFrame.SearchBar
    if AuctionHouseFrame.SetDisplayMode and AuctionHouseFrameDisplayMode then
      AuctionHouseFrame:SetDisplayMode(AuctionHouseFrameDisplayMode.Buy)
    end
    bar.SearchBox:SetText(name)
    bar:StartSearch()
  end)
  return ok
end

AL:On("AL_SCAN_DONE", function(kind)
  if kind == "full" then
    C_Timer.After(0.5, function()
      local list = Dl:Find()
      local cfg = Dl:Settings()
      local n = 0
      for _, d in ipairs(list or {}) do if d.profit >= cfg.minProfit and d.roi >= cfg.minROI then n = n + 1 end end
      if n > 0 then
        AL:Print(string.format("deal finder: %d deals, best %s profit (%s) - /uah deals", n,
          AL.Money(list[1].profit), list[1].name or "?"))
      end
    end)
  end
end)

AL:Command("deals", "show buy-and-relist deals from the last full scan", function() AL.UI:Toggle("Deals") end)
