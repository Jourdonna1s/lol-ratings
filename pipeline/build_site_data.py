"""
Builds the data the website reads (docs/data/), rating v0.2.

    python build_site_data.py                 # 2026 file, writes ../docs/data
    python build_site_data.py --csv FILE --out DIR --report

Design
* Domestic games are rated against a baseline per group of leagues (BASELINE_GROUPS, per role);
  international games against their own baseline. Every game is rated once and stored.
* A player's rating for any selection of games (same formula as rateSums() in docs/app.js):
      rating = 1 + c(role) * sum(w * (game_rating - 1)) / (sum(w) + K)
  w = 1 for a domestic game, INTL_WEIGHT for an international one, c(role) a fixed spread constant.
* The site loads data in pieces:
      index.json              config, years, file list, player index (search + which files a player is in)
      summary/<year>.json     per player x league x split x stage: the sums the formula needs (leaderboards)
      games/<year>/<lg>.json  every rated player-game of one league (player pages)
* The rating is a performance rating relative to the games it is built from, not a measure of skill.

Needs rating_core.py and the Oracle's Elixir match-data CSV in this folder.
"""
import argparse, glob, json, os
from datetime import datetime
import numpy as np
import pandas as pd
import rating_core as rc

# ================= CONFIG =================
FILE = "2026_LoL_esports_match_data_from_OraclesElixir.csv"
BASELINE_GROUPS = {"main": ["LCK", "LPL", "LEC", "LCS"], "lcp": ["LCP"]}   # each group is rated against its OWN baseline
LEAGUES = [lg for grp in BASELINE_GROUPS.values() for lg in grp]            # leagues shown on the site
INTERNATIONAL = ["MSI", "WLDs", "FST", "EWC"]          # league codes of international events
# regional qualifiers filed under an international league code. They are shown on the site and count in the
# overall rating (weight 1, rated against the team's home-league baseline), but not as international games.
# EWC 2026: qualifiers Apr-Jun are playoffs=0, the main event in July is playoffs=1
QUALIFIERS = {"EWC": lambda p: p["playoffs"] == 0}
K = 12                 # small-sample shrinkage (use the K_USE printed by the baseline-check notebook)
INTL_WEIGHT = 2.0      # one international game counts as this many domestic games in the overall rating
TARGET_SD = 0.15       # typical spread of player ratings inside a role
MIN_GAMES_CALIBRATION = 15
# common split names across regions (the region's own name is kept in the "split" field)
SPLIT_MAP = {
    ("LEC", "Versus"): "Winter", ("LEC", "Spring"): "Spring", ("LEC", "Summer"): "Summer",
    ("LCK", "Cup"): "Winter", ("LCK", "Rounds 1-2"): "Spring", ("LCK", "Rounds 3-4"): "Summer",
    ("LPL", "Split 1"): "Winter", ("LPL", "Split 2"): "Spring", ("LPL", "Split 3"): "Summer",
    ("LCS", "Lock-In"): "Winter", ("LCS", "Spring"): "Spring", ("LCS", "Summer"): "Summer",
    ("LCS", None): "Summer",   # unlabelled LCS games of Oct 5-13, right after LCS Summer
    ("LCP", "Split 1"): "Winter", ("LCP", "Split 2"): "Spring", ("LCP", "Split 3"): "Summer",
}
OUT_DIR = "../docs/data"

GAME_FIELDS = ["player", "role", "team", "date", "league", "kind", "stage", "period", "split", "opponent", "champion",
               "result", "minutes", "kills", "deaths", "assists", "gd15", "r_early", "r_late", "r_overall"]
SUMMARY_FIELDS = ["player", "league", "kind", "period", "split", "stage",
                  "games", "n", "sw", "swd", "sw2", "s1", "s2", "first", "last", "team"]
PLAYER_FIELDS = ["name", "role", "team", "league", "games", "files"]
ROLES = ["top", "jng", "mid", "bot", "sup"]


def rate_baselines(df, cfg):
    """Rates domestic games per baseline group; international games and qualifiers each against their own baseline."""
    counts = df[df["position"] != "team"].groupby("league")["gameid"].nunique().sort_values(ascending=False)
    print("All league codes in the file and their game counts:")
    print(counts.to_string(), "\n")

    def pool(leagues, label, qualifiers=None):
        """qualifiers=None: all games; False: without the QUALIFIERS games; True: only those."""
        parts = []
        for lg in leagues:
            p = rc.load_games(df, lg, include_playoffs=True)      # keep playoffs, they are tagged and filterable
            if qualifiers is not None:
                q = QUALIFIERS[lg](p) if lg in QUALIFIERS else pd.Series(False, index=p.index)
                p = p[q] if qualifiers else p[~q]
            n = p["gameid"].nunique()
            if n < 10:
                print(f"{label}: {lg} has only {n} complete games, skipped"); continue
            parts.append(rc.add_raw_stats(p))
            print(f"{label}: {lg} {n} games")
        return pd.concat(parts, ignore_index=True) if parts else None

    parts, base_raw = [], {}
    for name, lgs in BASELINE_GROUPS.items():
        raw = pool(lgs, name)
        if raw is None or raw["gameid"].nunique() < 30:
            print(f"{name}: not enough games for its own baseline, skipped")
            continue
        base_raw[name] = raw.copy()                               # kept to rate qualifier games against
        rated = rc.rate(raw, cfg)                                 # this group's own baseline
        print(f"{name}: baseline built from {rated['gameid'].nunique()} games; stats skipped: {rated.attrs.get('skipped_stats')}")
        parts.append(rated)
    dom = pd.concat(parts, ignore_index=True)
    intl = pool(INTERNATIONAL, "international", qualifiers=False)
    if intl is not None and intl["gameid"].nunique() >= 30:
        intl = rc.rate(intl, cfg)                                 # separate international baseline
        print("stats skipped in the international baseline:", intl.attrs.get("skipped_stats"))
    else:
        print("not enough international games, international ratings will be empty")
        intl = None
    print("\nSplit labels per league (domestic), with playoffs flag:")
    print(dom.groupby(["league", "split", "playoffs"])["gameid"].nunique().to_string())
    qual = pool([lg for lg in INTERNATIONAL if lg in QUALIFIERS], "qualifiers", qualifiers=True)
    if qual is not None:
        qual = rate_qualifiers(df, qual, base_raw, pool, cfg)
    return dom, intl, qual


def home_leagues(df):
    """teamid -> the non-international league the team played most games in (from the whole CSV)."""
    t = df[(df["position"] == "team") & ~df["league"].isin(INTERNATIONAL)]
    n = t.groupby(["teamid", "league"])["gameid"].nunique().reset_index()
    return n.sort_values("gameid", ascending=False).drop_duplicates("teamid").set_index("teamid")["league"].to_dict()


def rate_qualifiers(df, qual, base_raw, pool, cfg):
    """Each qualifier player-game is rated against the baseline of the team's home league: the site's baseline
    group if the league is on the site, else a baseline from that league's own games in the CSV.
    The baselines are built from domestic games only, so the qualifier games don't change them.
    A team with no home league in the file gets its opponent's (qualifiers are regional)."""
    home = home_leagues(df)
    qual = qual.copy()
    qual["home"] = qual["teamid"].map(home)
    opp_home = qual.groupby(["gameid", "teamname"])["home"].first()
    for i in qual.index[qual["home"].isna()]:
        other = opp_home.drop((qual.at[i, "gameid"], qual.at[i, "teamname"]), errors="ignore").loc[qual.at[i, "gameid"]]
        qual.at[i, "home"] = other.dropna().iloc[0] if other.notna().any() else None
    group_of = {lg: name for name, lgs in BASELINE_GROUPS.items() for lg in lgs}
    qual["baseline"] = [group_of.get(h, h) if isinstance(h, str) else None for h in qual["home"]]

    parts = []
    for key, q in qual.groupby("baseline", dropna=False):
        ref = base_raw.get(key) if isinstance(key, str) else None
        if ref is None and isinstance(key, str):
            ref = pool([key], f"qualifier baseline {key}")        # a league not on the site: its own games
        if ref is None or ref["gameid"].nunique() < 30:
            print(f"qualifiers: no baseline for {key} ({q['teamname'].unique().tolist()}), {len(q)} player-games skipped")
            continue
        both = pd.concat([ref.assign(_ref=True), q.drop(columns=["home", "baseline"]).assign(_ref=False)], ignore_index=True)
        rated = rc.rate(both, cfg, ref=both["_ref"])
        parts.append(rated[~rated["_ref"]].drop(columns="_ref"))
        print(f"qualifiers: {q['gameid'].nunique()} games, {len(q)} player-games rated against the {key} baseline "
              f"({ref['gameid'].nunique()} games): {', '.join(sorted(q['teamname'].unique()))}")
    return pd.concat(parts, ignore_index=True) if parts else None


def tidy(p, kind):
    """One row per rated player-game, in the columns the site uses."""
    out = pd.DataFrame({
        "player": p["playername"], "role": p["position"], "team": p["teamname"], "gameid": p["gameid"],
        "date": p["date"], "league": p["league"], "kind": kind,
        "stage": np.where(p["playoffs"] == 1, "playoffs", "regular"),
        "split": "Qualifier" if kind == "qualifier" else p["split"],
        "opponent": p["opponent"], "champion": p["champion"], "result": p["result"],
        "minutes": p["minutes"].round(1), "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
        "gd15": p["golddiffat15"],
        "r_early": p["r_early"], "r_late": p["r_late"], "r_overall": p["r_overall"],
    })
    out["period"] = [SPLIT_MAP.get((lg, sp if pd.notna(sp) else None), sp) for lg, sp in zip(out["league"], out["split"])]
    out["year"] = out["date"].dt.year
    return out


def rate_players(g, c_by_role, K=K, W=INTL_WEIGHT, z=1.645):
    """Rating (with ~90% interval) per player for the games in g. Same formula the website uses."""
    g = g.copy()
    g["w"] = np.where(g["kind"] == "international", W, 1.0)
    out = None
    for m in ["overall", "early", "late"]:
        r = g["r_" + m]
        wm = g["w"].where(r.notna(), 0.0)
        tmp = pd.DataFrame({"player": g["player"], "role": g["role"], "wm": wm,
                            "wdev": wm * (r.fillna(1.0) - 1), "w2": wm ** 2, "r": r})
        a = tmp.groupby(["player", "role"]).agg(n_eff=("wm", "sum"), s=("wdev", "sum"), w2=("w2", "sum"), sd=("r", "std"))
        c = a.index.get_level_values("role").map(c_by_role).to_numpy(dtype=float)
        den = a["n_eff"] + K
        a[m] = 1 + c * a["s"] / den
        half = z * c * a["sd"].fillna(0) * np.sqrt(a["w2"]) / den
        a[m + "_low"], a[m + "_high"] = a[m] - half, a[m] + half
        keep = [m, m + "_low", m + "_high"] + (["n_eff"] if m == "overall" else [])
        out = a[keep] if out is None else out.join(a[keep])
    info = g.groupby(["player", "role"]).agg(games=("gameid", "nunique"), team=("team", "last"))
    return out.join(info).reset_index()


def calibrate_c(games):
    """Fixed spread constants c(role): calibrated once, on the first baseline group (the main leagues)."""
    cal = list(BASELINE_GROUPS.values())[0]
    base = rate_players(games[(games["kind"] == "domestic") & games["league"].isin(cal)], {r: 1.0 for r in ROLES})
    q = base[base["games"] >= MIN_GAMES_CALIBRATION].copy()
    q["dev"] = q["overall"] - 1
    c = {r: float(TARGET_SD / q.loc[q["role"] == r, "dev"].std()) for r in ROLES}
    print("spread constants c(role):", {r: round(v, 2) for r, v in c.items()})
    return c


def default_table(games, c_by_role):
    """Per-player table (all games, domestic, international) for players_default_view.csv and the report."""
    dom_t = rate_players(games[games["kind"] == "domestic"], c_by_role).add_prefix("dom_").rename(columns={"dom_player": "player", "dom_role": "role"})
    all_t = rate_players(games, c_by_role)
    if (games["kind"] == "international").any():
        int_t = rate_players(games[games["kind"] == "international"], c_by_role).add_prefix("intl_").rename(columns={"intl_player": "player", "intl_role": "role"})
    else:
        int_t = pd.DataFrame(columns=["player", "role"])
    table = all_t.merge(dom_t[["player", "role", "dom_overall", "dom_games"]], on=["player", "role"], how="left") \
                 .merge(int_t[["player", "role"] + [c for c in int_t.columns if c in ("intl_overall", "intl_overall_low", "intl_overall_high", "intl_games")]],
                        on=["player", "role"], how="left")
    table["league"] = table["team"].map(games.groupby("team")["league"].agg(lambda s: s[s.isin(LEAGUES)].mode().iloc[0] if s.isin(LEAGUES).any() else s.iloc[0]))
    return table


def report(table):
    show = ["league", "team", "player", "games", "dom_overall", "intl_overall", "overall", "overall_low", "overall_high", "early", "late"]
    for role in ROLES:
        x = table[(table["role"] == role) & (table["games"] >= MIN_GAMES_CALIBRATION)].sort_values("overall", ascending=False).head(10)
        print(role.upper(), "(top 10, all games)")
        print(x[[c for c in show if c in x.columns]].round(2).to_string(index=False), "\n")


def rows_of(frame):
    f = frame.astype(object).where(frame.notna(), None)
    return f.values.tolist()


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, default=str, separators=(",", ":"))


def write_site_data(games, c_by_role, cfg, out_dir):
    """Writes index.json, summary/<year>.json and games/<year>/<league>.json (see the module docstring)."""
    g_out = games[GAME_FIELDS + ["year"]].copy()
    g_out["date"] = g_out["date"].dt.strftime("%Y-%m-%d")
    for c in ["r_early", "r_late", "r_overall"]:
        g_out[c] = g_out[c].round(3)
    g_out["gd15"] = g_out["gd15"].round(0)
    g_out[GAME_FIELDS].to_csv(os.path.join(out_dir, "games_rated.csv"), index=False)

    # players in order of first appearance (the site gives them their page addresses in this order)
    pkey = list(zip(g_out["player"], g_out["role"]))
    players = list(dict.fromkeys(pkey))
    pidx = {k: i for i, k in enumerate(players)}
    g_out["pi"] = [pidx[k] for k in pkey]

    years, files, pfiles = sorted(g_out["year"].unique().tolist()), {}, {k: [] for k in players}
    for y in years:
        gy = g_out[g_out["year"] == y].reset_index(drop=True)
        gy["seq"] = np.arange(len(gy))                       # position in the year's date order, used to merge files
        for old in glob.glob(os.path.join(out_dir, "games", str(y), "*.json")):
            os.remove(old)                                    # drop league files that are no longer produced
        for lg, part in gy.groupby("league", sort=False):
            key = f"{y}/{lg}"
            dump(os.path.join(out_dir, "games", str(y), f"{lg}.json"),
                 {"fields": GAME_FIELDS, "rows": rows_of(part[GAME_FIELDS]), "seq": part["seq"].tolist()})
            files[key] = {"rows": int(len(part)), "kinds": sorted(part["kind"].unique().tolist())}
            for k in dict.fromkeys(zip(part["player"], part["role"])):
                pfiles[k].append(key)

        # the sums rateSums() in docs/app.js needs, per player x league x split x stage
        r = gy["r_overall"]
        w = np.where(gy["kind"] == "international", INTL_WEIGHT, 1.0)
        wm = np.where(r.notna(), w, 0.0)
        gy = gy.assign(rated=r.notna().astype(int), wm=wm, wdev=wm * (r.fillna(1.0) - 1), w2=wm ** 2,
                       d1=(r - 1).fillna(0.0), d2=((r - 1) ** 2).fillna(0.0))
        cell = ["pi", "league", "kind", "period", "split", "stage"]
        s = gy.groupby(cell, sort=False, dropna=False).agg(games=("seq", "size"), n=("rated", "sum"), sw=("wm", "sum"), swd=("wdev", "sum"),
                                             sw2=("w2", "sum"), s1=("d1", "sum"), s2=("d2", "sum"),
                                             first=("seq", "min"), last=("seq", "max")).reset_index()
        s["team"] = gy["team"].to_numpy()[s["last"].to_numpy()]
        # ratings have 3 decimals, so these roundings only drop float noise
        s = s.round({"sw": 3, "swd": 3, "sw2": 3, "s1": 3, "s2": 6})
        s = s.rename(columns={"pi": "player"}).sort_values("first")
        dump(os.path.join(out_dir, "summary", f"{y}.json"), {"fields": SUMMARY_FIELDS, "rows": rows_of(s[SUMMARY_FIELDS])})

    # player index: last team, league of the last domestic game (else last game), games, files
    last = g_out.groupby("pi").tail(1).set_index("pi")
    last_dom = g_out[g_out["kind"] == "domestic"].groupby("pi").tail(1).set_index("pi")
    n_games = g_out.groupby("pi").size()
    prow = [[name, role, last.at[i, "team"], (last_dom if i in last_dom.index else last).at[i, "league"],
             int(n_games[i]), pfiles[(name, role)]] for i, (name, role) in enumerate(players)]

    for old in ["site_data.json"]:                            # the single-file layout from before
        if os.path.exists(os.path.join(out_dir, old)):
            os.remove(os.path.join(out_dir, old))
    dump(os.path.join(out_dir, "index.json"), {
        "version": "0.2",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "note": "Performance rating relative to the games it is built from. Not a measure of skill or of league strength.",
        "config": {"leagues": LEAGUES, "baseline_groups": BASELINE_GROUPS, "international": INTERNATIONAL, "qualifiers": sorted(QUALIFIERS), "K": K, "intl_weight": INTL_WEIGHT,
                   "min_games": MIN_GAMES_CALIBRATION, "target_sd": TARGET_SD, "c_by_role": c_by_role,
                   "baselines": "domestic games: one baseline per group of leagues (see baseline_groups); international games: their own baseline; qualifiers of international events: the baseline of each team's home league (a league not on the site: its own games), weight 1, not counted as international",
                   "formula": "rating = 1 + c(role) * sum(w * (game_rating - 1)) / (sum(w) + K)",
                   "early_weights": cfg["EARLY_WEIGHTS"], "late_groups": cfg["LATE_GROUPS"],
                   "late_weights": cfg["LATE_WEIGHTS"], "early_share": cfg["EARLY_SHARE"]},
        "years": years, "files": files, "game_fields": GAME_FIELDS, "summary_fields": SUMMARY_FIELDS,
        "players": {"fields": PLAYER_FIELDS, "rows": prow},
    })


def main(csv=FILE, out_dir=OUT_DIR, show_report=False):
    df = pd.read_csv(csv, low_memory=False)
    cfg = dict(rc.CFG)
    dom, intl, qual = rate_baselines(df, cfg)
    games = pd.concat([tidy(dom, "domestic")] + [tidy(x, k) for x, k in [(intl, "international"), (qual, "qualifier")] if x is not None],
                      ignore_index=True)
    games = games.sort_values("date", kind="stable").reset_index(drop=True)
    print("rated player-games:", len(games), "| domestic:", int((games["kind"] == "domestic").sum()),
          "| international:", int((games["kind"] == "international").sum()), "| qualifier:", int((games["kind"] == "qualifier").sum()))
    c_by_role = calibrate_c(games)
    os.makedirs(out_dir, exist_ok=True)
    table = default_table(games, c_by_role)
    table.round(3).to_csv(os.path.join(out_dir, "players_default_view.csv"), index=False)
    if show_report:
        report(table)
    write_site_data(games, c_by_role, cfg, out_dir)
    total = 0
    for path in sorted(glob.glob(os.path.join(out_dir, "**", "*.json"), recursive=True)):
        kb = os.path.getsize(path) / 1024; total += kb
        print(f"{os.path.relpath(path, out_dir):26s} {kb:8.0f} KB")
    print(f"{'total':26s} {total:8.0f} KB   saved in: {os.path.abspath(out_dir)}")
    return games, table


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build docs/data for the ratings site.")
    ap.add_argument("--csv", default=FILE, help="Oracle's Elixir match-data CSV")
    ap.add_argument("--out", default=OUT_DIR, help="output folder (docs/data)")
    ap.add_argument("--report", action="store_true", help="print the top 10 per role")
    a = ap.parse_args()
    main(a.csv, a.out, a.report)
