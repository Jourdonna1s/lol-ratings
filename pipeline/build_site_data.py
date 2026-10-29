"""
Builds the data the website reads (docs/data/), rating v0.2.

    python build_site_data.py                 # 2026 file, writes ../docs/data
    python build_site_data.py --csv FILE --out DIR --report

Design
* Every regular league in the file is rated against its own baseline (per role), except the leagues grouped
  in BASELINE_GROUPS, which share one. International games are rated against their own baseline.
  Cross-league events (EVENTS) and qualifiers (QUALIFIERS): each team against its home league's baseline.
  Every game is rated once and stored.
* A player's rating for any selection of games (same formula as rateSums() in docs/app.js):
      rating = 1 + c(role) * sum(w * (game_rating - 1)) / (sum(w) + K)
  w = 1, or INTL_WEIGHT for an international game; c(role) a fixed spread constant.
* The site loads data in pieces:
      index.json              config, years, file list, player index (search + which files a player is in)
      summary/<year>.json     per player x league x split x stage: the sums the formula needs (leaderboards)
      games/<year>/<lg>.json  every rated player-game of one league (player pages)
* The rating is a performance rating relative to the games it is built from, not a measure of skill.

Needs rating_core.py and the Oracle's Elixir match-data CSV in this folder.
"""
import argparse, glob, json, os
from datetime import datetime
from itertools import combinations
import numpy as np
import pandas as pd
import rating_core as rc
import team_elo

# ================= CONFIG =================
FILE = "2026_LoL_esports_match_data_from_OraclesElixir.csv"
# leagues that share one baseline; every other league with enough games gets its own
BASELINE_GROUPS = {"main": ["LCK", "LPL", "LEC", "LCS"], "lcp": ["LCP"]}
MIN_BASELINE_GAMES = 30   # complete games a league needs for its own baseline (smaller leagues are left out)
# league tiers shown on the site: major, tier 1, tier 2 (leagues not listed), tier 3
TIERS = {"major": ["LCK", "LPL", "LEC", "LCS"],
         "tier1": ["LCP", "CBLOL"],
         "tier3": ["LAS", "NL", "HC"]}
INTERNATIONAL = ["MSI", "WLDs", "FST", "EWC"]          # league codes of international events
# cross-league events (teams from several leagues): each team is rated against its home league's baseline,
# counted with weight 1, and not as international games. They get their own leaderboard on the site.
EVENTS = ["EM", "KeSPA Cup", "AM", "AC", "CCWS", "HW", "WSCI", "DCGI", "DCup", "WLRQ"]
# regional qualifiers filed under an international league code: rated like EVENTS, shown as "<event> Qualifier"
# EWC 2026: qualifiers Apr-Jun are playoffs=0, the main event in July is playoffs=1
# Worlds: a region's own qualifier filed under WLDs (2026: the LPL qualifier of Sep 17-19) = the games before the
# event's last break of 14+ days
def before_last_gap(p, days=14):
    d = pd.to_datetime(p["date"]).dt.normalize()
    u = np.sort(d.unique())
    gaps = np.where(np.diff(u) >= np.timedelta64(days, "D"))[0]
    return d < u[gaps[-1] + 1] if len(gaps) else pd.Series(False, index=p.index)
QUALIFIERS = {"EWC": lambda p: p["playoffs"] == 0, "WLDs": before_last_gap}
# names shown on the site (codes not listed are shown as the code)
LEAGUE_NAMES = {
    "LCKC": "LCK Challengers", "LAS": "LCK Academy Series", "NACL": "NA Challengers", "CD": "Circuito Desafiante", "PRM": "Prime League",
    "EBL": "Esports Balkan League", "ROL": "Road of Legends", "AL": "Arabian League", "RL": "Rift Legends",
    "HM": "Hitpoint Masters", "LRN": "Liga Regional Norte", "LRS": "Liga Regional Sur",
    "EM": "EMEA Masters", "WLDs": "Worlds", "EWC": "Esports World Cup", "FST": "First Stand",
}
K = 12                 # small-sample shrinkage (use the K_USE printed by the baseline-check notebook)
INTL_WEIGHT = 2.0      # one international game counts as this many domestic games in the overall rating
TARGET_SD = 0.15       # typical spread of player ratings inside a role
MIN_GAMES_CALIBRATION = 15
# common split names for the major leagues (the region's own name is kept in the "split" field).
# Other leagues keep their own split names.
SPLIT_MAP = {
    ("LEC", "Versus"): "Winter", ("LEC", "Spring"): "Spring", ("LEC", "Summer"): "Summer",
    ("LCK", "Cup"): "Winter", ("LCK", "Rounds 1-2"): "Spring", ("LCK", "Rounds 3-4"): "Summer",
    ("LPL", "Split 1"): "Winter", ("LPL", "Split 2"): "Spring", ("LPL", "Split 3"): "Summer",
    ("LCS", "Lock-In"): "Winter", ("LCS", "Spring"): "Spring", ("LCS", "Summer"): "Summer",
    ("LCS", "Promotion"): None,   # the LCS Promotion tournament (see UNLABELLED): not a split, no common name
}
# unlabelled games of a major league that are their own tournament: league -> split name
UNLABELLED = {"LCS": "Promotion"}   # LCS Oct 5-13, 2026: the LCS Promotion tournament (NA Challengers / LRN teams)
# tournaments shown in another tier than their league's: (league, split) -> tier
TOUR_TIERS = {("LCS", "Promotion"): "tier2"}
# tournament formats (hand-written from Riot's announcements and press coverage; the data has no format or stage
# information beyond a playoffs flag on league games). Key: (year, league, split or None).
# stages: name, type ("table": standings make sense, e.g. a round robin or Swiss; "bracket": series in order),
# which games: {"flag": "regular"/"playoffs"} (the data's playoffs flag) or {"from": "MM-DD", "to": "MM-DD"} (dates).
# Tournaments not listed get stages from the data: regular season + playoffs, or one list of results.
def _st(name, kind, desc, **games):
    return {"name": name, "type": kind, "desc": desc, **games}
_LEAGUE = [_st("Regular season", "table", "", flag="regular"), _st("Playoffs", "bracket", "", flag="playoffs")]
def _lg(regular, playoffs):
    return [_st("Regular season", "table", regular, flag="regular"), _st("Playoffs", "bracket", playoffs, flag="playoffs")]
FORMATS = {
    (2026, "FST", None): {"about": "8 teams: the winners of the LCK, LPL, LEC, LCS, LCP and CBLOL opening tournaments, plus a second LCK and LPL team. Every series is a best of 5 with Fearless Draft.",
                          "stages": [_st("Group stage", "bracket", "Two groups of four, double elimination (GSL style); two teams of each group go through.", **{"from": "03-16", "to": "03-20"}),
                                     _st("Knockout stage", "bracket", "Semifinals and final, single elimination.", **{"from": "03-21", "to": "03-22"})]},
    (2026, "MSI", None): {"about": "11 teams. Every series is a best of 5 with Fearless Draft.",
                          "stages": [_st("Play-In", "bracket", "Four teams, double elimination; one goes through to the Bracket Stage.", **{"from": "06-28", "to": "07-01"}),
                                     _st("Bracket Stage", "bracket", "Eight teams, double elimination.", **{"from": "07-02", "to": "07-12"})]},
    (2026, "EWC", None): {"about": "16 teams at the Esports World Cup.",
                          "stages": [_st("Group stage", "bracket", "Four groups of four, double elimination: opening matches best of 1, deciding matches best of 3. The top two of each group go through.", **{"from": "07-15", "to": "07-16"}),
                                     _st("Playoffs", "bracket", "Eight teams, single elimination, best of 3; the final is a best of 5.", **{"from": "07-17", "to": "07-19"})]},
    (2026, "EWC", "Qualifier"): {"about": "Regional qualifiers for the Esports World Cup, filed under EWC in the data. Not part of the main event.",
                                 "stages": [_st("Qualifier matches", "bracket", "", **{"from": "01-01", "to": "12-31"})]},
    (2026, "WLDs", "Qualifier"): {"about": "The LPL's own qualifier for its last Worlds spots, filed under Worlds in the data. Not part of the Worlds event (no Play-In).",
                                  "stages": [_st("Qualifier matches", "bracket", "Best of 5.", **{"from": "01-01", "to": "12-31"})]},
    (2026, "WLDs", None): {"about": "Three stages: Play-In, Swiss Stage and Knockout Stage.",
                           "stages": [_st("Play-In", "bracket", "Four teams, double elimination, best of 5; one goes through to the Swiss Stage.", **{"from": "10-01", "to": "10-19"}),
                                      _st("Swiss Stage", "table", "16 teams, paired by record; 3 wins go through, 3 losses are out. Best of 1, except best of 3 when a team can go through or be eliminated.", **{"from": "10-20", "to": "10-31"}),
                                      _st("Knockout Stage", "bracket", "Eight teams, single elimination, best of 5 with Fearless Draft.", **{"from": "11-01", "to": "12-31"})]},
    (2026, "LEC", "Versus"): {"about": "12 teams (the 10 LEC teams plus two ERL invitees). The winner goes to First Stand.",
                              "stages": _lg("Single round robin, best of 1.", "Playoff bracket; the last rounds are best of 5.")},
    (2026, "LEC", "Spring"): {"about": "10 teams. The top two go to MSI.", "stages": _lg("Single round robin, best of 3; the top six go to the playoffs.", "Double elimination, best of 5.")},
    (2026, "LEC", "Summer"): {"about": "10 teams. The top three go to Worlds.", "stages": _lg("Single round robin, best of 3; the top six go to the playoffs.", "Double elimination, best of 5.")},
    (2026, "LCK", "Cup"): {"about": "10 teams, Fearless Draft. The winner goes to First Stand.",
                           "stages": [_st("Group stage", "table", "Two groups; teams play the other group's teams.", **{"from": "01-14", "to": "02-01"}),
                                      _st("Play-In", "bracket", "", **{"from": "02-02", "to": "02-10"}),
                                      _st("Playoffs", "bracket", "Double elimination, best of 5.", **{"from": "02-11", "to": "03-01"})]},
    (2026, "LCK", "Rounds 1-2"): {"about": "10 teams. After Rounds 1-2 the top five form the Legend group and the bottom five the Rise group for Rounds 3-4.",
                                  "stages": _lg("Double round robin, best of 3.", "Playoffs for the MSI spots.")},
    (2026, "LCK", "Rounds 3-4"): {"about": "Rounds 3-4 in the Legend and Rise groups (results carry over), then the Season Play-In and Season Playoffs, with Fearless Draft. The top three go to Worlds.",
                                  "stages": _lg("Rounds 3-4: double round robin, best of 3, in the Legend and Rise groups (the table mixes both groups).", "Season Play-In and Season Playoffs: double elimination, best of 5.")},
    (2026, "LPL", "Split 1"): {"about": "14 teams in three groups (Ascend, Perseverance, Nirvana). The top two go to First Stand.",
                               "stages": _lg("Double round robin in each group, best of 3 (the table mixes the groups).", "Play-In, then an eight-team double-elimination bracket, best of 5.")},
    (2026, "LPL", "Split 2"): {"about": "14 teams in two groups. The top two go to MSI.", "stages": _lg("Regular season in two groups, best of 3 (the table mixes the groups).", "Playoffs, best of 5.")},
    (2026, "LPL", "Split 3"): {"about": "12 teams. The winner is the LPL season champion.", "stages": _lg("Regular season, best of 3.", "Playoffs, best of 5.")},
    (2026, "LCS", "Lock-In"): {"about": "8 teams, Fearless Draft. The winner goes to First Stand.",
                               "stages": [_st("Swiss stage", "table", "Best of 3, paired by record.", **{"from": "01-24", "to": "02-10"}),
                                          _st("Playoffs", "bracket", "", **{"from": "02-11", "to": "03-02"})]},
    (2026, "LCS", "Spring"): {"about": "8 teams. The top two go to MSI.", "stages": _lg("Round robin, best of 3; the top six go to the playoffs.", "Double elimination, best of 5.")},
    (2026, "LCS", "Summer"): {"about": "8 teams. The top three go to Worlds.",
                              "stages": _lg("Round robin, best of 3; the top six go to the playoffs.", "Double elimination with a lower-bracket gauntlet, best of 5.")},
    (2026, "LCS", "Promotion"): {"about": "The LCS Promotion Tournament for the LCS guest slot in 2027: Disguised, the current guest team, against the top teams of NA Challengers and Liga Regional Norte. Hybrid, with LAN finals in Mexico City. The data files these games as LCS games without a split name.",
                                 "stages": [_st("Bracket", "bracket", "Double elimination, best of 5, with a play-in.", **{"from": "01-01", "to": "12-31"})]},
    (2026, "LCP", "Split 1"): {"about": "8 teams. The winner goes to First Stand.", "stages": _lg("Single round robin, best of 3.", "Knockout playoffs, best of 5.")},
    (2026, "LCP", "Split 2"): {"about": "8 teams. The top two go to MSI.", "stages": _lg("Single round robin, best of 3.", "Knockout playoffs, best of 5.")},
    (2026, "LCP", "Split 3"): {"about": "8 teams. The top three go to Worlds.",
                               "stages": [_st("Swiss stage", "table", "Best of 3 and best of 5 series, paired by record.", **{"from": "07-25", "to": "08-01"}),
                                          _st("Playoffs", "bracket", "", **{"from": "08-02", "to": "08-30"})]},
    (2026, "CBLOL", "Cup"): {"about": "8 teams. The winner goes to First Stand.",
                             "stages": [_st("Round robin", "table", "Single round robin, best of 1. The top four go to the playoffs, 5th to 8th to the entry phase.", **{"from": "01-17", "to": "02-01"}),
                                        _st("Entry phase and playoffs", "bracket", "", **{"from": "02-02", "to": "03-01"})]},
    (2026, "CBLOL", "Split 1"): {"about": "The winner goes to MSI.", "stages": _lg("Single round robin, best of 3, Fearless Draft.", "Playoffs with Fearless Draft.")},
    (2026, "CBLOL", "Split 2"): {"about": "The top teams go to Worlds.", "stages": _lg("Single round robin, best of 3, Fearless Draft.", "Playoffs with Fearless Draft.")},
}
SPLIT_GAP_DAYS = 21    # unlabelled games: take the nearest labelled game's split within this many days
OUT_DIR = "../docs/data"

GAME_FIELDS = ["player", "role", "team", "date", "league", "kind", "stage", "period", "split", "opponent", "champion",
               "result", "minutes", "kills", "deaths", "assists", "gd15", "r_early", "r_late", "r_overall"]
SUMMARY_FIELDS = ["player", "league", "kind", "period", "split", "stage",
                  "games", "n", "sw", "swd", "sw2", "s1", "s2", "first", "last", "team", "ti"]
PLAYER_FIELDS = ["name", "role", "team", "league", "games", "files"]
# team-games (one row per team per game, partial games included: records and Elo use every game)
TEAM_FIELDS = ["team", "ti", "date", "league", "kind", "stage", "period", "split", "opponent", "oi", "side", "result", "game",
               "series", "s_result", "minutes", "kills", "deaths", "fb", "fd", "fh", "ft", "dragons", "grubs", "barons", "towers",
               "inhibs", "gd15", "csd15", "xpd15", "dpm", "wpm", "vspm", "picks", "bans", "elo_before", "elo_after"]
TEAM_SUMMARY_FIELDS = ["team", "league", "kind", "period", "split", "stage", "games", "wins", "s_won", "s_lost",
                       "gd_n", "gd_sum", "blue_games", "blue_wins", "first", "last", "elo"]
TEAM_INDEX_FIELDS = ["name", "league", "games", "files"]
# tournaments: year, league, kind and split identify one (the same fields as on the game rows); champ/runner: team index
TOUR_FIELDS = ["year", "league", "kind", "split", "period", "name", "first", "last", "teams", "series", "games", "champ", "runner",
               "done", "final", "playoffs", "format", "stages", "places", "tier"]
ROLES = ["top", "jng", "mid", "bot", "sup"]


def tier_of(lg):
    if lg in INTERNATIONAL: return "international"
    if lg in EVENTS: return "event"
    return next((t for t, lgs in TIERS.items() if lg in lgs), "tier2")


def regular_leagues(df):
    """Leagues with enough complete games for a baseline: major first (TIERS order), then by code."""
    t = df[(df["position"] == "team") & (df["datacompleteness"] == "complete")]
    n = t.groupby("league")["gameid"].nunique()
    ok = [lg for lg in n.index if lg not in INTERNATIONAL and lg not in EVENTS and n[lg] >= MIN_BASELINE_GAMES]
    small = sorted(lg for lg in n.index if lg not in INTERNATIONAL and lg not in EVENTS and n[lg] < MIN_BASELINE_GAMES)
    if small:
        print(f"leagues with fewer than {MIN_BASELINE_GAMES} complete games, left out:", small)
    major = [lg for lg in TIERS["major"] if lg in ok]
    return major + sorted((lg for lg in ok if lg not in major), key=str.lower)


def baselines(leagues):
    """Baseline name -> its leagues: the BASELINE_GROUPS, then every other league on its own."""
    grouped = {lg for lgs in BASELINE_GROUPS.values() for lg in lgs}
    return {**BASELINE_GROUPS, **{lg: [lg] for lg in leagues if lg not in grouped}}


def home_leagues(df):
    """teamid -> the regular league the team played most games in (from the whole CSV)."""
    t = df[(df["position"] == "team") & ~df["league"].isin(INTERNATIONAL + EVENTS)]
    n = t.groupby(["teamid", "league"])["gameid"].nunique().reset_index()
    return n.sort_values("gameid", ascending=False).drop_duplicates("teamid").set_index("teamid")["league"].to_dict()


def check_events(df, leagues):
    """Warns about regular leagues whose teams mostly belong to other leagues (probably an event to list in EVENTS)."""
    home = home_leagues(df)
    t = df[(df["position"] == "team") & df["league"].isin(leagues)].drop_duplicates(["league", "teamid"])
    away = (t["teamid"].map(home) != t["league"]).groupby(t["league"]).mean()
    for lg in away[away > 0.5].index:
        print(f"WARNING: most {lg} teams belong to other leagues. If it is a cup or tournament, add it to EVENTS.")
    unlisted = [lg for lg in leagues if not any(lg in lgs for lgs in TIERS.values())]
    print("tier 2 (not listed in TIERS):", ", ".join(unlisted))


def rate_baselines(df, cfg):
    """Rates every regular league against its baseline, international games against their own, and
    events + qualifiers against each team's home-league baseline. Returns (domestic, international, events)."""
    counts = df[df["position"] != "team"].groupby("league")["gameid"].nunique().sort_values(ascending=False)
    print("All league codes in the file and their game counts:")
    print(counts.to_string(), "\n")

    def pool(leagues, label, qualifiers=None, quiet=False):
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
            p = rc.add_raw_stats(p)
            p["qualifier"] = bool(qualifiers)
            parts.append(p)
            if not quiet:
                print(f"{label}: {lg} {n} games")
        return pd.concat(parts, ignore_index=True) if parts else None

    leagues = regular_leagues(df)
    check_events(df, leagues)
    parts, base_raw = [], {}
    for name, lgs in baselines(leagues).items():
        raw = pool(lgs, name, quiet=True)
        if raw is None or raw["gameid"].nunique() < MIN_BASELINE_GAMES:
            print(f"{name}: not enough games for its own baseline, skipped")
            continue
        base_raw[name] = raw.copy()                               # kept to rate event and qualifier games against
        rated = rc.rate(raw, cfg)                                 # this baseline's own games
        rated["baseline"] = name
        skipped = rated.attrs.get("skipped_stats")
        print(f"baseline {name}: {rated['gameid'].nunique()} games ({', '.join(lgs)})" + (f"; stats skipped: {skipped}" if skipped else ""))
        parts.append(rated)
    dom = pd.concat(parts, ignore_index=True)
    intl = pool(INTERNATIONAL, "international", qualifiers=False)
    if intl is not None and intl["gameid"].nunique() >= 30:
        intl = rc.rate(intl, cfg)                                 # separate international baseline
        intl["baseline"] = "international"
        print("stats skipped in the international baseline:", intl.attrs.get("skipped_stats"))
    else:
        print("not enough international games, international ratings will be empty")
        intl = None
    cross = [x for x in [pool(EVENTS, "events"), pool([lg for lg in INTERNATIONAL if lg in QUALIFIERS], "qualifiers", qualifiers=True)]
             if x is not None]
    ev = rate_cross_league(df, pd.concat(cross, ignore_index=True), base_raw, cfg) if cross else None
    if ev is not None:
        ev.loc[ev["qualifier"], "split"] = "Qualifier"
    return dom, intl, ev, leagues


def rate_cross_league(df, games, base_raw, cfg):
    """Each event/qualifier player-game is rated against the baseline of the team's home league.
    The baselines are built from league games only, so these games don't change them.
    A team with no home league in the file gets its opponent's."""
    home = home_leagues(df)
    games = games.copy()
    games["home"] = games["teamid"].map(home)
    opp_home = games.groupby(["gameid", "teamname"])["home"].first()
    for i in games.index[games["home"].isna()]:
        other = opp_home.drop((games.at[i, "gameid"], games.at[i, "teamname"]), errors="ignore").loc[games.at[i, "gameid"]]
        games.at[i, "home"] = other.dropna().iloc[0] if other.notna().any() else None
    group_of = {lg: name for name, lgs in BASELINE_GROUPS.items() for lg in lgs}
    games["baseline"] = [group_of.get(h, h) if isinstance(h, str) else None for h in games["home"]]

    parts = []
    for key, q in games.groupby("baseline", dropna=False):
        ref = base_raw.get(key) if isinstance(key, str) else None
        if ref is None:
            print(f"events: no baseline for {key} ({', '.join(sorted(q['teamname'].unique()))}), {len(q)} player-games skipped")
            continue
        both = pd.concat([ref.assign(_ref=True), q.drop(columns=["home", "baseline"]).assign(_ref=False)], ignore_index=True)
        rated = rc.rate(both, cfg, ref=both["_ref"])
        rated = rated[~rated["_ref"]].drop(columns="_ref")
        rated["baseline"] = key
        parts.append(rated)
    out = pd.concat(parts, ignore_index=True) if parts else None
    if out is not None:
        n = out.groupby(["league", "baseline"])["gameid"].nunique().unstack(fill_value=0)
        print("event games per home-league baseline:\n" + n.to_string())
    return out


def tidy(p, kind):
    """One row per rated player-game, in the columns the site uses."""
    out = pd.DataFrame({
        "player": p["playername"], "role": p["position"], "team": p["teamname"], "gameid": p["gameid"],
        "date": p["date"], "league": p["league"], "kind": kind,
        "stage": np.where(p["playoffs"] == 1, "playoffs", "regular"),
        "split": p["split"],
        "opponent": p["opponent"], "champion": p["champion"], "result": p["result"],
        "minutes": p["minutes"].round(1), "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
        "gd15": p["golddiffat15"],
        "r_early": p["r_early"], "r_late": p["r_late"], "r_overall": p["r_overall"],
        "playerid": p["playerid"], "baseline": p["baseline"],
    })
    out["year"] = out["date"].dt.year
    return out


def label_splits(games):
    """period = the split name the site filters on. Major leagues: the common name from SPLIT_MAP.
    Other leagues keep their own split names; their unlabelled games take the nearest labelled game's split
    (within SPLIT_GAP_DAYS), else a name from the schedule ("Split 1", ... or the months, e.g. "Feb-Mar")."""
    games["split"] = games["split"].astype(object)
    # where the split name comes from: data, near (the nearest split), schedule (a league without split names in the
    # data: Split 1, 2, ...) or months (leftover games of a league with split names, e.g. "Feb-Mar")
    games["split_src"] = np.where(games["split"].notna(), "data", None)
    mapped = {lg for lg, _ in SPLIT_MAP}
    for lg in games.loc[(games["kind"] == "domestic") & ~games["league"].isin(mapped), "league"].unique():
        m = (games["league"] == lg).to_numpy()
        g = games.loc[m, ["date", "split"]]
        lab, unl = g[g["split"].notna()], g[g["split"].isna()]
        if unl.empty:
            continue
        fill = pd.Series(None, index=unl.index, dtype=object)
        known = lab
        while len(known):   # repeat, so a run of unlabelled games next to a split joins it
            todo = unl.loc[fill[fill.isna()].index]
            if todo.empty:
                break
            near = pd.merge_asof(todo.reset_index().sort_values("date"), known.sort_values("date").rename(columns={"split": "near"}),
                                 on="date", direction="nearest", tolerance=pd.Timedelta(days=SPLIT_GAP_DAYS))
            near = near[near["near"].notna()]
            if near.empty:
                break
            fill.loc[near["index"]] = near["near"].to_numpy()
            games.loc[near["index"], "split_src"] = "near"
            known = pd.concat([lab, pd.DataFrame({"date": unl.loc[fill.notna(), "date"], "split": fill[fill.notna()]})])
        rest = fill[fill.isna()].index
        if len(rest):
            d = g.loc[rest, "date"].sort_values()
            block = (d.diff() > pd.Timedelta(days=SPLIT_GAP_DAYS)).cumsum()
            for b, idx in d.groupby(block).groups.items():
                if len(lab):   # a league with its own names: don't invent "Split 2" next to a real "Split 2"
                    a, z = d[idx].min(), d[idx].max()
                    fill.loc[idx] = a.strftime("%b") if a.month == z.month else f"{a:%b}-{z:%b}"
                    games.loc[idx, "split_src"] = "months"   # leftover games next to named splits: no tournament
                else:
                    fill.loc[idx] = f"Split {b + 1}"
                    games.loc[idx, "split_src"] = "schedule"
        games.loc[unl.index, "split"] = fill
    # major leagues: their unlabelled games get the name in UNLABELLED (LCS Oct 5-13: the LCS Promotion tournament)
    for lg, name in UNLABELLED.items():
        m = (games["league"] == lg) & games["split"].isna() & (games["kind"] == "domestic")
        games.loc[m, "split"] = name
        games.loc[m, "split_src"] = "near"
    games["period"] = [SPLIT_MAP.get((lg, sp if pd.notna(sp) else None), sp) if lg in mapped else sp
                       for lg, sp in zip(games["league"], games["split"])]
    return games


def team_games(df, games, leagues, events):
    """One row per team per game for the leagues, events and international events on the site (partial games included).
    Split labels come from the player games of the same game; partial games use their own label."""
    t = df[(df["position"] == "team") & df["league"].isin(leagues + events + INTERNATIONAL)].copy()
    t = t[t.groupby("gameid")["gameid"].transform("size") == 2]
    t["date"] = pd.to_datetime(t["date"])
    t = t.sort_values(["date", "gameid", "side"], kind="stable").reset_index(drop=True)
    qual = pd.Series(False, index=t.index)
    for lg, f in QUALIFIERS.items():
        m = t["league"] == lg
        qual[m] = f(t[m])
    t["kind"] = np.where(t["league"].isin(INTERNATIONAL) & ~qual, "international",
                         np.where(t["league"].isin(EVENTS) | qual, "event", "domestic"))
    lab = games.drop_duplicates("gameid").set_index("gameid")
    have = t["gameid"].isin(lab.index)
    own = t["split"].astype(object).where(~qual, "Qualifier")
    for lg, name in UNLABELLED.items():             # as in label_splits: LCS Oct 5-13 -> LCS Promotion
        own = own.where(~((t["league"] == lg) & own.isna()), name)
    t["split"] = t["gameid"].map(lab["split"]).where(have, own)
    mapped = {lg for lg, _ in SPLIT_MAP}
    t["period"] = t["gameid"].map(lab["period"]).where(have, [
        SPLIT_MAP.get((lg, sp if pd.notna(sp) else None), sp) if lg in mapped else sp for lg, sp in zip(t["league"], own)])
    t["stage"] = np.where(t["playoffs"] == 1, "playoffs", "regular")
    src = t["gameid"].map(lab["split_src"]).where(have, np.where(own.notna(), "data", None))
    t["tour"] = (t["kind"] != "domestic") | (t["split"].notna() & src.isin(["data", "near", "schedule"]))

    # team identity: teamid, else the name
    t["key"] = t["teamid"].where(t["teamid"].notna(), "name:" + t["teamname"].astype(str))
    keys = list(dict.fromkeys(t["key"]))
    t["ti"] = t["key"].map({k: i for i, k in enumerate(keys)})
    other = t[["gameid", "ti", "teamname"]].rename(columns={"ti": "oi", "teamname": "opponent"})
    t = t.merge(other, on="gameid")
    t = t[t["ti"] != t["oi"]].sort_values(["date", "gameid", "side"], kind="stable").reset_index(drop=True)

    # series: same league, same day, same two teams; the result is set on the team's last game of the series
    day = t["date"].dt.strftime("%Y-%m-%d")
    pair = [f"{min(a, b)}-{max(a, b)}" for a, b in zip(t["ti"], t["oi"])]
    t["series"] = pd.factorize(pd.Series([f"{lg}|{d}|{p}" for lg, d, p in zip(t["league"], day, pair)]))[0]
    sw = t.groupby(["series", "ti"])["result"].agg(["sum", "size"])
    t["s_result"] = None
    last = t.groupby(["series", "ti"]).tail(1).index
    for i in last:
        w, n = sw.loc[(t.at[i, "series"], t.at[i, "ti"])]
        t.at[i, "s_result"] = 1 if w > n - w else 0 if w < n - w else None

    # home league per team (for the Elo league level): its most played regular league, else its league here
    home = home_leagues(df)
    by_name = (df[(df["position"] == "team") & ~df["league"].isin(INTERNATIONAL + EVENTS)]
               .groupby(["teamname", "league"])["gameid"].nunique().reset_index()
               .sort_values("gameid", ascending=False).drop_duplicates("teamname").set_index("teamname")["league"])
    t["home"] = [home.get(k) if not k.startswith("name:") else by_name.get(n) for k, n in zip(t["key"], t["teamname"])]
    t["home"] = t["home"].where(t["home"].notna(), t["league"])

    # Elo, one row per game (blue vs red)
    b = t[t["side"] == "Blue"].set_index("gameid")
    r = t[t["side"] == "Red"].set_index("gameid")
    order = b.index[b.index.isin(r.index)]
    g = pd.DataFrame({"blue": b.loc[order, "ti"].to_numpy(), "red": r.loc[order, "ti"].to_numpy(),
                      "blue_lg": b.loc[order, "home"].to_numpy(), "red_lg": r.loc[order, "home"].to_numpy(),
                      "blue_win": b.loc[order, "result"].to_numpy(dtype=float)}, index=order)
    major_events = {lg for lg, c in t[t["kind"] == "event"].groupby("league") if any(tier_of(h) in ("major", "tier1") for h in c["home"])}
    major_events -= set(QUALIFIERS)
    # what a game counts for: international events by name, EM, other events, EWC qualifiers, leagues by tier
    t["comp"] = np.where(t["kind"] == "international", t["league"],
                         np.where(t["kind"] == "event", np.where(t["league"].isin(QUALIFIERS), "qualifier",
                                                                 np.where(t["league"].isin(["EM", "WSCI"]), t["league"],
                                                                          np.where(t["league"].isin(major_events), "event_major", "event"))),
                                  t["league"].map(tier_of)))
    cb = t.drop_duplicates("gameid").set_index("gameid").loc[order, "comp"]
    g["weight"] = cb.map(team_elo.WEIGHT).to_numpy()
    g["series"] = b.loc[order, "series"].to_numpy()
    g["day"] = ((t.drop_duplicates("gameid").set_index("gameid").loc[order, "date"] - t["date"].min()).dt.total_seconds() / 86400).to_numpy()
    prior = {lg: team_elo.prior_of(lg, tier_of(lg)) for lg in set(g["blue_lg"]) | set(g["red_lg"])}
    # titles: the champion of each finished competition (see finals()) gets a bonus after the final
    pos = pd.Series(np.arange(len(order)), index=order)
    end = t["date"].max()
    fins = finals(t)
    titles, title_list = {}, []
    for (y, lg, kind, sp), f in fins.items():
        if f["champ"] is None:
            continue
        bonus = team_elo.TITLE[f["comp"]]
        titles.setdefault(pos[f["gameid"]], []).append((f["champ"], bonus))
        title_list.append([f["champ"], lg if kind == "international" else f"{lg} {sp}" if sp != "None" else lg,
                           f["date"].strftime("%Y-%m-%d"), bonus])
    rb, rr, after_b, after_r, k, rep, now = team_elo.fit(g, prior, titles)
    rep["titles"] = title_list
    rep["finals"] = fins
    # Elo now: after decay up to the last day in the file
    end_day = (end - t["date"].min()).total_seconds() / 86400
    homes = t.drop_duplicates("ti").set_index("ti")["home"]
    rep["now"] = {int(i): round(now(i, h, end_day)) for i, h in homes.items()}
    rep["as_of"] = end.strftime("%Y-%m-%d")
    eb = pd.Series(rb, index=order), pd.Series(after_b, index=order)
    er = pd.Series(rr, index=order), pd.Series(after_r, index=order)
    blue = (t["side"] == "Blue").to_numpy()
    t["elo_before"] = np.where(blue, t["gameid"].map(eb[0]), t["gameid"].map(er[0])).round(0)
    t["elo_after"] = np.where(blue, t["gameid"].map(eb[1]), t["gameid"].map(er[1])).round(0)

    def n(c):
        return pd.to_numeric(t[c], errors="coerce") if c in t.columns else np.nan
    out = pd.DataFrame({
        "team": t["teamname"], "ti": t["ti"], "date": t["date"], "league": t["league"], "kind": t["kind"],
        "stage": t["stage"], "period": t["period"], "split": t["split"], "opponent": t["opponent"], "oi": t["oi"],
        "side": t["side"], "result": t["result"].astype(int), "game": t["game"], "series": t["series"], "s_result": t["s_result"],
        "minutes": (n("gamelength") / 60).round(1), "kills": n("kills"), "deaths": n("deaths"),
        "fb": n("firstblood"), "fd": n("firstdragon"), "fh": n("firstherald"), "ft": n("firsttower"),
        "dragons": n("dragons"), "grubs": n("void_grubs"), "barons": n("barons"), "towers": n("towers"), "inhibs": n("inhibitors"),
        "gd15": n("golddiffat15").round(0), "csd15": n("csdiffat15").round(0), "xpd15": n("xpdiffat15").round(0),
        "dpm": n("dpm").round(0), "wpm": n("wpm").round(2), "vspm": n("vspm").round(2),
        "picks": [[x for x in row if isinstance(x, str)] for row in t[[f"pick{i}" for i in range(1, 6)]].to_numpy()],
        "bans": [[x for x in row if isinstance(x, str)] for row in t[[f"ban{i}" for i in range(1, 6)]].to_numpy()],
        "elo_before": t["elo_before"], "elo_after": t["elo_after"], "year": t["date"].dt.year, "gameid": t["gameid"],
        "home": t["home"], "tour": t["tour"], "comp": t["comp"],
    })
    return out, keys, rep


def finals(t):
    """The final of each competition (year x league x kind x split): its last playoff series, its last series if it has
    no playoffs. It has a champion when the competition ended more than 2 days before the end of the data, is not a
    qualifier, and the winner of the final took 3 games (a best of 5) and won at least half its games in the competition
    (not a relegation match). Returns {(year, league, kind, split): {champ, runner, gameid, date, done, comp}}."""
    end = t["date"].max()
    out = {}
    keyed = t.assign(sp=t["split"].astype(object).fillna("None").astype(str), y=t["date"].dt.year)
    for (y, lg, kind, sp), c in keyed.groupby(["y", "league", "kind", "sp"], sort=False, dropna=False):
        po = c[c["stage"] == "playoffs"]
        fin = c[c["series"] == (po if len(po) else c).sort_values(["date", "series"]).iloc[-1]["series"]]
        wins = fin.groupby("ti")["result"].sum()
        champ = wins.idxmax()
        done = not c["date"].max() > end - pd.Timedelta(days=2)
        ok = done and c["comp"].iloc[0] != "qualifier" and wins.max() == 3 and c.loc[c["ti"] == champ, "result"].mean() >= 0.5
        other = [i for i in wins.index if i != champ]
        out[(int(y), lg, kind, sp)] = {"champ": int(champ) if ok else None, "runner": int(other[0]) if ok and other else None,
                                       "gameid": fin["gameid"].iloc[-1], "date": fin["date"].iloc[-1], "done": done,
                                       "comp": c["comp"].iloc[0], "series": int(fin["series"].iloc[0])}
    return out


def tournaments(tg, fins):
    """One row per tournament: a league split, an event (or one of its splits) or an international event. League games
    without a split label in the data are in no tournament (e.g. LCS games of Oct 5-13, "TCL Oct"), except in a league
    that has no split labels at all, whose splits are named from the schedule (LFL Split 1, 2, 3)."""
    t = tg[tg["tour"]].assign(sp=tg["split"].astype(object).fillna("None").astype(str), y=tg["date"].dt.year)
    rows = []
    for (y, lg, kind, sp), c in t.groupby(["y", "league", "kind", "sp"], sort=False):
        f = fins[(int(y), lg, kind, sp)]
        name = LEAGUE_NAMES.get(lg, lg) + ("" if sp == "None" else " " + sp)
        per = c["period"].dropna()
        if kind == "domestic" and len(per) and per.iloc[0] != sp:
            name += f" ({per.iloc[0]})"                       # major leagues: the common split name too
        rows.append({"year": int(y), "league": lg, "kind": kind, "split": None if sp == "None" else sp, "name": name,
                     "tier": TOUR_TIERS.get((lg, sp), tier_of(lg) if kind == "domestic" else None),
                     "period": per.iloc[0] if len(per) else None,
                     "first": c["date"].min().strftime("%Y-%m-%d"), "last": c["date"].max().strftime("%Y-%m-%d"),
                     "teams": int(c["ti"].nunique()), "series": int(c["series"].nunique()), "games": int(c["gameid"].nunique()),
                     "champ": f["champ"], "runner": f["runner"], "done": int(f["done"]),
                     "final": f["series"] if f["champ"] is not None else None, "playoffs": int((c["stage"] == "playoffs").any()),
                     **(fm := format_of(int(y), lg, kind, None if sp == "None" else sp, c)),
                     "places": placings(c, f, fm["stages"])})
    tours = pd.DataFrame(rows).sort_values(["first", "last", "name"], kind="stable").reset_index(drop=True)
    return tours.astype({"champ": "Int64", "runner": "Int64", "final": "Int64"})


def in_stage(g, c):
    """Rows of c in stage g (the same rule as inStage() in docs/app.js)."""
    m = pd.Series(True, index=c.index)
    if g.get("flag"):
        m &= c["stage"] == g["flag"]
    if g.get("from"):
        md = c["date"].dt.strftime("%m-%d")
        m &= (md >= g["from"]) & (md <= g["to"])
    return m


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def placings(c, f, stages):
    """[[team, place]]: a finished tournament with a champion: 1st, 2nd, then the other teams by how late they went out
    (teams out on the same day share a place, e.g. "3rd-4th"); only games up to the final count. A tournament still being
    played: the stage each team reached. Else none."""
    if not f["done"]:
        out = []
        for g in stages:
            for ti in c.loc[in_stage(g, c), "ti"].unique():
                out = [x for x in out if x[0] != int(ti)] + [[int(ti), g["name"]]]
        return out if len(stages) > 1 else []
    if f["champ"] is None:
        return []
    last = c[c["date"] <= f["date"]].groupby("ti")["date"].max().drop([f["champ"], f["runner"]], errors="ignore")
    out, n = [[f["champ"], "1st"]] + ([[f["runner"], "2nd"]] if f["runner"] is not None else []), 3
    for _, grp in sorted(last.groupby(last.dt.normalize()), key=lambda x: -x[0].value):
        k = len(grp)
        lab = ordinal(n) if k == 1 else f"{ordinal(n)}–{ordinal(n + k - 1)}"
        out += [[int(ti), lab] for ti in grp.index]
        n += k
    return out


def format_of(y, lg, kind, sp, c):
    """The format text and stages of a tournament: from FORMATS, else from the data (league: regular season + playoffs,
    or one table; events and international events: one list of results)."""
    f = FORMATS.get((y, lg, sp))
    if f:
        return {"format": f["about"], "stages": f["stages"]}
    if kind == "domestic":
        both = (c["stage"] == "playoffs").any() and (c["stage"] == "regular").any()
        return {"format": None, "stages": _LEAGUE if both else [_st("Season", "table", "")]}
    return {"format": None, "stages": [_st("Results", "bracket", "")]}


def tournament_links(tg, tours):
    """Qualification paths, found from the teams that played both tournaments: [from, to, [teams]].
    * International events and events: each team comes from the qualifier of the same event it played before (EWC
      Qualifier -> EWC), else from the latest league split it played that was at least half played (by games) when
      the event started.
    * Finals stages of a league (EBL Finals, LES Final Four, VCS Finals): from the team's latest earlier split of that league.
    A link is kept when some, but not all, of the earlier tournament's teams went on (a real selection)."""
    t = tg[tg["tour"]].assign(sp=tg["split"].astype(object).fillna("None").astype(str), y=tg["date"].dt.year)
    idx = {(r.year, r.league, r.kind, "None" if pd.isna(r.split) else r.split): i for i, r in tours.iterrows()}
    t["tn"] = [idx[k] for k in zip(t["y"], t["league"], t["kind"], t["sp"])]
    played = t.groupby("ti")["tn"].agg(lambda s: sorted(set(s)))
    teams_of = t.groupby("tn")["ti"].agg(lambda s: set(s))
    first = tours["first"]
    days = t.drop_duplicates("gameid").groupby("tn")["date"].agg(lambda s: np.sort(s.to_numpy()))
    half = lambda v, d: (days[v] < np.datetime64(d)).mean() >= 0.5   # tournament v had played half its games by day d
    links = []
    for u, U in tours.iterrows():
        final_stage = U["kind"] == "domestic" and "final" in str(U["split"]).lower()
        promo = U["kind"] == "domestic" and "promotion" in str(U["split"]).lower()
        if U["kind"] == "domestic" and not (final_stage or promo):
            continue
        src = {}
        for x in teams_of[u]:
            before = [v for v in played[x] if first[v] < U["first"] and half(v, U["first"])]
            if promo:
                cand = [v for v in before if tours.at[v, "kind"] == "domestic"]
            elif final_stage:
                cand = [v for v in before if tours.at[v, "league"] == U["league"] and tours.at[v, "kind"] == "domestic"]
            else:
                cand = [v for v in before if U["kind"] == "international" and tours.at[v, "league"] == U["league"]
                        and tours.at[v, "kind"] == "event"] or [v for v in before if tours.at[v, "kind"] == "domestic"]
            if cand:
                v = max(cand, key=lambda v: (first[v], tours.at[v, "last"]))
                src.setdefault(v, []).append(int(x))
        for v, xs in sorted(src.items()):
            if 0 < len(xs) < len(teams_of[v]):
                links.append([int(v), int(u), sorted(xs)])
    return links


def player_keys(games):
    """Which rows are the same player. The same name + role is one player, unless that name has several Oracle's
    Elixir playerids that never played for the same team (then they are different people). Duplicate ids of one
    player on one team stay together. Returns a number per row: 0 for the player with the most games, then 1, ..."""
    key = np.zeros(len(games), dtype=int)
    ids = games.dropna(subset=["playerid"])
    multi = ids.groupby(["player", "role"])["playerid"].nunique()
    for nm, rl in multi[multi > 1].index:
        m = ((games["player"] == nm) & (games["role"] == rl)).to_numpy()
        sub = games[m]
        teams = sub.dropna(subset=["playerid"]).groupby("playerid")["team"].agg(set)
        root = {i: i for i in teams.index}
        def find(x):
            while root[x] != x:
                x = root[x]
            return x
        for a, b in combinations(teams.index, 2):
            if teams[a] & teams[b]:
                root[find(a)] = find(b)
        group = sub["playerid"].map(lambda i: find(i) if isinstance(i, str) else None)
        order = {r: k for k, r in enumerate(group.value_counts().index)}
        key[m] = group.map(order).fillna(0).astype(int).to_numpy()   # rows without an id join the biggest
    return key


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


def default_table(games, c_by_role, leagues):
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
    table["league"] = table["team"].map(games.groupby("team")["league"].agg(lambda s: s[s.isin(leagues)].mode().iloc[0] if s.isin(leagues).any() else s.iloc[0]))
    return table


def report(table, games, rated, cfg):
    show = ["league", "team", "player", "games", "dom_overall", "intl_overall", "overall", "overall_low", "overall_high", "early", "late"]
    major = table["league"].isin(TIERS["major"])
    for role in ROLES:
        x = table[major & (table["role"] == role) & (table["games"] >= MIN_GAMES_CALIBRATION)].sort_values("overall", ascending=False).head(10)
        print(role.upper(), "(top 10, major-league players, all games)")
        print(x[[c for c in show if c in x.columns]].round(2).to_string(index=False), "\n")
    print("Checks per baseline: acc = how often the team with the better-rated players won (leave-one-out),"
          " stability = split-half reliability of r_overall")
    rows = []
    for name, p in rated.groupby("baseline"):
        v = rc.validate(p.copy(), rc.player_table(p.copy(), cfg))
        rows.append({"baseline": name, "games": v["games"], "players": v["players"], "acc": v["acc_player_ratings"],
                     "acc_team_winrate": v["acc_team_winrate"], "stability": v["rel_overall"], "gap_win_loss": v["gap_overall"]})
    print(pd.DataFrame(rows).round(3).to_string(index=False), "\n")


def team_report(tg, rep):
    print("league levels (Elo points above the average team):", rep["league_levels"])
    last = tg.groupby("ti").tail(1)
    print("top 15 teams by Elo after their last game:")
    print(last.sort_values("elo_after", ascending=False).head(15)[["team", "home", "elo_after", "date"]].to_string(index=False))
    for lg in TIERS["major"]:
        x = last[last["home"] == lg].sort_values("elo_after", ascending=False).head(3)
        print(f"  {lg}: " + ", ".join(f"{a} {int(e)}" for a, e in zip(x["team"], x["elo_after"])))
    print()


def split_table(games):
    """One line per league: its split names (with the common name for major leagues), games and dates."""
    g = games.drop_duplicates(["gameid", "league"])
    for lg, x in g.groupby("league", sort=False):
        parts = []
        for (per, sp), y in x.groupby(["period", "split"], dropna=False, sort=False):
            name = f"{sp}" if per == sp or pd.isna(per) else f"{per} ({sp})"
            parts.append(f"{name}: {len(y)} {y['date'].min():%m-%d}..{y['date'].max():%m-%d}")
        print(f"  {lg:9s} {' | '.join(parts)}")


def rows_of(frame):
    f = frame.astype(object).where(frame.notna(), None)
    return f.values.tolist()


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, default=str, separators=(",", ":"))


def write_site_data(games, c_by_role, cfg, out_dir, leagues, complete, tg, team_keys, elo_report, tours, links):
    """Writes index.json, summary/<year>.json, games/<year>/<league>.json and teams/<year>/<league>.json."""
    g_out = games[GAME_FIELDS + ["year", "playerid", "gameid"]].copy()
    # which team (index into the team list) each player-game belongs to
    ti_of = dict(zip(zip(tg["gameid"], tg["team"]), tg["ti"]))
    g_out["ti"] = [ti_of.get(k, -1) for k in zip(g_out["gameid"], g_out["team"])]
    g_out["date"] = g_out["date"].dt.strftime("%Y-%m-%d")
    for c in ["r_early", "r_late", "r_overall"]:
        g_out[c] = g_out[c].round(3)
    g_out["gd15"] = g_out["gd15"].round(0)
    g_out[GAME_FIELDS].to_csv(os.path.join(out_dir, "games_rated.csv"), index=False)

    # players: the same name + role is one player unless player_keys() splits it. Order: players with games in the
    # BASELINE_GROUPS leagues or international events first, by first game there, then the rest by first game.
    # The site gives page addresses in this order, so the players from before phase 1 keep theirs.
    g_out["pk"] = player_keys(g_out)
    pkey = list(zip(g_out["player"], g_out["role"], g_out["pk"]))
    old = g_out["league"].isin([lg for lgs in BASELINE_GROUPS.values() for lg in lgs] + INTERNATIONAL).to_numpy()
    first_old = dict.fromkeys(k for k, o in zip(pkey, old) if o)
    players = list(first_old) + [k for k in dict.fromkeys(pkey) if k not in first_old]
    pidx = {k: i for i, k in enumerate(players)}
    g_out["pi"] = [pidx[k] for k in pkey]
    game_fields = GAME_FIELDS + ["pi"]

    years, files, pfiles = sorted(g_out["year"].unique().tolist()), {}, [[] for _ in players]
    tfiles = [[] for _ in team_keys]
    for y in years:
        gy = g_out[g_out["year"] == y].reset_index(drop=True)
        gy["seq"] = np.arange(len(gy))                       # position in the year's date order, used to merge files
        for f in glob.glob(os.path.join(out_dir, "games", str(y), "*.json")):
            os.remove(f)                                      # drop league files that are no longer produced
        for lg, part in gy.groupby("league", sort=False):
            key = f"{y}/{lg}"
            dump(os.path.join(out_dir, "games", str(y), f"{lg}.json"),
                 {"fields": game_fields, "rows": rows_of(part[game_fields]), "seq": part["seq"].tolist()})
            files[key] = {"rows": int(len(part)), "kinds": sorted(part["kind"].unique().tolist())}
            for i in dict.fromkeys(part["pi"]):
                pfiles[i].append(key)

        # the sums rateSums() in docs/app.js needs, per player x league x split x stage
        r = gy["r_overall"]
        w = np.where(gy["kind"] == "international", INTL_WEIGHT, 1.0)
        wm = np.where(r.notna(), w, 0.0)
        gy = gy.assign(rated=r.notna().astype(int), wm=wm, wdev=wm * (r.fillna(1.0) - 1), w2=wm ** 2,
                       d1=(r - 1).fillna(0.0), d2=((r - 1) ** 2).fillna(0.0))
        cell = ["pi", "league", "kind", "period", "split", "stage", "ti"]
        s = gy.groupby(cell, sort=False, dropna=False).agg(games=("seq", "size"), n=("rated", "sum"), sw=("wm", "sum"), swd=("wdev", "sum"),
                                             sw2=("w2", "sum"), s1=("d1", "sum"), s2=("d2", "sum"),
                                             first=("seq", "min"), last=("seq", "max")).reset_index()
        s["team"] = gy["team"].to_numpy()[s["last"].to_numpy()]
        # ratings have 3 decimals, so these roundings only drop float noise
        s = s.round({"sw": 3, "swd": 3, "sw2": 3, "s1": 3, "s2": 6})
        s = s.rename(columns={"pi": "player"}).sort_values("first")

        # teams: one file per league, and the team leaderboard sums per team x league x split x stage
        ty = tg[tg["year"] == y].reset_index(drop=True)
        ty["seq"] = np.arange(len(ty))
        t_out = ty.assign(date=ty["date"].dt.strftime("%Y-%m-%d"))
        for f in glob.glob(os.path.join(out_dir, "teams", str(y), "*.json")):
            os.remove(f)
        for lg, part in t_out.groupby("league", sort=False):
            dump(os.path.join(out_dir, "teams", str(y), f"{lg}.json"),
                 {"fields": TEAM_FIELDS, "rows": rows_of(part[TEAM_FIELDS]), "seq": part["seq"].tolist()})
            for i in dict.fromkeys(part["ti"]):
                tfiles[i].append(f"{y}/{lg}")
        ty = ty.assign(gd_n=ty["gd15"].notna().astype(int), gd_sum=ty["gd15"].fillna(0),
                       blue_games=(ty["side"] == "Blue").astype(int), blue_wins=((ty["side"] == "Blue") & (ty["result"] == 1)).astype(int),
                       s_won=(ty["s_result"] == 1).astype(int), s_lost=(ty["s_result"] == 0).astype(int))
        ts = ty.groupby(["ti", "league", "kind", "period", "split", "stage"], sort=False, dropna=False).agg(
            games=("seq", "size"), wins=("result", "sum"), s_won=("s_won", "sum"), s_lost=("s_lost", "sum"),
            gd_n=("gd_n", "sum"), gd_sum=("gd_sum", "sum"), blue_games=("blue_games", "sum"), blue_wins=("blue_wins", "sum"),
            first=("seq", "min"), last=("seq", "max")).reset_index()
        ts["elo"] = ty["elo_after"].to_numpy()[ts["last"].to_numpy()]
        ts = ts.rename(columns={"ti": "team"}).sort_values("first")
        dump(os.path.join(out_dir, "summary", f"{y}.json"), {"fields": SUMMARY_FIELDS, "rows": rows_of(s[SUMMARY_FIELDS]),
                                                             "teams": {"fields": TEAM_SUMMARY_FIELDS, "rows": rows_of(ts[TEAM_SUMMARY_FIELDS])}})

    # player index: last team, league of the last domestic game (else last game), games, files
    last = g_out.groupby("pi").tail(1).set_index("pi")
    last_dom = g_out[g_out["kind"] == "domestic"].groupby("pi").tail(1).set_index("pi")
    n_games = g_out.groupby("pi").size()
    prow = [[name, role, last.at[i, "team"], (last_dom if i in last_dom.index else last).at[i, "league"],
             int(n_games[i]), pfiles[i]] for i, (name, role, _) in enumerate(players)]

    # team index: name, home league (if on the site, else the league it played most here), team-games, files
    tl = tg.groupby("ti").agg(name=("team", "last"), home=("home", "first"), games=("ti", "size"),
                              most=("league", lambda s: s.mode().iloc[0]))
    trow = [[r["name"], r["home"] if r["home"] in leagues else r["most"], int(r["games"]), tfiles[i]]
            for i, r in tl.reindex(range(len(team_keys))).iterrows()]

    for f in ["site_data.json"]:                              # the single-file layout from before
        if os.path.exists(os.path.join(out_dir, f)):
            os.remove(os.path.join(out_dir, f))
    shown = leagues + sorted(set(g_out["league"]) - set(leagues))
    events = [lg for lg in EVENTS if lg in set(g_out.loc[g_out["kind"] == "event", "league"])]
    dump(os.path.join(out_dir, "index.json"), {
        "version": "0.2",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "note": "Performance rating relative to the games it is built from. Not a measure of skill or of league strength.",
        "config": {"leagues": leagues, "events": events, "tiers": {lg: tier_of(lg) for lg in shown},
                   "names": {lg: LEAGUE_NAMES[lg] for lg in shown if lg in LEAGUE_NAMES},
                   "complete": {lg: complete[lg] for lg in shown if lg in complete and complete[lg] < 0.995},
                   "baseline_groups": BASELINE_GROUPS, "international": INTERNATIONAL, "qualifiers": sorted(QUALIFIERS),
                   "K": K, "intl_weight": INTL_WEIGHT,
                   "min_games": MIN_GAMES_CALIBRATION, "target_sd": TARGET_SD, "c_by_role": c_by_role,
                   "baselines": "each league its own baseline, except the leagues in baseline_groups, which share one; international games: their own baseline; events and qualifiers of international events: the baseline of each team's home league, weight 1, not counted as international",
                   "formula": "rating = 1 + c(role) * sum(w * (game_rating - 1)) / (sum(w) + K)",
                   "early_weights": cfg["EARLY_WEIGHTS"], "late_groups": cfg["LATE_GROUPS"],
                   "late_weights": cfg["LATE_WEIGHTS"], "early_share": cfg["EARLY_SHARE"]},
        "years": years, "files": files, "game_fields": game_fields, "summary_fields": SUMMARY_FIELDS,
        "players": {"fields": PLAYER_FIELDS, "rows": prow},
        "team_fields": TEAM_FIELDS, "team_summary_fields": TEAM_SUMMARY_FIELDS,
        "teams": {"fields": TEAM_INDEX_FIELDS, "rows": trow},
        "tournaments": {"fields": TOUR_FIELDS, "rows": rows_of(tours[TOUR_FIELDS])}, "tournament_links": links,
        "elo": {k: v for k, v in elo_report.items() if k not in ("league_levels", "finals")} | {"league_levels": elo_report["league_levels"],
                "base": team_elo.BASE, "weights": team_elo.WEIGHT, "title_bonus": team_elo.TITLE,
                "decay": [team_elo.DECAY_GRACE, team_elo.DECAY_HALF_LIFE]},
    })


def main(csv=FILE, out_dir=OUT_DIR, show_report=False):
    df = pd.read_csv(csv, low_memory=False)
    cfg = dict(rc.CFG)
    dom, intl, ev, leagues = rate_baselines(df, cfg)
    games = pd.concat([tidy(dom, "domestic")] + [tidy(x, k) for x, k in [(intl, "international"), (ev, "event")] if x is not None],
                      ignore_index=True)
    games = games.sort_values("date", kind="stable").reset_index(drop=True)
    games = label_splits(games)
    print("rated player-games:", len(games), "| domestic:", int((games["kind"] == "domestic").sum()),
          "| international:", int((games["kind"] == "international").sum()), "| events:", int((games["kind"] == "event").sum()))
    print("splits per league:"); split_table(games)
    c_by_role = calibrate_c(games)
    os.makedirs(out_dir, exist_ok=True)
    table = default_table(games, c_by_role, leagues)
    table.round(3).to_csv(os.path.join(out_dir, "players_default_view.csv"), index=False)
    if show_report:
        report(table, games, pd.concat([x for x in [dom, intl] if x is not None], ignore_index=True), cfg)
    t = df[df["position"] == "team"]
    complete = (t.drop_duplicates("gameid").groupby("league")["datacompleteness"].agg(lambda s: round(float((s == "complete").mean()), 2))).to_dict()
    events = [lg for lg in EVENTS if lg in set(games.loc[games["kind"] == "event", "league"])]
    tg, team_keys, elo_report = team_games(df, games, leagues, events)
    print(f"team Elo: {len(team_keys)} teams, {elo_report['games']} games in {elo_report['series']} series, K {elo_report['k']}, "
          f"series winner predicted {elo_report['accuracy']:.1%} (better series win rate so far: {elo_report['baseline_accuracy']:.1%})")
    if show_report:
        team_report(tg, elo_report)
    tours = tournaments(tg, elo_report["finals"])
    links = tournament_links(tg, tours)
    print(f"tournaments: {len(tours)}, {int(tours['champ'].notna().sum())} with a champion, {len(links)} qualification links")
    write_site_data(games, c_by_role, cfg, out_dir, leagues, complete, tg, team_keys, elo_report, tours, links)
    sizes = {os.path.relpath(p, out_dir): os.path.getsize(p) / 1024
             for p in glob.glob(os.path.join(out_dir, "**", "*.json"), recursive=True)}
    for p in sorted(p for p in sizes if not p.startswith(("games", "teams"))):
        print(f"{p:26s} {sizes[p]:8.0f} KB")
    for d in ["games", "teams"]:
        kb = [v for p, v in sizes.items() if p.startswith(d)]
        if kb:
            print(f"{d + ' (' + str(len(kb)) + ' files)':26s} {sum(kb):8.0f} KB, largest {max(kb):.0f} KB")
    print(f"{'total':26s} {sum(sizes.values()):8.0f} KB   saved in: {os.path.abspath(out_dir)}")
    return games, table


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build docs/data for the ratings site.")
    ap.add_argument("--csv", default=FILE, help="Oracle's Elixir match-data CSV")
    ap.add_argument("--out", default=OUT_DIR, help="output folder (docs/data)")
    ap.add_argument("--report", action="store_true", help="print the top 10 per role and checks per baseline")
    a = ap.parse_args()
    main(a.csv, a.out, a.report)
