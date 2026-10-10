"""Build the skill's cinematic sound library: impacts, risers, whooshes, sub drops, braams, stingers, glitches, UI clicks.

  python3 sound_collect.py              # every category, ~6 sounds each, into <skill>/sfx/<category>/, index in sfx/INDEX.json
  python3 sound_collect.py riser 10     # one category

Sources:
  freesound.org  - CC0 sounds only (search filtered to "Creative Commons 0", sorted by downloads), HQ preview mp3, no API key needed.
  bbcrewind.co.uk - BBC Sound Effects archive (RemArc licence: personal, educational and research use; NOT for commercial work).
                    Stored under sfx/bbc_* and used only when CFG["sfx_sources"] includes "bbc".
The renderer picks from these by cue name (see overlay.py SFX_LIB) with the synthesized / macOS sounds as the last fallback."""
import json, pathlib, re, sys, time, urllib.parse, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
LIB = HERE / "sfx"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"}
# category: (freesound queries, bbc queries, max duration s)
CATS = {
    "impact":  (["cinematic impact", "deep impact hit", "trailer hit boom"], ["impact", "thud"], 4),
    "riser":   (["riser cinematic", "riser whoosh buildup", "tension riser"], [], 8),
    "whoosh":  (["whoosh transition", "swoosh cinematic", "whoosh short"], ["whoosh", "swish"], 2.5),
    "sub":     (["sub drop", "bass drop cinematic", "sub boom"], [], 4),
    "braam":   (["braam", "trailer braam", "cinematic brass hit"], [], 5),
    "stinger": (["stinger cinematic", "reveal stinger", "logo reveal sting"], [], 5),
    "glitch":  (["glitch sfx short", "digital glitch", "data glitch"], [], 2),
    "click":   (["ui click", "mouse click", "camera shutter click"], ["click", "camera shutter"], 1),
    "pop":     (["pop bubble short", "ui pop", "cartoon pop"], ["pop"], 1),
    "ding":    (["notification ding", "bell ding", "success chime"], ["bell small"], 2.5),
    "typing":  (["keyboard typing short", "mechanical keyboard click"], ["typewriter key"], 3),
    "cash":    (["cash register", "coins drop", "money counter"], ["cash register", "coins"], 3),
    "heartbeat": (["heartbeat", "heart beat slow"], ["heartbeat"], 6),
    "ticking": (["clock ticking", "stopwatch tick"], ["clock tick"], 6),
}

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "snd"

def get(url, data=None, headers=None, binary=False):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=40) as r: return r.read() if binary else r.read().decode("utf-8", "ignore")

def freesound(q, maxdur, want, seen):
    out = []
    html = get(f"https://freesound.org/search/?q={urllib.parse.quote(q)}&f=license:%22Creative+Commons+0%22+duration:[0+TO+{int(maxdur)}]&s=num_downloads+desc")
    blocks = re.split(r'class="bw-search__result', html)[1:]
    for b in blocks:
        m_id = re.search(r'/people/([^/"]+)/sounds/(\d+)/', b); m_mp3 = re.search(r'(https://cdn\.freesound\.org/previews/\d+/\d+_\d+)-lq\.mp3', b); m_t = re.search(r'title="([^"]{2,80})"', b)
        if not (m_id and m_mp3) or m_id.group(2) in seen: continue
        seen.add(m_id.group(2)); out.append(dict(src="freesound", id=m_id.group(2), author=m_id.group(1), name=m_t.group(1) if m_t else q, url=m_mp3.group(1) + "-hq.mp3",
                                                page=f"https://freesound.org/people/{m_id.group(1)}/sounds/{m_id.group(2)}/", license="CC0"))
        if len(out) >= want: break
    return out

def bbc(q, maxdur, want, seen):
    out = []
    data = json.loads(get("https://sound-effects-api.bbcrewind.co.uk/api/sfx/search", data=json.dumps({"criteria": {"from": 0, "size": 30, "query": q}}).encode(), headers={"Content-Type": "application/json"}))
    for r in data.get("results", []):
        if r.get("duration", 1e9) / 1000 > maxdur or r["id"] in seen: continue
        seen.add(r["id"]); out.append(dict(src="bbc", id=r["id"], author="BBC", name=r.get("description", q)[:80], url=f"https://sound-effects-media.bbcrewind.co.uk/mp3/{r['id']}.mp3",
                                       page=f"https://sound-effects.bbcrewind.co.uk/search?q={urllib.parse.quote(q)}", license="BBC RemArc (personal/educational/research only)"))
        if len(out) >= want: break
    return out

def collect(cats, per):
    LIB.mkdir(exist_ok=True); index = json.loads((LIB / "INDEX.json").read_text()) if (LIB / "INDEX.json").exists() else {}
    for cat in cats:
        fsq, bbcq, maxdur = CATS[cat]; seen = {v["id"] for v in index.values()}; cands = []
        for q in fsq:
            try: cands += freesound(q, maxdur, per, seen)
            except Exception as e: print(f"  freesound '{q}': {e}")
        if bbcq:
            for q in bbcq:
                try: cands += bbc(q, maxdur, max(2, per // 2), seen)
                except Exception as e: print(f"  bbc '{q}': {e}")
        have = [k for k, v in index.items() if v["cat"] == cat and (LIB / (("bbc_" if v["src"] == "bbc" else "") + cat) / v["file"]).exists()]
        need = max(0, per + (per // 2) - len(have)); print(f"{cat}: {len(have)} present, {len(cands)} candidates, downloading {min(need, len(cands))}")
        for c in cands[:need]:
            folder = LIB / (("bbc_" if c["src"] == "bbc" else "") + cat); folder.mkdir(exist_ok=True)
            fn = f"{slug(c['name'])}-{c['id']}.mp3"; dst = folder / fn
            try:
                b = get(c["url"], binary=True)
                if len(b) < 8000: print("   skip", fn, len(b)); continue
                dst.write_bytes(b)
            except Exception as e: print("   fail", fn, e); continue
            index[f"{c['src']}:{c['id']}"] = dict(cat=cat, file=fn, **c); print(f"   + [{c['src']}] {fn}"); time.sleep(.4)
        (LIB / "INDEX.json").write_text(json.dumps(index, indent=1))
    print("total sounds:", len(index))

if __name__ == "__main__":
    if len(sys.argv) > 1: collect([sys.argv[1]], int(sys.argv[2]) if len(sys.argv) > 2 else 6)
    else: collect(list(CATS), 6)
