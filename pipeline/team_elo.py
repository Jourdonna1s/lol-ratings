"""
Team strength (Elo) from game results, in date order, across every league, event and international game, through
all years in one go (a team carries its Elo into the next year).

A team's rating = BASE + level of its home league + its own Elo level.
* Every game has a weight by where it is played (WEIGHT): Worlds most, then MSI, the other international events
  (WSCI included), the leagues, and less for events and cups that teams take less seriously.
* Decay: after a grace period without a game, a team's own level halves every half-life (towards its league's level),
  so teams that keep playing (internationals) hold their Elo, the list stays current and the off-season pulls teams
  back towards their league.
* Roster changes: at the start of a series, each player who had not played for the team in the last ROSTER_DAYS days
  cuts the team's own level by a share (five new players: almost back to the league level). A stand-in for one
  series does nothing once the regular player is back.
* The grace period, half-life, roster cut and K: from the grids below (fit() takes the combination whose ratings
  before each series predict its winner best, by log loss).
* League levels are estimated per league and year from the whole season: a weighted model of every game (blue side
  + team strength (one per team and year) + league level) fitted to all results. League levels start from a prior
  (LEAGUE_PRIOR, else TIER_PRIOR by the league's tier that year), so major leagues sit well above tier 2 and tier 3
  unless the games between them say otherwise. A look back over the season.
* Team levels start at 0 and move once per series (a Bo1, Bo3 and Bo5 each count as one result): by
  K * weight * (series result - series win chance), in opposite directions. A series cut short in the data
  (equal games won) counts as a draw (0.5).
* Winning a competition adds a title bonus (TITLE) right after the final.
* Series win chance: 1 / (1 + 10^(-(R_a - R_b) / 400)), from the ratings at the start of the series.
"""
import numpy as np
import pandas as pd

BASE = 1500
ELO = 400 / np.log(10)        # logit -> Elo points
# Chosen 2026-11-01 from a test on all 2024-2026 series (log loss; lower is better): K 32 / 90 days / no cut 0.6195,
# K 48 / 90 days / 10% cut 0.6133 (the best right after rebuilds), K 48 / 180 days / 10% cut 0.6116, K 32 / 45 days /
# 20% cut 0.6288. Faster decay predicted worse; a higher K and a small roster cut predicted better. With K 48 one Worlds
# series can move a team up to ~96 points. Put more values in a grid to have fit() choose among them.
GRID_K = [48]
GRID_GRACE = [14]               # days without a game before the decay starts
GRID_HALF_LIFE = [90]           # days in which a team's own level halves once the decay runs
GRID_ROSTER = [0.1]             # share of the team's own level lost per new player
ROSTER_DAYS = 120               # a player is new if they had not played for the team in this many days
SD_TEAM = 0.8                 # prior spread (logit units) of team strengths in the season fit
# game weights: international events by name, then leagues by tier; events (cups) and EWC qualifiers
# (event_major: an event with teams from major or tier 1 leagues, e.g. KeSPA Cup; event: the other events)
WEIGHT = {"WLDs": 2.0, "MSI": 1.6, "FST": 1.3, "EWC": 1.3, "WSCI": 1.25, "major": 1.0, "tier1": 1.0, "tier2": 1.0, "tier3": 1.0,
          "qualifier": 0.5, "event_major": 0.5, "EM": 0.25, "event": 0.25}
# league levels in the season fit: prior mean (Elo points) per league, else by tier, and its spread
TIER_PRIOR = {"major": 0, "tier1": -270, "tier2": -735, "tier3": -935}
LEAGUE_PRIOR = {"LCS": -100, "LCP": -220, "CBLOL": -320, "LTA N": -100, "LTA S": -320}   # LTA North/South: LCS/CBLOL in 2025
SD_LEAGUE = 50
# title bonus (Elo points) for winning a competition
TITLE = {"WLDs": 150, "MSI": 100, "FST": 60, "EWC": 60, "WSCI": 40, "major": 50, "tier1": 40, "tier2": 30, "tier3": 20,
         "qualifier": 0, "event_major": 15, "EM": 15, "event": 10}


def prior_of(league, tier):
    return LEAGUE_PRIOR.get(league, TIER_PRIOR.get(tier, TIER_PRIOR["tier2"]))


def fit_levels(g, prior):
    """Weighted season fit: logit P(blue wins) = side + (team_b - team_r) + (league_b - league_r).
    prior: league -> prior mean (Elo). Returns side, league levels (Elo, centred so the average team is 0), team strengths."""
    teams = pd.Index(pd.unique(np.concatenate([g["blue"], g["red"]])))
    lgs = pd.Index(pd.unique(np.concatenate([g["blue_lg"], g["red_lg"]])))
    n, T, L = len(g), len(teams), len(lgs)
    X = np.zeros((n, 1 + T + L))
    X[:, 0] = 1
    rows = np.arange(n)
    np.add.at(X, (rows, 1 + teams.get_indexer(g["blue"])), 1)
    np.add.at(X, (rows, 1 + teams.get_indexer(g["red"])), -1)
    np.add.at(X, (rows, 1 + T + lgs.get_indexer(g["blue_lg"])), 1)
    np.add.at(X, (rows, 1 + T + lgs.get_indexer(g["red_lg"])), -1)
    y, w = g["blue_win"].to_numpy(dtype=float), g["weight"].to_numpy(dtype=float)
    P = np.r_[0.0, np.full(T, 1 / SD_TEAM ** 2), np.full(L, (ELO / SD_LEAGUE) ** 2)]
    mu = np.r_[0.0, np.zeros(T), [prior.get(lg, 0) / ELO for lg in lgs]]
    beta = mu.copy()
    for _ in range(30):                                     # Newton steps on the penalised, weighted log-likelihood
        p = 1 / (1 + np.exp(-X @ beta))
        grad = X.T @ (w * (y - p)) - P * (beta - mu)
        H = (X * (w * p * (1 - p))[:, None]).T @ X + np.diag(P)
        step = np.linalg.solve(H, grad)
        beta += step
        if np.abs(step).max() < 1e-8:
            break
    side, team, league = beta[0], beta[1:1 + T], beta[1 + T:]
    home = pd.Series(np.concatenate([g["blue_lg"], g["red_lg"]]), index=np.concatenate([g["blue"], g["red"]]))
    home = home[~home.index.duplicated()]
    centre = np.mean(league[lgs.get_indexer(home.reindex(teams).to_numpy())] + team)
    return float(side * ELO), dict(zip(lgs, (league - centre) * ELO)), dict(zip(teams, team * ELO))


def decay(days, grace, half_life):
    return 0.5 ** (max(0.0, days - grace) / half_life)


def run(g, league, titles, k, grace, half_life, cut):
    """Series-by-series Elo with fixed league levels. g: games in date order (blue, red, blue_lg, red_lg, blue_win,
    weight, day, series, blue_new, red_new). titles: game position -> [(team, bonus)], added after that game.
    Returns blue/red ratings before and after each game (one change per series, at its last game), the series
    predictions [(chance, result)], final team levels and last series days."""
    team, last, start, preds = {}, {}, {}, []
    n = len(g)
    rb, rr, ab, ar = (np.empty(n) for _ in range(4))
    cols = [g[c].to_numpy() for c in ["blue", "red", "blue_lg", "red_lg", "blue_win", "weight", "day", "series",
                                      "blue_new", "red_new"]]
    ends = ~pd.Series(cols[7]).duplicated(keep="last").to_numpy()   # last game of each series in date order
    won = {}
    for i, (b, r, lb, lr, w, wt, day, s, nb, nr) in enumerate(zip(*cols)):
        if s not in start:                                  # series start: decay and roster cut, then fix the ratings
            for x, new in ((b, nb), (r, nr)):
                if x in last:
                    team[x] = team.get(x, 0.0) * decay(day - last[x], grace, half_life) * (1 - cut) ** new
                last[x] = day
            start[s] = {b: BASE + league[lb] + team.get(b, 0.0), r: BASE + league[lr] + team.get(r, 0.0)}
            won[s] = {b: 0, r: 0}
        rb[i], rr[i] = start[s][b], start[s][r]
        won[s][b if w else r] += 1
        if ends[i]:
            a, o = list(start[s])                           # the team that was blue in the first game, and its opponent
            p = 1.0 / (1.0 + 10 ** (-(start[s][a] - start[s][o]) / 400))
            res = 1.0 if won[s][a] > won[s][o] else 0.0 if won[s][a] < won[s][o] else 0.5
            preds.append((p, res))
            d = k * wt * (res - p)
            team[a] = team.get(a, 0.0) + d
            team[o] = team.get(o, 0.0) - d
        for t, bonus in titles.get(i, ()):
            team[t] = team.get(t, 0.0) + bonus
        if ends[i] or i in titles:
            ab[i] = BASE + league[lb] + team.get(b, 0.0)
            ar[i] = BASE + league[lr] + team.get(r, 0.0)
        else:
            ab[i], ar[i] = rb[i], rr[i]
    return rb, rr, ab, ar, preds, team, last


def log_loss(p, w):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(w * np.log(p) + (1 - w) * np.log(1 - p)))


def fit(g, prior, titles):
    """g: one row per game in date order with blue, red, blue_lg, red_lg (league and year), blue_fit, red_fit (team and
    year, for the season fit), blue_win, weight, day (days since the first game), series, blue_new, red_new (new
    players). League levels from the season fit, then K, decay and roster cut by log loss. Returns before/after
    ratings, a report and now(team, league level, day): the team's Elo on that day, after decay."""
    w = g["blue_win"].to_numpy(dtype=float)
    side, league, strength = fit_levels(g.assign(blue=g["blue_fit"], red=g["red_fit"]), prior)
    best, grid = None, []
    for k in GRID_K:
        for grace in GRID_GRACE:
            for half in GRID_HALF_LIFE:
                for cut in GRID_ROSTER:
                    out = run(g, league, titles, k, grace, half, cut)
                    p, y = np.array(out[4]).T
                    dec = y != 0.5
                    ll = log_loss(p[dec], y[dec])
                    grid.append((ll, k, grace, half, cut))
                    if best is None or ll < best[0]:
                        best = (ll, (k, grace, half, cut), out, p[dec], y[dec])
    ll, (k, grace, half, cut), (rb, rr, ab, ar, preds, team, last), p, y = best
    report = {"k": k, "decay": [grace, half], "roster_cut": cut, "roster_days": ROSTER_DAYS,
              "grid": [[round(x[0], 4), *x[1:]] for x in sorted(grid)[:10]],
              "side": round(side, 1), "blue_win_rate": round(float(w.mean()), 3), "log_loss": round(ll, 4),
              "accuracy": round(float(((p > 0.5) == (y == 1)).mean()), 3), "games": int(len(g)), "series": len(preds),
              "baseline_accuracy": round(winrate_baseline(g), 3),
              "league_levels": {lg: round(v) for lg, v in sorted(league.items(), key=lambda x: -x[1])}}
    def now(t, lvl, day):
        return BASE + league[lvl] + team.get(t, 0.0) * decay(day - last.get(t, day), grace, half)
    return rb, rr, ab, ar, report, now


def winrate_baseline(g):
    """Accuracy of 'the team with the better series win rate so far wins' (first-game blue side on ties), for comparison."""
    s = g.assign(red_win=1 - g["blue_win"]).groupby("series", sort=False).agg(
        a=("blue", "first"), o=("red", "first"), first_blue=("blue", "first"), bw=("blue_win", "sum"), n=("blue", "size"),
        blues=("blue", list), wins=("blue_win", list))
    won, played, hit = {}, {}, []
    for a, o, blues, wins in zip(s["a"], s["o"], s["blues"], s["wins"]):
        wa = sum(w if b == a else 1 - w for b, w in zip(blues, wins)); wo = len(wins) - wa
        if wa == wo:
            continue
        ra = won.get(a, 0) / played[a] if played.get(a) else 0.5
        ro = won.get(o, 0) / played[o] if played.get(o) else 0.5
        hit.append((ra >= ro) == (wa > wo))
        for t, x in ((a, wa > wo), (o, wo > wa)):
            won[t] = won.get(t, 0) + x
            played[t] = played.get(t, 0) + 1
    return float(np.mean(hit))
