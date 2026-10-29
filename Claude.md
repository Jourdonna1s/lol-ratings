# Pro player ratings

Static website (docs/) plus a Python rating pipeline (pipeline/).

## Layout
- pipeline/rating_core.py: the rating formula (role z-scores, early/late scores, shrinkage). The notebooks call it.
- pipeline/lec_rating_site_data.ipynb: builds docs/data/site_data.json. Never edit that JSON by hand.
- docs/: index.html, app.js, style.css. Loads data/site_data.json with fetch. No frameworks, no build step.

## Rules
- Never commit CSV files. The Oracle's Elixir data stays local (.gitignore covers *.csv).
- These are performance ratings relative to the games counted, not skill. Keep that wording on the site.
- LCP has its own baseline and international games have theirs (BASELINE_GROUPS in the notebook).
- Keep docs/ working as plain static files (GitHub Pages serves /docs).
- Do not add the unofficial lolesports feed to the repo.
- Ask before changing the rating formula or weights, and say how rankings would change.

## Commands
- Preview: cd docs, then python -m http.server 8000, then open http://localhost:8000
- Python 3.14; install packages with python -m pip install.