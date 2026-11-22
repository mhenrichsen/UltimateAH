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
  by 168 automated checks against a mocked game API and by the offline renders, but it has not
  been run in the live client yet. Treat 2.x as a beta.
- The API scan script and the server scan have been run against Blizzard's real API (EU).

## What is in here

| Path | What it is |
|---|---|
| `UltimateAH/` | The addon. Copy this folder into `_forever_\Interface\AddOns`. Its [README](UltimateAH/README.md) describes every page and command. |
| `ah_api.py` | Auto scans: downloads your auction house from Blizzard's Game Data API every hour and writes `ApiData.lua` for the addon. |
| `ah_server.py` | Server scan: every Forever auction house, both factions, every hour, into a SQLite database. Runs as a small Docker service (`Dockerfile`). |
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

### Without an API key: a server scan's data

A [server scan](#the-server-scan) scans every Forever auction house of a region, Alliance and Horde,
around the clock and hands out one data file per house. If you (or someone you trust) run one:

1. Copy `blizzard_api.example.json` to `blizzard_api.json` and set `"server"` to its address.
   Then do a Full Scan in the game once and `/reload`.
2. `python ah_api.py detect` finds which auction house is yours by comparing the server's files with
   your scan. `python ah_api.py fetch` downloads your house's file into the addon folder.
3. Schedule `python ah_api.py auto` hourly, for example with Windows Task Scheduler.
4. The addon loads the data at login or `/reload`. `/uah api` shows what it loaded.

### With your own API key

Your PC scans your auction house itself, which also tells the addon which auctions are yours. With
`"server"` set, the server's file still adds the price history and sale rates of the hours your PC
was off.

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
| `/eu-<house>.lua.gz` | What the addon loads: current prices, 14 days of daily prices, units sold per day. |
| `/history.db.gz` | A SQLite database: one row per auction house, item and day with the mean market price, the lowest buyout, the listed quantity and the units sold. |
| `/index.json` | The houses and the time of their last scan. |
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

### Units sold per day

Each hourly scan is compared with the one before. An auction that vanished counts as sold when it
still had more time left than passed between the scans and no cheaper auction of the same item
stayed behind. A commodity listing whose quantity dropped counts as partly bought. Cancelled
auctions cannot be told apart perfectly, so read the number as an estimate.

## Development

```
pip install lupa pillow
python luacheck.py
python test_tracker.py
python test_ui.py
python test_api.py
python test_server.py
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
