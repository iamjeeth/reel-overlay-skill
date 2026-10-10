"""Real stock footage and photos from Pixabay without an API key (Pixabay Content License: free for commercial use, no attribution).

  python3 pixabay_stock.py video "developer coding at night" out_dir [pick] [--landscape]
  python3 pixabay_stock.py photo "startup team office" out_dir [pick]

Drives the installed Chrome (Pixabay is behind Cloudflare) and reads the page's own bootstrap JSON, like the music/fx collectors.
Vertical results first (9:16 reels). Videos: the CDN 'medium' rendition (~1080p); photos: the 1280 px rendition. Filters out
AI-generated media. Cached by query in out_dir; also importable: fetch(query, kind, dest, pick, vertical)."""
import json, pathlib, re, sys, urllib.parse

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]

def fetch(query, kind="video", dest=".", pick=0, vertical=True, min_duration=4, _ctx=None):
    """Returns the local path of the pick-th result (downloads once). kind: video | photo."""
    dest = pathlib.Path(dest).expanduser(); dest.mkdir(parents=True, exist_ok=True)
    ext = ".mp4" if kind == "video" else ".jpg"; out = dest / f"{slug(query)}_{'v' if vertical else 'h'}_{pick}{ext}"
    meta = out.with_suffix(".json")
    if out.exists() and out.stat().st_size > 50_000: return out
    from playwright.sync_api import sync_playwright
    def run(ctx):
        pg = ctx.new_page()
        base = "videos" if kind == "video" else "photos"
        url = f"https://pixabay.com/{base}/search/{urllib.parse.quote(query)}/" + ("?orientation=vertical" if vertical else "?orientation=horizontal")
        pg.goto(url, wait_until="domcontentloaded"); pg.wait_for_timeout(2500)
        u = pg.evaluate("window.__BOOTSTRAP_URL__")
        if not u: raise RuntimeError("no bootstrap url (Cloudflare challenge?)")
        d = json.loads(pg.evaluate("async u => (await fetch(u, {credentials:'include'})).text()", u))
        res = [r for r in d.get("page", {}).get("results", []) if not r.get("isAiGenerated")]
        if kind == "video": res = [r for r in res if r.get("duration", 0) >= min_duration and r.get("sources", {}).get("mp4")]
        else: res = [r for r in res if r.get("sources", {}).get("2x")]
        # relevance: Pixabay's vertical ranking is loose, so prefer results whose name/tags share words with the query
        kw = [w for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 2 and w not in ("the", "and", "with", "close", "night")]
        def score(r): tx = (str(r.get("name", "")) + " " + str(r.get("description", ""))).lower(); return sum(k in tx for k in kw)
        ranked = sorted(res, key=lambda r: -score(r)); good = [r for r in ranked if score(r) > 0]
        if len(good) <= pick and vertical:   # the vertical pool is thin: fall back to landscape (windows cover-crop it)
            pg.goto(url.replace("orientation=vertical", "orientation=horizontal"), wait_until="domcontentloaded"); pg.wait_for_timeout(2500)
            u2 = pg.evaluate("window.__BOOTSTRAP_URL__"); d2 = json.loads(pg.evaluate("async u => (await fetch(u, {credentials:'include'})).text()", u2))
            res2 = [r for r in d2.get("page", {}).get("results", []) if not r.get("isAiGenerated") and (kind != "video" or r.get("duration", 0) >= min_duration)]
            good = good + sorted([r for r in res2 if score(r) > 0], key=lambda r: -score(r))
        if len(good) <= pick: raise RuntimeError(f"stock '{query}' ({kind}): no relevant results")
        r = good[pick]
        src = r["sources"]["mp4"].replace("_tiny.mp4", "_large.mp4") if kind == "video" else r["sources"]["2x"]   # 'large' = the 4K rendition when the clip has one (ultra-HD rule); falls back to 'medium' below
        resp = ctx.request.get(src, headers={"Referer": "https://pixabay.com/"}, timeout=120000)
        if kind == "video":   # rendition ladder: large (4K) -> medium (~1080p) -> small; the report flags anything under 4K as half-screen only
            for rend in ("_medium.mp4", "_small.mp4"):
                if resp.status == 200 and len(resp.body()) >= 50_000: break
                src = r["sources"]["mp4"].replace("_tiny.mp4", rend); resp = ctx.request.get(src, headers={"Referer": "https://pixabay.com/"}, timeout=120000)
        if resp.status != 200: raise RuntimeError(f"download failed {resp.status}")
        out.write_bytes(resp.body())
        meta.write_text(json.dumps(dict(query=query, kind=kind, name=r.get("name"), tags=r.get("description"), duration=r.get("duration"),
                                        width=r.get("width"), height=r.get("height"), page="https://pixabay.com" + r.get("href", ""), src=src), indent=1))
        pg.close(); print(f"  stock: {query} -> {out.name} ({r.get('name', '')[:40]})")
    if _ctx: run(_ctx)
    else:
        with sync_playwright() as p:
            br = p.chromium.launch(executable_path=CHROME, headless=False, args=["--disable-blink-features=AutomationControlled"])
            ctx = br.new_context(viewport={"width": 1280, "height": 900}, user_agent=UA); run(ctx); br.close()
    return out

def fetch_many(items, dest):
    """items: [(query, kind, pick), ...] in one browser session."""
    from playwright.sync_api import sync_playwright
    outs = []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = br.new_context(viewport={"width": 1280, "height": 900}, user_agent=UA)
        for q, kind, pick in items:
            try: outs.append(fetch(q, kind, dest, pick, _ctx=ctx))
            except Exception as e: print(f"  stock '{q}': {e}"); outs.append(None)
        br.close()
    return outs

if __name__ == "__main__":
    kind, q, dest = sys.argv[1], sys.argv[2], sys.argv[3]; pick = int(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4].isdigit() else 0
    print(fetch(q, kind, dest, pick, vertical="--landscape" not in sys.argv))
