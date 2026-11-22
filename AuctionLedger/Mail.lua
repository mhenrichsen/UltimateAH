-- AuctionLedger: login reminder for sales waiting in the mail
local _, AL = ...

AL:On("AL_LOGIN", function()
  C_Timer.After(8, function()
    local snap = AL.db.listings and AL.db.listings[AL:CharKey()]
    local n, sum = 0, 0
    for _, a in ipairs(snap and snap.list or {}) do
      if a.sold then n = n + 1; sum = sum + (a.buyout or 0) * 0.95 end
    end
    local pending = 0
    for _, r in ipairs(AL.db.tx) do
      if r.provisional and r.type == "sell" and r.char == AL:CharKey() then pending = pending + 1 end
    end
    if n > 0 or pending > 0 then
      AL:Print(string.format("%d sold auction(s) waiting in the mail on this character (about %s) - visit a mailbox",
        math.max(n, pending), AL.Money(sum, true)))
    end
  end)
end)
