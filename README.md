# Pro player ratings

pipeline/  rating code and notebooks (needs the Oracle's Elixir match-data CSV, not stored in git)
docs/      the website (static files). docs/data/ is written by pipeline/build_site_data.py

## Preview locally
    cd docs
    python -m http.server 8000
Open http://localhost:8000 (double-clicking index.html will not work, the browser blocks loading the data files).

## Update the ratings
1. Put the CSV in pipeline/ and run, from pipeline/:
       python build_site_data.py
   (or open pipeline/lec_rating_site_data.ipynb and Run All, it runs the same script). It rewrites docs/data/.
2. Preview, then commit on a branch and open a pull request into main:
       git checkout -b update-ratings
       git add docs/data
       git commit -m "update ratings"
       git push -u origin update-ratings

## Data files (docs/data/, generated)
    index.json               config, years, list of game files, player index (search, which files a player is in)
    summary/<year>.json      per player x league x split x stage: the sums behind the leaderboards
    games/<year>/<lg>.json   every rated player-game of one league (loaded on player pages)

Leagues, tiers, events and split names are set at the top of pipeline/build_site_data.py.
