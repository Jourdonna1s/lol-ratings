# Pro player ratings

Static website (docs/) plus a Python rating pipeline (pipeline/).

## Layout
- pipeline/rating_core.py: the rating formula (role z-scores, early/late scores, shrinkage). The notebooks call it.
- pipeline/build_site_data.py: builds docs/data/ (settings at the top: BASELINE_GROUPS, TIERS, INTERNATIONAL, EVENTS, QUALIFIERS, LEAGUE_NAMES, K, SPLIT_MAP). lec_rating_site_data.ipynb just runs it.
- docs/data/ is generated, never edit it by hand: index.json (config, player index), summary/<year>.json (sums per player x league x split x stage, used by the leaderboards), games/<year>/<league>.json (games, loaded on player pages).
- docs/: index.html, app.js, style.css. Loads the data files with fetch. No frameworks, no build step.
- The leaderboard math (rateSums in app.js) and the summary sums (write_site_data in build_site_data.py) must stay in step.

## Rules
- Never commit CSV files. The Oracle's Elixir data stays local (.gitignore covers *.csv).
- These are performance ratings relative to the games counted, not skill. Keep that wording on the site.
- Every league in the file with 30+ complete games is on the site with its own baseline; LCK/LPL/LEC/LCS share one (BASELINE_GROUPS), international games have theirs. Ratings of the main leagues must not change when leagues are added.
- Every league has a tier (TIERS): Major, Tier 2 (default) or Tier 3, shown on the site. The "Major leagues" board combines the major leagues and international games; "All leagues" combines every game.
- Events (EVENTS: cups like EMEA Masters, KeSPA Cup) and qualifiers of international events (QUALIFIERS, e.g. EWC qualifiers) are rated per team against its home league's baseline, count 1× in the overall rating, and are not international games. Events get their own board.
- Only major leagues use the common Winter/Spring/Summer names (SPLIT_MAP). Other leagues keep their real split names; unlabelled games join the nearest split, else get a name from the schedule.
- A player is name + role, split into separate players only when several playerids never shared a team. Players from before phase 1 come first in the index so their page addresses stay the same.
- Keep docs/ working as plain static files (GitHub Pages serves /docs).
- Do not add the unofficial lolesports feed to the repo.
- Ask before changing the rating formula or weights, and say how rankings would change.

## Commands
- Build data: cd pipeline, then python build_site_data.py (add --report for the top 10 per role and checks per baseline)
- Preview: cd docs, then python -m http.server 8000, then open http://localhost:8000
- Python 3.14; install packages with python -m pip install.