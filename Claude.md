# Pro player ratings

Static website (docs/) plus a Python rating pipeline (pipeline/).

## Layout
- pipeline/rating_core.py: the rating formula (role z-scores, early/late scores, shrinkage). The notebooks call it.
- pipeline/team_elo.py: team strength (Elo) from results (settings at the top: WEIGHT, TIER_PRIOR, LEAGUE_PRIOR, TITLE, DECAY_*). Game weights: Worlds > MSI > FST/EWC > WSCI > leagues > events with major teams / EWC qualifiers > EM and other events; league levels fitted on the whole season with a prior per tier (major leagues about 60 apart: LCS, then LCP and CBLOL lower; tier 2 far below, its best team just above the weakest major teams); one Elo change per series (Bo1/Bo3/Bo5); title bonus for winning a league split or event; decay towards the league level after 14 idle days; boards without a split/stage filter show Elo now and only teams that played in their league's latest split (final stages like VCS Finals don't count as a split). Team rosters: starting lineup and subs (in the latest split, still on the team), former, event stand-ins. K chosen by log loss of series results, capped at 32.
- pipeline/build_site_data.py: builds docs/data/ (settings at the top: BASELINE_GROUPS, TIERS, INTERNATIONAL, EVENTS, QUALIFIERS, LEAGUE_NAMES, K, SPLIT_MAP). lec_rating_site_data.ipynb just runs it.
- docs/data/ is generated, never edit it by hand: index.json (config, player and team index, tournaments and qualification links), summary/<year>.json (sums per player x league x split x stage, used by the leaderboards), games/<year>/<league>.json (games, loaded on player pages), teams/<year>/<league>.json (team-games, loaded on team pages; summary/<year>.json "teams" holds the team leaderboard sums).
- docs/: index.html, app.js, style.css. Loads the data files with fetch. No frameworks, no build step.
- The leaderboard math (rateSums in app.js) and the summary sums (write_site_data in build_site_data.py) must stay in step.

## Rules
- Never commit CSV files. The Oracle's Elixir data stays local (.gitignore covers *.csv).
- These are performance ratings relative to the games counted, not skill. Keep that wording on the site.
- Every league in the file with 30+ complete games is on the site with its own baseline; LCK/LPL/LEC/LCS share one (BASELINE_GROUPS), international games have theirs. Ratings of the main leagues must not change when leagues are added.
- Every league has a tier (TIERS): Major (LCK, LPL, LEC, LCS), Tier 1 (LCP, CBLOL), Tier 2 (default) or Tier 3, shown on the site. The "Major leagues" board combines the major leagues and international games; "All leagues" combines every game.
- Events (EVENTS: cups like EMEA Masters, KeSPA Cup) and qualifiers of international events (QUALIFIERS: EWC qualifiers; a region's own Worlds qualifier filed under WLDs = the games before the event's last 14+ day break) are rated per team against its home league's baseline, count 1× in the overall rating, and are not international games. Events get their own board.
- Only major leagues use the common Winter/Spring/Summer names (SPLIT_MAP). Other leagues keep their real split names; unlabelled games join the nearest split, else get a name from the schedule.
- A player is name + role, split into separate players only when several playerids never shared a team. Players from before phase 1 come first in the index so their page addresses stay the same.
- Teams: Elo uses every game (partial ones too) and is a win-based strength, separate from the player performance ratings; adding teams or Elo must never change player numbers. Team key = teamid, else the name. Series = same league, day and two teams.
- Site pages: #home (menu), #players (player leaderboards), #teams (team leaderboards), #events (tournaments), #p-... player pages, #t-... team pages, #e-... tournament pages.
- Tournaments (tournaments() in build_site_data.py): one per year x league x kind x split, from the team-games. League games without a split label in the data (e.g. "TCL Oct", "CD Feb-Mar") are in no tournament, except a major league's unlabelled games listed in UNLABELLED (LCS Oct 5-13 = "LCS Promotion", a Tier 2 tournament via TOUR_TIERS, with no common split name); a league with no split labels at all keeps its schedule-named splits (LFL Split 1-3). Champion = the title rule used for Elo (finals()). Formats and stages: FORMATS in build_site_data.py, hand-written from Riot's announcements and press coverage (per year; stages by the playoffs flag or by dates); tournaments not listed get regular season + playoffs from the data, or one list of results. Standings tables only for "table" stages (round robin, Swiss), marking the teams that reached the next stage; the stage with the final shows places (placings() in the pipeline) and the tournament each team qualified for with its place there. "Qualified from" is grouped by region (the team's home league) and shown below the stages. Qualification links (tournament_links()) come only from teams that played both tournaments, never from a hand-made list.
- Keep docs/ working as plain static files (GitHub Pages serves /docs).
- Do not add the unofficial lolesports feed to the repo.
- Ask before changing the rating formula or weights, and say how rankings would change.

## Commands
- Build data: cd pipeline, then python build_site_data.py (add --report for the top 10 per role and checks per baseline)
- Preview: cd docs, then python -m http.server 8000, then open http://localhost:8000
- Python 3.14; install packages with python -m pip install.