# Ultimate AH

An auction house toolkit for **World of Warcraft: Forever** (interface 16001): a ledger of every
buy and sale across your characters, price scans, a value graph, a deal finder, a watchlist,
posting from your bags, and hourly price scans through Blizzard's web API, including an estimate
of how many units of each item sell per day.

![Sell page](renders/Sell.png)

The screenshots in `renders/` are drawn outside the game by `render_ui.py` from the addon's real
layout code with sample data. Fonts and icons differ a little from the game.

## Status

- The ledger, scans, value graph, deal finder and guild price replies (1.x) were built and
  checked in the game.
- The 2.x work has only been tested outside the game so far: the new look, the Watch, Sell and
  Settings pages, posting auctions from the Sell page, and loading API scan data. It is covered
  by 279 automated checks against a mocked game API and by the offline renders, but it has not
  been run in the live client yet. Treat 2.x as a beta.
- The API scan script and the server scan have been run against Blizzard's real API (EU).

## What is in here

| Path | What it is |
|---|---|
| `UltimateAH/` | The addon. Copy this folder into `_forever_\Interface\AddOns`. Its [README](UltimateAH/README.md) describes every page and command. |
| `ah_api.py` | Auto scans: downloads your auction house from Blizzard's Game Data API every hour and writes `ApiData.lua` for the addon. |
| `ah_server.py` | Server scan: every Forever auction house, both factions, every hour, into a SQLite database. Runs as a small Docker service (`Dockerfile`). |
| `ah_ml.py` | The server's learned price forecasts: trained every hour on the database, handed out only while they beat "unchanged". Needs numpy and scikit-learn. |
| `deploy.py` | Copies `UltimateAH/` into the game folder. |
| `sync_accounts.py` | Merges the addon's saved data across WoW accounts on one PC. |
| `test_*.py`, `tests_v2.py` | Tests: the addon's Lua runs in [lupa](https://pypi.org/project/lupa/) against a mocked WoW API; the scan scripts run against a fake Blizzard API. |
| `render_ui.py` | Draws every page to a PNG without the game. |
| `luacheck.py`, `uipass.py` | Syntax check and a search/replace helper. |
| `media/` | The project logo and the script that draws it. |

## Install the addon

The addon is also on CurseForge as a beta: https://www.curseforge.com/wow/addons/ultimate-ah
(the page appears once CurseForge's moderators have approved it).

1. Copy the `UltimateAH` folder into `World of Warcraft\_forever_\Interface\AddOns`
   (or run `python deploy.py`).
2. Start the game, then `/uah` or the minimap button.

## Auto scans (optional)

An addon cannot reach the internet, so a small Python script does it from outside the game. There
are two ways to use it.

### Without an API key (EU)

The project runs a [server scan](#the-server-scan) for the EU region: every Forever auction house,
Alliance and Horde, every hour, around the clock. The script downloads your house's file from it,
so there is nothing to sign up for.

1. Do a Full Scan in the game once, then `/reload`.
2. `python ah_api.py auto`. The first run finds which auction house is yours by comparing the
   server's files with your scan, then downloads your house's file into the addon folder.
3. Schedule `python ah_api.py auto` hourly, for example with Windows Task Scheduler.
4. The addon loads the data at login or `/reload`. `/uah api` shows what it loaded.

If the game is not in the default folder, copy `blizzard_api.example.json` to `blizzard_api.json`
and set `wow_dir`.

The script only downloads files: it sends nothing about you, your account or your characters, and
the server keeps no request log. The address is `SERVER` at the top of `ah_api.py`. The service is
a hobby project and comes with no promise to stay up; `"server": "<address>"` in
`blizzard_api.json` points the script at a server scan of your own, and `"server": ""` switches it
off.

### With your own API key

Your PC scans your auction house itself, which also tells the addon which auctions are yours. The
server's file still adds the price history and sale rates of the hours your PC was off.

1. Create an API client at https://develop.battle.net/access/clients.
2. Copy `blizzard_api.example.json` to `blizzard_api.json` and fill in the client ID and secret.
   That file is ignored by git: never commit it.
3. `python ah_api.py check` tests the keys. `python ah_api.py detect` finds which auction house is
   yours by comparing prices with your last in-game Full Scan (do one first, then `/reload`).
4. `python ah_api.py auto` runs a scan. Schedule it hourly, for example with Windows Task Scheduler.
5. The addon loads the data at login or `/reload`. `/uah api` shows what it loaded.

Needs Python 3.10+ and `pip install lupa` (used to read the addon's saved data).

Blizzard has not documented the Forever API. The script uses what the community found by probing:
namespace `dynamic-forever-<region>`, auctions under `/data/wow/ruleset/<id>/auctions/<house>`.
It may break when Blizzard changes things.

### The server scan

`ah_server.py` is the same scan for a machine that is always on. `python ah_server.py serve` checks
every five minutes whether Blizzard has new data (it publishes once an hour, at about :23), scans
every Alliance and Horde house of the region when it has, and hands out the results over HTTP:

| File | What it is |
|---|---|
| `/eu-<house>.lua.gz` | What the addon loads: current prices, 14 days of daily prices, units sold per day, price patterns. |
| `/history.db.gz` | A SQLite database: one row per auction house, item and day with the mean market price, the lowest buyout, the listed quantity and the units sold; prices and sales by hour of the day; the forecast's check per house. |
| `/index.json` | The houses, the time of their last scan, the days of history, and how the forecast did against "unchanged". |
| `/ml.json` | The last training of the learned forecasts, by day and by hour: rows, errors against "unchanged", how often the direction was right, on or off. |
| `/healthz` | A small status answer for health checks. |

The previous snapshot of each house (needed to see what was sold) and the log stay in the data
folder and are not handed out.

The `Dockerfile` packs it as a service: build it, give it a volume at `/data` and the environment
variables `BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET`, and put HTTPS in front of port 8080
(the data file is Lua code the game loads, so do not hand it out over plain HTTP). One scan of the
eight EU houses takes about 25 seconds and 500 MB of memory; the rest of the hour it idles.

```
docker build -t ultimate-ah-scan .
docker run -d -p 8080:8080 -v ah-data:/data -e BLIZZARD_CLIENT_ID=... -e BLIZZARD_CLIENT_SECRET=... ultimate-ah-scan
```

Without Docker, `python ah_server.py run --dir <folder>` once an hour does the same scan.

Blizzard's API terms allow keeping API data for 30 days at most, so the database drops anything
older. Auction data: Blizzard Entertainment, through the Battle.net Game Data API.

### Price patterns

The server scan keeps 30 days of history, and from it works out for every item:

| Pattern | What it means | Needs |
|---|---|---|
| Trend | How the price moved over the last week, in percent per day. Only when the days agree on a direction. | 5 of the last 8 days |
| Position | Where today's price sits among the last 30 days: "high for the month", "low for the month". | 7 days |
| Weekday | The weekday the item is usually cheapest and the one it is usually dearest, against the days around it. | about 4 weeks |
| Hour | The hour of the day it is usually cheapest and dearest, and the hour most units sell. Only for items with at least 5 auctions. | 5 days per hour |
| Forecast | The expected market price in 6 hours, tomorrow and in 7 days, with the range the price in 7 days will most likely be in. Learned from every item's history: see [Learned forecasts](#learned-forecasts). | 1 day to 3 weeks |

The addon shows them in item tooltips, as a Trend column on the Prices page, under the price graph,
and as a one-line hint on the Sell page ("usually 12% higher on Saturday", "high for the month").

They are statistics, not promises, and they are built to say nothing rather than guess:

- A weekday or an hour is only named when it stands out clearly against the item's own noise. On
  random prices the checks name a weekday in about 3% of items and an hour in under 1%.
- A forecast is only handed out while it beats "the price stays the same" on days it had not seen.
  `/ml.json`, `/index.json` and the scan log show both errors.
- Thirty days is all Blizzard's terms allow anyone to keep, so there is no seasonality beyond the
  week: holiday events and patch cycles are out of reach.

### Learned forecasts

After every hourly scan the service retrains its forecast models on the whole database
(`ah_ml.py`, gradient-boosted trees from scikit-learn):

- **What it learns from.** One row is one item on one day, from every auction house: how the price
  moved over the last 1, 2, 3 and 7 days, how far it is from its weekly and monthly median, how
  jumpy it is, where it sits in its range, the gap between market price and lowest buyout, how much
  is listed and sold, and the weekday. The answer to learn is the price change one day and seven
  days later.
- **What it makes.** Four models: the price in a day, the price in a week, and the 20% and 80% ends
  of the range the price in a week will most likely be in.
- **How it is checked.** Every training holds back the latest fifth of the days, forecasts them with
  a model that has not seen them, and compares the error with "the price stays the same". A forecast
  is handed out only when its error is under 97% of that; the range only when it caught between 45%
  and 75% of the real prices. A market that stops being predictable loses its forecasts at the next
  training.
- **What it costs.** With 30 days of all eight EU houses (3.6 million item-days) a training takes
  about a minute on one CPU and 420 MB, in a process of its own.

**Hour by hour.** The scan also keeps 14 days of prices per scan (`hourly.db`: every item with two
or more auctions, about 1 MB per hour for all eight houses, not handed out). The same kind of model
learns the price 1, 6 and 24 hours ahead from them: how the price moved over the last 1 to 24 hours,
how far it is from its 6, 24 and 72 hour mean, the gap to the lowest buyout, what is listed and
sold, the hour and the weekday. It is checked the same way, on the latest fifth of the hours. The
6-hour forecast goes to the addon ("~1g 20s around 21:00"); the 24-hour one stands in for
"tomorrow" while the day-by-day forecast is off; the 1-hour one is only reported, as the earliest
sign of whether prices can be predicted at all. They need about half a day, a day and three days of
archive.

While the learned week-ahead forecast is off, a plain one (the week's trend plus a pull towards the
monthly median, with two weights fitted per house once a day) stands in, under the same rule.
The first learned one-day forecasts need about a week of history, the week-ahead ones about three.
`python ah_ml.py info --dir <folder>` and `/ml.json` show how the last training went.

### Units sold per day

Each hourly scan is compared with the one before. An auction that vanished counts as sold when it
still had more time left than passed between the scans and no cheaper auction of the same item
stayed behind. A commodity listing whose quantity dropped counts as partly bought. Cancelled
auctions cannot be told apart perfectly, so read the number as an estimate.

## Development

```
pip install lupa pillow numpy scikit-learn
python luacheck.py
python test_tracker.py
python test_ui.py
python test_api.py
python test_server.py
python test_ml.py
python test_sell.py
python render_ui.py renders
```

Edit the addon in `UltimateAH/`, run the tests, then `python deploy.py` to try it in the game.

Two things worth knowing:

- The game runs Lua 5.1, which refuses a file with more than 262,143 different constants. That
  is why `ApiData.lua` stores each item as one string and price history keeps three significant
  digits.
- The game only accepts posting, buying and cancelling from a real click, so nothing here
  automates trading: every auction is one click.
