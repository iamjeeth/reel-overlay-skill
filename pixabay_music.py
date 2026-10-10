"""Build / refresh the skill's music collection from Pixabay (Pixabay Content License: free for commercial use, no attribution required).

  python3 pixabay_music.py            # ~10 tracks per mood into <skill>/music/<mood>/, index in music/INDEX.json
  python3 pixabay_music.py tech 15    # one mood, N tracks

Drives the installed Chrome (non-headless, Pixabay sits behind Cloudflare) and reads the page's own bootstrap JSON, so no API key.
Filters: music only, 45-240 s, not AI-generated, no YouTube Content ID (so uploads don't get claimed), editors' choice / most liked first.
The renderer picks from these by mood (see overlay.py music_bed); drop your own tracks in the same folders to extend the set."""
import json, pathlib, re, sys, time, urllib.parse
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
LIB = HERE / "music"
QUERIES = {
    "trailer":   ["epic cinematic trailer", "cinematic trailer hit", "epic hybrid trailer", "dark epic cinematic", "trailer tension", "cinematic action", "epic percussion"],
    "hiphop":    ["dark trap beat", "cinematic hip hop", "trap instrumental", "drill beat dark", "hip hop beat hard", "phonk", "boom bap"],
    "upbeat":    ["upbeat hip hop", "energetic trap", "upbeat funk", "energetic pop", "summer upbeat", "sport energetic", "fashion house"],
    "tech":      ["technology", "electronic minimal", "future bass", "tech house", "synthwave", "deep house", "cyberpunk"],
    "lofi":      ["lofi chill", "chill hop", "lofi study", "jazz hop", "chill beats", "lofi piano", "relaxing beat"],
    "cinematic": ["cinematic inspiring", "ambient piano", "epic emotional", "inspirational cinematic", "orchestral", "emotional piano", "hopeful cinematic"],
    "dramatic":  ["dark cinematic", "suspense tension", "trailer dramatic", "dark ambient", "epic trailer", "thriller", "mysterious dark"],
}
PAGES = 2
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]

def collect(moods, per):
    LIB.mkdir(exist_ok=True); index = json.loads((LIB / "INDEX.json").read_text()) if (LIB / "INDEX.json").exists() else {}
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = br.new_context(viewport={"width": 1280, "height": 900}, user_agent=UA); pg = ctx.new_page()
        for mood in moods:
            have = [k for k, v in index.items() if v["mood"] == mood and (LIB / mood / v["file"]).exists()]
            seen = set(index); cands = []
            for q in QUERIES[mood]:
              for page in range(1, PAGES + 1):
                if len(cands) >= per * 3: break
                pg.goto(f"https://pixabay.com/music/search/{urllib.parse.quote(q)}/" + (f"?pagi={page}" if page > 1 else ""), wait_until="domcontentloaded"); pg.wait_for_timeout(2200)
                u = pg.evaluate("window.__BOOTSTRAP_URL__")
                if not u: print(f"  {q}: no bootstrap url (blocked?)"); continue
                d = json.loads(pg.evaluate("async u => (await fetch(u, {credentials:'include'})).text()", u))
                for r in d.get("page", {}).get("results", []):
                    if r.get("mediaDescriptiveType") != "music" or r.get("isAiGenerated") or r.get("hasYoutubeContentId") or not 45 <= r.get("duration", 0) <= 240: continue
                    if str(r["id"]) in seen: continue
                    seen.add(str(r["id"])); cands.append((r.get("isEditorsChoice", False), r.get("likeCount", 0), r))
            cands.sort(key=lambda c: (not c[0], -c[1]))
            need = max(0, per - len(have)); print(f"{mood}: {len(have)} present, {len(cands)} candidates, downloading {min(need, len(cands))}")
            (LIB / mood).mkdir(exist_ok=True)
            for ec, likes, r in cands[:need]:
                fn = f"{slug(r['name'] or 'track')}-{r['id']}.mp3"; dst = LIB / mood / fn
                try:
                    resp = ctx.request.get(r["sources"]["src"], headers={"Referer": "https://pixabay.com/"})
                    if resp.status != 200 or len(resp.body()) < 200_000: print("   skip", fn, resp.status); continue
                    dst.write_bytes(resp.body())
                except Exception as e: print("   fail", fn, e); continue
                index[str(r["id"])] = dict(mood=mood, file=fn, name=r["name"], duration=r["duration"], likes=likes, editors_choice=ec,
                                           page="https://pixabay.com" + r["href"], tags=r.get("description", ""), attribution=re.sub("<[^>]+>", "", r.get("attributionHtml", "")))
                print(f"   + {fn} ({r['duration']}s, {likes} likes{', EC' if ec else ''})"); time.sleep(.6)
            (LIB / "INDEX.json").write_text(json.dumps(index, indent=1))
        br.close()
    print("total tracks:", sum(1 for v in index.values() if (LIB / v["mood"] / v["file"]).exists()))

if __name__ == "__main__":
    if len(sys.argv) > 1: collect([sys.argv[1]], int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    else: collect(list(QUERIES), 12)
