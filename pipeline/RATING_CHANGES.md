# Rating versions

The player rating formula is frozen at the version in `rating_core.RATING_VERSION` (shown in the site header and on the "How the ratings work" page). Any change to the formula, its weights or the settings below gets a new version and an entry here, with the reason and a before/after (`compare_ratings.py OLD NEW`). The site explains the rating as concepts only; the numbers live here and in the code.

## 1.0 (2026-11, phase 9)
v0.3 plus:
- Same spread in every league (`league_spread()` in build_site_data.py): weaker, uneven leagues spread their player ratings wider than the main leagues (2026: up to 0.23 vs 0.15; tops up to 1.8). Each baseline outside the main group and the international one has its game ratings narrowed to TARGET_SD (factor = TARGET_SD / spread of its players with 15+ games, at most 1; baselines with fewer than 30 such players unchanged). Events use the home league's factor. Main leagues and rankings inside a league unchanged.
- Few-games shrinkage checked and kept: K = 12 (split-to-split test, 2014-26: K 8-20 predict the next split equally well, 12 at the top), leaderboard minimum 15 games (ratings from 13+ games predict the next split clearly better than from 8-12).
- Site: concepts only; index.json no longer exports the weights.

## 0.3 (2026-11-25, PR #30)
- Early weights per role: CS lead, support kill participation at 15, jungle early team objectives (first dragon, first Herald, void grub share); supports barely count gold.
- Fights: the better of damage or tanking (share of team damage taken + mitigated) for top/jng/sup; deaths weigh ×1.5 early and ×2 in fights (supports ×1 in fights).
- Late weights: top tower damage .30 → .20, support gold swing .15 → .08.
- Corrections fitted per year on the main leagues + international games: style stats against the champion's average in the role, lane leads against the matchup (shrunk: champion 25, pair 10), the extra gold of TF, Gangplank, Draven, Pyke (shrunk 30).
- Fix: a team with no deaths after 15 minutes lost all its late fight stats; games without 15-minute stats use whole-game numbers.
- Before/after (major leagues 2014-26): champion bias .067/.080/.072/.037/.105 → .028/.034/.038/.022/.038 (top/jng/mid/bot/sup); better-rated team won 63.7% → 63.3%; deathless games (8+ K+A) under 1.00 10.1% → 5.5%; leaderboard rank correlation per year 0.94-0.98.

## 0.2 (2026-10/11)
Role z-scores within each baseline, early (one set of weights for all roles) and late scores (fights, gold swing, vision, pressure) blended per role; player rating = 1 + c(role)·Σw(r−1)/(Σw + K), K = 12, c(role) calibrated per year to a 0.15 spread in the main leagues and put on the reference year's scale; international games count 2×.
