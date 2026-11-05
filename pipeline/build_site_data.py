"""
Builds the data the website reads (docs/data/), rating v0.2.

    python build_site_data.py                 # every year's file in this folder, writes ../docs/data
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

* Years: each year's file is rated on its own (its own baselines, tiers, split names: YEARS), and each year's game
  ratings are put on the scale of REFERENCE_YEAR (the spread constant c(role) is calibrated per year), so adding a
  year never changes another year's numbers. Players and teams are linked across years by Oracle's Elixir ids, and
  the team Elo runs through all years in one go.

Needs rating_core.py and the Oracle's Elixir match-data CSVs (<year>_LoL_esports_match_data_from_OraclesElixir.csv)
in this folder.
"""
import argparse, glob, json, os
from itertools import combinations
import numpy as np
import pandas as pd
import rating_core as rc
import team_elo

# ================= CONFIG =================
FILES = "*_LoL_esports_match_data_from_OraclesElixir.csv"
REFERENCE_YEAR = 2026     # game ratings of every year are put on this year's scale (its c(role))
# leagues that share one baseline; every other league with enough games gets its own
BASELINE_GROUPS = {"main": ["LCK", "LPL", "LEC", "LCS"], "lcp": ["LCP"]}
MIN_BASELINE_GAMES = 30   # complete games a league needs for its own baseline (smaller leagues are left out)
# league tiers shown on the site: major, tier 1, tier 2 (leagues not listed), tier 3
TIERS = {"major": ["LCK", "LPL", "LEC", "LCS"],
         "tier1": ["LCP", "CBLOL"],
         "tier3": ["LAS", "NL", "HC", "LFL2", "CBLOLA"]}
INTERNATIONAL = ["MSI", "WLDs", "FST", "EWC",          # league codes of international events
                 "IEM", "MSC"]                         # 2015-17 Intel Extreme Masters, 2020 Mid-Season Cup
# page addresses come from the order of the player and team lists: the years on the site before phase 7 (from this one)
# keep their place, older years come after them, newest first
KEEP_ORDER_FROM = 2024
MIN_TEAM_GAMES = 30   # games (complete or partial) a league needs to be on the team side (Elo, team pages, tournaments)
# cross-league events (teams from several leagues): each team is rated against its home league's baseline,
# counted with weight 1, and not as international games. They get their own leaderboard on the site.
EVENTS = ["EM", "KeSPA Cup", "AM", "AC", "CCWS", "HW", "WSCI", "DCGI", "DCup", "WLRQ",
          "AmCh", "CDF", "CT", "EPL", "GLLPA", "EBLPA", "IC", "NLC Aurora Open", "TSC", "USP", "PRMP",   # 2024
          "ASI", "LTA",   # 2025 (LTA: the games between the LTA North and South conferences)
          "IWCI", "EUM", "ASCI", "NEST", "Riot", "LGL", "AOL", "GSG", "NERD", "UGP", "EL"]   # 2015-2023
# regional qualifiers filed under an international league code: rated like EVENTS, shown as "<event> Qualifier"
# EWC 2026: qualifiers Apr-Jun are playoffs=0, the main event in July is playoffs=1
# Worlds: a region's own qualifier filed under WLDs (2026: the LPL qualifier of Sep 17-19) = the games before the
# event's last break of 14+ days, or before WORLDS_START
def before_last_gap(p, days=14):
    d = pd.to_datetime(p["date"]).dt.normalize()
    u = np.sort(d.unique())
    gaps = np.where(np.diff(u) >= np.timedelta64(days, "D"))[0]
    return d < u[gaps[-1] + 1] if len(gaps) else pd.Series(False, index=p.index)
# Worlds start dates where the break rule doesn't work (2024: the LCK and LPL qualifiers end 11 days before the Play-In)
WORLDS_START = {2024: "2024-09-25", 2025: "2025-10-14"}
def worlds_qualifier(p):
    d = pd.to_datetime(p["date"])
    y = int(d.dt.year.mode().iloc[0]) if len(d) else None
    return d < pd.Timestamp(WORLDS_START[y]) if y in WORLDS_START else before_last_gap(p)
QUALIFIERS = {"EWC": lambda p: p["playoffs"] == 0, "WLDs": worlds_qualifier}
# names shown on the site (codes not listed are shown as the code)
LEAGUE_NAMES = {
    "LCKC": "LCK Challengers", "LAS": "LCK Academy Series", "NACL": "NA Challengers", "CD": "Circuito Desafiante", "PRM": "Prime League",
    "EBL": "Esports Balkan League", "ROL": "Road of Legends", "AL": "Arabian League", "RL": "Rift Legends",
    "HM": "Hitpoint Masters", "LRN": "Liga Regional Norte", "LRS": "Liga Regional Sur",
    "HLL": "Hellenic Legends League", "NLC": "Northern League of Legends Championship", "LPLOL": "Liga Portuguesa",
    "TCL": "Turkish Championship League", "LJL": "League of Legends Japan League", "HC": "Hitpoint Challengers",
    "AM": "Asia Masters", "AC": "Americas Cup",
    "LTA N": "LTA North", "LTA S": "LTA South", "LLA": "Liga Latinoamérica",
    "LCO": "League of Legends Circuit Oceania", "CBLOLA": "CBLOL Academy", "PCS": "Pacific Championship Series",
    "VCS": "Vietnam Championship Series", "LFL2": "LFL Division 2", "UL": "Ultraliga", "LVP SL": "LVP Superliga",
    "LDL": "LPL Development League",
    "EM": "EMEA Masters", "WLDs": "Worlds", "EWC": "Esports World Cup", "FST": "First Stand",
    "ESLOL": "Elite Series", "GLL": "Greek Legends League", "IGNIS": "Ignis Cup", "LES": "Liga Española",
    "LIT": "LoL Italian Tournament", "NEXO": "Liga Nexo", "NL": "Nexus League", "PCL": "Pacific Challengers League",
    "ASI": "Asia Invitational", "AmCh": "Americas Challengers", "CCWS": "Prime League Winter Snowdown",
    "CDF": "Coupe de France", "CT": "Circuito Tormenta", "DCGI": "Demacia Cup Global Invitational",
    "DCup": "Demacia Cup", "EBLPA": "EBL Pro-Am", "EPL": "European Pro League", "GLLPA": "GLL Pro-Am",
    "HW": "Hitpoint Winter", "IC": "Iberian Cup", "PRMP": "Prime League Pokal", "TSC": "TCL Season Cup",
    "USP": "Ultraliga Super Puchar", "WSCI": "World Star Challengers Invitational", "WLRQ": "WSCI China Qualifier",
    # 2014-2023
    "LMS": "League of Legends Master Series", "NA CS": "NA Challenger Series", "EU CS": "EU Challenger Series",
    "IEM": "Intel Extreme Masters", "MSC": "Mid-Season Cup", "IWCI": "International Wildcard Invitational",
    "EUM": "European Masters", "OPL": "Oceanic Pro League", "LCL": "LoL Continental League",
    "LLN": "Liga Latinoamérica Norte", "CLS": "Copa Latinoamérica Sur", "GPL": "Garena Premier League",
    "LSPL": "LoL Secondary Pro League", "CK": "Challengers Korea", "LJLCS": "LJL Challenger Series",
    "OCS": "Oceanic Challenger Series", "ASCI": "Asia Star Challengers Invitational",
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
# split names changed when the file is read: league -> {data split: split}, e.g. a placement stage filed as its own
# split joins the split it belongs to
MERGE_SPLITS = {}
# split names by date for a league whose games have none: league -> [(from "MM-DD", to "MM-DD", split)]
DATE_SPLITS = {}
# the settings above that change by year (the ones above are REFERENCE_YEAR's): year -> {setting: value}.
# use_year() switches to a year's settings.
_TIER3 = TIERS["tier3"]
YEARS = {
    2025: {"TIERS": {"major": ["LCK", "LPL", "LEC", "LTA N"], "tier1": ["LTA S", "LCP"], "tier3": _TIER3},
           "BASELINE_GROUPS": {"main": ["LCK", "LPL", "LEC", "LTA N"], "lcp": ["LCP"]},
           # LPL and LTA North have three splits that don't line up with the others: their own names
           "SPLIT_MAP": {("LEC", "Winter"): "Winter", ("LEC", "Spring"): "Spring", ("LEC", "Summer"): "Summer",
                         ("LCK", "Cup"): "Winter", ("LCK", "Rounds 1-2"): "Spring", ("LCK", "Rounds 3-5"): "Summer"},
           "UNLABELLED": {}, "TOUR_TIERS": {},
           "MERGE_SPLITS": {"LPL": {"Split 2 Placements": "Split 2"}},
           # the games between the LTA North and South conferences: the Split 1 playoffs and the LTA Championship
           "DATE_SPLITS": {"LTA": [("01-01", "06-30", "Split 1 Playoffs"), ("07-01", "12-31", "Championship")]}},
    2024: {"TIERS": {"major": ["LCK", "LPL", "LEC", "LCS"], "tier1": ["CBLOL", "PCS", "VCS", "LJL", "LLA", "LCO"], "tier3": _TIER3},
           "BASELINE_GROUPS": {"main": ["LCK", "LPL", "LEC", "LCS"]},
           "SPLIT_MAP": {("LEC", "Winter"): "Winter", ("LEC", "Spring"): "Spring", ("LEC", "Summer"): "Summer",
                         ("LEC", "Finals"): None, ("LCK", "Spring"): "Spring", ("LCK", "Summer"): "Summer",
                         ("LCS", "Spring"): "Spring", ("LCS", "Summer"): "Summer"},
           "UNLABELLED": {}, "TOUR_TIERS": {},
           "MERGE_SPLITS": {"LPL": {"Summer Placements": "Summer"}}, "DATE_SPLITS": {}},
}
# 2014-2023 (phase 7): the leagues of the time. Major: the big four (EU LCS and NA LCS until 2018, LEC and LCS from
# 2019; no LPL in the 2014-15 files, no LCK in 2014); tier 1: the other regions with their own Worlds spots. A major
# league's unlabelled games (late Aug/Sep) are its regional Worlds qualifier: "Regional Finals". RENAME_LEAGUES: league
# codes changed when the file is read (2015: OGN = the LCK; 2015-18: the EU LCS and NA LCS regional finals are filed
# as "LEC" and "LCS").
RENAME_LEAGUES = {}
_EU_NA = {"LCS": "NA LCS", "LEC": "EU LCS"}
# OLD_DATE_SPLITS: games the data files under a split but that belong to another tournament, by date: promotion and
# relegation series (filed under the next split), the 2014 expansion tournament, the LCS Lock In (2021-22, filed as
# Spring playoffs), and the IEM events (one code per year in the data). Promotion and expansion tournaments are tier 2.
_SP, _PR = "Spring Promotion", "Summer Promotion"
_IEM = {2015: [("03-01", "03-31", "Katowice"), ("11-01", "11-30", "San Jose"), ("12-01", "12-31", "Cologne")],
        2016: [("03-01", "03-31", "Katowice"), ("11-01", "11-30", "Gyeonggi"), ("12-01", "12-31", "Oakland")],
        2017: [("02-01", "02-28", "Katowice")]}
OLD_DATE_SPLITS = {
    2014: {"EU LCS": [("04-20", "04-30", _PR), ("09-05", "09-15", _SP), ("11-15", "12-31", "Expansion Tournament")],
           "NA LCS": [("04-21", "04-30", _PR), ("09-05", "09-15", _SP), ("11-10", "12-31", "Expansion Tournament")]},
    2015: {"EU LCS": [("04-24", "04-26", _PR), ("09-04", "09-06", _SP)], "NA LCS": [("04-25", "04-28", _PR), ("09-05", "09-08", _SP)],
           "LCK": [("05-14", "05-17", _PR), ("09-02", "09-05", "Regional Finals"), ("09-10", "09-30", _SP)]},
    2016: {"EU LCS": [("03-22", "03-28", _PR), ("08-01", "08-08", _SP)], "NA LCS": [("04-05", "04-08", _PR), ("08-03", "08-08", _SP)],
           "LCK": [("04-27", "04-30", _PR), ("08-21", "08-28", _SP)]},
    2017: {"EU LCS": [("04-06", "04-07", _PR), ("04-13", "04-14", _PR), ("08-17", "08-18", _SP), ("08-24", "08-25", _SP)],
           "NA LCS": [("03-31", "04-02", _PR), ("08-11", "08-13", _SP)], "LCK": [("04-24", "04-30", _PR), ("09-10", "09-20", _SP)]},
    2018: {"LCK": [("04-16", "04-23", _PR), ("09-17", "09-25", _SP)]},
    2019: {"LCK": [("04-15", "04-22", _PR), ("09-08", "09-12", _SP)]},
    2020: {"LCK": [("04-27", "05-01", _PR)]},
    2021: {"LCS": [("01-01", "01-31", "Lock In")]},
    # 2022: also the LCS Spring playoffs (Apr 2-24), which have no split name in the data
    2022: {"LCS": [("01-01", "01-31", "Lock In"), ("04-01", "04-30", "Spring")]},
}
for _y, _r in _IEM.items():
    OLD_DATE_SPLITS.setdefault(_y, {})["IEM"] = _r
def _old_year(year, major, tier1, rename=None, splits=("Spring", "Summer"), split_map=None):
    ds = OLD_DATE_SPLITS.get(year, {})
    tiers = {(lg, n): "tier2" for lg, rules in ds.items() for _, _, n in rules if "Promotion" in n or "Expansion" in n}
    return {"TIERS": {"major": major, "tier1": tier1, "tier3": _TIER3}, "BASELINE_GROUPS": {"main": major},
            "SPLIT_MAP": {**{(lg, sp): sp for lg in major for sp in splits}, **(split_map or {})},
            "UNLABELLED": {lg: "Regional Finals" for lg in major}, "TOUR_TIERS": tiers,
            "MERGE_SPLITS": {}, "DATE_SPLITS": ds, "RENAME_LEAGUES": rename or {}}
_OLD4, _NEW4 = ["LCK", "LPL", "EU LCS", "NA LCS"], ["LCK", "LPL", "LEC", "LCS"]
_WILD = ["LMS", "CBLOL", "TCL", "OPL", "LJL", "LCL", "LLN", "CLS", "GPL"]     # 2016-18 (wildcard regions + LMS)
YEARS.update({
    2014: _old_year(2014, ["EU LCS", "NA LCS"], []),
    # 2015: OGN = the LCK (its Sep 2-5 games = the regional finals); KeSPA = the KeSPA Cup
    2015: _old_year(2015, ["LCK", "EU LCS", "NA LCS"], ["LMS", "CBLOL", "TCL", "OPL"],
                    rename={"OGN": "LCK", "KeSPA": "KeSPA Cup", **_EU_NA}),
    2016: _old_year(2016, _OLD4, _WILD, rename=_EU_NA),
    2017: _old_year(2017, _OLD4, _WILD, rename=_EU_NA),
    2018: _old_year(2018, _OLD4, _WILD + ["VCS"], rename=_EU_NA),
    2019: _old_year(2019, _NEW4, ["LMS", "CBLOL", "TCL", "OPL", "LJL", "LCL", "LLA", "VCS"]),
    2020: _old_year(2020, _NEW4, ["PCS", "VCS", "CBLOL", "TCL", "LJL", "LCL", "LLA", "OPL"]),
    2021: _old_year(2021, _NEW4, ["PCS", "VCS", "CBLOL", "TCL", "LJL", "LCL", "LLA", "LCO"]),
    2022: _old_year(2022, _NEW4, ["PCS", "VCS", "CBLOL", "TCL", "LJL", "LLA", "LCO"]),
    2023: _old_year(2023, _NEW4, ["PCS", "VCS", "CBLOL", "LJL", "LLA", "LCO"], splits=("Winter", "Spring", "Summer"),
                    split_map={("LEC", "Finals"): None}),
})
YEARS[REFERENCE_YEAR] = {k: globals()[k] for k in ["TIERS", "BASELINE_GROUPS", "SPLIT_MAP", "UNLABELLED", "TOUR_TIERS",
                                                    "MERGE_SPLITS", "DATE_SPLITS"]}


def use_year(y):
    """Switches the year-dependent settings (TIERS, BASELINE_GROUPS, SPLIT_MAP, UNLABELLED, TOUR_TIERS, MERGE_SPLITS,
    DATE_SPLITS) to year y."""
    globals().update({"RENAME_LEAGUES": {}}, **YEARS.get(y, YEARS[REFERENCE_YEAR]))


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
    (2026, "LCK", "Rounds 1-2"): {"about": "Regular season Rounds 1-2 (10 teams), then the Road to MSI playoffs for the MSI spots. After Rounds 1-2 the top five form the Legend group and the bottom five the Rise group for Rounds 3-4. The data files these games as \"Rounds 1-2\".",
                                  "stages": [_st("Rounds 1-2", "table", "Double round robin, best of 3.", flag="regular"), _st("Road to MSI", "bracket", "Playoffs for the MSI spots.", flag="playoffs")]},
    (2026, "LCK", "Rounds 3-4"): {"about": "Regular season Rounds 3-4 in the Legend and Rise groups (results carry over), then the Season Play-In and Season Playoffs, with Fearless Draft. The winner is the LCK champion; the top three go to Worlds. The data files these games as \"Rounds 3-4\".",
                                  "stages": [_st("Rounds 3-4", "table", "Double round robin, best of 3, in the Legend and Rise groups (the table mixes both groups).", flag="regular"), _st("Season Play-In and Season Playoffs", "bracket", "Double elimination, best of 5.", flag="playoffs")]},
    (2024, "LEC", "Finals"): {"about": "The LEC Season Finals for the 2024 splits. The data files these games as \"Finals\".",
                              "stages": [_st("Bracket", "bracket", "", flag="playoffs")]},
    (2024, "LPL", "Summer"): {"about": "A placements stage, then the regular season and playoffs. The data files the placement games as a split of their own (\"Summer Placements\").",
                              "stages": [_st("Placements", "table", "", **{"from": "06-01", "to": "06-30"}),
                                         _st("Regular season", "table", "", flag="regular", **{"from": "07-01", "to": "12-31"}),
                                         _st("Playoffs", "bracket", "", flag="playoffs")]},
    (2025, "LPL", "Split 2"): {"about": "A placements stage, then the regular season and playoffs. The data files the placement games as a split of their own (\"Split 2 Placements\").",
                               "stages": [_st("Placements", "table", "", **{"from": "03-01", "to": "04-03"}),
                                          _st("Regular season", "table", "", flag="regular", **{"from": "04-04", "to": "12-31"}),
                                          _st("Playoffs", "bracket", "", flag="playoffs")]},
    (2025, "LCK", "Rounds 1-2"): {"about": "Regular season Rounds 1-2 (10 teams), then the Road to MSI playoffs for the MSI spots. After Rounds 1-2 the teams split into the Legend and Rise groups for Rounds 3-5. The data files these games as \"Rounds 1-2\".",
                                  "stages": [_st("Rounds 1-2", "table", "Double round robin, best of 3.", flag="regular"), _st("Road to MSI", "bracket", "Playoffs for the MSI spots.", flag="playoffs")]},
    (2025, "LCK", "Rounds 3-5"): {"about": "Regular season Rounds 3-5 in the Legend and Rise groups, then the Season Play-In and Season Playoffs. The winner is the LCK champion. The data files these games as \"Rounds 3-5\".",
                                  "stages": [_st("Rounds 3-5", "table", "Legend and Rise groups (the table mixes both groups).", flag="regular"), _st("Season Play-In and Season Playoffs", "bracket", "", flag="playoffs")]},
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
    # 2025
    (2025, "FST", None): {"about": "5 teams: the winners of the LCK Cup, LPL Split 1, LEC Winter, the LTA Split 1 Playoffs and LCP Split 1. Fearless Draft.",
                          "stages": [_st("Group stage", "table", "Single round robin, best of 3; the top four go through.", **{"from": "03-10", "to": "03-14"}),
                                     _st("Knockout stage", "bracket", "Semifinals (1st against 4th, 2nd against 3rd) and final, best of 5.", **{"from": "03-15", "to": "03-16"})]},
    (2025, "MSI", None): {"about": "10 teams. Every series is a best of 5 with Fearless Draft.",
                          "stages": [_st("Play-In", "bracket", "Four teams, double elimination; two go through to the Bracket Stage.", **{"from": "06-27", "to": "07-01"}),
                                     _st("Bracket Stage", "bracket", "Eight teams, double elimination.", **{"from": "07-02", "to": "07-31"})]},
    (2025, "EWC", None): {"about": "12 teams at the Esports World Cup. Fearless Draft.",
                          "stages": [_st("Group stage", "bracket", "Eight teams in two groups of four, double elimination; two teams of each group go through to the playoffs.", **{"from": "07-16", "to": "07-17"}),
                                     _st("Playoffs", "bracket", "Eight teams, single elimination, best of 3; the final is a best of 5.", **{"from": "07-18", "to": "07-31"})]},
    (2025, "WLDs", None): {"about": "Three stages: Play-In, Swiss Stage and Knockout Stage. Fearless Draft.",
                           "stages": [_st("Play-In", "bracket", "One best of 5 between two teams; the winner goes to the Swiss Stage.", **{"from": "10-01", "to": "10-14"}),
                                      _st("Swiss Stage", "table", "16 teams, paired by record; 3 wins go through, 3 losses are out. Best of 1, except best of 3 when a team can go through or be eliminated.", **{"from": "10-15", "to": "10-25"}),
                                      _st("Knockout Stage", "bracket", "Eight teams, single elimination, best of 5.", **{"from": "10-26", "to": "12-31"})]},
    (2025, "LCK", "Cup"): {"about": "10 teams, Fearless Draft. The winner goes to First Stand.",
                           "stages": [_st("Group Battle", "table", "Two groups (Baron and Elder); each team plays the other group's teams once, best of 3. The winning group gets more playoff spots.", **{"from": "01-15", "to": "02-02"}),
                                      _st("Play-In", "bracket", "", **{"from": "02-03", "to": "02-10"}),
                                      _st("Playoffs", "bracket", "Six teams, double elimination, best of 5.", **{"from": "02-11", "to": "02-28"})]},
    (2025, "LPL", "Split 1"): {"about": "16 teams in four groups of four, Fearless Draft. The winner goes to First Stand.",
                               "stages": _lg("Single round robin in each group, best of 5; the top two of each group go to the playoffs (the table mixes the groups).", "Eight teams.")},
    (2025, "LPL", "Split 3"): {"about": "14 teams in two groups (Ascend and Nirvana). The top teams go to Worlds.",
                               "stages": _lg("Round robin in each group (the table mixes the groups).", "Playoffs, best of 5.")},
    (2025, "LEC", "Winter"): {"about": "10 teams, Fearless Draft. The winner goes to First Stand.",
                              "stages": _lg("Single round robin, best of 1; the top eight go to the playoffs.", "Double elimination; rounds 1-2 best of 3, then best of 5.")},
    (2025, "LEC", "Spring"): {"about": "10 teams, Fearless Draft. The top two go to MSI.",
                              "stages": _lg("Single round robin, best of 3; the top six go to the playoffs.", "Double elimination, best of 5.")},
    (2025, "LEC", "Summer"): {"about": "10 teams, Fearless Draft. The top three go to Worlds.",
                              "stages": _lg("Two groups of five, best of 3; the top eight go to the playoffs, the top two of each group in the upper bracket (the table mixes the groups).", "Double elimination, best of 5.")},
    (2025, "LTA N", "Split 1"): {"about": "The LTA North conference's part of Split 1, Fearless Draft. The top four go to the LTA Split 1 Playoffs.",
                                 "stages": [_st("Conference stage", "bracket", "", **{"from": "01-01", "to": "12-31"})]},
    (2025, "LTA S", "Split 1"): {"about": "The LTA South conference's part of Split 1, Fearless Draft. The top four go to the LTA Split 1 Playoffs.",
                                 "stages": [_st("Conference stage", "bracket", "", **{"from": "01-01", "to": "12-31"})]},
    (2025, "LTA", "Split 1 Playoffs"): {"about": "The top four teams of each LTA conference. The winner goes to First Stand.",
                                        "stages": [_st("Bracket", "bracket", "Single elimination.", **{"from": "01-01", "to": "12-31"})]},
    (2025, "LTA N", "Split 2"): {"about": "8 teams, Fearless Draft. The winner goes to MSI.",
                                 "stages": [_st("Positioning", "table", "Single round robin, best of 1; the standings set the groups.", flag="regular", **{"from": "01-01", "to": "04-23"}),
                                            _st("Group stage", "table", "Two groups of four, single round robin, best of 3; the top six go to the playoffs (the table mixes the groups).", flag="regular", **{"from": "04-24", "to": "12-31"}),
                                            _st("Playoffs", "bracket", "Double elimination, best of 5.", flag="playoffs")]},
    (2025, "LTA S", "Split 2"): {"about": "8 teams, Fearless Draft. The winner goes to MSI.",
                                 "stages": [_st("Positioning", "table", "Single round robin, best of 1; the standings set the groups.", flag="regular", **{"from": "01-01", "to": "04-23"}),
                                            _st("Group stage", "table", "Two groups of four, single round robin, best of 3; the top six go to the playoffs (the table mixes the groups).", flag="regular", **{"from": "04-24", "to": "12-31"}),
                                            _st("Playoffs", "bracket", "Double elimination, best of 5.", flag="playoffs")]},
    (2025, "LTA N", "Split 3"): {"about": "Fearless Draft. Teams pick their opponents for the following week (Pick & Play).",
                                 "stages": [_st("Regular season", "table", "Best of 3.", **{"from": "07-26", "to": "08-10"}),
                                            _st("Playoffs", "bracket", "Best of 5.", **{"from": "08-11", "to": "09-07"})]},
    (2025, "LTA S", "Split 3"): {"about": "Fearless Draft. Teams pick their opponents for the following week (Pick & Play).",
                                 "stages": [_st("Regular season", "table", "Best of 3.", **{"from": "07-26", "to": "08-10"}),
                                            _st("Playoffs", "bracket", "Best of 5.", **{"from": "08-11", "to": "09-07"})]},
    (2025, "LTA", "Championship"): {"about": "The top teams of LTA North and LTA South after Split 3, for the LTA title and the Worlds spots.",
                                    "stages": [_st("Bracket", "bracket", "Best of 5.", **{"from": "01-01", "to": "12-31"})]},
    (2025, "LCP", "Split 1"): {"about": "8 teams, Fearless Draft. The winner goes to First Stand.", "stages": _LEAGUE},
    (2025, "LCP", "Split 2"): {"about": "8 teams, Fearless Draft. The top two go to MSI.",
                               "stages": _lg("Double round robin, best of 1; the top six go to the playoffs.", "Double elimination; rounds 1-2 best of 3, then best of 5.")},
    (2025, "LCP", "Split 3"): {"about": "Fearless Draft. The top three go to Worlds.", "stages": _LEAGUE},
    # 2024
    (2024, "MSI", None): {"about": "12 teams.",
                          "stages": [_st("Play-In", "bracket", "Eight teams in two groups of four, double elimination, best of 3; two teams of each group go through.", **{"from": "05-01", "to": "05-05"}),
                                     _st("Bracket Stage", "bracket", "Eight teams, double elimination, best of 5.", **{"from": "05-06", "to": "05-31"})]},
    (2024, "EWC", None): {"about": "8 teams at the first Esports World Cup: the top two of the LCK, LPL, LEC and LCS.",
                          "stages": [_st("Bracket", "bracket", "Single elimination, best of 3; the final is a best of 5.", **{"from": "01-01", "to": "12-31"})]},
    (2024, "WLDs", None): {"about": "Three stages: Play-In, Swiss Stage and Knockout Stage.",
                           "stages": [_st("Play-In", "bracket", "Eight teams in two groups of four, double elimination, best of 3; two teams of each group go through to the Swiss Stage.", **{"from": "09-20", "to": "09-30"}),
                                      _st("Swiss Stage", "table", "16 teams, paired by record; 3 wins go through, 3 losses are out. Best of 1, except best of 3 when a team can go through or be eliminated.", **{"from": "10-01", "to": "10-14"}),
                                      _st("Knockout Stage", "bracket", "Eight teams, single elimination, best of 5.", **{"from": "10-15", "to": "12-31"})]},
    (2024, "LCK", "Spring"): {"about": "10 teams. The top two go to MSI.",
                              "stages": _lg("Double round robin, best of 3; the top six go to the playoffs.", "Double elimination, best of 5.")},
    (2024, "LCK", "Summer"): {"about": "10 teams. Worlds spots come from this split, championship points and the LCK Regional Finals.",
                              "stages": _lg("Double round robin, best of 3; the top six go to the playoffs.", "Double elimination, best of 5.")},
    (2024, "LPL", "Spring"): {"about": "17 teams. The top two go to MSI.", "stages": _lg("Single round robin, best of 3.", "Playoffs, best of 5.")},
    (2024, "LEC", "Winter"): {"about": "10 teams. Championship points for the LEC Season Finals.",
                              "stages": _lg("Single round robin, best of 1; the top eight go to the playoffs.", "Double elimination; rounds 1-2 best of 3, then best of 5.")},
    (2024, "LEC", "Spring"): {"about": "10 teams. The top two go to MSI; championship points for the LEC Season Finals.",
                              "stages": _lg("Single round robin, best of 1; the top eight go to the playoffs.", "Double elimination; rounds 1-2 best of 3, then best of 5.")},
    (2024, "LEC", "Summer"): {"about": "10 teams. Championship points for the LEC Season Finals, where the Worlds spots are decided.",
                              "stages": _lg("Single round robin, best of 1; the top eight go to the playoffs.", "Double elimination; rounds 1-2 best of 3, then best of 5.")},
    (2024, "LCS", "Spring"): {"about": "8 teams. The top two go to MSI.",
                              "stages": _lg("Double round robin, best of 1; the top six go to the playoffs.", "Double elimination, best of 5.")},
    (2024, "LCS", "Summer"): {"about": "8 teams. The top three of the LCS Championship (the playoffs) go to Worlds.",
                              "stages": _lg("Single round robin, best of 3; the top six go to the LCS Championship.", "Double elimination with a lower-bracket gauntlet; the top two seeds get a first-round bye.")},
    (2024, "CBLOL", "Split 1"): {"about": "10 teams. The winner goes to MSI.",
                                 "stages": _lg("Double round robin, best of 1; the top six go to the playoffs.", "Double elimination, best of 5.")},
    (2024, "CBLOL", "Split 2"): {"about": "10 teams. The winner goes to Worlds.",
                                 "stages": _lg("Double round robin, best of 1; the top six go to the playoffs.", "Double elimination, best of 5.")},
    (2024, "PCS", "Spring"): {"about": "8 PCS teams. The PCS Playoffs add the top three LJL teams and the top two LCO teams to the top six PCS teams; the winner goes to MSI.",
                              "stages": _lg("PCS teams only.", "The PCS Spring Playoffs, with the LJL and LCO teams.")},
    (2024, "PCS", "Summer"): {"about": "7 PCS teams. The PCS Playoffs add the top three LJL teams and the top two LCO teams; the top two go to Worlds.",
                              "stages": _lg("PCS teams only.", "The PCS Summer Playoffs, with the LJL and LCO teams.")},
    (2024, "VCS", "Spring"): {"about": "8 teams. The winner goes to MSI.",
                              "stages": _lg("Double round robin, best of 3; the top six go to the playoffs.", "Double elimination.")},
    (2024, "VCS", "Summer"): {"about": "7 teams. The winner goes to Worlds as the VCS first seed.",
                              "stages": _lg("Double round robin; the top five go to the playoffs.", "")},
    (2024, "LJL", "Spring"): {"about": "6 teams. The top three go to the PCS Spring Playoffs.",
                              "stages": _lg("Double round robin, two games per meeting (best of 2); the top four go to the playoffs.", "Single elimination, best of 5.")},
    (2024, "LJL", "Summer"): {"about": "6 teams. The top three go to the PCS Summer Playoffs, for the Worlds spots.",
                              "stages": _lg("Double round robin, two games per meeting (best of 2); the top five go to the playoffs.", "Single elimination, best of 5.")},
    (2024, "LCO", "Split 1"): {"about": "8 teams. The top two go to the PCS Spring Playoffs.",
                               "stages": _lg("Single round robin, best of 2; the top six go to the playoffs.", "Double elimination.")},
    (2024, "LCO", "Split 2"): {"about": "8 teams. The top two go to the PCS Summer Playoffs, for the Worlds spots.",
                               "stages": _lg("Single round robin, best of 2; the top six go to the playoffs.", "Double elimination.")},
    (2024, "LLA", "Opening"): {"about": "7 teams. The winner goes to MSI.",
                               "stages": _lg("Double round robin, best of 3; the top six go to the playoffs.", "")},
    (2024, "LLA", "Closing"): {"about": "6 teams. The winner goes to Worlds.", "stages": _LEAGUE},
}
# tournament names where the data's split name is not what the league calls it: (year, league, split) -> name shown
# (LCK since 2025: the data files the season as "Rounds 1-2" and "Rounds 3-5"/"3-4"; each ends with the playoffs
# that decide its title)
TOUR_NAMES = {(2023, "LEC", "Finals"): "Season Finals", (2024, "LEC", "Finals"): "Season Finals",
              (2025, "LCK", "Rounds 1-2"): "Road to MSI", (2025, "LCK", "Rounds 3-5"): "Season Playoffs",
              (2026, "LCK", "Rounds 1-2"): "Road to MSI", (2026, "LCK", "Rounds 3-4"): "Season Playoffs",
              # "" = the league name alone: one tournament a year, filed under a season name or the year
              (2024, "DCup", "Season"): "", (2025, "DCup", "Season"): "", (2026, "DCup", "Season"): "",
              (2024, "LRN", "2024"): "", (2024, "LRS", "2024"): ""}
SPLIT_GAP_DAYS = 21    # unlabelled games: take the nearest labelled game's split within this many days
OUT_DIR = "../docs/data"

GAME_FIELDS = ["player", "role", "team", "date", "league", "kind", "stage", "period", "split", "opponent", "champion",
               "result", "minutes", "kills", "deaths", "assists", "gd15", "r_early", "r_late", "r_overall",
               "cs", "dpm", "vspm", "series", "gn"]       # series + gn (game number in it): the match pages
SUMMARY_FIELDS = ["player", "league", "kind", "period", "split", "stage",
                  "games", "n", "sw", "swd", "sw2", "s1", "s2", "first", "last", "team", "ti"]
PLAYER_FIELDS = ["name", "role", "team", "league", "games", "files"]
# team-games (one row per team per game, partial games included: records and Elo use every game)
TEAM_FIELDS = ["team", "ti", "date", "league", "kind", "stage", "period", "split", "opponent", "oi", "side", "result", "game",
               "series", "s_result", "minutes", "kills", "deaths", "fb", "fd", "fh", "ft", "dragons", "grubs", "barons", "towers",
               "inhibs", "gd15", "csd15", "xpd15", "dpm", "wpm", "vspm", "picks", "bans", "elo_before", "elo_after", "gn"]
TEAM_SUMMARY_FIELDS = ["team", "league", "kind", "period", "split", "stage", "games", "wins", "s_won", "s_lost",
                       "gd_n", "gd_sum", "blue_games", "blue_wins", "first", "last", "elo"]
TEAM_INDEX_FIELDS = ["name", "league", "games", "files"]
# tournaments: year, league, kind and split identify one (the same fields as on the game rows); champ/runner: team index
TOUR_FIELDS = ["year", "league", "kind", "split", "period", "name", "first", "last", "teams", "series", "games", "champ", "runner",
               "done", "final", "playoffs", "format", "stages", "places", "tier"]
ROLES = ["top", "jng", "mid", "bot", "sup"]
# official awards, written by hand from the leagues' announcements and press coverage (only awards the sources agree
# on): (year, league, split, award, [players]). split: the tournament's data split name (None for an international
# event or event), or "*" for an award of the league's whole year (e.g. the LCK's regular-season MVP from 2025).
# Players by name as in the data; each is found among the players of that tournament (or league and year).
OFFICIAL_AWARDS = [
    # international events
    (2024, "MSI", None, "Finals MVP", ["Lehends"]),
    (2024, "EWC", None, "MVP", ["Faker"]),
    (2024, "WLDs", None, "Finals MVP", ["Faker"]),
    (2025, "FST", None, "Finals MVP", ["Zeka"]),
    (2025, "MSI", None, "MVP", ["Chovy"]),
    (2025, "EWC", None, "MVP", ["Kiin"]),
    (2025, "WLDs", None, "Finals MVP", ["Gumayusi"]),
    (2026, "FST", None, "Finals MVP", ["Bin"]),
    (2026, "MSI", None, "Finals MVP", ["Zeus"]),
    (2026, "EWC", None, "MVP", ["Smash"]),
    # LCK
    (2024, "LCK", "Spring", "Regular season MVP", ["Chovy"]),
    (2024, "LCK", "Spring", "All-LCK 1st team", ["Kiin", "Canyon", "Chovy", "Peyz", "Keria"]),
    (2024, "LCK", "Spring", "All-LCK 2nd team", ["Zeus", "Oner", "Faker", "Viper", "Lehends"]),
    (2024, "LCK", "Spring", "All-LCK 3rd team", ["Doran", "Peanut", "Zeka", "Gumayusi", "Delight"]),
    (2024, "LCK", "Summer", "Regular season MVP", ["Chovy"]),
    (2024, "LCK", "Summer", "All-LCK 1st team", ["Kiin", "Canyon", "Chovy", "Peyz", "Lehends"]),
    (2024, "LCK", "Summer", "All-LCK 2nd team", ["Doran", "Peanut", "Zeka", "Viper", "Delight"]),
    (2024, "LCK", "Summer", "All-LCK 3rd team", ["Kingen", "Oner", "Bdd", "Aiming", "Keria"]),
    (2025, "LCK", "*", "Regular season MVP", ["Chovy"]),
    (2025, "LCK", "*", "All-LCK 1st team", ["Kiin", "Canyon", "Chovy", "Ruler", "Duro"]),
    (2025, "LCK", "*", "All-LCK 2nd team", ["Doran", "Oner", "Bdd", "Viper", "Keria"]),
    (2025, "LCK", "*", "All-LCK 3rd team", ["Zeus", "Peanut", "Faker", "Gumayusi", "Delight"]),
    (2026, "LCK", "*", "Regular season MVP", ["Chovy"]),
    (2026, "LCK", "*", "All-LCK 1st team", ["Zeus", "Kanavi", "Chovy", "Peyz", "Keria"]),
    (2026, "LCK", "*", "All-LCK 2nd team", ["Kiin", "Lucid", "Zeka", "Ruler", "Delight"]),
    (2026, "LCK", "*", "All-LCK 3rd team", ["Siwoo", "Canyon", "ShowMaker", "Gumayusi", "Career"]),
    # LPL
    (2024, "LPL", "Spring", "Regular season MVP", ["knight"]),
    (2026, "LPL", "Split 1", "Regular season MVP", ["Tarzan"]),
    (2026, "LPL", "Split 1", "1st All-Pro team", ["Flandre", "Tarzan", "knight", "Elk", "Kael"]),
    (2026, "LPL", "Split 1", "2nd All-Pro team", ["Bin", "Xun", "Shanks", "Viper", "ON"]),
    (2026, "LPL", "Split 1", "3rd All-Pro team", ["Xiaoxu", "Jiejie", "Creme", "Hope", "Vampire"]),
    (2026, "LPL", "Split 2", "Regular season MVP", ["knight"]),
    (2026, "LPL", "Split 2", "1st All-Pro team", ["Bin", "Xun", "knight", "Viper", "ON"]),
    (2026, "LPL", "Split 2", "2nd All-Pro team", ["Flandre", "Tarzan", "HongQ", "JackeyLove", "Vampire"]),
    (2026, "LPL", "Split 2", "3rd All-Pro team", ["Xiaoxu", "JunJia", "Creme", "Gala", "Kael"]),
    (2026, "LPL", "Split 3", "Regular season MVP", ["knight"]),
    # LEC
    (2024, "LEC", "*", "Season MVP", ["Caps"]),
    (2024, "LEC", "Winter", "Finals MVP", ["BrokenBlade"]),
    (2024, "LEC", "Winter", "Team of the Split", ["BrokenBlade", "Yike", "Caps", "Hans Sama", "Mikyx"]),
    (2024, "LEC", "Spring", "Team of the Split", ["BrokenBlade", "Razork", "Caps", "Ice", "Jun"]),
    (2024, "LEC", "Spring", "Finals MVP", ["Caps"]),
    (2024, "LEC", "Summer", "Finals MVP", ["Caps"]),
    (2024, "LEC", "Finals", "Finals MVP", ["Hans Sama"]),
    (2024, "LEC", "*", "Rookie of the Year", ["Jackies"]),
    (2025, "LEC", "Winter", "Finals MVP", ["Vladi"]),
    (2025, "LEC", "Spring", "Finals MVP", ["Elyoya"]),
    (2025, "LEC", "Spring", "Season MVP", ["Upset"]),
    (2025, "LEC", "Spring", "Season MVP 2nd place", ["Canna"]),
    (2025, "LEC", "Spring", "Season MVP 3rd place", ["Vladi"]),
    (2025, "LEC", "Spring", "1st All-Pro team", ["Canna", "Yike", "Vladi", "Upset", "Mikyx"]),
    (2025, "LEC", "Spring", "2nd All-Pro team", ["Myrwn", "Razork", "Jojopyun", "Caliste", "Alvaro"]),
    (2025, "LEC", "Spring", "3rd All-Pro team", ["Naak Nako", "Elyoya", "Caps", "Hans Sama", "Targamas"]),
    (2025, "LEC", "Summer", "Finals MVP", ["SkewMond"]),
    (2025, "LEC", "*", "Rookie of the Year", ["Caliste"]),
    (2025, "LEC", "*", "Rookie of the Year 2nd place", ["SkewMond"]),
    (2025, "LEC", "*", "Rookie of the Year 3rd place", ["Naak Nako"]),
    (2026, "LEC", "Versus", "Finals MVP", ["Caps"]),
    (2026, "LEC", "Spring", "Season MVP", ["Naak Nako"]),
    (2026, "LEC", "Spring", "Season MVP 2nd place", ["Jojopyun"]),
    (2026, "LEC", "Spring", "Season MVP 3rd place", ["Busio"]),
    (2026, "LEC", "Spring", "Finals MVP", ["SkewMond"]),
    (2026, "LEC", "Spring", "1st All-Pro team", ["Naak Nako", "SkewMond", "Jojopyun", "Caliste", "Busio"]),
    (2026, "LEC", "Spring", "2nd All-Pro team", ["Canna", "Yike", "Caps", "Hans Sama", "Fleshy"]),
    (2026, "LEC", "Spring", "3rd All-Pro team", ["BrokenBlade", "Lyncas", "Kyeahoo", "Carzzy", "Labrov"]),
    (2026, "LEC", "Summer", "Season MVP", ["Caliste"]),
    (2026, "LEC", "Summer", "Season MVP 2nd place", ["Yike"]),
    (2026, "LEC", "Summer", "Season MVP 3rd place", ["Busio"]),
    (2026, "LEC", "Summer", "Finals MVP", ["Labrov"]),
    (2026, "LEC", "Summer", "1st All-Pro team", ["Canna", "Yike", "Kyeahoo", "Caliste", "Busio"]),
    (2026, "LEC", "Summer", "2nd All-Pro team", ["Naak Nako", "SkewMond", "Caps", "Hans Sama", "Labrov"]),
    (2026, "LEC", "Summer", "3rd All-Pro team", ["BrokenBlade", "Rhilech", "Jojopyun", "Carzzy", "Jun"]),
    (2026, "LEC", "*", "Rookie of the Year", ["Rhilech"]),
    (2026, "LEC", "*", "Rookie of the Year 2nd place", ["Jopa"]),
    (2026, "LEC", "*", "Rookie of the Year 3rd place", ["Rooster"]),
    # LCS
    (2024, "LCS", "Summer", "1st All-Pro team", ["Impact", "Blaber", "APA", "Yeon", "CoreJJ"]),
    (2024, "LCS", "Summer", "2nd All-Pro team", ["Thanatos", "Inspired", "Jojopyun", "Berserker", "Vulcan"]),
    (2024, "LCS", "Summer", "3rd All-Pro team", ["Bwipo", "UmTi", "Quad", "Massu", "Busio"]),
    (2026, "LCS", "Spring", "MVP", ["Vulcan"]),
    (2026, "LCS", "Spring", "1st All-Pro team", ["Thanatos", "Josedeodo", "Saint", "Berserker", "Vulcan"]),
    (2026, "LCS", "Summer", "1st All-Pro team", ["Morgan", "Josedeodo", "Saint", "Berserker", "CoreJJ"]),
    (2026, "LCS", "Summer", "2nd All-Pro team", ["Dhokla", "HamBak", "Quid", "Yeon", "Isles"]),
    (2026, "LCS", "Summer", "3rd All-Pro team", ["Thanatos", "Blaber", "Loki", "Rahel", "Vulcan"]),
]
# trophy cabinet (awards()): kind, tournament (index) or league, year, player, team, rating, games, detail
AWARD_FIELDS = ["kind", "tour", "league", "year", "pi", "ti", "rating", "games", "detail"]
# Tournament MVP: only players of top 4 teams; rating + this bonus by the team's final place (1st, 2nd, 3rd-4th) picks
# the winner, so a player of a team that went further wins unless someone else rated clearly better (the rating shown
# stays the real one)
MVP_PLACE_BONUS = {1: 0.15, 2: 0.05, 3: 0.0, 4: 0.0}


# 2014-2023 (phase 7). International events: stages by date (hand-written, dates checked against the data). Major
# league splits: teams, round robins and best-of measured from the games in the data; the playoff format named where
# known. Promotion, expansion and regional-finals tournaments: format_of().
_GROUPS16 = "16 teams in four groups of four, double round robin, best of 1; the top two of each group go through (the table mixes the groups)."
_KO8 = "Eight teams, single elimination, best of 5."
_PI17 = "12 teams in four groups of three, double round robin, best of 1; the top two of each group go to round 2 (the table mixes the groups)."
_PI20 = "Ten teams in two groups of five, single round robin, best of 1 (the table mixes the groups)."
def _worlds(about, *stages):
    return {"about": about, "stages": [_st(n, k, d, **{"from": a, "to": b}) for n, k, d, a, b in stages]}
def _old_worlds(g, ko):
    return _worlds("16 teams: a group stage, then a knockout stage.",
                   ("Group stage", "table", _GROUPS16, *g), ("Knockout stage", "bracket", _KO8, *ko))
def _pi_worlds(about, pi_r1, pi_r2, g, ko, r1=_PI17, r2="Best of 5; four teams go through to the group stage."):
    return _worlds(about, ("Play-In groups", "table", r1, *pi_r1), ("Play-In knockouts", "bracket", r2, *pi_r2),
                   ("Group stage", "table", _GROUPS16, *g), ("Knockout stage", "bracket", _KO8, *ko))
_MSI_G = "Six teams, double round robin, best of 1; the top four go through."
_MSI_KO = "Semifinals and final, best of 5."
_MSI_PI1 = "Eight teams in two groups of four, double round robin, best of 1; the top two of each group go to round 2 (the table mixes the groups)."
_MSI_GROUPS = "Three groups; each team plays the teams of its group twice (four times in the group of three), best of 1. The top two of each group go through (the table mixes the groups)."
_MSI_RUMBLE = "Six teams, double round robin, best of 1; the top four go to the semifinals."
FORMATS.update({
    (2014, "WLDs", None): _old_worlds(("09-18", "09-28"), ("10-03", "10-19")),
    (2015, "WLDs", None): _old_worlds(("10-01", "10-11"), ("10-15", "10-31")),
    (2016, "WLDs", None): _old_worlds(("09-29", "10-10"), ("10-13", "10-30")),
    (2017, "WLDs", None): _pi_worlds("24 teams: Play-In, group stage and knockout stage.", ("09-23", "09-26"), ("09-28", "09-29"), ("10-05", "10-15"), ("10-19", "11-04")),
    (2018, "WLDs", None): _pi_worlds("24 teams: Play-In, group stage and knockout stage.", ("10-01", "10-04"), ("10-06", "10-07"), ("10-10", "10-17"), ("10-20", "11-03")),
    (2019, "WLDs", None): _pi_worlds("24 teams: Play-In, group stage and knockout stage.", ("10-02", "10-05"), ("10-07", "10-08"), ("10-12", "10-20"), ("10-26", "11-10")),
    (2020, "WLDs", None): _pi_worlds("22 teams (the Vietnamese teams could not travel): Play-In, group stage and knockout stage.",
                                     ("09-25", "09-28"), ("09-29", "10-01"), ("10-03", "10-11"), ("10-15", "10-31"), r1=_PI20,
                                     r2="Best of 5; the group winners go straight through, four teams in all."),
    (2021, "WLDs", None): _pi_worlds("22 teams (the Vietnamese teams could not travel): Play-In, group stage and knockout stage.",
                                     ("10-05", "10-07"), ("10-08", "10-10"), ("10-11", "10-18"), ("10-22", "11-06"), r1=_PI20,
                                     r2="Best of 5; the group winners go straight through, four teams in all."),
    (2022, "WLDs", None): _worlds("24 teams: Play-In, group stage and knockout stage.",
                                  ("Play-In", "bracket", "12 teams in two groups of six, single round robin, best of 1, then best-of-5 knockout rounds; four teams go through to the group stage.", "09-29", "10-04"),
                                  ("Group stage", "table", _GROUPS16, "10-07", "10-17"), ("Knockout stage", "bracket", _KO8, "10-20", "11-06")),
    (2023, "WLDs", None): _worlds("Three stages: Play-In, Swiss Stage and Knockout Stage.",
                                  ("Play-In", "bracket", "Double elimination.", "10-01", "10-15"),
                                  ("Swiss Stage", "table", "16 teams, paired by record; 3 wins go through, 3 losses are out. Best of 1, except best of 3 when a team can go through or be eliminated.", "10-19", "10-29"),
                                  ("Knockout Stage", "bracket", _KO8, "11-02", "11-19")),
    (2015, "MSI", None): _worlds("6 teams: the spring champions of the LCK, LPL, EU LCS, NA LCS and LMS, and the winner of the International Wildcard Invitational.",
                                 ("Group stage and knockout", "bracket", "Single round robin, best of 1; the top four went to the semifinals and final, best of 5. (Group and semifinal games were played on the same days, so this page shows them together.)", "05-01", "05-31")),
    (2016, "MSI", None): _worlds("6 teams: the spring champions of the LCK, LPL, EU LCS, NA LCS and LMS, and the winner of the International Wildcard Invitational.",
                                 ("Group stage", "table", _MSI_G, "05-04", "05-08"), ("Knockout stage", "bracket", _MSI_KO, "05-13", "05-15")),
    (2017, "MSI", None): _worlds("13 teams: the spring champions of every region.",
                                 ("Play-In round 1", "table", _MSI_PI1, "04-28", "05-01"), ("Play-In round 2", "bracket", "Best of 5; the winners go to the group stage.", "05-03", "05-07"),
                                 ("Group stage", "table", _MSI_G, "05-10", "05-15"), ("Knockout stage", "bracket", _MSI_KO, "05-19", "05-21")),
    (2018, "MSI", None): _worlds("14 teams: the spring champions of every region.",
                                 ("Play-In round 1", "table", _MSI_PI1, "05-03", "05-06"), ("Play-In round 2", "bracket", "Best of 5; the winners go to the group stage.", "05-08", "05-09"),
                                 ("Group stage", "table", _MSI_G, "05-11", "05-15"), ("Knockout stage", "bracket", _MSI_KO, "05-18", "05-20")),
    (2019, "MSI", None): _worlds("13 teams: the spring champions of every region.",
                                 ("Play-In", "bracket", "Two groups (best of 1), then best-of-5 knockout rounds; the winners go to the group stage.", "05-01", "05-07"),
                                 ("Group stage", "table", _MSI_G, "05-10", "05-14"), ("Knockout stage", "bracket", _MSI_KO, "05-17", "05-19")),
    (2021, "MSI", None): _worlds("11 teams (the Vietnamese champion could not travel).",
                                 ("Group stage", "table", _MSI_GROUPS, "05-06", "05-11"), ("Rumble stage", "table", _MSI_RUMBLE, "05-14", "05-18"),
                                 ("Knockout stage", "bracket", _MSI_KO, "05-21", "05-23")),
    (2022, "MSI", None): _worlds("11 teams (the LPL champion played online from China).",
                                 ("Group stage", "table", _MSI_GROUPS, "05-10", "05-15"), ("Rumble stage", "table", _MSI_RUMBLE, "05-20", "05-24"),
                                 ("Knockout stage", "bracket", _MSI_KO, "05-27", "05-29")),
    (2023, "MSI", None): _worlds("13 teams.", ("Play-In", "bracket", "Eight teams in two groups, double elimination, best of 3.", "05-02", "05-07"),
                                 ("Bracket Stage", "bracket", "Eight teams, double elimination, best of 5.", "05-09", "05-21")),
    (2020, "MSC", None): _worlds("8 teams from the LCK and LPL, played online, in place of MSI (cancelled because of the pandemic).",
                                 ("Group stage", "table", "Two groups of four, single round robin, best of 1; the top two of each group go through (the table mixes the groups).", "05-28", "05-29"),
                                 ("Knockout stage", "bracket", _MSI_KO, "05-30", "05-31")),
    (2015, "IEM", "Katowice"): _worlds("IEM Season IX World Championship in Katowice.", ("Results", "bracket", "", "01-01", "12-31")),
    (2015, "IEM", "San Jose"): _worlds("IEM Season X San Jose.", ("Results", "bracket", "", "01-01", "12-31")),
    (2015, "IEM", "Cologne"): _worlds("IEM Season X Cologne.", ("Results", "bracket", "", "01-01", "12-31")),
    (2016, "IEM", "Katowice"): _worlds("IEM Season X World Championship in Katowice.", ("Results", "bracket", "", "01-01", "12-31")),
    (2016, "IEM", "Gyeonggi"): _worlds("IEM Season XI Gyeonggi.", ("Results", "bracket", "", "01-01", "12-31")),
    (2016, "IEM", "Oakland"): _worlds("IEM Season XI Oakland.", ("Results", "bracket", "", "01-01", "12-31")),
    (2017, "IEM", "Katowice"): _worlds("IEM Season XI World Championship in Katowice.", ("Results", "bracket", "", "01-01", "12-31")),
    (2021, "LCS", "Lock In"): _worlds("A preseason tournament for all 10 LCS teams. The data files these games as Spring playoffs.",
                                      ("Bracket", "bracket", "Two groups of five, single round robin, best of 1; then quarterfinals (best of 3), semifinals and final (best of 5).", "01-01", "01-31")),
    (2022, "LCS", "Lock In"): _worlds("A preseason tournament for all 10 LCS teams. The data files these games as Spring playoffs.",
                                      ("Bracket", "bracket", "Two groups of five, single round robin, best of 1; then quarterfinals (best of 3), semifinals and final (best of 5).", "01-01", "01-31")),
    (2023, "LEC", "Finals"): {"about": "The LEC Season Finals: the six best teams of the year's three splits. The data files these games as \"Finals\".",
                              "stages": [_st("Bracket", "bracket", "Double elimination, best of 5.", flag="playoffs")]},
    (2014, "EU LCS", "Spring"): {"about": "8 teams.", "stages": _lg("Quadruple round robin, best of 1.", "Six teams, single elimination, best of 3 and best of 5.")},
    (2014, "EU LCS", "Summer"): {"about": "8 teams.", "stages": _lg("Quadruple round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2014, "NA LCS", "Spring"): {"about": "8 teams.", "stages": _lg("Quadruple round robin, best of 1.", "Six teams, single elimination.")},
    (2014, "NA LCS", "Summer"): {"about": "8 teams.", "stages": _lg("Quadruple round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2015, "EU LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2015, "EU LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2015, "LCK", "Spring"): {"about": "8 teams.", "stages": _lg("Double round robin, best of 3.", "Four teams, step-ladder (each round's winner plays the next-higher seed), best of 5.")},
    (2015, "LCK", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed), best of 5.")},
    (2015, "NA LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2015, "NA LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2016, "EU LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2016, "EU LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 2.", "Six teams, single elimination, best of 5.")},
    (2016, "LCK", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed), best of 3 and best of 5.")},
    (2016, "LCK", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed), best of 3 and best of 5.")},
    (2016, "LPL", "Summer"): {"about": "12 teams.", "stages": _lg("Two groups of six: double round robin within the group, single round robin against the other group, best of 3.", "Six teams, best of 3 and best of 5.")},
    (2016, "NA LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2016, "NA LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Six teams, single elimination, best of 5.")},
    (2017, "EU LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Two groups of five: double round robin within the group, single round robin against the other group, best of 3.", "Six teams, single elimination, best of 5.")},
    (2017, "EU LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Two groups of five: double round robin within the group, single round robin against the other group, best of 3.", "Six teams, single elimination, best of 5.")},
    (2017, "LCK", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed).")},
    (2017, "LCK", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed), best of 3 and best of 5.")},
    (2017, "NA LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Six teams, single elimination, best of 5.")},
    (2017, "NA LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Six teams, single elimination, best of 5.")},
    (2018, "EU LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2018, "EU LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2018, "LCK", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed), best of 5.")},
    (2018, "LCK", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed), best of 3 and best of 5.")},
    (2018, "LPL", "Spring"): {"about": "14 teams.", "stages": _lg("Two groups of seven: double round robin within the group, single round robin against the other group, best of 3.", "Eight teams, single elimination, best of 3 and best of 5.")},
    (2018, "LPL", "Summer"): {"about": "14 teams.", "stages": _lg("Two groups of seven: double round robin within the group, single round robin against the other group, best of 3.", "Eight teams, single elimination, best of 5.")},
    (2018, "NA LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2018, "NA LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2019, "LCK", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed).")},
    (2019, "LCK", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed), best of 5.")},
    (2019, "LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2019, "LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, single elimination, best of 5.")},
    (2019, "LEC", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, best of 5.")},
    (2019, "LEC", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, best of 5.")},
    (2019, "LPL", "Spring"): {"about": "16 teams.", "stages": _lg("Single round robin, best of 3.", "Eight teams, single elimination, best of 5.")},
    (2019, "LPL", "Summer"): {"about": "16 teams.", "stages": _lg("Single round robin, best of 3.", "Eight teams, single elimination, best of 5.")},
    (2020, "LCK", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed), best of 5.")},
    (2020, "LCK", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Five teams, step-ladder (each round's winner plays the next-higher seed).")},
    (2020, "LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, double elimination, best of 5.")},
    (2020, "LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Eight teams, double elimination, best of 5.")},
    (2020, "LEC", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, double elimination, best of 5.")},
    (2020, "LEC", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, double elimination, best of 5.")},
    (2020, "LPL", "Spring"): {"about": "17 teams.", "stages": _lg("Single round robin, best of 3.", "Eight teams, single elimination, best of 5.")},
    (2020, "LPL", "Summer"): {"about": "17 teams.", "stages": _lg("Single round robin, best of 3.", "Eight teams, single elimination, best of 5.")},
    (2021, "LCK", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Six teams, single elimination, best of 5.")},
    (2021, "LCK", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Six teams, single elimination, best of 5.")},
    (2021, "LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, double elimination, best of 5.")},
    (2021, "LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Triple round robin, best of 1.", "Eight teams, double elimination, best of 5.")},
    (2021, "LEC", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, double elimination, best of 5.")},
    (2021, "LEC", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, double elimination, best of 5.")},
    (2021, "LPL", "Spring"): {"about": "17 teams.", "stages": _lg("Single round robin, best of 3.", "Ten teams, best of 5.")},
    (2021, "LPL", "Summer"): {"about": "17 teams.", "stages": _lg("Single round robin, best of 3.", "Ten teams, best of 5.")},
    (2022, "LCK", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Six teams, single elimination, best of 5.")},
    (2022, "LCK", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Six teams, single elimination, best of 5.")},
    (2022, "LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, double elimination, best of 5.")},
    (2022, "LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Eight teams, double elimination, best of 5.")},
    (2022, "LEC", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, double elimination, best of 5.")},
    (2022, "LEC", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, double elimination, best of 5.")},
    (2022, "LPL", "Spring"): {"about": "17 teams.", "stages": _lg("Single round robin, best of 3.", "Ten teams, best of 5.")},
    (2022, "LPL", "Summer"): {"about": "17 teams.", "stages": _lg("Single round robin, best of 3.", "Ten teams, best of 5.")},
    (2023, "LCK", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Six teams, double elimination, best of 5.")},
    (2023, "LCK", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 3.", "Six teams, double elimination, best of 5.")},
    (2023, "LCS", "Spring"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Six teams, double elimination, best of 5.")},
    (2023, "LCS", "Summer"): {"about": "10 teams.", "stages": _lg("Double round robin, best of 1.", "Eight teams, double elimination, best of 5.")},
    (2023, "LPL", "Spring"): {"about": "17 teams.", "stages": _lg("Single round robin, best of 3.", "Ten teams, best of 5.")},
    (2023, "LPL", "Summer"): {"about": "17 teams.", "stages": _lg("Single round robin, best of 3.", "Ten teams, best of 5.")},
})
for _sp, _rs, _gs in (("Winter", ("01-01", "02-08"), ("02-09", "02-19")), ("Spring", ("03-01", "04-01"), ("04-02", "04-16")),
                      ("Summer", ("06-01", "07-08"), ("07-09", "07-23"))):
    FORMATS[(2023, "LEC", _sp)] = {"about": "10 teams. Results count toward the Season Finals.", "stages": [
        _st("Regular season", "table", "Single round robin, best of 1; the top eight go to the group stage.", flag="regular", **{"from": _rs[0], "to": _rs[1]}),
        _st("Group stage", "bracket", "Two groups of four, double elimination, best of 3; the top two of each group go to the playoffs.", flag="regular", **{"from": _gs[0], "to": _gs[1]}),
        _st("Playoffs", "bracket", "Four teams, best of 5.", flag="playoffs")]}


def tier_of(lg, y=None):
    """A league's tier, in year y (default: the year in use)."""
    if lg in INTERNATIONAL: return "international"
    if lg in EVENTS: return "event"
    tiers = TIERS if y is None else YEARS.get(y, YEARS[REFERENCE_YEAR])["TIERS"]
    return next((t for t, lgs in tiers.items() if lg in lgs), "tier2")


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
        "cs": (p["total cs"] if "total cs" in p.columns else p["cspm"] * p["gamelength"] / 60).round(0),
        "dpm": p["dpm"].round(0), "vspm": p["vspm"].round(2),
        "r_early": p["r_early"], "r_late": p["r_late"], "r_overall": p["r_overall"],
        "playerid": p["playerid"], "baseline": p["baseline"],
    })
    out["year"] = out["date"].dt.year
    return out


def clean_year(df):
    """Fixes for the older files (in place). Stats that did not exist yet are 0 in the data (vision score and tower
    damage before 2017): missing, not 0, per league. Team rows without picks (2014-16): the players' champions (by
    role, not the draft order). Games with a team without a name (one VCS game in 2021) are left out."""
    df.drop(df.index[df["gameid"].isin(df.loc[df["teamname"].isna(), "gameid"])], inplace=True)
    df.reset_index(drop=True, inplace=True)
    for c in [c for c in rc.NUM_COLS if c in df.columns]:
        x = pd.to_numeric(df[c], errors="coerce")
        dead = (x.fillna(0) != 0).groupby(df["league"]).mean()
        dead = dead[dead < 0.01].index
        if len(dead):
            df.loc[df["league"].isin(dead), c] = np.nan
    team = df["position"] == "team"
    if "pick1" in df.columns and df.loc[team, "pick1"].isna().all():
        ch = (df[~team].sort_values("participantid").groupby(["gameid", "side"])["champion"].agg(list))
        keys = list(zip(df.loc[team, "gameid"], df.loc[team, "side"]))
        for i in range(5):
            df[f"pick{i + 1}"] = df[f"pick{i + 1}"].astype(object)
            df.loc[team, f"pick{i + 1}"] = [(ch.get(k) or [])[i] if len(ch.get(k) or []) > i else None for k in keys]


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


def team_leagues(df):
    """Regular leagues with MIN_TEAM_GAMES games, complete or partial (LPL 2024-25 has only partial games): these are
    on the team side (Elo, team pages, tournaments) even without player ratings."""
    t = df[(df["position"] == "team") & ~df["league"].isin(INTERNATIONAL + EVENTS)]
    n = t.groupby("league")["gameid"].nunique()
    return n[n >= MIN_TEAM_GAMES].index.tolist()


def team_rows(df, games, leagues, events, y):
    """One row per team per game of one year's file (year y's settings in use) for the leagues, events and international
    events on the site (partial games included). Split labels come from the player games of the same game; partial
    games use their own label."""
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
    # home league per team this year (for the Elo league level): its most played regular league, else its league here
    home = home_leagues(df)
    by_name = (df[(df["position"] == "team") & ~df["league"].isin(INTERNATIONAL + EVENTS)]
               .groupby(["teamname", "league"])["gameid"].nunique().reset_index()
               .sort_values("gameid", ascending=False).drop_duplicates("teamname").set_index("teamname")["league"])
    t["home"] = [home.get(k) if not k.startswith("name:") else by_name.get(n) for k, n in zip(t["key"], t["teamname"])]
    t["home"] = t["home"].where(t["home"].notna(), t["league"])
    major_events = {lg for lg, c in t[t["kind"] == "event"].groupby("league") if any(tier_of(h) in ("major", "tier1") for h in c["home"])}
    major_events -= set(QUALIFIERS)
    # what a game counts for: international events by name, EM, other events, EWC qualifiers, leagues by tier
    t["comp"] = np.where(t["kind"] == "international", t["league"],
                         np.where(t["kind"] == "event", np.where(t["league"].isin(QUALIFIERS), "qualifier",
                                                                 np.where(t["league"].isin(["EM", "EUM", "WSCI"]), t["league"].replace({"EUM": "EM"}),
                                                                          np.where(t["league"].isin(major_events), "event_major", "event"))),
                                  t["league"].map(tier_of)))
    t["tier"] = t["home"].map(tier_of)               # tier of the home league this year (Elo league-level prior)
    return t


def new_starters(df):
    """(gameid, team key) -> how many of the team's players had not played for it in the last team_elo.ROSTER_DAYS days
    (a team's first game counts 0). df: the player rows of every year."""
    p = df[df["position"] != "team"][["gameid", "date", "teamid", "teamname", "playerid", "playername"]].copy()
    p["key"] = p["teamid"].where(p["teamid"].notna(), "name:" + p["teamname"].astype(str))
    p["who"] = p["playerid"].where(p["playerid"].notna(), "name:" + p["playername"].astype(str))
    p["date"] = pd.to_datetime(p["date"])
    p = p.sort_values(["date", "gameid"], kind="stable")
    prev = p.groupby(["key", "who"])["date"].shift()
    first = p["date"] == p.groupby("key")["date"].transform("min")
    p["new"] = ((prev.isna() | (p["date"] - prev > pd.Timedelta(days=team_elo.ROSTER_DAYS))) & ~first).astype(int)
    return p.groupby(["gameid", "key"])["new"].sum()


def team_games(parts, roster):
    """All years' team rows (from team_rows) in one table: team index, opponent, series, and the Elo through every year.
    roster: new_starters()."""
    t = pd.concat(parts, ignore_index=True)
    t = t.sort_values(["date", "gameid", "side"], kind="stable").reset_index(drop=True)
    # REFERENCE_YEAR's teams first, in their order, so their page addresses stay the same
    ty = t["date"].dt.year
    keys = list(dict.fromkeys(list(t.loc[ty == REFERENCE_YEAR, "key"]) + list(t.loc[ty >= KEEP_ORDER_FROM, "key"])
                              + [k for y in sorted(set(ty[ty < KEEP_ORDER_FROM]), reverse=True) for k in t.loc[ty == y, "key"]]))
    t["ti"] = t["key"].map({k: i for i, k in enumerate(keys)})
    other = t[["gameid", "ti", "teamname"]].rename(columns={"ti": "oi", "teamname": "opponent"})
    t = t.merge(other, on="gameid")
    t = t[t["ti"] != t["oi"]].sort_values(["date", "gameid", "side"], kind="stable").reset_index(drop=True)

    # series: same league, same two teams, under 12 hours between games (so a series can run past midnight); such a
    # run is split where the game number does not go up, unless no game number repeats in it (numbers out of order in
    # the data); the result is set on the team's last game of the series
    t["pair"] = [f"{lg}|{min(a, b)}-{max(a, b)}" for lg, a, b in zip(t["league"], t["ti"], t["oi"])]
    gm = t.drop_duplicates("gameid")[["gameid", "pair", "date", "game"]].sort_values(["date", "gameid"], kind="stable")
    prev = gm.groupby("pair")[["date", "game"]].shift()
    run = (prev["date"].isna() | (gm["date"] - prev["date"] > pd.Timedelta(hours=12))).astype(int).groupby(gm["pair"]).cumsum()
    rep = gm.groupby([gm["pair"], run])["game"].transform(lambda s: s.duplicated().any())
    new = (run != run.groupby(gm["pair"]).shift()) | (rep & (gm["game"] <= prev["game"]))
    gm["series"] = (new.astype(int).groupby(gm["pair"]).cumsum()).astype(str)
    sid = (gm["pair"] + "|" + gm["series"]).set_axis(gm["gameid"])
    t["series"] = pd.factorize(t["gameid"].map(sid))[0]
    t = t.drop(columns="pair")
    t["gn"] = t.groupby("series")["gameid"].transform(lambda s: pd.factorize(s)[0] + 1)   # game number in the series
    sw = t.groupby(["series", "ti"])["result"].agg(["sum", "size"])
    t["s_result"] = None
    last = t.groupby(["series", "ti"]).tail(1).index
    for i in last:
        w, n = sw.loc[(t.at[i, "series"], t.at[i, "ti"])]
        t.at[i, "s_result"] = 1 if w > n - w else 0 if w < n - w else None

    # Elo, one row per game (blue vs red). League levels are per league and year ("LCK 2025"), from the home league's
    # tier that year; in the season fit a team is one team per year (rosters change)
    t["year"] = t["date"].dt.year
    t["lvl"] = t["home"] + " " + t["year"].astype(str)
    t["new"] = [roster.get((gid, k), 0) for gid, k in zip(t["gameid"], t["key"])]
    b = t[t["side"] == "Blue"].set_index("gameid")
    r = t[t["side"] == "Red"].set_index("gameid")
    order = b.index[b.index.isin(r.index)]
    g = pd.DataFrame({"blue": b.loc[order, "ti"].to_numpy(), "red": r.loc[order, "ti"].to_numpy(),
                      "blue_lg": b.loc[order, "lvl"].to_numpy(), "red_lg": r.loc[order, "lvl"].to_numpy(),
                      "blue_win": b.loc[order, "result"].to_numpy(dtype=float),
                      "blue_new": b.loc[order, "new"].to_numpy(), "red_new": r.loc[order, "new"].to_numpy()}, index=order)
    g["blue_fit"] = [f"{i} {y}" for i, y in zip(g["blue"], b.loc[order, "year"])]
    g["red_fit"] = [f"{i} {y}" for i, y in zip(g["red"], r.loc[order, "year"])]
    cb = t.drop_duplicates("gameid").set_index("gameid").loc[order, "comp"]
    g["weight"] = cb.map(team_elo.WEIGHT).to_numpy()
    g["series"] = b.loc[order, "series"].to_numpy()
    g["day"] = ((t.drop_duplicates("gameid").set_index("gameid").loc[order, "date"] - t["date"].min()).dt.total_seconds() / 86400).to_numpy()
    lv = t.drop_duplicates("lvl").set_index("lvl")
    prior = {v: team_elo.prior_of(lv.at[v, "home"], lv.at[v, "tier"]) for v in lv.index}
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
    rb, rr, after_b, after_r, rep, now = team_elo.fit(g, prior, titles)
    rep["titles"] = title_list
    rep["finals"] = fins
    # Elo now: after decay up to the last day in the data, at the league level of the team's latest year
    end_day = (end - t["date"].min()).total_seconds() / 86400
    homes = t.groupby("ti")["lvl"].last()
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
        "home": t["home"], "tour": t["tour"], "comp": t["comp"], "gn": t["gn"],
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
        tn = "" if sp == "None" else TOUR_NAMES.get((int(y), lg, sp), sp)
        name = LEAGUE_NAMES.get(lg, lg) + (" " + tn if tn else "")
        per = c["period"].dropna()
        if kind == "domestic" and len(per) and per.iloc[0] != sp:
            name += f" ({per.iloc[0]})"                       # major leagues: the common split name too
        rows.append({"year": int(y), "league": lg, "kind": kind, "split": None if sp == "None" else sp, "name": name,
                     "tier": YEARS.get(int(y), YEARS[REFERENCE_YEAR])["TOUR_TIERS"].get((lg, sp), tier_of(lg, int(y)) if kind == "domestic" else None),
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
    one = [_st("Results", "bracket", "")]
    if kind == "domestic" and sp in ("Summer Promotion", "Spring Promotion"):
        nxt = "the Summer split" if sp == "Summer Promotion" else "next year's Spring split"
        return {"format": f"Promotion and relegation series for {nxt}: the league's bottom teams against the best teams of "
                          "the second division. The data files these games under a split of the league.", "stages": one}
    if kind == "domestic" and sp == "Expansion Tournament":
        return {"format": "The tournament for the two new places in 2015, when the league grew from 8 to 10 teams. The data "
                          "files these games under the Spring split.", "stages": one}
    if kind == "domestic" and sp == "Regional Finals":
        return {"format": "The region's qualifier for its last Worlds spot, after the Summer split. The data files these "
                          "games without a split name.", "stages": one}
    if kind == "domestic":
        both = (c["stage"] == "playoffs").any() and (c["stage"] == "regular").any()
        return {"format": None, "stages": _LEAGUE if both else [_st("Season", "table", "")]}
    return {"format": None, "stages": [_st("Results", "bracket", "")]}


def tournament_links(tg, tours):
    """Qualification paths, found from the teams that played both tournaments: [from, to, [teams]].
    * International events and events: each team comes from the qualifier of the same event and year it played before
      (EWC Qualifier -> EWC), else from the latest league split it played that was at least half played (by games) when
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
                        and tours.at[v, "kind"] == "event" and tours.at[v, "year"] == U["year"]] or [v for v in before if tours.at[v, "kind"] == "domestic"]
            if cand:
                v = max(cand, key=lambda v: (first[v], tours.at[v, "last"]))
                src.setdefault(v, []).append(int(x))
        for v, xs in sorted(src.items()):
            if 0 < len(xs) < len(teams_of[v]):
                links.append([int(v), int(u), sorted(xs)])
    return links


def awards(g_out, tg, tours, raw, c_by_role):
    """The trophy cabinet. Results: champion and runner-up of every tournament with a champion, for the team and for
    each player who played for it in that tournament (detail "final" if they played in the final series, else
    "roster"; from the raw player rows, so tournaments without player ratings count too). Awards by rating (ours, not
    official), for major-league splits and international events that have finished: Tournament MVP (highest rating +
    MVP_PLACE_BONUS among players of top 4 teams with at least half of their team's games), Finals MVP (highest rating on the champion in the final
    series), and per major league and year the Player of the Year (overall and per role; games of every split, at
    least MIN_GAMES_CALIBRATION and half the most games anyone played there). Ratings: the leaderboard formula."""
    def rating(g):
        w = np.where(g["kind"] == "international", INTL_WEIGHT, 1.0)
        r = g["r_overall"]
        ok = r.notna().to_numpy()
        a = pd.DataFrame({"pi": g["pi"], "role": g["role"], "ti": g["ti"], "wm": np.where(ok, w, 0.0),
                          "wd": np.where(ok, w * (r.fillna(1.0) - 1), 0.0), "n": ok.astype(int)})
        a = a.groupby("pi").agg(role=("role", "first"), ti=("ti", "last"), sw=("wm", "sum"), swd=("wd", "sum"), games=("n", "sum"))
        a = a[a["games"] > 0]
        a["rating"] = 1 + a["role"].map(c_by_role) * a["swd"] / (a["sw"] + K)
        return a.sort_values("rating", ascending=False)

    rows = []
    key = lambda d: (int(d["year"]), d["league"], d["kind"], "None" if pd.isna(d["split"]) else d["split"])
    tg_k = tg[tg["tour"]].assign(k=[key(r) for r in tg[tg["tour"]][["year", "league", "kind", "split"]].to_dict("records")])
    g_k = g_out.assign(k=[key(r) for r in g_out[["year", "league", "kind", "split"]].to_dict("records")])
    # raw player rows -> player index: by playerid + role, else name + role; team index by game and team name
    by_id = dict(zip(zip(g_out["playerid"], g_out["role"]), g_out["pi"]))
    by_name = dict(zip(zip(g_out["player"], g_out["role"]), g_out["pi"]))
    ti_of = dict(zip(zip(tg["gameid"], tg["team"]), tg["ti"]))
    raw = raw.assign(ti=[ti_of.get(k) for k in zip(raw["gameid"], raw["teamname"])])
    raw = raw.assign(pi=[by_id.get((i, r)) if isinstance(i, str) and (i, r) in by_id else by_name.get((n, r))
                         for i, n, r in zip(raw["playerid"], raw["playername"], raw["position"])])
    raw = raw[raw["pi"].notna() & raw["ti"].notna()]
    for i, e in tours.iterrows():
        if pd.isna(e["champ"]):
            continue
        k = (int(e["year"]), e["league"], e["kind"], "None" if pd.isna(e["split"]) else e["split"])
        c = tg_k[tg_k["k"] == k]
        fin = set(c.loc[c["series"] == e["final"], "gameid"])
        for kind, ti in (("champion", e["champ"]), ("runner_up", e["runner"])):
            if pd.isna(ti):
                continue
            ti = int(ti)
            rows.append([kind, i, e["league"], int(e["year"]), None, ti, None, None, None])
            mine = raw[raw["gameid"].isin(set(c.loc[c["ti"] == ti, "gameid"])) & (raw["ti"] == ti)]
            for pi, x in mine.groupby("pi"):
                rows.append([kind, i, e["league"], int(e["year"]), int(pi), ti, None, int(x["gameid"].nunique()),
                             "final" if fin & set(x["gameid"]) else "roster"])
        if not (e["kind"] == "international" or (e["kind"] == "domestic" and e["tier"] == "major")):
            continue
        g = g_k[g_k["k"] == k]
        if g.empty:
            continue
        team_games = c.groupby("ti")["gameid"].nunique()
        a = rating(g)
        a = a[a["games"] >= 0.5 * a["ti"].map(team_games).fillna(0)]
        place = {ti: int(lab.split("–")[0].rstrip("stndrh")) for ti, lab in (e["places"] or [])}
        a = a[a["ti"].map(lambda ti: place.get(ti, 99) <= 4)]
        a = a.assign(score=a["rating"] + a["ti"].map(lambda ti: MVP_PLACE_BONUS[place[ti]])).sort_values("score", ascending=False)
        if len(a):
            rows.append(["mvp", i, e["league"], int(e["year"]), int(a.index[0]), int(a["ti"].iloc[0]),
                         round(float(a["rating"].iloc[0]), 3), int(a["games"].iloc[0]), None])
        f = rating(g[g["gameid"].isin(fin) & (g["ti"] == int(e["champ"]))])
        if len(f):
            rows.append(["finals_mvp", i, e["league"], int(e["year"]), int(f.index[0]), int(f["ti"].iloc[0]),
                         round(float(f["rating"].iloc[0]), 3), int(f["games"].iloc[0]), None])
    # Player of the Year: per major league and year (a year that is over: the data runs past its last league game)
    for (y, lg), g in g_out[g_out["kind"] == "domestic"].groupby(["year", "league"]):
        if tier_of(lg, int(y)) != "major":
            continue
        a = rating(g)
        a = a[a["games"] >= max(MIN_GAMES_CALIBRATION, 0.5 * a["games"].max())]
        if a.empty:
            continue
        rows.append(["poy", None, lg, int(y), int(a.index[0]), int(a["ti"].iloc[0]), round(float(a["rating"].iloc[0]), 3),
                     int(a["games"].iloc[0]), None])
        for role in ROLES:
            b = a[a["role"] == role]
            if len(b):
                rows.append(["poy_role", None, lg, int(y), int(b.index[0]), int(b["ti"].iloc[0]),
                             round(float(b["rating"].iloc[0]), 3), int(b["games"].iloc[0]), role])
    # official awards (OFFICIAL_AWARDS): the player is found by name among the raw player rows of the tournament (or of
    # the league's domestic games that year); team = the one they played the most games for there
    tidx = {(int(e["year"]), e["league"], None if pd.isna(e["split"]) else e["split"]): i for i, e in tours.iterrows()}
    yr = tg["date"].dt.year
    for y, lg, sp, label, names in OFFICIAL_AWARDS:
        if sp == "*":
            ti_ = None
            gids = set(tg.loc[(yr == y) & (tg["league"] == lg) & (tg["kind"] == "domestic"), "gameid"])
        else:
            ti_ = tidx.get((y, lg, sp))
            if ti_ is None:
                print(f"  official award: no tournament {y} {lg} {sp}")
                continue
            e = tours.loc[ti_]
            gids = set(tg_k.loc[tg_k["k"] == (y, lg, e["kind"], "None" if sp is None else sp), "gameid"])
        r = raw[raw["gameid"].isin(gids)]
        for nm in names:
            x = r[r["playername"].astype(str).str.casefold() == nm.casefold()]
            if x["pi"].nunique() != 1:
                print(f"  official award: {nm} ({y} {lg} {sp} {label}): {x['pi'].nunique()} players found")
                continue
            ti = int(x.groupby("ti")["gameid"].nunique().idxmax())
            rows.append(["official", None if ti_ is None else int(ti_), lg, y, int(x["pi"].iloc[0]), ti, None,
                         int(x["gameid"].nunique()), label])
    return rows


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
    """Spread constants c(role) of one year: calibrated on its first baseline group (the main leagues)."""
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


def write_site_data(games, c_by_role, cfg, out_dir, leagues, complete, tg, team_keys, elo_report, tours, links, raw):
    """Writes index.json, summary/<year>.json, games/<year>/<league>.json and teams/<year>/<league>.json."""
    sg = tg.drop_duplicates("gameid").set_index("gameid")
    games = games.assign(series=games["gameid"].map(sg["series"]), gn=games["gameid"].map(sg["gn"]))
    g_out = games[GAME_FIELDS + ["year", "playerid", "gameid"]].copy()
    # which team (index into the team list) each player-game belongs to
    ti_of = dict(zip(zip(tg["gameid"], tg["team"]), tg["ti"]))
    g_out["ti"] = [ti_of.get(k, -1) for k in zip(g_out["gameid"], g_out["team"])]
    g_out["date"] = g_out["date"].dt.strftime("%Y-%m-%d")
    for c in ["r_early", "r_late", "r_overall"]:
        g_out[c] = g_out[c].round(3)
    g_out["gd15"] = g_out["gd15"].round(0)
    g_out[GAME_FIELDS].to_csv(os.path.join(out_dir, "games_rated.csv"), index=False)

    # players of REFERENCE_YEAR: the same name + role is one player unless player_keys() splits it. Order: players
    # with games in the BASELINE_GROUPS leagues or international events first, by first game there, then the rest by
    # first game. The site gives page addresses in this order, so the players from before phase 1 keep theirs.
    # Other years: a row joins the REFERENCE_YEAR player with its playerid and role, else the players are its playerid
    # + role (name + role without an id), shown under their latest name, after the REFERENCE_YEAR players.
    ref = (g_out["year"] == REFERENCE_YEAR).to_numpy()
    rk = player_keys(g_out[ref].reset_index(drop=True))
    pkey = [None] * len(g_out)
    for j, i in enumerate(np.flatnonzero(ref)):
        pkey[i] = (g_out.at[i, "player"], g_out.at[i, "role"], int(rk[j]))
    by_id = {}
    for i in np.flatnonzero(ref):
        if isinstance(g_out.at[i, "playerid"], str):
            by_id.setdefault((g_out.at[i, "playerid"], g_out.at[i, "role"]), []).append(pkey[i])
    by_id = {k: max(set(v), key=v.count) for k, v in by_id.items()}
    rest = np.flatnonzero(~ref)
    own = [(g_out.at[i, "playerid"], g_out.at[i, "role"]) if isinstance(g_out.at[i, "playerid"], str)
           else ("name:" + str(g_out.at[i, "player"]), g_out.at[i, "role"]) for i in rest]
    latest = {k: g_out.at[i, "player"] for k, i in zip(own, rest)}          # rows are in date order: the last name wins
    for k, i in zip(own, rest):
        pkey[i] = by_id.get(k) or (latest[k], k[1], k[0])
    old = (ref & g_out["league"].isin([lg for lgs in YEARS[REFERENCE_YEAR]["BASELINE_GROUPS"].values() for lg in lgs]
                                      + INTERNATIONAL).to_numpy())
    first_old = dict.fromkeys(k for k, o in zip(pkey, old) if o)
    first_ref = dict.fromkeys(k for k, o in zip(pkey, ref) if o and k not in first_old)
    gy_ = g_out["year"].to_numpy()
    order = list(np.flatnonzero(gy_ >= KEEP_ORDER_FROM)) + [i for y in sorted(set(gy_[gy_ < KEEP_ORDER_FROM]), reverse=True)
                                                            for i in np.flatnonzero(gy_ == y)]
    players = list(first_old) + list(first_ref) + [k for k in dict.fromkeys(pkey[i] for i in order)
                                                    if k not in first_old and k not in first_ref]
    pidx = {k: i for i, k in enumerate(players)}
    g_out["pi"] = [pidx[k] for k in pkey]
    game_fields = GAME_FIELDS + ["pi"]

    years, files, pfiles = sorted(set(g_out["year"]) | set(tg["year"])), {}, [[] for _ in players]
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
    tl = tg.groupby("ti").agg(name=("team", "last"), home=("home", "last"), games=("ti", "size"),
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
        # the latest game in the data (not the build time, so a rebuild of the same data changes nothing)
        "data_until": tg["date"].max().strftime("%Y-%m-%d"),
        "note": "Performance rating relative to the games it is built from. Not a measure of skill or of league strength.",
        "config": {"leagues": leagues, "events": events,
                   # a league's tier in the latest year it played, and per year (tiers change: PCS was tier 1 in 2024)
                   "tiers": {lg: tier_of(lg, max(y for y in complete if lg in complete[y])) for lg in shown},
                   "tiers_by_year": {y: {lg: tier_of(lg, y) for lg in shown if lg in complete[y]} for y in years},
                   "names": {lg: LEAGUE_NAMES[lg] for lg in shown if lg in LEAGUE_NAMES},
                   # share of complete games (only leagues below 99.5%) per year; no complete games = no player ratings
                   "complete": {y: {lg: v for lg, v in complete[y].items() if lg in shown and v < 0.995} for y in years},
                   # tournament names for data split names (TOUR_NAMES): league -> {split: name}
                   "split_names": {lg: {sp: n for (_, l2, sp), n in TOUR_NAMES.items() if l2 == lg and n} for (_, lg, _), n0 in TOUR_NAMES.items() if n0},
                   "reference_year": REFERENCE_YEAR, "baseline_groups": YEARS[REFERENCE_YEAR]["BASELINE_GROUPS"],
                   "baseline_groups_by_year": {y: YEARS.get(y, YEARS[REFERENCE_YEAR])["BASELINE_GROUPS"] for y in years}, "international": INTERNATIONAL, "qualifiers": sorted(QUALIFIERS),
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
        "awards": {"fields": AWARD_FIELDS, "rows": awards(g_out, tg, tours, raw, c_by_role)},
        "elo": {k: v for k, v in elo_report.items() if k not in ("league_levels", "finals")} | {"league_levels": elo_report["league_levels"],
                "base": team_elo.BASE, "weights": team_elo.WEIGHT, "title_bonus": team_elo.TITLE,
                "decay": elo_report["decay"]},
    })


def main(pattern=FILES, out_dir=OUT_DIR, show_report=False):
    files = sorted(glob.glob(pattern), key=lambda f: (int(os.path.basename(f)[:4]) != REFERENCE_YEAR, f))
    cfg = dict(rc.CFG)
    parts, team_parts, player_rows, leagues, complete, c_ref, table = [], [], [], [], {}, None, None
    for csv in files:                       # REFERENCE_YEAR first: its c(role) is the scale for the other years
        y = int(os.path.basename(csv)[:4])
        use_year(y)
        print(f"===== {y}: {csv}")
        df = pd.read_csv(csv, low_memory=False)
        df["league"] = df["league"].replace(RENAME_LEAGUES)
        clean_year(df)
        for lg, m in MERGE_SPLITS.items():
            sel = df["league"] == lg
            df.loc[sel, "split"] = df.loc[sel, "split"].replace(m)
        for lg, rules in DATE_SPLITS.items():
            md = df["date"].str[5:10]
            for a, z, name in rules:
                df.loc[(df["league"] == lg) & (md >= a) & (md <= z), "split"] = name
        dom, intl, ev, lg_y = rate_baselines(df, cfg)
        games = pd.concat([tidy(dom, "domestic")] + [tidy(x, k) for x, k in [(intl, "international"), (ev, "event")] if x is not None],
                          ignore_index=True)
        games = games.sort_values("date", kind="stable").reset_index(drop=True)
        games = label_splits(games)
        print("rated player-games:", len(games), "| domestic:", int((games["kind"] == "domestic").sum()),
              "| international:", int((games["kind"] == "international").sum()), "| events:", int((games["kind"] == "event").sum()))
        print("splits per league:"); split_table(games)
        c_y = calibrate_c(games)
        if c_ref is None:
            if y != REFERENCE_YEAR:
                raise SystemExit(f"the {REFERENCE_YEAR} file (REFERENCE_YEAR) is missing")
            c_ref = c_y
        else:                               # put this year's game ratings on REFERENCE_YEAR's scale
            f = games["role"].map(lambda r: c_y[r] / c_ref[r])
            for c in ["r_early", "r_late", "r_overall"]:
                games[c] = (1 + (games[c] - 1) * f).round(6)
        if show_report and y == REFERENCE_YEAR:
            table = default_table(games, c_ref, lg_y)
            report(table, games, pd.concat([x for x in [dom, intl] if x is not None], ignore_index=True), cfg)
        t = df[df["position"] == "team"]
        complete[y] = (t.drop_duplicates("gameid").groupby("league")["datacompleteness"]
                       .agg(lambda s: round(float((s == "complete").mean()), 2))).to_dict()
        t_lg = lg_y + [lg for lg in team_leagues(df) if lg not in lg_y]
        leagues += [lg for lg in t_lg if lg not in leagues]
        events = [lg for lg in EVENTS if lg in set(t["league"])]
        team_parts.append(team_rows(df, games, t_lg, events, y))
        player_rows.append(df.loc[df["position"] != "team", ["gameid", "date", "teamid", "teamname", "playerid", "playername", "position"]])
        parts.append(games)
    use_year(REFERENCE_YEAR)
    games = pd.concat(parts, ignore_index=True).sort_values("date", kind="stable").reset_index(drop=True)
    os.makedirs(out_dir, exist_ok=True)
    table = default_table(games, c_ref, leagues)
    table.round(3).to_csv(os.path.join(out_dir, "players_default_view.csv"), index=False)
    raw = pd.concat(player_rows, ignore_index=True)
    tg, team_keys, elo_report = team_games(team_parts, new_starters(raw))
    print(f"team Elo: {len(team_keys)} teams, {elo_report['games']} games in {elo_report['series']} series, K {elo_report['k']}, "
          f"decay after {elo_report['decay'][0]} days, half-life {elo_report['decay'][1]} days, roster cut {elo_report['roster_cut']}, "
          f"series winner predicted {elo_report['accuracy']:.1%} (better series win rate so far: {elo_report['baseline_accuracy']:.1%})")
    print("best settings (log loss, K, grace, half-life, roster cut):", elo_report["grid"][:5])
    if show_report:
        team_report(tg, elo_report)
    tours = tournaments(tg, elo_report["finals"])
    links = tournament_links(tg, tours)
    print(f"tournaments: {len(tours)}, {int(tours['champ'].notna().sum())} with a champion, {len(links)} qualification links")
    write_site_data(games, c_ref, cfg, out_dir, leagues, complete, tg, team_keys, elo_report, tours, links, raw)
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
    import sys
    sys.stdout.reconfigure(encoding="utf-8")     # team names outside the Windows code page, when printing to a file
    ap = argparse.ArgumentParser(description="Build docs/data for the ratings site.")
    ap.add_argument("--csv", default=FILES, help="Oracle's Elixir match-data CSV(s), a pattern (default: every year)")
    ap.add_argument("--out", default=OUT_DIR, help="output folder (docs/data)")
    ap.add_argument("--report", action="store_true", help="print the top 10 per role and checks per baseline")
    a = ap.parse_args()
    main(a.csv, a.out, a.report)
