"""
Core of the rating v0.3 as functions, so the same method can be run for several leagues.
v0.3 (phase 9): early-game weights per role (CS lead, kill participation at 15, early team objectives for
junglers), fights count the better of damage or tanking for top/jungle/support and deaths double (supports:
normal), less tower damage for top, less gold swing for supports; and before the z-scores the stats are corrected for (fit_adjustments,
apply_adjustments): style stats against the champion's own average, lane leads against the matchup, and the
extra gold of GOLD_CHAMPS (optional, off: gold and XP leads without the kill gold, KILL_RESIDUAL).
v0.2 is in the git history (before the rating-v03 branch); v0.1 in lec_rating_v0_1.ipynb.
Keep this file in the same folder as the notebooks.
"""
import numpy as np
import pandas as pd

CFG = {
    "MIN_GAMES": 10, "K": 3, "GAME_SD": 0.25, "PLAYER_SD": 0.15,
    # early score (first 15 minutes) per role; each role's weights sum to 1
    "EARLY_WEIGHTS": {      # deaths weigh 1.5x what v0.3's first draft had (deathless games rated too low)
        "top": {"golddiffat10": .09, "golddiffat15": .21, "xpdiffat15": .14, "csdiffat15": .14,
                "killsat15": .14, "assistsat15": .05, "deathsat15": .21, "fb_score": .02},
        "jng": {"golddiffat15": .07, "xpdiffat15": .09, "csdiffat15": .09, "killsat15": .17,
                "assistsat15": .16, "deathsat15": .21, "fb_score": .05, "obj_early": .16},
        "mid": {"golddiffat10": .07, "golddiffat15": .16, "xpdiffat15": .11, "csdiffat15": .11,
                "killsat15": .19, "assistsat15": .09, "deathsat15": .21, "fb_score": .06},
        "bot": {"golddiffat10": .07, "golddiffat15": .16, "xpdiffat15": .07, "csdiffat15": .14,
                "killsat15": .19, "assistsat15": .09, "deathsat15": .21, "fb_score": .07},
        "sup": {"golddiffat15": .04, "xpdiffat15": .09, "killsat15": .09, "assistsat15": .18,
                "deathsat15": .33, "kp15": .18, "fb_score": .09},
    },
    # late groups: stat -> weight inside the group. "dmg" = average of the DMG stats' z-scores, or for TANK_ROLES the
    # better of that and the TANK stat's z-score
    "LATE_GROUPS": {
        "fights":   {"late_kp": 1, "late_deathshare": 2, "dmg": 2, "late_killshare": 1},
        "swing":    {"gold_prog": 1},
        "vision":   {"vspm": 1, "wpm": 1, "wcpm": 1, "cwpm": 1},
        "pressure": {"towerdmg_pm": 1},
    },
    # supports: deaths in fights at normal weight (single support games swung too far with 2)
    "GROUP_WEIGHTS_BY_ROLE": {"sup": {"fights": {"late_kp": 1, "late_deathshare": 1, "dmg": 2, "late_killshare": 1}}},
    "DMG": ["damageshare", "dpm"], "TANK": "tank_share", "TANK_ROLES": ["top", "jng", "sup"],
    "LATE_WEIGHTS": {
        "top": {"fights": .50, "swing": .25, "vision": .05, "pressure": .20},
        "jng": {"fights": .40, "swing": .20, "vision": .15, "pressure": .25},
        "mid": {"fights": .50, "swing": .25, "vision": .05, "pressure": .20},
        "bot": {"fights": .50, "swing": .30, "vision": .05, "pressure": .15},
        "sup": {"fights": .42, "swing": .08, "vision": .40, "pressure": .10},
    },
    "EARLY_SHARE": {"top": .30, "jng": .30, "mid": .25, "bot": .25, "sup": .20},
    "SIGNS": {"deathsat15": -1, "deathshare": -1, "late_deathshare": -1},
    # corrections before the z-scores (fit_adjustments / apply_adjustments)
    # gold/XP leads without the kill gold: off (tested 2026-11-25; it made deathless games rate lower and was left
    # out). To try it: {"golddiffat10": "10", "golddiffat15": "15", "xpdiffat15": "15", "gold_prog": "prog"},
    # with "KILL_SHARE": {"gold_prog": 0.5} to take out only half of the kill gold from the gold swing
    "KILL_RESIDUAL": {},
    "STYLE_STATS": ["damageshare", "dpm", "tank_share", "late_killshare", "late_kp", "towerdmg_pm",
                    "vspm", "wpm", "wcpm", "cwpm", "kp15"],
    "LANE_STATS": ["golddiffat10", "golddiffat15", "xpdiffat15", "csdiffat15"], "LANE_ROLES": ["top", "mid", "bot"],
    "GOLD_STATS": ["golddiffat10", "golddiffat15"],
    "GOLD_CHAMPS": ["Twisted Fate", "Gangplank", "Draven", "Pyke"],
    "SHRINK": {"champ": 25, "pair": 10, "gold_prog": 30},   # n / (n + k): champion averages, matchup pairs
}

NUM_COLS = ["gamelength", "result", "kills", "deaths", "assists", "teamkills", "teamdeaths",
            "firstbloodkill", "firstbloodassist", "firstbloodvictim", "damageshare", "dpm",
            "earned gpm", "earnedgoldshare", "cspm", "vspm", "wpm", "wcpm",
            "controlwardsbought", "damagetotowers", "damagetakenperminute", "damagemitigatedperminute",
            "firstdragon", "firstherald", "void_grubs", "opp_void_grubs"]
for _t in (10, 15, 20, 25):
    NUM_COLS += [f"golddiffat{_t}", f"xpdiffat{_t}", f"csdiffat{_t}",
                 f"killsat{_t}", f"assistsat{_t}", f"deathsat{_t}",
                 f"opp_killsat{_t}", f"opp_assistsat{_t}", f"opp_deathsat{_t}"]
TEAM_OBJ = ["firstdragon", "firstherald", "void_grubs", "opp_void_grubs"]   # from the team rows (load_games)


def blend(frame, weights):
    """Weighted average across columns, ignoring missing values (weights re-scaled per row)."""
    Z = frame.to_numpy(dtype=float)
    W = np.asarray(weights, dtype=float)
    present = ~np.isnan(Z)
    num = np.where(present, Z, 0.0) @ W
    den = present.astype(float) @ W
    out = np.full(len(Z), np.nan)
    np.divide(num, den, out=out, where=den > 0)
    return pd.Series(out, index=frame.index)


def load_games(df, league, splits=None, include_playoffs=False, only_complete=True):
    mask = (df["league"] == league)
    if splits is not None:
        mask &= df["split"].isin(splits)
    if not include_playoffs:
        mask &= (df["playoffs"] == 0)
    p = df[mask & (df["position"] != "team")].copy()
    if only_complete and "datacompleteness" in p.columns:
        p = p[p["datacompleteness"] == "complete"].copy()
    p = p[p.groupby("gameid")["gameid"].transform("size") == 10].copy()
    cols = [c for c in TEAM_OBJ if c in df.columns]
    if cols and "side" in df.columns:                   # early objectives are only on the team rows
        t = df.loc[mask & (df["position"] == "team"), ["gameid", "side"] + cols].drop_duplicates(["gameid", "side"])
        p = p.drop(columns=cols).merge(t, on=["gameid", "side"], how="left")
    p["date"] = pd.to_datetime(p["date"])
    return p.sort_values(["date", "gameid"]).reset_index(drop=True)


def add_raw_stats(p):
    for c in NUM_COLS:
        if c in p.columns:
            p[c] = pd.to_numeric(p[c], errors="coerce")
        else:
            p[c] = np.nan
    p = p.copy()                                        # one block again after the inserts (faster, no warnings)
    p["minutes"] = p["gamelength"] / 60
    tk = p["teamkills"].replace(0, np.nan)
    td = p["teamdeaths"].replace(0, np.nan)
    p["kp"] = (p["kills"] + p["assists"]) / tk
    p["killshare"] = p["kills"] / tk
    p["deathshare"] = p["deaths"] / td
    p["cwpm"] = p["controlwardsbought"] / p["minutes"]
    p["towerdmg_pm"] = p["damagetotowers"] / p["minutes"]
    p["fb_score"] = (p["firstbloodkill"].fillna(0) + 0.5 * p["firstbloodassist"].fillna(0)
                     - p["firstbloodvictim"].fillna(0))
    p["team_k15"] = p.groupby(["gameid", "teamname"])["killsat15"].transform("sum")
    p["team_d15"] = p.groupby(["gameid", "teamname"])["deathsat15"].transform("sum")
    late_tk = p["teamkills"] - p["team_k15"]
    late_td = p["teamdeaths"] - p["team_d15"]
    # v0.3: kill stats need late team kills, the death share late team deaths; a team that never died after 15
    # gives every player a death share of 0 (until v0.2 such games lost all three stats)
    long = p["minutes"] > 18
    ok_k = long & (late_tk > 0)
    late_ka = (p["kills"] - p["killsat15"]) + (p["assists"] - p["assistsat15"])
    p["late_kp"] = (late_ka / late_tk.where(late_tk > 0)).where(ok_k)
    p["late_killshare"] = ((p["kills"] - p["killsat15"]) / late_tk.where(late_tk > 0)).where(ok_k)
    p["late_deathshare"] = ((p["deaths"] - p["deathsat15"]) / late_td.where(late_td > 0)).where(long & (late_td > 0))
    p.loc[long & (late_td == 0), "late_deathshare"] = 0.0
    # games without 15-minute stats: the whole game instead (until v0.2 they had no late fight stats)
    no15 = long & p["killsat15"].isna()
    p.loc[no15, "late_kp"] = p.loc[no15, "kp"]
    p.loc[no15, "late_killshare"] = p.loc[no15, "killshare"]
    p.loc[no15, "late_deathshare"] = p.loc[no15, "deathshare"].where(p.loc[no15, "teamdeaths"] > 0, 0.0)
    d15, d20, d25 = p["golddiffat15"], p["golddiffat20"], p["golddiffat25"]
    p["gold_prog"] = ((d25 - d15) / 10).where(d25.notna(), (d20 - d15) / 5)
    p["kp15"] = ((p["killsat15"] + p["assistsat15"]) / p["team_k15"].where(p["team_k15"] > 0))
    grubs = p["void_grubs"] + p["opp_void_grubs"]
    p["grub_share"] = (p["void_grubs"] / grubs).where(grubs > 0)
    p["obj_early"] = p[["firstdragon", "firstherald", "grub_share"]].mean(axis=1)
    tank = p["damagetakenperminute"] + p["damagemitigatedperminute"]
    p["tank_share"] = tank / tank.groupby([p["gameid"], p["teamname"]]).transform("sum").replace(0, np.nan)
    lane = p.groupby(["gameid", "position"])["champion"]      # the lane opponent: same role, other team
    p["opp_champion"] = np.where(lane.cumcount() == 0, lane.transform("last"), lane.transform("first"))
    p.loc[lane.transform("size") != 2, "opp_champion"] = None
    teams_in_game = p.groupby("gameid")["teamname"].agg(lambda s: sorted(set(s)))
    p["opponent"] = [next((x for x in teams_in_game[g] if x != t_), None)
                     for g, t_ in zip(p["gameid"], p["teamname"])]
    return p


# ---------------- corrections before the z-scores ----------------
def _kill_X(p, key):
    """Own minus lane opponent's kills, assists and deaths: at minute key ("10", "15"), or per minute between 15 and
    25 (20 when the game has no 25-minute stats) for the gold swing ("prog")."""
    cols = ("kills", "assists", "deaths")
    if key == "prog":
        long = p["golddiffat25"].notna()

        def d(c):
            return ((p[f"{c}at25"] - p[f"{c}at15"]) / 10).where(long, (p[f"{c}at20"] - p[f"{c}at15"]) / 5)
        return np.column_stack([(d(c) - d("opp_" + c)).to_numpy(dtype=float) for c in cols])
    return np.column_stack([(p[f"{c}at{key}"] - p[f"opp_{c}at{key}"]).to_numpy(dtype=float) for c in cols])


def _src(p, s):
    return "adj_" + s if "adj_" + s in p.columns else s


def _lookup(p, table, keys):
    """table: Series with a MultiIndex on the columns keys -> the values for p's rows (missing: 0)."""
    if table is None or not len(table):
        return np.zeros(len(p))
    idx = pd.MultiIndex.from_arrays([p[k].to_numpy() for k in keys])
    return table.reindex(idx).fillna(0).to_numpy(dtype=float)


def _shrunk(x, by, k):
    """Group means of x shrunk towards 0 by n / (n + k)."""
    g = x.groupby(by)
    m, n = g.mean(), g.count()
    return n / (n + k) * m


def _apply_kill(p, adj, cfg):
    for s, key in cfg["KILL_RESIDUAL"].items():
        if s not in p.columns:
            continue
        X = _kill_X(p, key)
        coef = np.vstack([adj["kill"].get((s, r), np.zeros(3)) for r in p["position"]])
        fit = np.einsum("ij,ij->i", X, coef) * cfg.get("KILL_SHARE", {}).get(s, 1.0)
        p["adj_" + s] = (p[s] - fit).where(~np.isnan(fit), p[s])


def _apply_style(p, adj):
    for s, t in adj["style"].items():
        p["adj_" + s] = p[_src(p, s)] - _lookup(p, t, ["position", "champion"])


def _lane_expect(p, adj, cfg, s):
    a, pair, pn = adj["champ_lead"][s], adj["pair"][s], adj["pair_n"][s]
    ea = _lookup(p, a, ["position", "champion"])
    eb = _lookup(p, a, ["position", "opp_champion"])
    prior = ea - eb
    m = _lookup(p, pair, ["position", "champion", "opp_champion"])
    n = _lookup(p, pn, ["position", "champion", "opp_champion"])
    w = n / (n + cfg["SHRINK"]["pair"])
    lane = p["position"].isin(cfg["LANE_ROLES"]).to_numpy()
    e = np.where(lane, prior + w * (m - prior), 0.0)
    if s in cfg["GOLD_STATS"]:                  # other roles: only the gold champions' own extra gold
        ga = np.where(p["champion"].isin(cfg["GOLD_CHAMPS"]), ea, 0.0)
        gb = np.where(p["opp_champion"].isin(cfg["GOLD_CHAMPS"]), eb, 0.0)
        e = np.where(lane, e, ga - gb)
    return e


def _apply_lane(p, adj, cfg):
    for s in adj["champ_lead"]:
        p["adj_" + s] = p[_src(p, s)] - _lane_expect(p, adj, cfg, s)


def _apply_gold_prog(p, adj):
    t = adj.get("gold_prog")
    if t is not None and "gold_prog" in p.columns:
        p["adj_gold_prog"] = (p[_src(p, "gold_prog")] - _lookup(p, t, ["position", "champion"])
                              + _lookup(p, t, ["position", "opp_champion"]))


def fit_adjustments(p, cfg=CFG):
    """Fits the corrections on reference games p (after add_raw_stats): gold/XP per kill, assist and death (own
    minus lane opponent, no intercept, so a lane's leads stay zero-sum), champion averages of the style stats
    (shrunk to the role average), expected lane leads per champion and matchup (shrunk), and the gold champions'
    extra gold swing. Returns a dict for apply_adjustments."""
    q = p.copy()
    adj = {"kill": {}, "style": {}, "champ_lead": {}, "pair": {}, "pair_n": {}, "gold_prog": None}
    for s, key in cfg["KILL_RESIDUAL"].items():
        if s not in q.columns:
            continue
        X = _kill_X(q, key)
        y = q[s].to_numpy(dtype=float)
        for r in q["position"].unique():
            m = (q["position"] == r).to_numpy() & np.isfinite(X).all(axis=1) & np.isfinite(y)
            if m.sum() >= 200:
                adj["kill"][(s, r)] = np.linalg.lstsq(X[m], y[m], rcond=None)[0]
    _apply_kill(q, adj, cfg)
    k = cfg["SHRINK"]["champ"]
    for s in cfg["STYLE_STATS"]:
        if s in q.columns and q[s].notna().mean() >= 0.5:
            dev = q[s] - q[s].groupby(q["position"]).transform("mean")
            adj["style"][s] = _shrunk(dev, [q["position"], q["champion"]], k)
    for s in cfg["LANE_STATS"]:
        if s in q.columns and q[s].notna().mean() >= 0.5:
            x = q[_src(q, s)]
            adj["champ_lead"][s] = _shrunk(x, [q["position"], q["champion"]], k)
            g = x.groupby([q["position"], q["champion"], q["opp_champion"]])
            adj["pair"][s], adj["pair_n"][s] = g.mean(), g.count()
    if "gold_prog" in q.columns and q["gold_prog"].notna().mean() >= 0.5:
        sel = q["champion"].isin(cfg["GOLD_CHAMPS"])
        gp = q.loc[sel, _src(q, "gold_prog")]
        adj["gold_prog"] = _shrunk(gp, [q.loc[sel, "position"], q.loc[sel, "champion"]], cfg["SHRINK"]["gold_prog"])
    return adj


def apply_adjustments(p, adj, cfg=CFG):
    """Writes the corrected stats as adj_<stat> columns (the raw columns stay as they are, for display; rate() uses
    adj_ when present). Same order as fit_adjustments: kills, style, lane leads, gold champions' gold swing."""
    if adj is None:
        return p
    _apply_kill(p, adj, cfg)
    _apply_style(p, adj)
    _apply_lane(p, adj, cfg)
    _apply_gold_prog(p, adj)
    return p


def adjustment_report(adj, cfg=CFG):
    """(gold/XP per kill, assist and death per role and stat; the gold champions' measured offsets)."""
    kill = pd.DataFrame([{"stat": s, "role": r, "per_kill": c[0], "per_assist": c[1], "per_death": c[2]}
                         for (s, r), c in adj["kill"].items()])
    champ = []
    for s in cfg["GOLD_STATS"]:
        for (r, ch), v in adj["champ_lead"].get(s, pd.Series(dtype=float)).items():
            if ch in cfg["GOLD_CHAMPS"]:
                champ.append({"stat": s, "role": r, "champion": ch, "offset": v})
    if adj["gold_prog"] is not None:
        champ += [{"stat": "gold_prog", "role": r, "champion": ch, "offset": v}
                  for (r, ch), v in adj["gold_prog"].items()]
    return kill, pd.DataFrame(champ)


def _early_stats(cfg):
    return list(dict.fromkeys(s for w in cfg["EARLY_WEIGHTS"].values() for s in w))


def rate(p, cfg=CFG, ref=None):
    """Adds z-scores, early/late/overall scores and game ratings (r_early, r_late, r_overall).
    ref: optional boolean mask of the rows that make up the baseline (default: all rows). The other rows
    are rated against that baseline without changing it. Uses the adj_<stat> columns of apply_adjustments
    when present."""
    def moments(col):
        g = (p[col] if ref is None else p[col].where(ref)).groupby(p["position"])
        return g.transform("mean"), g.transform("std")

    def zscore(s):
        col = _src(p, s)
        mu, sd = moments(col)
        z = (p[col] - mu) / sd
        return (cfg["SIGNS"].get(s, 1) * z).clip(-3, 3)

    late_stats = [s for grp in cfg["LATE_GROUPS"].values() for s in grp if s != "dmg"]
    stats = _early_stats(cfg) + late_stats + cfg["DMG"] + [cfg["TANK"]]
    skipped = []
    for s in dict.fromkeys(stats):
        if s in p.columns and p[_src(p, s)].notna().mean() >= 0.5:
            p["z_" + s] = zscore(s)
        else:
            skipped.append(s)
    dcols = ["z_" + s for s in cfg["DMG"] if "z_" + s in p.columns]
    if dcols:                                   # damage, or for TANK_ROLES the better of damage and tanking
        p["z_dmg"] = blend(p[dcols], [1.0] * len(dcols))
        if "z_" + cfg["TANK"] in p.columns:
            tk = p["position"].isin(cfg["TANK_ROLES"]) & p["z_" + cfg["TANK"]].notna()
            p.loc[tk, "z_dmg"] = np.fmax(p.loc[tk, "z_dmg"], p.loc[tk, "z_" + cfg["TANK"]])

    p["early"] = np.nan
    for role, w in cfg["EARLY_WEIGHTS"].items():
        m = p["position"] == role
        ecols = [s for s in w if "z_" + s in p.columns]
        if ecols and m.any():
            p.loc[m, "early"] = blend(p.loc[m, ["z_" + s for s in ecols]], [w[s] for s in ecols])
    for name, st in cfg["LATE_GROUPS"].items():
        cols = [s for s in st if "z_" + s in p.columns]
        p["lg_" + name] = blend(p[["z_" + s for s in cols]], [st[s] for s in cols]) if cols else np.nan
    for role, groups in cfg.get("GROUP_WEIGHTS_BY_ROLE", {}).items():     # a role's own weights inside a group
        m = p["position"] == role
        for name, st in groups.items():
            cols = [s for s in st if "z_" + s in p.columns]
            if cols and m.any():
                p.loc[m, "lg_" + name] = blend(p.loc[m, ["z_" + s for s in cols]], [st[s] for s in cols])
    p["late"] = np.nan
    for role, w in cfg["LATE_WEIGHTS"].items():
        m = p["position"] == role
        groups = [g for g in w if "lg_" + g in p.columns and p.loc[m, "lg_" + g].notna().any()]
        if groups:
            p.loc[m, "late"] = blend(p.loc[m, ["lg_" + g for g in groups]], [w[g] for g in groups])
    share = p["position"].map(cfg["EARLY_SHARE"])
    both = p["early"].notna() & p["late"].notna()
    p["overall"] = np.where(both, share * p["early"] + (1 - share) * p["late"], p["early"].fillna(p["late"]))
    for c in ["early", "late", "overall"]:
        mu, sd = moments(c)
        p["r_" + c] = 1 + cfg["GAME_SD"] * (p[c] - mu) / sd
    p.attrs["skipped_stats"] = skipped
    return p


def player_table(p, cfg=CFG):
    z_cols = ([f"z_{s}" for s in _early_stats(cfg) if f"z_{s}" in p.columns]
              + [c for c in p.columns if c.startswith("lg_")])
    g = p.groupby(["playername", "position"])
    t = g.agg(team=("teamname", "last"),
              teams=("teamname", lambda s: ", ".join(dict.fromkeys(s))),
              games=("gameid", "nunique"),
              win_rate=("result", "mean"),
              early=("r_early", "mean"), late=("r_late", "mean"), overall=("r_overall", "mean"),
              early_n=("r_early", "count"), late_n=("r_late", "count"), overall_n=("r_overall", "count"),
              consistency=("r_overall", "std")).reset_index()
    t = t.merge(g[z_cols].mean().round(2).reset_index(), on=["playername", "position"])
    t["qualified"] = t["games"] >= cfg["MIN_GAMES"]
    for c in ["early", "late", "overall"]:
        n = t[c + "_n"]
        shrunk = 1 + n / (n + cfg["K"]) * (t[c] - 1)
        ref = shrunk[t["qualified"]].groupby(t.loc[t["qualified"], "position"])
        mu = t["position"].map(ref.mean())
        sd = t["position"].map(ref.std())
        t[c + "_final"] = 1 + cfg["PLAYER_SD"] * (shrunk - mu) / sd
    t["rank_in_role"] = (t[t["qualified"]].groupby("position")["overall_final"]
                         .rank(ascending=False, method="min")).astype("Int64")
    return t.sort_values(["position", "rank_in_role"]).reset_index(drop=True)


def split_half(p, col, how, min_games=4):
    q = p.dropna(subset=[col]).copy()
    key = ["playername", "position"]
    q["_i"] = q.groupby(key).cumcount()
    q["_n"] = q.groupby(key)[col].transform("size")
    q["_half"] = (q["_i"] % 2) if how == "odd/even" else (q["_i"] >= q["_n"] / 2).astype(int)
    h = q.groupby(key + ["_half"])[col].agg(["mean", "size"]).reset_index()
    a = h[h["_half"] == 0].set_index(key)
    b = h[h["_half"] == 1].set_index(key)
    j = a.join(b, lsuffix="_a", rsuffix="_b", how="inner")
    j = j[(j["size_a"] >= min_games) & (j["size_b"] >= min_games)]
    if len(j) < 8:
        return np.nan, np.nan, int(len(j))
    r = j["mean_a"].rank().corr(j["mean_b"].rank())
    return float(r), float(2 * r / (1 + r)), int(len(j))


def _reliability(p, col):
    vals = [split_half(p, col, how)[1] for how in ("odd/even", "first/second half")]
    return float(np.nanmean(vals)) if not all(np.isnan(vals)) else np.nan


def validate(p, t):
    out = {"games": int(p["gameid"].nunique()), "players": int(p["playername"].nunique())}
    gap = p.groupby("result")[["r_early", "r_late", "r_overall"]].mean()
    for c in ["early", "late", "overall"]:
        out["gap_" + c] = float(gap.loc[1, "r_" + c] - gap.loc[0, "r_" + c]) if {0, 1} <= set(gap.index) else np.nan
    out["corr_gold15_early"] = float(p["r_early"].corr(p["golddiffat15"]))
    out["corr_gold15_overall"] = float(p["r_overall"].corr(p["golddiffat15"]))
    for c in ["early", "late", "overall"]:
        out["rel_" + c] = _reliability(p, "r_" + c)
    q = p.copy()
    q["r_within"] = q["r_overall"] - q.groupby(["gameid", "teamname"])["r_overall"].transform("mean") + 1
    out["rel_within_team"] = _reliability(q, "r_within")
    qq = t[t["qualified"]]
    out["corr_rating_team_winrate"] = float(qq["overall_final"].corr(qq["win_rate"])) if len(qq) > 5 else np.nan

    key = ["playername", "position"]
    tot = p.groupby(key)["r_overall"].transform("sum")
    cnt = p.groupby(key)["r_overall"].transform("count")
    loo = ((tot - p["r_overall"]) / (cnt - 1)).where(cnt > 1)
    ts = (p.assign(loo=loo).groupby(["gameid", "teamname"])
          .agg(strength=("loo", "mean"), result=("result", "first")).reset_index())
    wins = ts.groupby("teamname")["result"].transform("sum")
    n_g = ts.groupby("teamname")["result"].transform("size")
    ts["team_wr_loo"] = ((wins - ts["result"]) / (n_g - 1)).where(n_g > 1)
    pairs = ts.merge(ts, on="gameid", suffixes=("", "_o"))
    pairs = pairs[pairs["teamname"] != pairs["teamname_o"]]

    def accuracy(col):
        x = pairs.dropna(subset=[col, col + "_o"])
        x = x[x[col] != x[col + "_o"]]
        return float(((x[col] > x[col + "_o"]) == (x["result"] == 1)).mean()) if len(x) else np.nan

    out["acc_player_ratings"] = accuracy("strength")
    out["acc_team_winrate"] = accuracy("team_wr_loo")
    return out


def _player_scores(p, overall_game, cfg):
    pos = p["position"]
    r = 1 + cfg["GAME_SD"] * (overall_game - overall_game.groupby(pos).transform("mean")) / overall_game.groupby(pos).transform("std")
    tmp = p[["playername", "position", "gameid"]].copy()
    tmp["r"] = r
    a = tmp.groupby(["playername", "position"]).agg(avg=("r", "mean"), n=("r", "count"),
                                                    games=("gameid", "nunique")).reset_index()
    a["shrunk"] = 1 + a["n"] / (a["n"] + cfg["K"]) * (a["avg"] - 1)
    a = a[a["games"] >= cfg["MIN_GAMES"]].copy()
    mu = a.groupby("position")["shrunk"].transform("mean")
    sd = a.groupby("position")["shrunk"].transform("std")
    a["score"] = 1 + cfg["PLAYER_SD"] * (a["shrunk"] - mu) / sd
    return a.set_index(["playername", "position"])["score"]


def sensitivity(p, cfg=CFG):
    """Rank correlation between the current player ratings and ratings under changed weights."""
    base = _player_scores(p, p["overall"], cfg)
    variants = {"early share x0.5": dict(share=0.5), "early share x1.5": dict(share=1.5),
                "late only": dict(share=0.0), "early only": dict(share=99),
                "gold weight x0.5": dict(gold=0.5), "gold weight x1.5": dict(gold=1.5)}
    out = {}
    for name, v in variants.items():
        early_v = pd.Series(np.nan, index=p.index)
        for role, wr in cfg["EARLY_WEIGHTS"].items():
            w = {s: x * (v.get("gold", 1.0) if s.startswith("golddiff") else 1) for s, x in wr.items()}
            ec = [s for s in w if "z_" + s in p.columns]
            m = p["position"] == role
            if ec and m.any():
                early_v[m] = blend(p.loc[m, ["z_" + s for s in ec]], [w[s] for s in ec])
        share_v = (p["position"].map(cfg["EARLY_SHARE"]) * v.get("share", 1.0)).clip(0, 1)
        both = early_v.notna() & p["late"].notna()
        ov = pd.Series(np.where(both, share_v * early_v + (1 - share_v) * p["late"],
                                early_v.fillna(p["late"])), index=p.index)
        sc = _player_scores(p, ov, cfg).reindex(base.index)
        out[name] = float(base.rank().corr(sc.rank()))
    return out
