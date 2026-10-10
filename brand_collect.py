"""Brand / technology showcase videos from online (YouTube via yt-dlp): the first-choice B-roll when a product or technology is named.
Official launch and motion-graphics videos ("Introducing Claude Code", "Introducing GPT-6 in ChatGPT"), downloaded once into
<skill>/brand/<topic>/ and reused by `brand(topic)`.

  python3 brand_collect.py                 # every topic in TOPICS that has no clip yet
  python3 brand_collect.py claude 3        # one topic, up to 3 clips
  python3 brand_collect.py add notion "Introducing Notion AI" "Notion AI motion graphics"   # add a topic with its search queries

Rules: official channels first (channel name in OFFICIAL), 10-300 s, <= 1080p mp4, no live streams, no tutorials over 5 minutes.
These videos are the brands' own marketing material; use short excerpts in a window, never a full clip, and name the source in the
cue sheet. The user decides whether that use is appropriate for their channel."""
import json, pathlib, re, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
LIB = HERE / "brand"
TOPICS = {
    "claude":      (["Anthropic Claude introducing", "Claude AI motion graphics", "Keep thinking with Claude"], ["Anthropic", "Claude"]),
    "claude-code": (["Introducing Claude Code Anthropic", "Claude Code demo official"], ["Anthropic", "Claude"]),
    "chatgpt":     (["OpenAI introducing ChatGPT", "ChatGPT motion graphics official"], ["OpenAI"]),
    "openai":      (["OpenAI introducing GPT", "OpenAI launch video"], ["OpenAI"]),
    "gemini":      (["Google Gemini introducing", "Gemini AI official video"], ["Google", "Google DeepMind", "Google for Developers"]),
    "cursor":      (["Cursor AI editor introducing", "Cursor AI official"], ["Cursor"]),
    "notion":      (["Introducing Notion AI", "Notion official video"], ["Notion"]),
    "figma":       (["Figma introducing", "Figma AI official"], ["Figma"]),
    "stripe":      (["Stripe introducing", "Stripe Sessions keynote highlights"], ["Stripe"]),
    "vercel":      (["Vercel introducing v0", "Vercel official video"], ["Vercel"]),
    "midjourney":  (["Midjourney showcase", "Midjourney video model introducing"], ["Midjourney"]),
    "perplexity":  (["Perplexity AI introducing", "Perplexity Comet"], ["Perplexity"]),
}
OFFICIAL_BONUS = 100

def search(q, n=8):
    r = subprocess.run(["yt-dlp", f"ytsearch{n}:{q}", "--flat-playlist", "--print", "%(duration)s\t%(channel)s\t%(title)s\t%(id)s"], capture_output=True, text=True)
    out = []
    for line in r.stdout.strip().splitlines():
        try: d, ch, title, vid = line.split("\t"); out.append(dict(duration=float(d) if d not in ("NA", "") else 0, channel=ch, title=title, id=vid))
        except ValueError: continue
    return out

def collect(topic, per=2):
    queries, official = TOPICS[topic]; d = LIB / topic; d.mkdir(parents=True, exist_ok=True)
    index = json.loads((LIB / "INDEX.json").read_text()) if (LIB / "INDEX.json").exists() else {}
    have = [k for k, v in index.items() if v["topic"] == topic and (d / v["file"]).exists()]
    cands = {}
    for q in queries:
        for r in search(q):
            if not 10 <= r["duration"] <= 300 or r["id"] in index: continue
            bad = re.search(r"tutorial|course|zero to hero|in \d+ minutes|masterclass|review|vs\.?|reaction", r["title"], re.I)
            score = (OFFICIAL_BONUS if any(o.lower() == r["channel"].lower() for o in official) else 0) + (20 if re.search(r"introduc|meet|motion|showcase|official", r["title"], re.I) else 0) - (50 if bad else 0) - r["duration"] / 30
            cands[r["id"]] = (score, r)
    ranked = sorted(cands.values(), key=lambda c: -c[0]); need = max(0, per - len(have))
    print(f"{topic}: {len(have)} present, {len(ranked)} candidates, downloading {min(need, len(ranked))}")
    for score, r in ranked[:need]:   # candidates are many on purpose: the segment is chosen by eye from the sheets, never by rank alone
        fn = re.sub(r"[^a-z0-9]+", "-", r["title"].lower()).strip("-")[:50] + f"-{r['id']}.mp4"; out = d / fn
        # HD only: best video up to 4K with at least 1080 lines (a 720p film upscaled into a window looks cheap)
        # ULTRA HD first: 4K (2160 lines) when the film has it, 1440/1080 only as a fallback that --cue will flag
        res = subprocess.run(["yt-dlp", "-f", "bv*[height=2160]+ba/bv*[height>=1440]+ba/bv*[height>=1080]+ba/b[height>=1080]", "--merge-output-format", "mp4", "-o", str(out), f"https://www.youtube.com/watch?v={r['id']}"], capture_output=True, text=True)
        if not out.exists(): print("   skip (no HD rendition)", fn[:50]); continue
        pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip().split(",")
        wh = dict(width=int(pr[0]), height=int(pr[1])) if len(pr) == 2 else {}
        index[r["id"]] = dict(topic=topic, file=fn, title=r["title"], channel=r["channel"], duration=r["duration"], url=f"https://www.youtube.com/watch?v={r['id']}", official=any(o.lower() == r["channel"].lower() for o in official), **wh)
        print(f"   + [{r['channel']}] {r['title'][:60]} ({r['duration']:.0f}s, {wh.get('width')}x{wh.get('height')})")
    (LIB / "INDEX.json").write_text(json.dumps(index, indent=1))

def sheet(topic):
    """Contact sheets (1 frame per second, 20 per row) of every clip of a topic, for picking the exact 6 s segment: brand/<topic>/sheets/."""
    d = LIB / topic; out = d / "sheets"; out.mkdir(exist_ok=True)
    for clip in sorted(d.glob("*.mp4")):
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)], capture_output=True, text=True).stdout or 0)
        rows = max(1, -(-int(dur) // 20)); png = out / (clip.stem + ".png")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-vf", f"fps=1,scale=192:108,drawtext=text='%{{eif\\:t\\:d}}':x=4:y=4:fontsize=18:fontcolor=white:box=1:boxcolor=black@0.5,tile=20x{rows}", "-frames:v", "1", "-update", "1", str(png)], capture_output=True)
        if not png.exists():   # no drawtext in this ffmpeg build: plain sheet, second = column + 20 * row
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-vf", f"fps=1,scale=192:108,tile=20x{rows}", "-frames:v", "1", "-update", "1", str(png)], capture_output=True)
        print(f"  {png.name}: {dur:.0f}s, {rows} rows of 20 (second = column + 20*row)")

if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "sheet": sheet(a[1]); sys.exit()
    if a and a[0] == "add": TOPICS[a[1]] = (a[2:], [a[1].title()]); collect(a[1], 2)
    elif a: collect(a[0], int(a[1]) if len(a) > 1 else 2)
    else:
        for t in TOPICS: collect(t, 2)
