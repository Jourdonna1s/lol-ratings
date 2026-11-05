"""Download the Oracle's Elixir match-data CSVs of the years in data_sources.json into pipeline/.

    python fetch_data.py                 every year in data_sources.json
    python fetch_data.py --cache DIR     past years are kept in DIR and copied from there when present
                                         (the current year is always downloaded fresh)

Used by the Update data GitHub Action (.github/workflows/update-data.yml). The CSVs are never committed.
"""
import argparse, glob, json, os, shutil, sys
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


def folder_files(folder):
    """{file name: Drive file id} of the files in Oracle's Elixir's Drive folder."""
    import gdown
    try:
        files = gdown.download_folder(id=folder, skip_download=True, quiet=True)
    except Exception as e:
        sys.exit(f"listing Drive folder {folder} failed: {' '.join(l.strip() for l in str(e).splitlines() if l.strip())[:300]}")
    return {os.path.basename(f.path): f.id for f in files or []}


def main(cache):
    with open(os.path.join(HERE, "data_sources.json"), encoding="utf-8") as f:
        src = json.load(f)
    ids = folder_files(src["folder"])
    missing = [y for y in src["years"] if NAME.format(y) not in ids]
    if missing:
        sys.exit(f"not in the Drive folder: {', '.join(NAME.format(y) for y in missing)}")
    current = max(datetime.now(timezone.utc).year, max(src["years"]))   # a new year's file stays "current" until it ends
    for year in sorted(src["years"]):
        file_id, path = ids[NAME.format(year)], os.path.join(HERE, NAME.format(year))
        # past years: cached as <year>_<file id>.csv (a new upload of the file gets a new id and is downloaded again)
        cached = os.path.join(cache, f"{year}_{file_id}.csv") if cache and year < current else None
        if cached and os.path.exists(cached):
            check(cached)
            shutil.copyfile(cached, path)
            print(f"{year}: from cache")
            continue
        try:
            download(file_id, path)
        except SystemExit as e:
            # Drive's limit for popular files ("Too many users have viewed or downloaded this file recently"):
            # a past year can fall back to an older cached copy; the current year has to come through
            old = sorted(glob.glob(os.path.join(cache, f"{year}_*.csv")), key=os.path.getmtime) if cached else []
            if not old:
                raise
            print(f"{year}: {e}; using the cached copy {os.path.basename(old[-1])}")
            check(old[-1])
            shutil.copyfile(old[-1], path)
            continue
        if cached:
            os.makedirs(cache, exist_ok=True)
            for f in glob.glob(os.path.join(cache, f"{year}_*.csv")):     # older uploads of the same year
                os.remove(f)
            shutil.copyfile(path, cached)
        print(f"{year}: downloaded, {os.path.getsize(path) / 1e6:.1f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", help="folder that keeps past years' files between runs")
    main(ap.parse_args().cache)
