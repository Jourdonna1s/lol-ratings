"""
Before/after report for a rating change: compares two builds of docs/data (e.g. the live one and a test build).

    python compare_ratings.py OLD_DIR NEW_DIR [--years 2024 2025 2026] [--json out.json]

Per role: how much the rating separates wins from losses, how much it moves with the teammates' ratings, how stable
a player's average is (split-half), and how often the team with the better-rated players won (leave-one-out).
Champion spread: the average game rating per champion and role. Leaderboards: the major leagues per year (domestic
games, the site's formula), old vs new rank. Only reads the two folders.
"""
import argparse, json, os
import numpy as np
import pandas as pd

ROLES = ["top", "jng", "mid", "bot", "sup"]
MAJOR = {"LCK", "LPL", "LEC", "LCS", "EU LCS", "NA LCS", "LTA N"}
WATCH = [("sup", "Ashe"), ("sup", "Pyke"), ("sup", "Bard"), ("sup", "Alistar"), ("sup", "Nautilus"), ("sup", "Rell"),
         ("top", "Ornn"), ("top", "K'Sante"), ("top", "Sion"), ("top", "Fiora"), ("top", "Jayce"), ("top", "Gangplank"),
         ("bot", "Jhin"), ("bot", "Senna"), ("bot", "Zeri"), ("bot", "Smolder"), ("bot", "Draven"),
         ("mid", "Galio"), ("mid", "Twisted Fate"), ("mid", "Corki"), ("jng", "Sejuani"), ("jng", "Nidalee")]
KEY = ["player", "role", "date", "team", "opponent", "champion", "gn", "minutes"]


def load(d, years):
    idx = json.load(open(os.path.join(d, "index.json"), encoding="utf-8"))
    cfg = idx["config"]
    parts = []
    for y in years:
        gd = os.path.join(d, "games", str(y))
        if not os.path.isdir(gd):
            continue
        for f in sorted(os.listdir(gd)):
            g = json.load(open(os.path.join(gd, f), encoding="utf-8"))
            x = pd.DataFrame(g["rows"], columns=g["fields"])
            x["year"] = y
            parts.append(x)
    g = pd.concat(parts, ignore_index=True)
    return g[g["r_overall"].notna()].copy(), cfg


def role_checks(g):
    g = g.copy()
    g["tg"] = g["series"].astype(str) + "/" + g["gn"].astype(str) + "/" + g["team"]
    s = g.groupby("tg")["r_overall"].transform("sum")
    n = g.groupby("tg")["r_overall"].transform("count")
    g["mates"] = (s - g["r_overall"]) / (n - 1)
    rows = []
    for r in ROLES:
        x = g[g["role"] == r].sort_values("date", kind="stable").copy()
        gap = x.groupby("result")["r_overall"].mean()
        x["half"] = x.groupby(["player", "role"]).cumcount() % 2
        h = x.groupby(["player", "half"])["r_overall"].agg(["mean", "size"]).unstack()
        h = h[(h["size"] >= 8).all(axis=1)]
        rr = h["mean"][0].corr(h["mean"][1], method="spearman")
        rows.append({"role": r, "win_gap": gap.get(1, np.nan) - gap.get(0, np.nan),
                     "with_teammates": x["r_overall"].corr(x["mates"]),
                     "stability": 2 * rr / (1 + rr), "corr_gd15": x["r_overall"].corr(x["gd15"])})
    # leave-one-out: does the team with the better-rated players win?
    tot = g.groupby(["player", "role"])["r_overall"].transform("sum")
    cnt = g.groupby(["player", "role"])["r_overall"].transform("count")
    g["loo"] = ((tot - g["r_overall"]) / (cnt - 1)).where(cnt > 1)
    t = g.groupby("tg").agg(game=("series", "first"), gn=("gn", "first"), s=("loo", "mean"), res=("result", "first"))
    t["game"] = t["game"].astype(str) + "/" + t["gn"].astype(str)
    t = t.reset_index()
    pr = t.merge(t, on="game", suffixes=("", "_o"))
    pr = pr[(pr["tg"] != pr["tg_o"]) & (pr["s"] != pr["s_o"])].dropna(subset=["s", "s_o"])
    acc = float(((pr["s"] > pr["s_o"]) == (pr["res"] == 1)).mean())
    return pd.DataFrame(rows), acc


def board(g, cfg, year):
    x = g[(g["year"] == year) & (g["kind"] == "domestic") & g["league"].isin(MAJOR)]
    a = x.groupby(["player", "role"]).agg(n=("r_overall", "size"), s=("r_overall", lambda v: (v - 1).sum()),
                                          team=("team", "last")).reset_index()
    a["rating"] = 1 + a["role"].map(cfg["c_by_role"]) * a["s"] / (a["n"] + cfg["K"])
    a = a[a["n"] >= cfg.get("min_games", 15)]
    a["rank"] = a.groupby("role")["rating"].rank(ascending=False, method="min").astype(int)
    return a[["player", "role", "team", "n", "rating", "rank"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old"); ap.add_argument("new")
    ap.add_argument("--years", nargs="+", type=int, default=[2024, 2025, 2026])
    ap.add_argument("--json", help="also write the report as JSON (for a report page)")
    a = ap.parse_args()
    old, cfg_o = load(a.old, a.years)
    new, cfg_n = load(a.new, a.years)
    out = {"years": a.years, "c_old": cfg_o["c_by_role"], "c_new": cfg_n["c_by_role"]}
    pd.set_option("display.width", 200)

    print("== Per role, major leagues (domestic), all years given")
    for name, g in (("old", old), ("new", new)):
        m = g[(g["kind"] == "domestic") & g["league"].isin(MAJOR)]
        rc_, acc = role_checks(m)
        print(f"-- {name}: better-rated team won {acc:.1%}")
        print(rc_.round(3).to_string(index=False))
        out["roles_" + name] = rc_.round(4).to_dict("records")
        out["acc_" + name] = acc

    print("\n== Champion averages (game rating, all leagues, all years given)")
    def champ(g):
        c = g.groupby(["role", "champion"])["r_overall"].agg(["mean", "size"])
        return c
    co, cn = champ(old), champ(new)
    j = co.add_suffix("_old").join(cn.add_suffix("_new"))
    j = j[j["size_new"] >= 100]
    spread = j.groupby("role")[["mean_old", "mean_new"]].std()
    print("spread of champion averages (sd) per role:\n" + spread.round(3).to_string())
    out["champ_spread"] = spread.round(4).reset_index().to_dict("records")
    w = j.reindex([k for k in WATCH if k in j.index])
    print(w.round(3).to_string())
    out["champ_watch"] = w.round(4).reset_index().to_dict("records")

    print("\n== Deathless Jhin games with 8+ kills + assists")
    mo = old.merge(new[KEY + ["r_overall"]], on=KEY, suffixes=("_old", "_new"))
    jh = mo[(mo["champion"] == "Jhin") & (mo["deaths"] == 0) & (mo["kills"] + mo["assists"] >= 8)]
    print(f"{len(jh)} games; under 1.00: old {int((jh['r_overall_old'] < 1).sum())}, new {int((jh['r_overall_new'] < 1).sum())}; "
          f"average old {jh['r_overall_old'].mean():.3f}, new {jh['r_overall_new'].mean():.3f}")
    out["jhin"] = {"games": len(jh), "under1_old": int((jh["r_overall_old"] < 1).sum()), "under1_new": int((jh["r_overall_new"] < 1).sum()),
                   "avg_old": float(jh["r_overall_old"].mean()), "avg_new": float(jh["r_overall_new"].mean())}
    dl = mo[(mo["deaths"] == 0) & (mo["kills"] + mo["assists"] >= 8)]
    dlr = dl.groupby("role").agg(games=("r_overall_old", "size"),
                                 under1_old=("r_overall_old", lambda v: (v < 1).mean()),
                                 under1_new=("r_overall_new", lambda v: (v < 1).mean()))
    print("deathless games with 8+ kills + assists, share rated under 1.00:\n" + dlr.round(3).to_string())
    out["deathless"] = dlr.round(4).reset_index().to_dict("records")
    out["game_corr"] = mo.groupby("role")[["r_overall_old", "r_overall_new"]].corr().xs("r_overall_old", level=1)["r_overall_new"].round(3).to_dict()
    print("game rating old vs new correlation per role:", out["game_corr"])

    out["boards"] = {}
    for y in a.years:
        bo, bn = board(old, cfg_o, y), board(new, cfg_n, y)
        b = bn.merge(bo[["player", "role", "rating", "rank"]], on=["player", "role"], how="outer", suffixes=("_new", "_old"))
        b["move"] = b["rank_old"] - b["rank_new"]
        out["boards"][y] = {}
        print(f"\n== {y} major leagues, top 15 per role (new), with the old rank")
        for r in ROLES:
            x = b[b["role"] == r]
            corr = x["rating_old"].corr(x["rating_new"], method="spearman")
            top = x.sort_values("rank_new").head(15)
            print(f"-- {r} (rank correlation old/new {corr:.2f})")
            print(top[["rank_new", "player", "team", "n", "rating_new", "rank_old", "rating_old"]].round(2).to_string(index=False))
            mv = x.dropna(subset=["move"]).sort_values("move")
            out["boards"][y][r] = {"corr": float(corr),
                                   "rows": x.sort_values("rank_new").round(3).replace({np.nan: None}).to_dict("records"),
                                   "risers": mv.tail(5)[::-1][["player", "team", "rank_old", "rank_new"]].to_dict("records"),
                                   "fallers": mv.head(5)[["player", "team", "rank_old", "rank_new"]].to_dict("records")}
    if a.json:
        json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, default=float)


if __name__ == "__main__":
    main()
