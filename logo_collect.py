"""Fetch the REAL mark of a named thing from online and keep it in the skill's logo library (<skill>/brand/logos/).

  python3 logo_collect.py add <slug> "<query>" [--kind brand|person|place|car|auto] [--domain example.com] [--no-cutout]
  python3 logo_collect.py add <slug> "<query>" --file "BMW.svg"        -> pin a specific Wikimedia Commons file (when the automatic pick is wrong)
  python3 logo_collect.py remove <slug>
  python3 logo_collect.py list
  python3 logo_collect.py sheet            -> brand/logos/sheet.png, every logo on a plate (look before you use)

The rule it serves: when a reel names a brand, a product, a car, a famous person, a city, a state or a country, the on-screen element
is the ORIGINAL logo / flag / emblem / official portrait, never an emoji or a generic icon. Sources, in order:
  1. Wikidata -> Wikimedia Commons: logo image (P154), flag (P41), coat of arms (P94), image (P18). Vector SVG whenever it exists.
  2. Wikimedia Commons file search "<query> logo" (SVG first).
  3. Simple Icons CDN (official brand shape in the brand colour, SVG).
  4. The brand's own site (--domain): <link rel=icon type=image/svg+xml>, then og:image.
Raster files must be >= 800 px on the long side (ultra-HD rule); smaller ones are rejected. Portraits of people are cut out with the
Apple Vision person segmenter (bin/segment) so they sit on a plate without a background. Everything lands in INDEX.json with its source
URL, so attribution and licence can be checked (Commons files carry their licence on the file page)."""
import json, pathlib, re, subprocess, sys, urllib.parse, urllib.request, shutil, tempfile

HERE = pathlib.Path(__file__).parent
LIB = HERE / "brand" / "logos"; LIB.mkdir(parents=True, exist_ok=True)
INDEX = LIB / "INDEX.json"
UA = "reel-overlay/1.0 (https://github.com/tcipher/reel-overlay; editorial B-roll collector)"
MIN_RASTER = 800
PROPS = dict(brand=["P154", "P18"], car=["P154", "P18"], person=["P18"], place=["P41", "P94", "P18"], auto=["P154", "P41", "P18"])

def get(url, binary=False, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(); return data if binary else data.decode("utf-8", "replace")

def jget(url): return json.loads(get(url))

def load(): return json.loads(INDEX.read_text()) if INDEX.exists() else {}
def save(ix): INDEX.write_text(json.dumps(ix, indent=1, ensure_ascii=False))

def dims(f):
    """(w, h) of a raster or SVG file."""
    f = pathlib.Path(f)
    if f.suffix == ".svg":
        t = f.read_text(errors="replace")
        m = re.search(r"viewBox=['\"]\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)", t)
        if m: return float(m.group(1)), float(m.group(2))
        w = re.search(r"<svg[^>]*\swidth=['\"]([\d.]+)", t); h = re.search(r"<svg[^>]*\sheight=['\"]([\d.]+)", t)
        return (float(w.group(1)), float(h.group(1))) if w and h else (1.0, 1.0)
    out = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(f)], capture_output=True, text=True).stdout
    g = dict(re.findall(r"(pixelWidth|pixelHeight): (\d+)", out)); return int(g.get("pixelWidth", 0)), int(g.get("pixelHeight", 0))

def wikidata_candidates(query, kind):
    r = jget("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=en&limit=6&search=" + urllib.parse.quote(query))
    bad = ("book", "podcast", "episode", "film", "album", "song", "history of", "criticism of", "disambiguation", "family name", "given name")
    want = dict(brand=("company", "software", "brand", "corporation", "platform", "service", "manufacturer", "product", "tool", "website", "application",
                       "chatbot", "model", "business", "enterprise", "search engine", "operating system", "app"),
                car=("car", "automobile", "vehicle", "manufacturer", "automaker", "marque", "brand", "company"),
                place=("country", "state", "city", "region", "province", "capital", "territory", "island", "continent", "municipality", "town"),
                person=(), auto=())
    out = []
    for e in r.get("search", []):
        d = e.get("description", "").lower()
        if any(b in d for b in bad): continue
        if want[kind] and not any(w in d for w in want[kind]): continue   # "Moz" must not resolve to Mozambique for a brand
        norm = lambda s: re.sub(r"\s+", " ", re.sub(r"\(.*?\)|,? ?(inc|ltd|llc|corp|corporation|company|co)\.?$|[^a-z0-9 ]", "", s.lower())).strip()
        lab, q, hit = norm(e.get("label", "")), norm(query), norm(e.get("match", {}).get("text", ""))
        if lab == q or hit == q: out.append(e["id"])   # exact label or alias only: "Moz" is neither Mozambique nor Mozilla
    return out

def wikidata_files(qid, props):
    r = jget(f"https://www.wikidata.org/w/api.php?action=wbgetclaims&format=json&entity={qid}")
    out = []
    for p in props:
        for c in r.get("claims", {}).get(p, []):
            v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(v, str): out.append((p, v, c.get("rank", "normal")))
    # preferred rank first, then SVG before raster, keeping the property order
    out.sort(key=lambda x: (props.index(x[0]), 0 if x[2] == "preferred" else 1, 0 if x[1].lower().endswith(".svg") else 1))
    return out

def commons_search(query):
    r = jget("https://commons.wikimedia.org/w/api.php?action=query&list=search&format=json&srnamespace=6&srlimit=12&srsearch=" + urllib.parse.quote(f"{query} logo"))
    titles = [h["title"].split(":", 1)[1] for h in r.get("query", {}).get("search", [])]
    q = query.lower().split()[0]
    good = [t for t in titles if t.lower().startswith(q) and "logo" in t.lower() and not t.lower().endswith((".pdf", ".djvu", ".webp"))]   # "Sunsedraft logo with Canva" is not Canva's logo
    good.sort(key=lambda t: 0 if t.lower().endswith(".svg") else 1); return good

def fetch_commons(title, dest):
    url = "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(title.replace(" ", "_"))
    data = get(url, binary=True); dest.write_bytes(data); return url

def site_logo(domain, dest_base):
    html = get(f"https://{domain}/")
    for pat in (r"<link[^>]*rel=['\"]icon['\"][^>]*type=['\"]image/svg\+xml['\"][^>]*href=['\"]([^'\"]+)",
                r"<link[^>]*href=['\"]([^'\"]+\.svg[^'\"]*)['\"][^>]*rel=['\"](?:icon|mask-icon)['\"]",
                r"<link[^>]*rel=['\"](?:icon|mask-icon)['\"][^>]*href=['\"]([^'\"]+\.svg[^'\"]*)",
                r"<meta[^>]*property=['\"]og:image['\"][^>]*content=['\"]([^'\"]+)"):
        m = re.search(pat, html, re.I)
        if m:
            url = urllib.parse.urljoin(f"https://{domain}/", m.group(1)); ext = ".svg" if ".svg" in url.lower() else (".jpg" if ".jp" in url.lower() else ".png")
            dest = dest_base.with_suffix(ext); dest.write_bytes(get(url, binary=True)); return url, dest
    return None, None

def cutout(src, dest):
    """Transparent PNG of the person in `src` via bin/segment (Apple Vision)."""
    seg = HERE / "bin" / "segment"
    if not seg.exists(): print("  no bin/segment, keeping the plain photo"); return False
    tmp = pathlib.Path(tempfile.mkdtemp()); mp4 = tmp / "p.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(src), "-t", "1", "-r", "1", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p", str(mp4)], check=True)
    subprocess.run([str(seg), str(mp4), "0", "1", "1", str(tmp / "m"), "1", "accurate"], check=True, capture_output=True)
    matte = tmp / "m" / "00000.png"
    if not matte.exists(): shutil.rmtree(tmp, ignore_errors=True); return False
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(matte), "-filter_complex",
                    "[0]format=rgba[a];[1]format=gray[m];[m][a]scale2ref[m2][a2];[a2][m2]alphamerge,format=rgba", "-frames:v", "1", str(dest)], check=True)
    shutil.rmtree(tmp, ignore_errors=True); return True

def accept(f, kind):
    w, h = dims(f)
    if f.suffix != ".svg" and max(w, h) < MIN_RASTER: print(f"  {f.name}: {w}x{h} too small (< {MIN_RASTER}px), rejected"); f.unlink(); return None
    return dict(width=w, height=h, vector=f.suffix == ".svg")

def remove(slug):
    ix = load(); e = ix.pop(slug, None)
    for f in list(LIB.glob(slug + ".*")) + list(LIB.glob(slug + "_cutout.*")): f.unlink()
    save(ix); print(f"{slug}: removed" if e else f"{slug}: not in the library")

def add(slug, query, kind="auto", domain=None, do_cutout=True, pin=None):
    ix = load(); base = LIB / slug
    for old in list(LIB.glob(slug + ".*")) + list(LIB.glob(slug + "_cutout.*")): old.unlink()
    tried = []
    def done(f, source, url, extra=None):
        meta = accept(f, kind)
        if not meta: return False
        entry = dict(slug=slug, query=query, kind=kind, file=f.name, source=source, url=url, **meta)
        if extra: entry.update(extra)
        if kind == "person" and do_cutout and f.suffix != ".svg":
            cut = LIB / f"{slug}_cutout.png"
            if cutout(f, cut): entry["cutout"] = cut.name; print(f"  cutout: {cut.name}")
        ix[slug] = entry; save(ix); print(f"{slug}: {f.name} {int(meta['width'])}x{int(meta['height'])} from {source}  {url}"); return True
    props = PROPS[kind]
    if pin:   # a hand-picked Commons file
        f = base.with_suffix(pathlib.Path(pin).suffix.lower()); url = fetch_commons(pin, f)
        return done(f, "commons-pinned", url)
    try:
        for qid in wikidata_candidates(query, kind)[:3]:
            for p, title, _ in wikidata_files(qid, props):
                ext = pathlib.Path(title).suffix.lower() or ".png"; f = base.with_suffix(ext); tried.append(f"wikidata {qid} {p} {title}")
                try: url = fetch_commons(title, f)
                except Exception as e: print(f"  {title}: {e}"); continue
                if done(f, f"wikidata:{qid}:{p}", url): return True
    except Exception as e: print(f"  wikidata: {e}")
    if kind in ("brand", "car", "auto"):
        try:
            for title in commons_search(query)[:4]:
                f = base.with_suffix(pathlib.Path(title).suffix.lower()); tried.append(f"commons {title}")
                try: url = fetch_commons(title, f)
                except Exception as e: print(f"  {title}: {e}"); continue
                if done(f, "commons-search", url): return True
        except Exception as e: print(f"  commons: {e}")
        si = re.sub(r"[^a-z0-9]", "", query.lower()); tried.append(f"simpleicons {si}")
        try:
            data = get(f"https://cdn.simpleicons.org/{si}", binary=True); f = base.with_suffix(".svg"); f.write_bytes(data)
            if done(f, "simpleicons", f"https://cdn.simpleicons.org/{si}", dict(mono=True)): return True
        except Exception: pass
    if domain:
        tried.append(f"site {domain}")
        try:
            url, f = site_logo(domain, base)
            if f and done(f, "site", url): return True
        except Exception as e: print(f"  site: {e}")
    print(f"{slug}: nothing usable online. Tried: " + "; ".join(tried)); return False

def sheet():
    import base64
    from playwright.sync_api import sync_playwright
    ix = load(); cells = ""
    for s, e in sorted(ix.items()):
        f = LIB / e.get("cutout", e["file"]); mime = "image/svg+xml" if f.suffix == ".svg" else ("image/jpeg" if f.suffix in (".jpg", ".jpeg") else "image/png")
        uri = f"data:{mime};base64," + base64.b64encode(f.read_bytes()).decode()
        cells += f"<div class='c'><div class='p'><img src='{uri}'></div><span>{s}<br><small>{e['source']} {int(e['width'])}x{int(e['height'])}</small></span></div>"
    html = ("<html><body style='margin:0;background:#2b2b2b;font-family:-apple-system;color:#ddd;display:flex;flex-wrap:wrap;gap:18px;padding:18px;width:1164px'>"
            "<style>.c{width:270px;text-align:center;font-size:13px}.p{height:170px;background:linear-gradient(160deg,rgba(255,255,255,.55),rgba(255,255,255,.18));"
            "border-radius:28px;display:flex;align-items:center;justify-content:center;padding:22px;box-sizing:border-box}img{max-width:100%;max-height:100%}small{color:#999}</style>" + cells + "</body></html>")
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        pg = br.new_page(viewport={"width": 1200, "height": 800}); pg.set_content(html); pg.wait_for_timeout(600)
        pg.screenshot(path=LIB / "sheet.png", full_page=True); br.close()
    print("sheet:", LIB / "sheet.png")

def main(argv):
    if not argv: sys.exit(__doc__)
    if argv[0] == "list":
        for s, e in sorted(load().items()): print(f"{s:24} {e['file']:34} {int(e['width'])}x{int(e['height'])} {e['kind']:6} {e['source']}")
    elif argv[0] == "sheet": sheet()
    elif argv[0] == "remove": remove(argv[1])
    elif argv[0] == "add":
        a = argv[1:]; kind = "auto"; domain = None; cut = True; pin = None
        if "--file" in a: i = a.index("--file"); pin = a[i + 1]; del a[i:i + 2]
        if "--kind" in a: i = a.index("--kind"); kind = a[i + 1]; del a[i:i + 2]
        if "--domain" in a: i = a.index("--domain"); domain = a[i + 1]; del a[i:i + 2]
        if "--no-cutout" in a: a.remove("--no-cutout"); cut = False
        if len(a) < 2: sys.exit(__doc__)
        ok = add(a[0], a[1], kind, domain, cut, pin); sys.exit(0 if ok else 1)
    else: sys.exit(__doc__)

if __name__ == "__main__": main(sys.argv[1:])
