"""
Core of the LEC rating v0.1 as functions, so the same method can be run for several leagues.
It mirrors lec_rating_v0_1.ipynb (same formula). Keep this file in the same folder as the notebook.
"""
import numpy as np
import pandas as pd

CFG = {
    "MIN_GAMES": 10, "K": 3, "GAME_SD": 0.25, "PLAYER_SD": 0.15,
    "EARLY_WEIGHTS": {
        "golddiffat10": .15, "golddiffat15": .25,
        "killsat15": .22, "assistsat15": .08, "deathsat15": .15,
        "xpdiffat15": .10, "fb_score": .05,
    },
    "LATE_GROUPS": {
        "fights":   ["late_kp", "late_deathshare", "damageshare", "dpm"],
        "swing":    ["gold_prog"],
        "vision":   ["vspm", "wpm", "wcpm", "cwpm"],
        "pressure": ["towerdmg_pm"],
    },
    "LATE_WEIGHTS": {
        "top": {"fights": .40, "swing": .25, "vision": .05, "pressure": .30},
        "jng": {"fights": .40, "swing": .20, "vision": .15, "pressure": .25},
        "mid": {"fights": .50, "swing": .25, "vision": .05, "pressure": .20},
        "bot": {"fights": .50, "swing": .30, "vision": .05, "pressure": .15},
        "sup": {"fights": .35, "swing": .15, "vision": .40, "pressure": .10},
    },
    "EARLY_SHARE": {"top": .40, "jng": .35, "mid": .35, "bot": .35, "sup": .25},
    "SIGNS": {"deathsat15": -1, "deathshare": -1, "late_deathshare": -1},
}

NUM_COLS = ["gamelength", "result", "kills", "deaths", "assists", "teamkills", "teamdeaths",
            "firstbloodkill", "firstbloodassist", "firstbloodvictim", "damageshare", "dpm",
            "earned gpm", "earnedgoldshare", "cspm", "vspm", "wpm", "wcpm",
            "controlwardsbought", "damagetotowers"]
for _t in (10, 15, 20, 25):
    NUM_COLS += [f"golddiffat{_t}", f"xpdiffat{_t}", f"csdiffat{_t}",
                 f"killsat{_t}", f"assistsat{_t}", f"deathsat{_t}"]


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
    p["date"] = pd.to_datetime(p["date"])
    return p.sort_values(["date", "gameid"]).reset_index(drop=True)


def add_raw_stats(p):
    for c in NUM_COLS:
        if c in p.columns:
            p[c] = pd.to_numeric(p[c], errors="coerce")
        else:
            p[c] = np.nan
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
    ok = (p["minutes"] > 18) & (late_tk > 0) & (late_td > 0)
    late_ka = (p["kills"] - p["killsat15"]) + (p["assists"] - p["assistsat15"])
    p["late_kp"] = (late_ka / late_tk).where(ok)
    p["late_deathshare"] = ((p["deaths"] - p["deathsat15"]) / late_td).where(ok)
    d15, d20, d25 = p["golddiffat15"], p["golddiffat20"], p["golddiffat25"]
    p["gold_prog"] = ((d25 - d15) / 10).where(d25.notna(), (d20 - d15) / 5)
    teams_in_game = p.groupby("gameid")["teamname"].agg(lambda s: sorted(set(s)))
    p["opponent"] = [next((x for x in teams_in_game[g] if x != t_), None)
                     for g, t_ in zip(p["gameid"], p["teamname"])]
    return p


def rate(p, cfg=CFG):
    """Adds z-scores, early/late/overall scores and game ratings (r_early, r_late, r_overall)."""
    def zscore(col):
        g = p.groupby("position")[col]
        z = (p[col] - g.transform("mean")) / g.transform("std")
        return (cfg["SIGNS"].get(col, 1) * z).clip(-3, 3)

    stats = list(cfg["EARLY_WEIGHTS"]) + [s for grp in cfg["LATE_GROUPS"].values() for s in grp]
    skipped = []
    for s in dict.fromkeys(stats):
        if s in p.columns and p[s].notna().mean() >= 0.5:
            p["z_" + s] = zscore(s)
        else:
            skipped.append(s)

    ecols = [s for s in cfg["EARLY_WEIGHTS"] if "z_" + s in p.columns]
    p["early"] = (blend(p[["z_" + s for s in ecols]], [cfg["EARLY_WEIGHTS"][s] for s in ecols])
                  if ecols else np.nan)
    for name, st in cfg["LATE_GROUPS"].items():
        cols = ["z_" + s for s in st if "z_" + s in p.columns]
        p["lg_" + name] = blend(p[cols], [1.0] * len(cols)) if cols else np.nan
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
        g = p.groupby("position")[c]
        p["r_" + c] = 1 + cfg["GAME_SD"] * (p[c] - g.transform("mean")) / g.transform("std")
    p.attrs["skipped_stats"] = skipped
    return p


def player_table(p, cfg=CFG):
    z_cols = ([f"z_{s}" for s in cfg["EARLY_WEIGHTS"] if f"z_{s}" in p.columns]
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
        w = {s: x * (v.get("gold", 1.0) if s.startswith("golddiff") else 1)
             for s, x in cfg["EARLY_WEIGHTS"].items()}
        ec = [s for s in w if "z_" + s in p.columns]
        early_v = blend(p[["z_" + s for s in ec]], [w[s] for s in ec])
        share_v = (p["position"].map(cfg["EARLY_SHARE"]) * v.get("share", 1.0)).clip(0, 1)
        both = early_v.notna() & p["late"].notna()
        ov = pd.Series(np.where(both, share_v * early_v + (1 - share_v) * p["late"],
                                early_v.fillna(p["late"])), index=p.index)
        sc = _player_scores(p, ov, cfg).reindex(base.index)
        out[name] = float(base.rank().corr(sc.rank()))
    return out
