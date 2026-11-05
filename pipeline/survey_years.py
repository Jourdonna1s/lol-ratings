"""Survey Oracle's Elixir year files before adding them to the site (phase 7): per year, which leagues, how many games,
how complete, and which of the columns the rating and the site use are filled in.

    python survey_years.py older            every <year>_LoL_esports_match_data_from_OraclesElixir.csv in older/
    python survey_years.py older --leagues  also one line per league (games, complete share, splits, playoffs)
"""
import argparse, glob, os, re
import pandas as pd
import rating_core as rc

# the columns behind the player rating (rating_core) and the team stats on the site
RATING = rc.NUM_COLS
TEAM = ["firstblood", "firstdragon", "firstherald", "firsttower", "dragons", "void_grubs", "barons", "towers",
        "inhibitors", "golddiffat15", "csdiffat15", "xpdiffat15", "dpm", "wpm", "vspm"]
DRAFT = [f"pick{i}" for i in range(1, 6)] + [f"ban{i}" for i in range(1, 6)]


def survey(path, leagues):
    year = re.match(r"(\d{4})_", os.path.basename(path)).group(1)
    d = pd.read_csv(path, low_memory=False)
    pl, tm = d[d["position"] != "team"], d[d["position"] == "team"]
    games = d["gameid"].nunique()
    comp = d.drop_duplicates("gameid")["datacompleteness"].value_counts(normalize=True)
    print(f"\n=== {year}: {games} games, {d['league'].nunique()} leagues, complete {comp.get('complete', 0):.0%}, "
          f"players {pl['playerid'].nunique()} ids / {pl['playername'].nunique()} names, teams {tm['teamname'].nunique()}")
    cplayers = pl[pl["datacompleteness"] == "complete"]
    ctm = tm[tm["datacompleteness"] == "complete"]
    def fill(frame, cols):
        return {c: (frame[c].notna().mean() if c in frame.columns else None) for c in cols}
    for name, frame, cols in (("rating (player rows, complete games)", cplayers, RATING),
                              ("team stats (team rows, complete games)", ctm, TEAM), ("draft (team rows)", tm, DRAFT)):
        f = fill(frame, cols)
        missing = [c for c, v in f.items() if v is None]
        low = [f"{c} {v:.0%}" for c, v in f.items() if v is not None and v < 0.95]
        print(f"  {name}: {len(cols) - len(missing) - len(low)}/{len(cols)} filled"
              + (f"; not in the file: {', '.join(missing)}" if missing else "")
              + (f"; partly: {', '.join(low)}" if low else ""))
    if leagues:
        g = d.drop_duplicates("gameid")
        for lg, x in g.groupby("league"):
            sp = ", ".join(str(s) for s in x["split"].dropna().unique()[:6])
            print(f"  {lg:<14} {len(x):>5} games  complete {(x['datacompleteness'] == 'complete').mean():>4.0%}  "
                  f"playoffs {int(x['playoffs'].sum()):>4}  splits: {sp or '-'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    ap.add_argument("--leagues", action="store_true")
    a = ap.parse_args()
    for p in sorted(glob.glob(os.path.join(a.folder, "*_LoL_esports_match_data_from_OraclesElixir.csv"))):
        survey(p, a.leagues)
