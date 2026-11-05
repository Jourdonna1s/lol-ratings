"""Download the Oracle's Elixir match-data CSVs listed in data_sources.json into pipeline/.

    python fetch_data.py                 every year with a file id
    python fetch_data.py --cache DIR     past years are kept in DIR and copied from there when present
                                         (the current year is always downloaded fresh)

Used by the Update data GitHub Action (.github/workflows/update-data.yml). The CSVs are never committed.
"""
import argparse, json, os, shutil, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "{}_LoL_esports_match_data_from_OraclesElixir.csv"
NEEDED = {"gameid", "datacompleteness", "league", "date", "position", "playerid", "teamid", "result"}


def check(path):
    """Fail unless path is an Oracle's Elixir CSV (Drive sends an HTML page when a download is refused)."""
    if os.path.getsize(path) < 1_000_000:
        sys.exit(f"{path}: only {os.path.getsize(path)} bytes, not a match-data file")
    with open(path, encoding="utf-8", errors="replace") as f:
        cols = set(f.readline().strip().split(","))
    if not NEEDED <= cols:
        sys.exit(f"{path}: not an Oracle's Elixir CSV (missing columns {sorted(NEEDED - cols)})")


def download(file_id, path):
    import gdown
    tmp = path + ".part"
    try:
        ok = gdown.download(id=file_id, output=tmp, quiet=True)
    except Exception as e:      # gdown raises on a wrong id, a private file or Drive's download limit
        sys.exit(f"download of Drive file {file_id} failed: {' '.join(l.strip() for l in str(e).splitlines() if l.strip())[:300]}")
    if not ok:
        sys.exit(f"download of Drive file {file_id} failed")
    check(tmp)
    os.replace(tmp, path)


def main(cache):
    with open(os.path.join(HERE, "data_sources.json"), encoding="utf-8") as f:
        sources = {int(y): i for y, i in json.load(f).items() if not y.startswith("_") and i}
    if not sources:
        sys.exit("no file ids in data_sources.json")
    current = max(datetime.now(timezone.utc).year, max(sources))   # a new year's file stays "current" until it ends
    for year, file_id in sorted(sources.items()):
        path = os.path.join(HERE, NAME.format(year))
        cached = os.path.join(cache, f"{file_id}.csv") if cache and year < current else None
        if cached and os.path.exists(cached):
            check(cached)
            shutil.copyfile(cached, path)
            print(f"{year}: from cache")
            continue
        download(file_id, path)
        if cached:
            os.makedirs(cache, exist_ok=True)
            shutil.copyfile(path, cached)
        print(f"{year}: downloaded, {os.path.getsize(path) / 1e6:.1f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", help="folder that keeps past years' files between runs")
    main(ap.parse_args().cache)
