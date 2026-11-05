# Pro player ratings

pipeline/  rating code and notebooks (needs the Oracle's Elixir match-data CSVs, one per year, not stored in git)
docs/      the website (static files). docs/data/ is written by pipeline/build_site_data.py

## Preview locally
    cd docs
    python -m http.server 8000
Open http://localhost:8000 (double-clicking index.html will not work, the browser blocks loading the data files).

## Update the ratings
1. Put the CSVs in pipeline/ (named <year>_LoL_esports_match_data_from_OraclesElixir.csv, as downloaded; the
   2026 file is required, it sets the rating scale) and run, from pipeline/:
       python build_site_data.py
   It reads every year's file. A new year also needs its settings in YEARS at the top of build_site_data.py
   (tiers, baseline groups, common split names).
   (or open pipeline/lec_rating_site_data.ipynb and Run All, it runs the same script). It rewrites docs/data/.
2. Preview, then commit on a branch and open a pull request into main:
       git checkout -b update-ratings
       git add docs/data
       git commit -m "update ratings"
       git push -u origin update-ratings

## Automatic updates (GitHub Action)
.github/workflows/update-data.yml runs daily at 06:00 UTC (or by hand: Actions tab > Update data > Run workflow).
It lists Oracle's Elixir's public Google Drive folder (pipeline/data_sources.json: folder id and years) and
downloads each year's file with pipeline/fetch_data.py (past years cached), runs build_site_data.py, and when docs/data changed it opens or
updates a pull request from the data-update branch. Merging it publishes the update. The site footer shows the
date of the latest game ("Games up to ..."), index.json "data_until".
- Repo setting needed once: Settings > Actions > General > Workflow permissions > "Allow GitHub Actions to create
  and approve pull requests".
- A new year: add it to "years" in data_sources.json and its settings to YEARS.
- Drive limits downloads of popular files ("Too many users have viewed or downloaded this file recently", lifts
  within a day): a past year then uses its cached copy; if the current year is refused the run fails and nothing
  changes on the site until the next run.

## Images
Champion icons: `python fetch_images.py` (from pipeline/) downloads new champions from Riot's Data Dragon into
docs/img/champions/ (--force: all again). The daily Action runs it too.

## Years
2014-2026, one Oracle's Elixir file per year in pipeline/. Each year is rated on its own baselines, so adding one never
changes another year's player numbers (team Elo runs through all years, so it does). 2014-16 have no vision score
or tower damage (rated without them); the LPL has no complete games in 2016-17 and 2022-23 (teams only).

## Data files (docs/data/, generated)
    index.json               config, years, list of game files, player and team index (search, which files each is in), Elo settings,
                             tournaments (one per league split, event and international event) and qualification links
    summary/<year>.json      per player x team x league x split x stage: the sums behind the player leaderboards;
                             "teams": per team x league x split x stage: record, series, gold diff @15, Elo (team leaderboards)
    games/<year>/<lg>.json   every rated player-game of one league (loaded on player pages)
    teams/<year>/<lg>.json   every team-game of one league, partial games included (loaded on team and tournament pages)

## Pages
    #home        main page: menu, top 5 players and teams
    #players     player leaderboards        #p-<player>-<role>   player page
    #teams       team leaderboards          #t-<team>            team page
    #events      tournaments                #e-<name>-<year>     tournament page: format, stages (tables, places or results), champion,
                                                                 qualified from (by region), top players, draft, records
    #m-<league>-<date>-<team>-<team>                             match page: one per series (/g2 = game 2): result, Elo,
                                                                 games, team stats, draft, players with their ratings

Team strength is an Elo rating (pipeline/team_elo.py): from game results only, a separate method from the player ratings.

Leagues, tiers, events and split names are set at the top of pipeline/build_site_data.py.
