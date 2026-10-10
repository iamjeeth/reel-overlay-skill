"""Build the skill's FX overlay collection from Pixabay videos (Pixabay Content License, free for commercial use).
Green-screen and black-background clips that composite over footage: falling money, confetti, light leaks, film burns,
sparkles, smoke, fire, rain, bokeh, dust, particles, arrows. The renderer keys them (`fx()` helper).

  python3 pixabay_fx.py              # ~4 clips per category into <skill>/fx/<category>/, index in fx/INDEX.json
  python3 pixabay_fx.py money 6      # one category, N clips

Drives the installed Chrome (Pixabay sits behind Cloudflare), reads the page's own bootstrap JSON, downloads the medium mp4."""
import json, pathlib, re, sys, time, urllib.parse
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
LIB = HERE / "fx"
# category: (queries, key) key = green (chroma key), screen (black background, blend screen), alpha (already transparent)
CATS = {
    "money":     (["green screen money falling", "falling dollars green screen", "cash rain green screen"], "green"),
    "confetti":  (["green screen confetti", "confetti black background", "confetti explosion green screen"], "green"),
    "leak":      (["light leak overlay", "light leaks black background", "lens flare overlay black"], "screen"),
    "burn":      (["film burn transition", "film burn overlay", "old film transition"], "screen"),
    "sparkle":   (["sparkles black background", "glitter particles black background", "bokeh particles black"], "screen"),
    "smoke":     (["smoke black background", "fog overlay black background"], "screen"),
    "fire":      (["fire black background", "flames green screen"], "screen"),
    "rain":      (["rain overlay black background", "rain green screen"], "screen"),
    "dust":      (["dust particles black background", "floating particles overlay"], "screen"),
    "arrow":     (["arrow green screen", "pointing arrow animation green screen"], "green"),
    "check":     (["check mark green screen", "tick animation green screen"], "green"),
    "like":      (["like button green screen", "subscribe green screen", "follow button green screen"], "green"),
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]

def collect(cats, per):
    LIB.mkdir(exist_ok=True); index = json.loads((LIB / "INDEX.json").read_text()) if (LIB / "INDEX.json").exists() else {}
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = br.new_context(viewport={"width": 1280, "height": 900}, user_agent=UA); pg = ctx.new_page()
        for cat in cats:
            queries, key = CATS[cat]; have = [k for k, v in index.items() if v["cat"] == cat and (LIB / cat / v["file"]).exists()]
            seen = set(index); cands = []
            for q in queries:
                try:
                    pg.goto(f"https://pixabay.com/videos/search/{urllib.parse.quote(q)}/", wait_until="domcontentloaded"); pg.wait_for_timeout(2500)
                    u = pg.evaluate("window.__BOOTSTRAP_URL__")
                    if not u: print(f"  {q}: no bootstrap url"); continue
                    d = json.loads(pg.evaluate("async u => (await fetch(u, {credentials:'include'})).text()", u))
                except Exception as e: print(f"  {q}: {e}"); continue
                kw = [w for w in q.lower().split() if w not in ("green", "screen", "black", "background", "overlay", "animation", "transition")]
                for r in d.get("page", {}).get("results", []):
                    if r.get("mediaType") != "video" or r.get("isAiGenerated") or not 3 <= r.get("duration", 0) <= 40: continue
                    desc = (r.get("name", "") + " " + r.get("description", "")).lower()
                    if not any(k in desc for k in kw): continue                                   # on topic
                    if key == "green" and "green" not in desc and "chroma" not in desc: continue
                    if key == "screen" and not any(w in desc for w in ("black", "overlay", "dark", "transition", "leak", "burn", "particle", "bokeh", "flare")): continue
                    if str(r["id"]) in seen or not r.get("sources", {}).get("mp4"): continue
                    seen.add(str(r["id"])); cands.append((r.get("likeCount", 0), r))
            cands.sort(key=lambda c: -c[0]); need = max(0, per - len(have))
            print(f"{cat}: {len(have)} present, {len(cands)} candidates, downloading {min(need, len(cands))}"); (LIB / cat).mkdir(exist_ok=True)
            for likes, r in cands[:need]:
                fn = f"{slug(r.get('name') or cat)}-{r['id']}.mp4"; dst = LIB / cat / fn
                try:
                    resp = ctx.request.get(r["sources"]["mp4"].replace("_tiny.mp4", "_small.mp4"), headers={"Referer": "https://pixabay.com/"})   # CDN 'small' (~960p), no login
                    if resp.status != 200 or len(resp.body()) < 100_000: print("   skip", fn, resp.status); continue
                    dst.write_bytes(resp.body())
                except Exception as e: print("   fail", fn, e); continue
                index[str(r["id"])] = dict(cat=cat, key=key, file=fn, name=r.get("name", ""), duration=r["duration"], likes=likes, tags=r.get("description", ""),
                                           page="https://pixabay.com" + r.get("href", ""))
                print(f"   + {fn} ({r['duration']}s, {likes} likes)"); time.sleep(.5)
            (LIB / "INDEX.json").write_text(json.dumps(index, indent=1))
        br.close()
    print("total fx clips:", sum(1 for v in index.values() if (LIB / v["cat"] / v["file"]).exists()))

if __name__ == "__main__":
    if len(sys.argv) > 1: collect([sys.argv[1]], int(sys.argv[2]) if len(sys.argv) > 2 else 4)
    else: collect(list(CATS), 4)
