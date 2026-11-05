"""Champion icons from Riot's Data Dragon (allowed for fan projects under Riot's "Legal Jibber Jabber" policy),
stored small in docs/img/champions/<key>.webp, key = the champion name in lower case without spaces or
punctuation ("Kai'Sa" -> kaisa, "Nunu & Willump" -> nunuwillump). docs/img/champions.json lists the keys; the site
only shows icons for those, so a new champion without an icon is just its name.

    python fetch_images.py            download the champions that have no icon yet
    python fetch_images.py --force    download them all again (e.g. after an icon update)
"""
import argparse, io, json, os, re, urllib.request
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "img", "champions")
DDRAGON = "https://ddragon.leagueoflegends.com"
SIZE = 64          # shown at 20-32 px, 64 px keeps them sharp on high-DPI screens


def key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lol-ratings-site"}), timeout=60) as r:
        return r.read()


def main(force):
    version = json.loads(get(f"{DDRAGON}/api/versions.json"))[0]
    champs = json.loads(get(f"{DDRAGON}/cdn/{version}/data/en_US/champion.json"))["data"].values()
    os.makedirs(OUT, exist_ok=True)
    new = 0
    for c in champs:
        path = os.path.join(OUT, key(c["name"]) + ".webp")
        if os.path.exists(path) and not force:
            continue
        img = Image.open(io.BytesIO(get(f"{DDRAGON}/cdn/{version}/img/champion/{c['image']['full']}")))
        img.convert("RGB").resize((SIZE, SIZE), Image.LANCZOS).save(path, "WEBP", quality=82, method=6)
        new += 1
    keys = sorted(f[:-5] for f in os.listdir(OUT) if f.endswith(".webp"))
    with open(os.path.join(OUT, "..", "champions.json"), "w", encoding="utf-8") as f:
        json.dump(keys, f, separators=(",", ":"))
    print(f"Data Dragon {version}: {new} new icons, {len(keys)} in total")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="download every icon again")
    main(ap.parse_args().force)
