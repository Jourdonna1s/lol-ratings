"""Download the Oracle's Elixir match-data CSVs of the years in data_sources.json into pipeline/.

    python fetch_data.py                 every year in data_sources.json
    python fetch_data.py --cache DIR     past years are kept in DIR and copied from there when present
                                         (the current year is always downloaded fresh)

Used by the Update data GitHub Action (.github/workflows/update-data.yml). The CSVs are never committed.

Signed in (GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN set, from drive_auth.py): the Drive API is
used, and a file that Drive refuses ("too many users have downloaded this file") is copied into the signed-in
account's Drive, downloaded from there and deleted again. Without them: gdown, as an anonymous visitor.
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


API = "https://www.googleapis.com/drive/v3/files"
_token = None


def signed_in():
    return all(os.environ.get(k) for k in ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN"))


def _auth():
    """Authorization header from the refresh token (one access token per run; they last an hour)."""
    global _token
    if _token is None:
        import requests
        r = requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
            "client_id": os.environ["GDRIVE_CLIENT_ID"], "client_secret": os.environ["GDRIVE_CLIENT_SECRET"],
            "refresh_token": os.environ["GDRIVE_REFRESH_TOKEN"], "grant_type": "refresh_token"})
        if r.status_code != 200:
            sys.exit(f"Google sign-in failed ({r.status_code}): {r.text[:300]} (new refresh token: drive_auth.py)")
        _token = r.json()["access_token"]
    return {"Authorization": f"Bearer {_token}"}


def _api_error(r):
    try:
        e = r.json()["error"]
        return f"{r.status_code} {', '.join(x.get('reason', '') for x in e.get('errors', []))}: {e.get('message', '')}"[:300]
    except Exception:
        return f"{r.status_code}: {r.text[:300]}"


def _get(file_id, tmp):
    """Download a Drive file with the API; returns None, or the error when Drive refused it."""
    import requests
    with requests.get(f"{API}/{file_id}", params={"alt": "media", "supportsAllDrives": "true"},
                      headers=_auth(), stream=True, timeout=300) as r:
        if r.status_code != 200:
            return _api_error(r)
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return None


def api_download(file_id, path):
    """Signed-in download; when Drive refuses the file, a server-side copy in the account's own Drive is
    downloaded instead and deleted right after (a copy is a new file, outside the original's download limit)."""
    import requests
    tmp = path + ".part"
    err = _get(file_id, tmp)
    if err:
        print(f"  direct download refused ({err}); downloading a copy")
        r = requests.post(f"{API}/{file_id}/copy", params={"supportsAllDrives": "true", "fields": "id"},
                          json={"name": "oe-temp-" + os.path.basename(path)}, headers=_auth(), timeout=300)
        if r.status_code != 200:
            sys.exit(f"copy of Drive file {file_id} failed: {_api_error(r)}")
        copy = r.json()["id"]
        try:
            err = _get(copy, tmp)
        finally:
            d = requests.delete(f"{API}/{copy}", headers=_auth(), timeout=60)     # permanent, skips the trash
            if d.status_code not in (200, 204):
                print(f"  warning: could not delete the temporary copy {copy}: {_api_error(d)}")
        if err:
            sys.exit(f"download of the copy of Drive file {file_id} failed: {err}")
    check(tmp)
    os.replace(tmp, path)


def download(file_id, path):
    if signed_in():
        return api_download(file_id, path)
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
    if signed_in():
        import requests
        files, page = {}, None
        while True:
            r = requests.get(API, headers=_auth(), timeout=60, params={
                "q": f"'{folder}' in parents and trashed = false", "fields": "nextPageToken, files(id, name)",
                "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                **({"pageToken": page} if page else {})})
            if r.status_code != 200:
                sys.exit(f"listing Drive folder {folder} failed: {_api_error(r)}")
            files.update({f["name"]: f["id"] for f in r.json().get("files", [])})
            page = r.json().get("nextPageToken")
            if not page:
                return files
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
    failed = []
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
            # a past year can fall back to an older cached copy; the current year has to come through.
            # The other years are still tried, so the ones that come through are cached for the next run.
            old = sorted(glob.glob(os.path.join(cache, f"{year}_*.csv")), key=os.path.getmtime) if cached else []
            if not old:
                print(f"{year}: {e}")
                failed.append(year)
                continue
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
    if failed:
        sys.exit(f"no file for {', '.join(map(str, failed))}"
                 + ("" if signed_in() else " (anonymous download: set the GDRIVE_* secrets, see drive_auth.py)"))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", help="folder that keeps past years' files between runs")
    main(ap.parse_args().cache)
