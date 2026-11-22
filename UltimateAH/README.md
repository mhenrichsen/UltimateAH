# Ultimate AH (WoW Forever)

Tracks every auction house buy and sale on all your characters, prices the AH like TSM, graphs your
total value (gold + items), finds buy-and-relist deals, watches prices for you, tells you when you
are undercut and what to post your bags for.

Open it with **/uah**, the **minimap button** (right-click = value graph) or **Open Ultimate AH** on
the panel next to the auction house. The window has its own dark theme: a sidebar with every page
(badges show undercut auctions, watch alerts and deals), stat cards, dropdown filters and switches.

## Overview pages
- **Ledger**: every buy, sale, post, cancel and expiry, by character, type, period or item name, with
  cards for bought, sold, AH cut, net profit and money still in the mail. "Sold\*" = a buyer was found
  and the money is still in the mail (the exact amount is read from the "Auction successful" mail).
  Right-click an entry to delete it; shift-click links the item in chat.
- **Summary**: per-character totals and per-item profit (sold after cut minus bought).
- **Value**: gold + item worth over time for each character or the whole account. Bags are read
  as you play, the bank when you open it, mail when you open the mailbox, auctions at the AH. Items are
  valued at the scanned market price; soulbound items count as 0.
- **Inventory**: every tradeable item of every character (bags, bank, mail) with its value.
- **Listings**: your auctions on every character. After a scan each one is marked **Lowest** or
  **Undercut** (someone else lists it cheaper; the tooltip says what to repost at). Your own
  auctions are recognised by your characters' names, so they never count as competition.
- **Prices**: every scanned item: lowest buyout, market value, average of the cheapest 100 auctions,
  14-day average, your own average buy and sell price. Click an item for its price-history graph,
  right-click to put it on the watchlist.
- **Deals**: after a Full Scan: auctions listed far below the normal price that are worth buying
  out and relisting (relist just under the next listing, never above the normal price; profit after
  the 5% cut, ROI), and auctions cheaper than a vendor pays. Your own auctions are skipped and
  random-suffix gear is compared per suffix. "Flip?" (gray) = less certain. Click a row to search it.

## Tools
- **Watch**: items with a max price. When one is listed at or under it (full scan, quick scan or any
  AH search you do) you get a chat line, a raid warning and a sound. No price given = 80% of normal.
  `/uah watch Arcanite Bar 40g`, `/uah unwatch Arcanite Bar`.
- **Sell**: post auctions straight from the page. The left side lists the tradeable items in your
  bags with a post price, the AH value after the cut, how many sell per day and Post / Vendor
  advice. Click one and the right side prepares the auction: the market (cheapest from others,
  normal price, sold per day, vendor price), the cheapest live auctions with yours marked, and a
  price, quantity, pricing rule (undercut by 1c, match the cheapest, normal price) and duration you
  can change. It shows the buyout, the deposit and what you receive, warns about typos (far below
  the cheapest auction) and vendor-beats-AH prices, and **Post** puts it up. After a post the next
  item is selected, so a bag is emptied with one click per item (the game demands a click for
  every auction). The auction house must be open; right-click a row to search it there.
  **Sell junk to vendor** (or `/uah junk`, or the auto option) sells grey items and items a vendor
  pays more for. Item tooltips show the post price and your stack's value too.
- **Settings**: switches for tooltips, guild/whisper replies, auto scan, undercut notices, watch
  alerts, auto-junk and the minimap button, plus what is stored.

## Scans
- **Full Scan**: every auction at once (about 15 s for 320k auctions). The server allows one every
  15 minutes. Computes market values (cheapest 15-30% of units, outliers dropped).
- **Quick Scan**: pages through the browse list; lowest price and quantity per item. No cooldown.
- **Deep Scan**: searches each item you've bought, sold, listed or carry, and prices it from its
  cheapest 100 auctions.
- Anything you search in the AH yourself also refreshes that item's price.

## Auto scans (Blizzard's API) and "Sold/day"
An addon cannot reach the internet, so `ah_api.py` (from the addon's GitHub repository, https://github.com/mhenrichsen/UltimateAH) does it from
outside the game. It gets your whole auction house from Blizzard's Game Data API, with the same
prices as a Full Scan, and writes `ApiData.lua` into this folder. The addon loads it at login
or `/reload` (`/uah api` shows what is loaded). No visit to the auction house needed.

Comparing one hourly scan with the next also gives what the game never shows: **how many units of
each item are sold per day** (the Sold/day column on Prices, and a tooltip line). It is an estimate.
An auction that vanished counts as sold when it still had time left and no cheaper auction of the
same item stayed behind; a commodity listing whose quantity dropped was partly bought.

With the server scan's 30 days of history come **price patterns**: the trend of the last week, whether
today's price is high or low for the month, the weekday and hour an item is usually cheapest and
dearest, when it sells, and a 7-day forecast. They show in tooltips, as the Trend column on Prices,
under the price graph and as a hint on the Sell page ("usually 12% higher on Saturday"). A pattern is
only shown when it stands out clearly, and the forecast only while it beats "the price stays the
same" on past data, so a new server shows nothing for the first week. They can be switched off in
Settings.

Setup without an API key (EU region): the project's server scans every Forever auction house each
hour, and the script downloads your house's file from it.
1. Do a Full Scan in the game once, then `/reload`.
2. `python ah_api.py auto` (the first run finds which auction house is yours by comparing with
   that scan), then let a scheduled task run it every hour.

Setup with your own API key (any region; your PC does the scan, which also knows your own auctions):
1. Create an API client at https://develop.battle.net/access/clients and put its client ID and
   secret into `blizzard_api.json` next to the script.
2. `python ah_api.py check` (credentials work?), then `python ah_api.py detect` (finds which
   auction house is yours by comparing with your last in-game Full Scan).
3. `python ah_api.py scan` once by hand, then let a scheduled task run it every hour.

The Forever API is not documented by Blizzard yet; the script uses the paths the community found
(namespace `dynamic-forever-eu`, auctions per ruleset and auction house).

## Price check in guild chat and whispers
When anyone in your guild writes **`AH <item>`** (item name, part of a name, a shift-clicked link
or an item ID), the addon answers in guild chat with your latest data, e.g.
`[UAH] [Arcanite Bar]: market 44g 45s 97c, lowest 41g 49s, top-100 avg 44g 72s 20c, 14d avg 44g 48s 39c, 65 listed (scanned 5m ago)`.
`AH <item> x20` adds what buying 20 costs right now (cheapest auctions first, from the last full
scan). `AH help` explains it. The same works as a whisper to you, answered by whisper.
Only an uppercase "AH " at the start counts ("ah ok" is ignored). If several guildies run the addon,
only one answers. Replies are throttled. `/uah guild` and `/uah whispers` turn them on/off;
`/uah ah <item>` previews the reply only to you.

## Characters on different WoW accounts
WoW stores addon data per account folder. To see characters from both accounts together, run
`python sync_accounts.py` (from the GitHub repository) while the game is closed or at the
character-select screen.

## Commands
`/uah` window - `/uah scan [quick|deep]` - `/uah deals` - `/uah watch <item> <price>` - `/uah unwatch <item>` -
`/uah sell` - `/uah junk` - `/uah value` - `/uah price <item>` - `/uah autoscan` - `/uah guild` - `/uah whispers` -
`/uah ah <item> [x20]` - `/uah tooltip` - `/uah minimap` - `/uah debug` - `/uah errors`
