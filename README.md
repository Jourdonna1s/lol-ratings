# Pro player ratings

pipeline/  rating code and notebooks (needs the Oracle's Elixir match-data CSV, not stored in git)
docs/      the website (static files). docs/data/site_data.json is written by pipeline/lec_rating_site_data.ipynb

## Preview locally
    cd docs
    python -m http.server 8000
Open http://localhost:8000 (double-clicking index.html will not work, the browser blocks loading the data file).

## Update the ratings
1. Put the CSV in pipeline/ and run pipeline/lec_rating_site_data.ipynb (Run All). It writes docs/data/site_data.json.
2. Preview, then (the first time only, run git init and git remote add origin <repo URL> first):
    git add .
    git commit -m "update ratings"
    git push
