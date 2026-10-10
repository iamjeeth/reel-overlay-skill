"""Reel overlay renderer: one-word captions, title, stickers, B-roll windows (with background blur), kinetic text,
annotations (red circle, cursor) and an auto-built SFX track, for a finished 9:16 cut.

Usage (from the reel's build folder, reel.py = this reel's config, see reel_example.py):
  python3 overlay.py reel.py --dry            print the caption words (check whisper fixes first)
  python3 overlay.py reel.py --cue            print the cue sheet: every item, its time, position and SFX
  python3 overlay.py reel.py --still 1 5.2    composite the overlay on the cut at those seconds -> out/stills.png
  python3 overlay.py reel.py                  transparent ProRes 4444 overlay MOV (SFX as audio) + preview MP4
  python3 overlay.py reel.py --final          burn overlay + blur + SFX into the cut (matches HDR/SDR), verify

Everything is laid out on a 1080x1920 canvas and scaled to the cut's resolution at render time.
The ONLY things that touch the footage itself are the background blur behind B-roll windows (blur=True) and
the audio mix; both happen in --final / the preview, not in the transparent overlay MOV."""
import json, math, os, pathlib, re, runpy, subprocess, sys

HERE = pathlib.Path(__file__).parent
ACCENT = "#FDF29E"          # neutral default; the theme sets the live accent. pale yellow: title line 2, emphasised caption words, kinetic text accents
LIME = "#EEFB00"            # default hero colour (premium reference); the active theme overrides it per reel
HOT = "#FF5C5C"
# Visual THEMES for headlines, captions, generated scenes and canvas set pieces. One is chosen PER REEL: the skill proposes the fit
# (tone, topic, speaker) and asks the user every time (AskUserQuestion, 3 options + custom), sometimes "simple" is the right call.
# bg/stage: UI-scene / canvas-card background; fg: text on the stage; acc: accent (hero words, bars, bubbles); ink: text on the accent;
# card/cardfg/cardline: the editorial card; over: overshoot of every pop (1.7 = classic, 2.6 = exaggerated); amp: motion amplitude 0-1.2.
# bg + acc/acc2/ink: UI scenes (chat, doc, chart, flow...) and their accent; hero + heroshadow: headline hero words and caption
# emphasis over the footage; stage + fg + stageacc: canvas set pieces (editorial cards) and their accent; card*: the editorial card.
THEMES = {
    "lime":    dict(label="lime on black, bold kinetic type", bg="#0B0B0F", acc="#D4FF3F", acc2="#8FD12A", ink="#0B0B0F", hero="#D4FF3F", heroshadow="0 4px 18px rgba(0,0,0,.5),0 1px 2px rgba(0,0,0,.4)",
                    stage="#0B0B0F", fg="#F4F4F6", stageacc="#D4FF3F", hot="#FF5C5C", card="#D4FF3F", cardfg="#0B0B0F", cardline="#0B0B0F", over=2.3, amp=1.0),
    "duotone": dict(label="electric duotone: yellow + violet", bg="#120B2E", acc="#FFE600", acc2="#FFB800", ink="#1A1033", hero="#FFE600", heroshadow="0 6px 0 #5B3DF5,0 10px 26px rgba(0,0,0,.45)",
                    stage="#FFE600", fg="#1A1033", stageacc="#5B3DF5", hot="#FF3D81", card="#5B3DF5", cardfg="#FFFFFF", cardline="#FFE600", over=2.6, amp=1.2),
    "brand":   dict(label="brand-driven: accent from the named product", bg="#0B0B0F", acc=None, acc2=None, ink=None, hero=None, heroshadow="0 4px 18px rgba(0,0,0,.5),0 1px 2px rgba(0,0,0,.4)",
                    stage="#0B0B0F", fg="#F4F4F6", stageacc=None, hot="#FF5C5C", card=None, cardfg=None, cardline=None, over=2.0, amp=.9),
    "simple":  dict(label="simple: calm premium reference, pale yellow, soft pops", bg="#0f1115", acc="#FDF29E", acc2="#c9b94a", ink="#111111", hero="#EEFB00", heroshadow="0 4px 18px rgba(0,0,0,.45),0 1px 2px rgba(0,0,0,.35)",
                    stage="#FED400", fg="#231D23", stageacc="#231D23", hot="#ff5a5a", card="#121014", cardfg="#ffffff", cardline="#EEFB00", over=1.7, amp=.5),
}

def theme_of(CFG):
    """The reel's theme dict. CFG["theme"] = "lime" | "duotone" | "brand" | "simple" (asked per reel); "brand" takes CFG["brand_color"]."""
    name = CFG.get("theme")
    if name not in THEMES:
        if name: print(f"theme '{name}' unknown, using 'simple' (options: {', '.join(THEMES)})")
        else: print("theme: none chosen -> 'simple'. Rule: propose and ASK the user which theme fits this reel (lime / duotone / brand / simple / custom)")
        name = "simple"
    th = dict(THEMES[name]); th["name"] = name
    if name == "brand":
        acc = CFG.get("brand_color") or "#FDF29E"; r_, g_, b_ = (int(acc.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        dark = (.299 * r_ + .587 * g_ + .114 * b_) < 150
        th.update(acc=acc, acc2=acc, ink="#F4F4F6" if dark else "#0B0B0F", hero=acc if not dark else "#FDF29E", stageacc=acc, card=acc, cardfg="#F4F4F6" if dark else "#0B0B0F", cardline="#F4F4F6" if dark else "#0B0B0F")
    return th            # editorial register: hero words (measured on the premium reference)
CARD_YEL = "#FED400"        # editorial register: full-screen card background
INK = "#231D23"             # editorial register: text on yellow
FONT_HERO = "'Helvetica Neue', Helvetica, Arial, sans-serif"   # tight-tracked bold grotesk, installed on every Mac
FONT_SERIF = "'NYI', 'New York', 'Instrument Serif', Georgia, serif"   # New York Italic (Apple), loaded via @font-face
RED = "#E0261C"             # annotation circle
FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif"

# ============================ safe zone (Instagram Reels UI, measured from the user's guide) ============================
SAFE = dict(x0=70, y0=270, x1=905, y1=1500)   # every word, card and sticker must sit inside this box; the UI covers the rest

# ============================ layout presets (1080x1920 canvas) ============================
# Window presets: x, y, w, h and where the caption moves while the window is up (cap_y, None = unchanged).
PRESETS = dict(
    top=dict(x=120, y=255, w=840, h=450, cap_y=None),          # screenshot above the head (DESIGN.md, chat bar)
    bar=dict(x=135, y=352, w=730, h=175, cap_y=None),          # a short wide UI bar (search / chat input)
    mid=dict(x=105, y=630, w=870, h=520, cap_y=1290),          # full B-roll: blur=True, caption drops below it
    laptop=dict(x=270, y=1155, w=470, h=360, cap_y=None),      # over the laptop screen: slide-up "file" windows
    card=dict(x=367, y=1185, w=323, h=405, cap_y=None),        # portrait card popping up from the bottom
    topright=dict(x=720, y=428, w=315, h=434, cap_y=None),     # meme / reaction clip
    topleft=dict(x=45, y=428, w=315, h=434, cap_y=None),
    stackA=dict(x=-40, y=400, w=600, h=400, cap_y=None),       # three-screen "gallery" look (use with stackB/C)
    stackB=dict(x=560, y=620, w=560, h=380, cap_y=None),
    stackC=dict(x=230, y=1220, w=560, h=340, cap_y=None),
    tophalf=dict(x=0, y=0, w=1080, h=800, cap_y=1420, radius=0, push="pan"),  # B-roll fills the top; the footage slides DOWN at full width (no side crop), face centred in the bottom section
    full=dict(x=0, y=0, w=1080, h=1920, cap_y=1420, radius=0),               # full-frame insert for a breath / topic change (1-2.5 s)
    behind=dict(x=0, y=0, w=1080, h=1920, cap_y=None, radius=0, person=True),     # B-roll BEHIND the speaker: full background, person cut out (Vision matte) over it
    behindtop=dict(x=0, y=0, w=1080, h=1240, cap_y=None, radius=0, person=True),  # same, but the B-roll fades out behind the chest so the real room stays below
)
# Sticker anchors: centre points.
SPOTS = dict(tr=(800, 600), tl=(230, 600), r=(880, 820), l=(220, 800), chest=(540, 1240), head=(540, 520))

# ============================ item helpers (used inside reel.py) ============================
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
def _t(t): return dict(a=float(t[0]), b=float(t[1]))

def sticker(id, src, spot=None, x=None, y=None, size=200, t=(0, 1), anim="pop", out="fade", sfx="sparkle", vol=.9, rot=0, plate="auto", idle="float"):
    """Logo / cutout / emoji that pops in. src = logo(slug) for anything with a real mark (brand, car, place, person), else an image path,
    an '<svg ...>' string, or an emoji (concepts only). x,y = centre on the canvas. plate: auto (by the mark's kind: white card for
    logos, bordered flag, round avatar for people, none for emoji/images) | none | white | dark | glass | round | flag."""
    if spot: x, y = SPOTS[spot]
    plate, asp = _plate_for(src, plate); w, h = _box(size, asp)
    return dict(kind="sticker", id=id, src=str(src), x=x, y=y, size=size, w=w, h=h, anim=anim, out=out, sfx=sfx, vol=vol, rot=rot, plate=plate, idle=idle, **_t(t))

def phrase(id, words, t, x=540, y=430, size=132, scale=1.0, ink=False, link=False, sfx=None, hero_sfx="thud", vol=.6):
    """Editorial kinetic typography (the premium-reference register): the words of ONE sentence appear at their spoken times and
    stay as a composition until t[1]. words = [(text, time, role), ...], role: 'hero' (lime, huge, tight grotesk), 'big' (same in
    white), 'small' (white, light), 'serif' (New York italic). Auto-layout: words before the hero sit in a spread row above it, the
    hero is centred on (x, y), small words after it go below-left, serif words below-right; a second hero starts a new block below.
    Override a word's place with a 4th tuple element (dx, dy) relative to the hero centre. ink=True for dark text on a yellow card.
    link=True draws a dashed hand-drawn connector from the hero to the previous small word (like the reference)."""
    W = []
    for w in words:
        d = dict(t=w[0], at=float(w[1]), role=w[2] if len(w) > 2 else "small"); 
        if len(w) > 3: d["dx"], d["dy"] = w[3]
        W.append(d)
    return dict(kind="phrase", id=id, words=W, x=x, y=y, size=size, scale=scale, ink=ink, link=link, sfx=sfx, hero_sfx=hero_sfx, vol=vol, out="fade", **_t(t))

def leak(id, t, dur=.45, hue="warm", vol=.7, sfx="whoosh"):
    """Film-burn / light-leak transition at a cut: a saturated wash (magenta -> white-yellow -> orange) sweeps over the frame for dur s.
    Put it exactly on the cut (t = the first frame of the new shot) so the burn hides the splice."""
    return dict(kind="leak", id=id, dur=dur, hue=hue, sfx=sfx, vol=vol, out="none", a=float(t) - dur * .45, b=float(t) + dur * .55)

def fx(id, clip, t, key=None, x=0, y=0, w=1080, h=1920, opacity=1.0, speed=1.0, sfx=None, vol=.6, offset=0.0):
    """Overlay clip composited over the footage in ffmpeg (GIF, mp4, webm, mov): falling money, confetti, sparkles, smoke, arrows.
    clip = a path, or a category name from the skill's fx/ collection ('money', 'confetti', 'leak', 'sparkle', ...), or fxclip(...).
    key: 'green' (chroma key), 'screen' (black background, screen blend), 'alpha' (transparent file), None = from the collection index.
    Loops for the whole range; offset skips into the clip. Canvas coords for x,y,w,h."""
    return dict(kind="fx", id=id, clip=str(clip), key=key, x=x, y=y, w=w, h=h, opacity=opacity, speed=speed, sfx=sfx, vol=vol, offset=offset, out="none", **_t(t))

def fxclip(cat, pick=0):
    """Path of the pick-th clip of a category in <skill>/fx/ (see fx/INDEX.json). Run pixabay_fx.py to grow the collection."""
    idx = json.loads((HERE / "fx" / "INDEX.json").read_text()) if (HERE / "fx" / "INDEX.json").exists() else {}
    c = sorted([v for v in idx.values() if v["cat"] == cat and (HERE / "fx" / cat / v["file"]).exists()], key=lambda v: -v.get("likes", 0))
    if not c: sys.exit(f"fx: no '{cat}' clips in {HERE / 'fx'}; run python3 pixabay_fx.py {cat} 4")
    return HERE / "fx" / cat / c[pick % len(c)]["file"]

def headshot(t, x=270, y=150, w=540, h=540):
    """A circular cutout of the speaker's head from the cut at time t (Vision matte), for the profile card. Canvas coords of the crop."""
    return f"headshot://{t},{x},{y},{w},{h}"

ACCENT_SPOTS = dict(ar=(870, 640), al=(210, 640), br=(900, 1000), bl=(180, 1000))
MOTION_SPOTS = dict(right=(600, 520), left=(80, 520), centre=(330, 520))   # top-left of a 400x300 box beside the head, under the headline

def motion(id, kind, t, side="right", w=400, h=300, radius=28, anim="pop", out="fade", sfx="click", vol=.45, **cfg):
    """A small motion graphic beside the head: any set piece or UI scene (calendar, race, flow, chart, counter, orbit, cards, marketmap,
    checklist, phone, headcount...) in a 400x300 card. The in-between device of the skill: when the speaker makes a point and no B-roll is
    due, a mini motion graphic illustrates it. Not counted as B-roll; counted as an extra. Vary the kind every time."""
    x, y = MOTION_SPOTS[side] if isinstance(side, str) else side
    d = scene(id, kind, t=t, x=x, y=y, w=w, h=h, anim=anim, out=out, radius=radius, sfx=sfx, vol=vol, **cfg); d["mini"] = True; return d   # beside the head, under the headline, inside the safe zone

def accent(id, icon, at, side="ar", hold=2.2, size=130, sfx="click", vol=.45, plate="auto", anim="pop"):
    """A small icon (emoji or logo path) that lands on a spoken word with a quiet mouse click (sfx="click") or a soft bell (sfx="bell"),
    holds ~2 s and fades. For nouns the speaker emphasises: "PRD" -> 📄, "budget" -> 💰, "sound like you" -> 🎙️. Not a sticker for a
    named brand (use sticker/logo) and not a list (use iconrow). Budget: <= 1 per 6 s of runtime; never over a B-roll window."""
    x, y = ACCENT_SPOTS[side] if isinstance(side, str) else side
    if plate == "auto" and _logo_meta(icon)[0] is None: plate = "glass"
    d = sticker(id, icon, x=x, y=y, size=size, t=(at, at + hold), anim=anim, out="fade", sfx=sfx, vol=vol, plate=plate, idle=None)
    d["x"] = min(max(d["x"], SAFE["x0"] + d["w"] // 2 + 10), SAFE["x1"] - d["w"] // 2 - 10)   # a wide wordmark still stays inside the safe area
    d["accent"] = True; return d

def iconrow(id, icons, t, y=640, x=540, size=150, gap=40, sfx="thud", vol=.5, plate="auto"):
    """Mini images for an enumeration ("a developer, a designer, a marketer, a sales guy"): one icon per spoken item, popping on its word
    time and staying until t[1]. icons = [(emoji_or_image_path, time), ...]; the row is centred on (x, y). Counts as ONE extra."""
    ics = []
    for a, b in icons:
        pl, asp = _plate_for(a, plate); pl = "glass" if pl == "auto" else pl; w, h = _box(size, asp)
        ics.append(dict(src=str(a), at=float(b), plate=pl, w=w, h=size))
    return dict(kind="iconrow", id=id, icons=ics, x=x, y=y, size=size, gap=gap, sfx=sfx, vol=vol, plate=plate, out="fade", **_t(t))

def flash(id, t, color="#fff", dur=.22, vol=.6, sfx="shutter"):
    """Full-frame flash (white by default) at a cut, like a light leak / camera flash. Peaks on frame 1 of t and decays over dur."""
    return dict(kind="flash", id=id, color=color, dur=dur, sfx=sfx, vol=vol, out="none", a=float(t), b=float(t) + dur)

def punch(id, t, amount=.08, dur=.4, sfx="hit", vol=.9):
    """Camera punch-in on the FOOTAGE (final/preview only): a quick zoom to 1+amount and back, on an emphasised word. The movie-trailer beat."""
    return dict(kind="punch", id=id, amount=amount, dur=dur, sfx=sfx, vol=vol, out="none", a=float(t), b=float(t) + dur)

def bars(id, t, size=180, sfx="swipe", vol=.5):
    """Cinematic letterbox: black bars slide in from top and bottom for the duration (t=(a,b)). Pair with full-screen inserts."""
    return dict(kind="bars", id=id, size=size, sfx=sfx, vol=vol, out="none", **_t(t))

def burst(id, x, y, t, n=42, colors=None, sfx="sparkle", vol=.9, spread=420):
    """Confetti / spark burst from a point at time t (0.9 s). For wins, big numbers, 'launch'."""
    return dict(kind="burst", id=id, x=x, y=y, n=n, colors=colors or ["#D4FF3F", "#fff", "#FF6B6B", "#6BCBFF", "#B388FF"], sfx=sfx, vol=vol, spread=spread, out="none", a=float(t), b=float(t) + .9)

BUILD = pathlib.Path(".")
def stock(query, kind="video", orientation="portrait", pick=0, min_duration=4):
    """Real footage / photo for a window: Pexels when a key exists ($PEXELS_API_KEY or ~/.config/reel-overlay/pexels_key), otherwise
    Pixabay through the installed Chrome (no key, see pixabay_stock.py). Cached in <build>/assets/stock/. Mention the source in the cue sheet."""
    import urllib.request, urllib.parse, json as _j
    d = BUILD / "assets" / "stock"; d.mkdir(parents=True, exist_ok=True)
    keyf = pathlib.Path("~/.config/reel-overlay/pexels_key").expanduser()
    key = os.environ.get("PEXELS_API_KEY") or (keyf.read_text().strip() if keyf.exists() else None)
    if not key:
        sys.path.insert(0, str(HERE)); import pixabay_stock
        return pixabay_stock.fetch(query, "video" if kind == "video" else "photo", d, pick, vertical=(orientation == "portrait"), min_duration=min_duration)
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-"); ext = ".mp4" if kind == "video" else ".jpg"; f = d / f"{slug}_{orientation}_{pick}{ext}"
    if f.exists(): return f
    url = (f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&orientation={orientation}&per_page={pick + 8}&size=medium" if kind == "video"
           else f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&orientation={orientation}&per_page={pick + 8}")
    req = urllib.request.Request(url, headers={"Authorization": key}); data = _j.loads(urllib.request.urlopen(req, timeout=30).read())
    if kind == "video":
        vids = [v for v in data.get("videos", []) if v.get("duration", 0) >= min_duration]
        if len(vids) <= pick: sys.exit(f"stock('{query}'): only {len(vids)} results")
        files = sorted([x for x in vids[pick]["video_files"] if x.get("height") and x["height"] <= 1920], key=lambda x: -(x.get("width", 0) * x.get("height", 0)))
        src = files[0]["link"]; print(f"  stock: {query} -> {vids[pick]['url']}")
    else:
        ph = data.get("photos", [])
        if len(ph) <= pick: sys.exit(f"stock('{query}'): only {len(ph)} results")
        src = ph[pick]["src"]["large2x"]; print(f"  stock: {query} -> {ph[pick]['url']}")
    urllib.request.urlretrieve(src, f); return f

def stock_many(items):
    """Prefetch several Pixabay stock items in one browser session: items = [(query, kind, pick), ...]. Call once at the top of reel.py."""
    sys.path.insert(0, str(HERE)); import pixabay_stock
    d = BUILD / "assets" / "stock"; need = [(q, "video" if k == "video" else "photo", pk) for q, k, pk in items
                                           if not (d / f"{pixabay_stock.slug(q)}_v_{pk}{'.mp4' if k == 'video' else '.jpg'}").exists()]
    if need: pixabay_stock.fetch_many(need, d)

def brand(topic, pick=0):
    """A brand / technology showcase video from the skill's library (<skill>/brand/<topic>/, downloaded from online with
    brand_collect.py). THE first-choice B-roll whenever a product or technology is named. Use window(..., offset=s) to pick the segment."""
    d = HERE / "brand" / topic; clips = sorted(d.glob("*.mp4")) if d.exists() else []
    if not clips: sys.exit(f"brand('{topic}'): nothing in {d}; run python3 brand_collect.py {topic}")
    def lines(f):
        try: return int(probe(f, "height").get("height", 0))
        except Exception: return 0
    clips.sort(key=lambda f: (-lines(f), f.name))   # ULTRA HD first: pick=0 is the highest-resolution film of the topic
    return clips[pick % len(clips)]

def web(topic, pick=0):
    """A clip from the skill's product-site library (<skill>/web/<topic>/*.mp4): real websites recorded once with capture.py and reused
    (claude, claude-code, chatgpt-prompt, notion, stripe, figma, make, vercel, producthunt, ...). Grow it with `python3 web_collect.py`.
    For a reel-specific prompt record a fresh one: capture.py demo https://chatgpt.com out.mp4 --type "..." --width 1080 --height 1920."""
    d = HERE / "web" / topic; clips = sorted(d.glob("*.mp4")) if d.exists() else []
    if not clips: sys.exit(f"web('{topic}'): nothing in {d}; run python3 web_collect.py {topic}")
    return clips[pick % len(clips)]

LOGOS = HERE / "brand" / "logos"
def _logo_index():
    f = LOGOS / "INDEX.json"; return json.loads(f.read_text()) if f.exists() else {}

def logo(slug, color=None, cutout=True):
    """The ORIGINAL mark of a named thing from the skill's logo library (<skill>/brand/logos/, fetched from online by logo_collect.py):
    the brand's real logo, a car marque, a country/state flag, a famous person's official portrait (cut out by the person segmenter).
    THE element to show whenever a brand, product, car, person or place is named; never an emoji or a generic icon in its place.
    The plate is chosen from the kind (white card for logos, bordered flag, round avatar for people) unless the item sets one.
    Missing slug -> python3 logo_collect.py add <slug> "<name>" --kind brand|car|place|person   (then look at brand/logos/sheet.png)."""
    e = _logo_index().get(slug)
    if not e: sys.exit(f"logo('{slug}'): not in {LOGOS}. Fetch the real mark first:  python3 {HERE}/logo_collect.py add {slug} \"<official name>\" --kind brand|car|place|person")
    return LOGOS / (e["cutout"] if cutout and e.get("cutout") else e["file"])

def _logo_meta(src):
    """(kind, aspect) of a library logo path; (None, 1.0) for anything else."""
    pth = pathlib.Path(str(src))
    if not str(src).startswith(str(LOGOS)): return None, 1.0
    for e in _logo_index().values():
        if pth.name == e.get("cutout"): return e["kind"], 1.0            # cutouts sit in a round plate, cover-cropped from the top
        if pth.name == e["file"]: return e["kind"], (e["width"] / e["height"]) if e.get("height") else 1.0
    return None, 1.0

def _plate_for(src, plate):
    kind, asp = _logo_meta(src)
    if plate == "auto": plate = {"brand": "white", "car": "white", "place": "flag", "person": "round"}.get(kind, "glass" if kind is None else "white")
    if plate in ("round",): return plate, 1.0
    return plate, asp

def _box(size, asp):
    """Width/height of a sticker box for a mark of aspect `asp` (1 = square): wide wordmarks get a wide card, tall marks a tall one."""
    if asp > 2.4: return int(size * min(asp * .78, 3.3)), int(size * .74)   # a long wordmark: wide, slightly lower card so the letters stay readable
    if asp > 1.15: return int(size * asp), size
    if asp < .85: return size, int(size * min(1 / asp, 1.5))
    return size, size

def window(id, media, preset=None, x=None, y=None, w=None, h=None, t=(0, 1), anim="fade", out="fade", blur=False, radius=36,
           frame="none", tilt=0, scroll=None, loop=True, cap_y=None, sfx="whoosh", vol=.6, fit="cover", shadow=True, dist=None, push=None, scene=None, drift=None, still=False, offset=0.0):
    """B-roll window: a screen recording (.mp4/.mov/.webm/.gif) or screenshot (.png/.jpg/.webp) in a rounded card.
    blur=True blurs the footage behind it. scroll=(px_per_s, delay_s) scrolls a tall screenshot (fit='width').
    anim: fade | pop | up | down | left | right | none.  frame: none | dark (thin tablet-like bezel).  tilt: rotateY deg."""
    p = PRESETS.get(preset, {}) if preset else {}
    box = dict(x=p.get("x", x), y=p.get("y", y), w=p.get("w", w), h=p.get("h", h))
    assert None not in box.values(), f"window {id}: give a preset or x,y,w,h"
    if media and pathlib.Path(str(media)).suffix.lower() in IMG_EXT and not still and not scroll:
        sys.exit(f"window {id}: '{pathlib.Path(str(media)).name}' is an image. B-roll is always VIDEO or an animation (scene). "
                 "Use stock(query, 'video') or a scene(); pass still=True only for a UI screenshot the user supplied.")
    if scroll and fit == "cover": fit = "width"
    if "radius" in p and radius == 36: radius = p["radius"]
    if push is None: push = p.get("push")
    if push == "pan":   # the standard top-half layout: the insert lands WITH the sliding footage, fast; slow dissolves read as lag
        if anim in ("fade", "dissolve", "down", "none", "blur", "zoom"): anim = "snap"
        if out in ("fade", "dissolve", "none", "blur", "down"): out = "snap"
    person = bool(p.get("person"))
    if drift is None: drift = .035 if preset in ("tophalf", "full") else 0
    if drift is True: drift = .035
    if preset in ("tophalf", "full") and anim == "fade": anim = "down" if preset == "tophalf" else "fade"
    return dict(kind="window", id=id, media=str(media) if media else None, **box, anim=anim, out=out, blur=blur, radius=radius, frame=frame, tilt=tilt,
                scroll=scroll, loop=loop, cap_y=p.get("cap_y") if cap_y is None else cap_y, sfx=sfx, vol=vol, fit=fit, shadow=shadow,
                dist=dist, push=push, scene=scene, drift=drift, person=person, offset=float(offset), **_t(t))

def scene(id, kind, preset=None, t=(0, 1), x=None, y=None, w=None, h=None, blur=False, anim="fade", out="fade", **cfg):
    """Generated B-roll: an animated UI drawn by the renderer itself (no files needed). Write the content from the transcript.
    kinds and their cfg:
      terminal  title='Claude Code', cmd='build the first version from PRD.md', lines=['Created app/page.tsx', ...], cps=28, delay=.2
      chat      name='SEO Agency', avatar='🏢', history=[('a','Monthly report attached 📈'),('u','Thanks')], prompt='...', reply='...', cps=30, reply_delay=.6 (a whole chat screen: header, faint earlier messages, typing dots, composer)
      doc       title='PRD.md', heading='# PRD: ...', lines=['## Problem', 'Freelancers lose ...'], cps=40
      browser   url='invoicechaser.app', heading='...', sub='...', button='Start free', cards=['...', '...'], step=.35
      search    query='why is it so hard to', results=['chase late invoices', ...], cps=22
      cards     cards=[dict(emoji='👥', title='Team of 5', sub='2019'), ...], step=.45, accent_last=True
      code      title='app.tsx', lines=['const x = 1', ...], cps=55
      chart     title='Days to launch', bars=[dict(label='2019', value=180), dict(label='Now', value=4, suffix='d')], step=.12
      counter   value=90, suffix='%', label='of my ops run on AI', sub='…', duration=1.2, prefix='$', decimals=0
      phone     notifications=[dict(app='Instagram', icon=logo('instagram'), title='New message', text='startup')]   (icon = real app logo; emoji only for concepts), step=.8, time='9:41'
      flow      nodes=[dict(emoji='🔍', label='Problem'), dict(emoji='📄', label='PRD'), ...], step=.45
      checklist title='Launch', items=['Positioning', 'Landing page', ...], step=.5
      stats     title='This month', tiles=[dict(label='Paying users', value=20, delta='+8', spark=[2,4,6,9,14,20])], step=.18
      timeline  title='Idea to launch', points=[dict(label='2019', text='Team of 5, 6 months'), dict(label='Now', text='You + AI, days')], step=.5
      kanban    title='Launch board', columns=['To do','Doing','Done'], cards=['Landing page', dict(text='Stripe', tag='backend')], step=.55
      quote     text='…', name='Priya', role='Freelance designer', wps=7
      email     title='Inbox', messages=[dict(sender='Stripe', subject='You got paid', preview='$499 from …', badge='NEW', color='#635bff')], step=.6
      dashboard brand='InvoiceChaser', title='Overview', kpis=[dict(label='MRR', value=4200, prefix='$')], bars=[...12 numbers], rows=[['Acme','$499']], chart_label='Revenue'
      cinematic style=sunset|forest|stars|aurora|city|ocean|grid|particles, text='Days, not months', sub='…', seed=7, text_delay=.5
                procedural animated footage (parallax, light, particles, film grain) for full-screen inserts when no real clip exists
      reveal    brand='runway', sub='Connector', logo=logo('runwayml','#fff'), tag='Free in Claude', per=.045, cps=26   (black-screen brand reveal)
      progress  title='Claude', model='Opus 5 · High', prompt='Create a 15 s video of …', label='Generating', to=100, duration=3, lines=['Shot 1 of 4', …]
      browser extras: toast='🚀 Deployed', cursor=True (a cursor flies in and clicks the button, then the toast pops)
    Windows on `tophalf`/`full` drift (slow 3.5% zoom) so even a finished scene keeps breathing; set drift=False to stop it.
    push="pan" (the tophalf standard): the footage slides down at full width so the face is centred under the insert, never shrunk or
    side-cropped; push=<0..1> is the old shrink-to-bottom layout, kept for special cases only.
    Extra window options (radius, push, cap_y, frame, tilt, sfx, vol) pass through."""
    wopts = {k: cfg.pop(k) for k in list(cfg) if k in ("radius", "push", "cap_y", "frame", "tilt", "sfx", "vol", "shadow", "dist", "drift")}
    def uri(v): return img_uri(v) if isinstance(v, pathlib.Path) else [uri(x) for x in v] if isinstance(v, list) else {k: uri(x) for k, x in v.items()} if isinstance(v, dict) else v
    cfg = {k: uri(v) for k, v in cfg.items()}   # logo=logo(...) or logos=[logo(...), ...] -> file URIs
    return window(id, None, preset=preset, x=x, y=y, w=w, h=h, t=t, anim=anim, out=out, blur=blur, scene=dict(kind=kind, **cfg), **wopts)

def text(id, s, x, y, size=84, em=False, t=(0, 1), anim="pop", out="fade", anchor="left", sfx="auto", vol=.6, weight=700, color=None, hide_cap=True, cps=18):
    """Kinetic word(s). anchor='left': x,y = top-left. anchor='center': x = centre. em=True -> accent colour.
    anim 'wipe' slides+reveals from the left (the 'Your / Typography' look). hide_cap: the normal caption is hidden while
    any text item is up (the kinetic words ARE the caption then)."""
    if sfx == "auto": sfx = {"wipe": "swipe", "slam": "hit", "type": "key", "rise": "swipe"}.get(anim, "tick")
    return dict(kind="text", id=id, s=s, x=x, y=y, size=size, em=em, anim=anim, out=out, anchor=anchor, sfx=sfx, vol=vol,
                weight=weight, color=color, hide_cap=hide_cap, cps=cps, **_t(t))

def circle(id, x, y, w, h, t=(0, 1), sfx="scribble", vol=.5, width=7):
    """Hand-drawn red circle around a UI element. x,y = centre, w,h = size. Draws itself over ~0.45s."""
    return dict(kind="circle", id=id, x=x, y=y, w=w, h=h, sfx=sfx, vol=vol, width=width, out="fade", **_t(t))

def cursor(id, path, t=(0, 1), sfx="click", vol=.8, size=64):
    """macOS arrow cursor gliding along path=[(x,y), (x,y), ...] between t[0] and t[1], then a click pulse."""
    return dict(kind="cursor", id=id, path=path, sfx=sfx, vol=vol, size=size, out="fade", **_t(t))

def card(id, label, value, y=1300, x=540, t=(0, 1), anim="up", out="fade", sfx="whoosh", vol=.6, chip=None):
    """Centred white pill: small grey label + big value (comment keyword, 'share this with', a stat). chip = red tag text."""
    return dict(kind="card", id=id, label=label, value=value, x=x, y=y, anim=anim, out=out, sfx=sfx, vol=vol, chip=chip, **_t(t))

HELPERS = dict(sticker=sticker, card=card, scene=scene, logo=logo, web=web, brand=brand, stock=stock, stock_many=stock_many, iconrow=iconrow, accent=accent, motion=motion, flash=flash, punch=punch, bars=bars, burst=burst, phrase=phrase, leak=leak, fx=fx, fxclip=fxclip, headshot=headshot,
               LIME=LIME, CARD_YEL=CARD_YEL, INK=INK, window=window, text=text, circle=circle, cursor=cursor, PRESETS=PRESETS, SPOTS=SPOTS, ACCENT=ACCENT, HERE=HERE)

# ============================ config ============================
def load_reel(path):
    global BUILD; BUILD = pathlib.Path(path).resolve().parent
    g = runpy.run_path(str(path), init_globals=dict(HELPERS))
    cfg = dict(fps=30, title=None, emph=set(), merges=[], fixes={}, cap_y=1100, cap_size=96, cap_words=1, cap_pop=True, style="kinetic",
               sfx_lib=None, sfx={}, intro_whoosh=False, sfx_gain=.7, voice=True, duck=True, music="auto", music_db=-4, music_lib=None, grade=None, smooth=1.3, sfx_style="soft", render_scale=1.5, out=pathlib.Path(path).parent / "out", chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if g["CFG"].get("style") == "cinematic":   # the clean register: 2-word boxed captions, no pop, full-screen inserts carry the visuals
        cfg.update(cap_words=2, cap_size=58, cap_style="box", cap_y=1480, cap_pop=False, sfx_gain=.7)
    if g["CFG"].get("style", "editorial") == "editorial":   # default: running 2-word subtitles at the bottom, context headlines (phrase) at the top
        cfg.update(cap_words=2, cap_size=66, cap_style="plain", cap_y=1420, cap_pop=True, cap_mode="always")   # measured on the reference: ~60px bold, black box r12
    cfg.setdefault("cap_style", "plain"); cfg.setdefault("cap_mode", "always")
    cfg.update(g["CFG"])
    cfg["cut"] = pathlib.Path(cfg["cut"]).expanduser()
    cfg["out"] = pathlib.Path(cfg["out"]).expanduser().resolve()
    cfg["whisper"] = pathlib.Path(cfg.get("whisper", pathlib.Path(path).parent / "audio.json")).expanduser()
    cfg["emph"] = {w.lower() for w in cfg["emph"]}
    return cfg, list(g.get("ITEMS", [])), list(g.get("SFX_EXTRA", []))

def probe(f, entries):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", f"stream={entries}", "-of", "json", str(f)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)["streams"][0]

def duration(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True, check=True).stdout)

def ff(*a): subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, a)], check=True)

# ============================ captions: whisper words -> one word at a time ============================
def bare(t): return re.sub(r"[^\w.%/'$]", "", t.lower())

def captions(CFG, DUR):
    if not CFG["whisper"].exists(): return []
    if CFG["whisper"].stat().st_mtime < CFG["cut"].stat().st_mtime:   # the cut was replaced after the transcript was made
        sys.exit(f"transcript {CFG['whisper'].name} is OLDER than the cut ({CFG['cut'].name}): the video changed. Re-run whisper on the new file first.")
    W_ = [dict(t=w["word"].strip(), s=w["start"], e=w["end"]) for seg in json.load(open(CFG["whisper"]))["segments"] for w in seg.get("words", [])]
    i = 0
    while i < len(W_):
        for toks, rep in CFG["merges"]:
            n = len(toks)
            if tuple(bare(w["t"]).strip(".,") for w in W_[i:i+n]) == tuple(toks):
                W_[i:i+n] = [dict(t=rep, s=W_[i]["s"], e=W_[i+n-1]["e"])]; break
        i += 1
    for w in W_: w["t"] = CFG["fixes"].get(w["t"], CFG["fixes"].get(bare(w["t"]).strip(".,"), w["t"]))
    W_ = [w for w in W_ if bare(w["t"]).strip(".,")]
    n = max(1, int(CFG["cap_words"]))
    chunks = []
    if n == 1: chunks = [[w] for w in W_]
    else:
        cur = []
        for w in W_:
            if cur and (len(cur) >= n or w["s"] - cur[-1]["e"] > .35): chunks.append(cur); cur = []
            cur.append(w)
            if re.search(r"[,!?]$|(?<!\w\.\w)\.$", w["t"]): chunks.append(cur); cur = []
        if cur: chunks.append(cur)
    caps = []
    for j, c in enumerate(chunks):
        s = c[0]["s"]; nxt = chunks[j+1][0]["s"] if j + 1 < len(chunks) else DUR
        e = nxt if nxt - c[-1]["e"] < .8 else c[-1]["e"] + .45      # hold the word until the next one, unless there's a real pause
        e = max(e, s + .06)
        caps.append(dict(s=round(s, 3), e=round(min(e, DUR), 3), end=bool(re.search(r"[.?!]$", c[-1]["t"])),
                         w=[dict(t=re.sub(r"[.,]+$", "", x["t"]), em=bare(x["t"]).strip(".,") in CFG["emph"]) for x in c]))
    return caps

# ============================ media prep for windows ============================
def prep_media(it, OUT, FPS, dsf):
    """Video/GIF -> frame PNGs at the render fps (scaled to the window width at device pixels). Image -> copied + measured.
    Returns dict(kind, n, h) where h = displayed height in canvas px when fit='width'."""
    src = pathlib.Path(it["media"]).expanduser(); d = OUT / "media" / it["id"]; d.mkdir(parents=True, exist_ok=True)
    meta = d / "meta.json"
    off = float(it.get("offset", 0) or 0); length = it["b"] - it["a"] + .5
    if meta.exists():
        m = json.loads(meta.read_text())
        if m.get("src") == str(src) and m.get("mtime") == src.stat().st_mtime and m.get("w") == it["w"] and m.get("fit") == it["fit"] and m.get("off") == off and m.get("len", 0) >= length - .01: return m
    for f in d.glob("*.png"): f.unlink()
    pw = int(round(it["w"] * dsf))
    if src.suffix.lower() in IMG_EXT:
        ff("-i", src, "-vf", f"scale={pw}:-2", d / "00000.png"); n = 1
    else:
        ff("-ss", f"{off:.3f}", "-t", f"{length:.3f}", "-i", src, "-vf", f"fps={FPS},scale={pw}:-2", d / "%05d.png"); n = len(list(d.glob("*.png")))
        os.rename(d / "00001.png", d / "00000.png") if (d / "00001.png").exists() and not (d / "00000.png").exists() else None
        for k in range(1, n):  # renumber to 0-based
            if (d / f"{k+1:05d}.png").exists(): os.rename(d / f"{k+1:05d}.png", d / f"{k:05d}.png")
    v = probe(d / "00000.png", "width,height")
    m = dict(src=str(src), mtime=src.stat().st_mtime, w=it["w"], fit=it["fit"], off=off, len=length, n=n, h=v["height"] / dsf, kind="image" if n == 1 else "frames")
    meta.write_text(json.dumps(m)); return m

# ============================ page ============================
CSS = """@font-face{font-family:'NYI';src:url('file:///System/Library/Fonts/NewYorkItalic.ttf');font-style:italic}
@font-face{font-family:'NYR';src:url('file:///System/Library/Fonts/NewYork.ttf')}
*{margin:0;box-sizing:border-box}html,body{background:transparent}
body{width:1080px;height:1920px;overflow:hidden;position:relative;font-family:FONT;font-weight:700;-webkit-font-smoothing:antialiased}
.sh{text-shadow:0 6px 22px rgba(0,0,0,.6),0 2px 5px rgba(0,0,0,.5),0 0 2px rgba(0,0,0,.3)}
#title{position:absolute;left:40px;right:40px;text-align:center;line-height:1.08;letter-spacing:-.5px;color:#fff;transform-origin:50% 50%;opacity:0}
#title .l2{color:ACC}
#cap{position:absolute;left:60px;right:60px;text-align:center;line-height:1.1;letter-spacing:-2px;color:#fff;transform-origin:50% 50%;white-space:nowrap}
#cap .em{color:HERO}
#cap.boxed{font-weight:700;letter-spacing:-1.5px;line-height:1.5}#cap.boxed .box{background:rgba(12,10,12,.9);padding:10px 22px;border-radius:12px;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.it{position:absolute;opacity:0;will-change:transform,opacity}
.stk{display:flex;align-items:center;justify-content:center;filter:drop-shadow(0 8px 18px rgba(0,0,0,.35))}
.stk img,.stk svg{width:100%;height:100%;object-fit:contain}
.stk .emo{line-height:1;filter:drop-shadow(0 6px 10px rgba(0,0,0,.3))}
.plate-white{background:#fff;border-radius:28%;box-shadow:0 18px 40px -12px rgba(0,0,0,.5)}
.plate-dark{background:linear-gradient(160deg,#2a2a30,#0e0e12);border-radius:28%;box-shadow:0 18px 40px -12px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.12)}
.plate-round{border-radius:50%!important;overflow:hidden;background:linear-gradient(160deg,rgba(255,255,255,.6),rgba(255,255,255,.2));border:3px solid rgba(255,255,255,.8);box-shadow:0 18px 40px -12px rgba(0,0,0,.5)}.plate-round img{object-fit:cover;object-position:50% 0}.plate-flag{overflow:hidden;border:3px solid rgba(255,255,255,.85);box-shadow:0 18px 40px -12px rgba(0,0,0,.5);background:#fff}.plate-flag img{object-fit:cover}.plate-glass{background:linear-gradient(160deg,rgba(255,255,255,.55),rgba(255,255,255,.18));border:2px solid rgba(255,255,255,.55);border-radius:28%;backdrop-filter:blur(8px);box-shadow:0 18px 40px -12px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.7)}
.scene{position:absolute;inset:0;background:BGC;color:#d7dae0;font-family:FONT;font-weight:500;overflow:hidden;font-size:22px}
.scene .tb{height:54px;background:#171a21;border-bottom:1px solid #262a33;display:flex;align-items:center;padding:0 18px;gap:9px;font-size:17px;color:#8a90a0}
.scene .tb i{width:14px;height:14px;border-radius:50%;display:inline-block}.scene .tb b{margin-left:14px;color:#fff;font-weight:600}
.scene .body{padding:22px 28px;line-height:1.5}
.sc-terminal .body,.sc-doc .body{font-family:'SF Mono',Menlo,monospace;font-size:21px}
.sc-terminal .cmd{color:#fff}.sc-terminal .cmd:before{content:'> ';color:ACC}.sc-terminal .ok{color:#9fe3a1}.sc-terminal .ok:before{content:'\\2713  '}
.sc-terminal .last{color:ACC}
.cur{display:inline-block;width:12px;height:1.1em;background:ACC;vertical-align:-3px;margin-left:2px}
.sc-doc .h1{font-size:30px;color:#fff;font-weight:700;margin-bottom:10px}.sc-doc .h2{color:ACC;margin-top:14px;font-weight:700}
.sc-chat .scene-bg{background:#121216}.sc-chat{display:flex;flex-direction:column}.sc-chat .ch{flex:none;height:66px;display:flex;align-items:center;gap:12px;padding:0 20px;background:#1a1a20;border-bottom:1px solid #2a2a32}.sc-chat .av{width:42px;height:42px;border-radius:50%;background:#2e2e37;display:flex;align-items:center;justify-content:center;font-size:22px}.sc-chat .nm{display:flex;flex-direction:column;line-height:1.15}.sc-chat .nm b{color:#fff;font-size:18px;font-weight:600}.sc-chat .nm span{color:#8a8f9c;font-size:13px}.sc-chat .dots{margin-left:auto;display:flex;gap:4px}.sc-chat .dots i{width:5px;height:5px;border-radius:50%;background:#8a8f9c}.sc-chat .body{flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-end;gap:14px;font-size:28px;padding:22px 26px;line-height:1.3}.sc-chat .h{opacity:.42;font-size:24px}.sc-chat .day{align-self:center;color:#6f7482;font-size:14px;margin:2px 0 4px}.sc-chat .ty{align-self:flex-start;background:#2a2a31;border-radius:22px 22px 22px 6px;padding:16px 18px;display:none;gap:6px}.sc-chat .ty i{width:9px;height:9px;border-radius:50%;background:#9aa0ad}.sc-chat .cp{flex:none;height:60px;margin:0 20px 18px;border-radius:30px;background:#1e1e25;border:1px solid #2d2d37;display:flex;align-items:center;padding:0 22px;color:#6f7482;font-size:18px}.sc-chat .cp b{margin-left:auto;width:34px;height:34px;border-radius:50%;background:ACC;color:INK;display:flex;align-items:center;justify-content:center;font-size:18px}
.sc-chat .chips{display:flex;gap:10px}.sc-chat .chip{background:#26262c;border:1px solid #3a3a44;border-radius:12px;padding:6px 12px;font-size:17px;color:#cfd0d6}
.sc-chat .u{align-self:flex-end;background:ACC;border-radius:22px 22px 6px 22px;padding:14px 20px;max-width:84%;color:INK;font-weight:700}
.sc-chat .a{align-self:flex-start;background:#2a2a31;border-radius:22px 22px 22px 6px;padding:14px 20px;max-width:84%;color:#e4e5ea;display:none}.sc-chat .a b{color:ACC;font-weight:700}
.sc-browser .url{flex:1;background:#0f1115;border-radius:10px;height:34px;display:flex;align-items:center;padding:0 14px;color:#9aa0ad;font-size:16px;margin-left:10px}
.sc-browser .hero{text-align:center;padding:38px 30px 20px}.sc-browser .hero h1{font-size:40px;font-weight:800;color:#fff;letter-spacing:-1px;line-height:1.1}
.sc-browser .hero p{color:#9aa0ad;margin:12px auto 0;font-size:19px;max-width:80%}.sc-browser .btn{display:inline-block;margin-top:18px;background:ACC;color:#111;font-weight:700;padding:12px 26px;border-radius:999px;font-size:19px}
.sc-browser .cards{display:flex;gap:14px;padding:10px 30px}.sc-browser .cardx{flex:1;background:#171a21;border:1px solid #262a33;border-radius:16px;padding:16px;font-size:17px;color:#cfd3dc;min-height:90px}
.sc-browser .el{opacity:0;transform:translateY(18px)}
.sc-search .bar{margin:46px 40px 24px;background:#fff;border-radius:999px;height:72px;display:flex;align-items:center;padding:0 28px;font-size:27px;color:#111;box-shadow:0 10px 30px rgba(0,0,0,.35)}
.sc-search .bar:before{content:'';width:24px;height:24px;border:3px solid #666;border-radius:50%;margin-right:18px;box-sizing:border-box}
.sc-search .res{margin:0 40px;background:#fff;border-radius:22px;overflow:hidden;color:#222;font-size:24px}.sc-search .r{padding:16px 28px;border-top:1px solid #eee;opacity:0}.sc-search .r:first-child{border:0}
.sc-search .r span{color:#999}.sc-search{background:#e9ebf0}
.sc-code .body{font-family:'SF Mono',Menlo,monospace;font-size:19px;line-height:1.6}.sc-code .ln{display:flex;gap:18px}.sc-code .no{width:28px;text-align:right;color:#4a5060}
.sc-code .kw{color:#c678dd}.sc-code .st{color:#98c379}.sc-code .cm{color:#5c6370}.sc-code .nu{color:#d19a66}
.sc-chart .body{height:100%;display:flex;flex-direction:column}.sc-chart .ct{font-size:22px;color:#9aa0ad;margin-bottom:6px}
.sc-chart .bars{flex:1;display:flex;gap:22px;align-items:flex-end;padding:40px 10px 0}.sc-chart .bw{flex:1;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end}
.sc-chart .bar{width:100%;background:linear-gradient(180deg,#3b4254,#262b36);border-radius:12px 12px 4px 4px;min-height:4px}.sc-chart .bar.acc{background:linear-gradient(180deg,ACC,ACC2)}
.sc-chart .bv{font-size:30px;font-weight:800;color:#fff;letter-spacing:-1px;margin-bottom:8px}.sc-chart .bl{font-size:17px;color:#9aa0ad;margin-top:10px}
.sc-counter .body{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
.sc-counter .big{font-size:150px;font-weight:900;letter-spacing:-6px;color:ACC;line-height:1}.sc-counter .lab{font-size:28px;color:#fff;margin-top:10px;font-weight:600}.sc-counter .sub{font-size:20px;color:#9aa0ad;margin-top:8px}
.sc-phone{background:transparent}.sc-phone .ph{position:absolute;inset:0;background:linear-gradient(170deg,#1c1d24,#0b0b0f);border:10px solid #111;border-radius:58px;overflow:hidden}
.sc-phone .notch{position:absolute;left:50%;top:14px;width:36%;height:30px;background:#000;border-radius:999px;transform:translateX(-50%)}
.sc-phone .time{position:absolute;left:28px;top:18px;color:#fff;font-size:20px;font-weight:600}.sc-phone .wall{position:absolute;inset:0;background:radial-gradient(circle at 30% 20%,rgba(212,255,63,.25),transparent 55%),radial-gradient(circle at 80% 90%,rgba(120,140,255,.25),transparent 50%)}
.sc-phone .nt{position:relative;margin:0 14px 10px;background:rgba(40,40,48,.92);border-radius:22px;padding:14px;display:flex;gap:12px;color:#fff;opacity:0;backdrop-filter:blur(10px)}
.sc-phone .nt:first-of-type{margin-top:70px}.sc-phone .ni{width:46px;height:46px;border-radius:12px;background:linear-gradient(160deg,#ff6a88,#ff99ac);display:flex;align-items:center;justify-content:center;font-size:26px;flex:none}
.sc-phone .nh{display:flex;justify-content:space-between;font-size:15px;color:#b9bcc7}.sc-phone .nh b{color:#fff}.sc-phone .ni.im{background:#fff;padding:6px;overflow:hidden}.sc-phone .ni img{position:static!important;width:100%!important;height:100%!important;object-fit:contain;transform:none!important}.sc-flow .ne img{position:static!important;height:1em!important;width:auto!important;max-width:2.4em;object-fit:contain;vertical-align:middle;transform:none!important}.sc-phone .nt1{font-size:19px;font-weight:600;margin-top:2px}.sc-phone .nt2{font-size:18px;color:#d9dbe3}
.sc-flow .fl{height:100%;display:flex;align-items:center;justify-content:center;gap:10px;padding:20px}.sc-flow .nd{background:#171a21;border:1px solid #2a2f3a;border-radius:20px;padding:18px 20px;text-align:center;min-width:120px;opacity:0}
.sc-flow .nd.acc{border-color:ACC;background:ACC}.sc-flow .ne{font-size:40px;line-height:1}.sc-flow .nl{font-size:21px;font-weight:700;color:#fff;margin-top:8px}.sc-flow .nd.acc .nl{color:INK}.sc-flow .ar{width:56px;height:24px;flex:none}
.sc-checklist .ck{display:flex;align-items:center;gap:16px;font-size:26px;font-weight:700;color:#fff;padding:9px 0;opacity:0}.sc-checklist .ck svg{width:32px;height:32px;flex:none}.sc-checklist .ck.done span{color:#9aa0ad;text-decoration:line-through}
.sc-checklist .pg{height:8px;background:#262a33;border-radius:999px;margin-top:14px;overflow:hidden}.sc-checklist .pf{height:100%;background:ACC;border-radius:999px;transition:none}
.sc-browser .toast{position:absolute;left:50%;bottom:22px;transform:translateX(-50%);background:#fff;color:#111;font-weight:700;font-size:19px;padding:12px 22px;border-radius:999px;box-shadow:0 10px 30px rgba(0,0,0,.4);opacity:0;white-space:nowrap}
.sc-browser .mcur{position:absolute;left:0;top:0;opacity:0;filter:drop-shadow(0 3px 6px rgba(0,0,0,.45))}
.sc-stats .ct,.sc-timeline .ct{font-size:22px;color:#9aa0ad;margin-bottom:14px}
.sc-stats .tiles{display:flex;gap:16px}.sc-stats .tile{flex:1;background:#171a21;border:1px solid #262a33;border-radius:18px;padding:18px 18px 10px;opacity:0;position:relative;overflow:hidden}
.sc-stats .tl{font-size:16px;color:#9aa0ad}.sc-stats .tv{font-size:46px;font-weight:900;color:ACC;letter-spacing:-2px;margin-top:4px}.sc-stats .td{font-size:15px;font-weight:700;margin-top:4px}.sc-stats .up{color:#7ddc8a}.sc-stats .dn{color:#ff7b7b}
.sc-stats .sp{width:100%;height:34px;margin-top:8px;opacity:.9}
.sc-timeline .tlb{height:100%;display:flex;flex-direction:column;justify-content:center}.sc-timeline .track{position:relative;height:6px;background:#262a33;border-radius:999px;margin:70px 60px 90px}
.sc-timeline .fill{position:absolute;left:0;top:0;height:100%;background:ACC;border-radius:999px}.sc-timeline .pt{position:absolute;top:-10px;transform:translateX(-50%);text-align:center;opacity:0;width:180px}
.sc-timeline .dot{width:26px;height:26px;border-radius:50%;background:#fff;border:5px solid #262a33;margin:0 auto}.sc-timeline .pt.acc .dot{background:ACC;border-color:#5a5320}
.sc-timeline .yr{position:absolute;top:-46px;left:0;right:0;font-size:22px;font-weight:800;color:#fff}.sc-timeline .pt.acc .yr{color:ACC}.sc-timeline .tx{margin-top:10px;font-size:17px;color:#b7bcc8}
.sc-kanban .kb{display:flex;gap:14px;height:calc(100% - 54px);padding:16px}.sc-kanban .col{flex:1;background:#13161c;border-radius:16px;padding:12px;display:flex;flex-direction:column;gap:10px}
.sc-kanban .ch{font-size:16px;color:#9aa0ad;font-weight:600;display:flex;justify-content:space-between}.sc-kanban .cnt{background:#262a33;border-radius:999px;padding:0 9px;font-size:14px}
.sc-kanban .kc{background:#1e222b;border:1px solid #2a2f3a;border-radius:12px;padding:10px 12px;font-size:17px;color:#e4e5ea;display:flex;justify-content:space-between;align-items:center;gap:8px}
.sc-kanban .kc i{font-style:normal;font-size:12px;background:#2f3440;color:#cfd3dc;border-radius:999px;padding:2px 8px}.sc-kanban .kc.done{border-color:ACC;color:#fff}.sc-kanban .kc.done span:before{content:'\\2713 ';color:ACC}
.sc-quote .qb{height:100%;display:flex;flex-direction:column;justify-content:center;padding:34px 44px}.sc-quote .qm{font-size:110px;line-height:.6;color:ACC;font-family:Georgia,serif;margin-bottom:6px}
.sc-quote .qt{font-size:30px;line-height:1.3;color:#fff;font-weight:600;letter-spacing:-.3px;min-height:1.3em}.sc-quote .qa{display:flex;align-items:center;gap:14px;margin-top:24px;opacity:0}
.sc-quote .av{width:52px;height:52px;border-radius:50%;background:linear-gradient(160deg,#ffb86b,#ff6a88);display:flex;align-items:center;justify-content:center;font-weight:800;color:#111;font-size:24px}
.sc-quote .qn{font-size:19px;font-weight:700;color:#fff}.sc-quote .qr{font-size:15px;color:#9aa0ad}.sc-quote .stars{margin-left:auto;color:ACC;font-size:20px;letter-spacing:2px}
.sc-email .eb{padding:8px 0}.sc-email .em{display:flex;gap:14px;padding:14px 22px;border-bottom:1px solid #1f232b;opacity:0;align-items:center}
.sc-email .eav{width:46px;height:46px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;font-size:20px;flex:none}
.sc-email .et{flex:1;min-width:0}.sc-email .ef{display:flex;justify-content:space-between;font-size:18px;font-weight:700;color:#fff}.sc-email .ef span{font-weight:500;color:#8a90a0;font-size:15px}
.sc-email .es{font-size:17px;color:#e4e5ea;margin-top:2px}.sc-email .ep{font-size:15px;color:#8a90a0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sc-email .ebd{background:ACC;color:#111;font-weight:800;font-size:14px;border-radius:999px;padding:4px 10px}
.sc-dashboard .db{position:absolute;inset:0;display:flex;background:#0d0f14}.sc-dashboard .side{width:190px;background:#111318;border-right:1px solid #1e222b;padding:22px 16px}
.sc-dashboard .lg{font-size:21px;font-weight:800;color:#fff;margin-bottom:22px;letter-spacing:-.5px}.sc-dashboard .nv{font-size:16px;color:#8a90a0;padding:9px 12px;border-radius:10px;margin-bottom:4px}.sc-dashboard .nv.on{background:#1e222b;color:#fff}
.sc-dashboard .main{flex:1;padding:22px 24px;display:flex;flex-direction:column;gap:16px;min-width:0}.sc-dashboard .hd{font-size:24px;font-weight:700;color:#fff;display:flex;justify-content:space-between;align-items:center}
.sc-dashboard .pill{font-size:14px;color:#cfd3dc;background:#1e222b;border-radius:999px;padding:5px 12px;font-weight:600}.sc-dashboard .kp{display:flex;gap:12px}
.sc-dashboard .k{flex:1;background:#151920;border:1px solid #232834;border-radius:14px;padding:14px;opacity:0}.sc-dashboard .kl{font-size:14px;color:#8a90a0}.sc-dashboard .kv{font-size:28px;font-weight:800;color:#fff;letter-spacing:-.5px}
.sc-dashboard .row{display:flex;gap:12px;flex:1;min-height:0}.sc-dashboard .chart{flex:1.4;background:#151920;border:1px solid #232834;border-radius:14px;padding:14px;display:flex;flex-direction:column}
.sc-dashboard .cl{font-size:14px;color:#8a90a0;margin-bottom:8px}.sc-dashboard .bars{flex:1;display:flex;align-items:flex-end;gap:6px}.sc-dashboard .b{flex:1;background:#2a3040;border-radius:4px 4px 2px 2px;min-height:2px}.sc-dashboard .b.acc{background:ACC}
.sc-dashboard .list{flex:1;background:#151920;border:1px solid #232834;border-radius:14px;padding:8px 14px;display:flex;flex-direction:column;justify-content:center}.sc-dashboard .lr{display:flex;justify-content:space-between;font-size:16px;color:#cfd3dc;padding:8px 0;border-bottom:1px solid #1f232b;opacity:0}.sc-dashboard .lr b{color:#fff}
.fullp .scene>.body{position:absolute;left:0;right:0;top:50%;transform:translateY(-50%);padding:40px 60px;height:auto}
.fullp .sc-chart .body{height:760px}.fullp .sc-chart .bars{padding-top:60px}.fullp .sc-chart .bv{font-size:40px}.fullp .sc-chart .bl{font-size:24px}.fullp .sc-chart .ct{font-size:30px}
.fullp .sc-stats .ct{font-size:30px}.fullp .sc-stats .tile{padding:28px 26px 16px}.fullp .sc-stats .tl{font-size:22px}.fullp .sc-stats .tv{font-size:64px}.fullp .sc-stats .td{font-size:20px}.fullp .sc-stats .sp{height:56px}
.fullp .sc-stats .tiles{flex-direction:column;gap:18px}.fullp .sc-stats .tiles .tile{display:grid;grid-template-columns:1fr 1fr;align-items:center}.fullp .sc-stats .sp{grid-column:2;grid-row:1/4}
.fullp .sc-timeline .tlb{height:auto}.fullp .sc-cards .body{height:auto;flex-direction:column}.fullp .sc-cards .c{padding:36px}.fullp .sc-cards .c .t{font-size:44px}.fullp .sc-cards .c .s{font-size:24px}.fullp .sc-cards .c .e{font-size:90px}
.fullp .sc-counter .body{height:auto}.fullp .sc-counter .big{font-size:170px}.fullp .sc-counter .lab{font-size:36px}.fullp .sc-counter .sub{font-size:26px}
.sc-cinematic{background:#000}.sc-cinematic .cv{position:absolute;inset:0;width:100%;height:100%}
.scene .mcv{position:absolute;inset:0;width:100%;height:100%}.scene .grain{position:absolute;inset:0;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='120' height='120' filter='url(%23n)' opacity='.5'/%3E%3C/svg%3E");opacity:.07;mix-blend-mode:overlay;pointer-events:none}
.sc-cinematic .grain{position:absolute;inset:0;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='120' height='120' filter='url(%23n)' opacity='.5'/%3E%3C/svg%3E");opacity:.09;mix-blend-mode:overlay}
.sc-cinematic .hl{position:absolute;left:60px;right:60px;bottom:38%;font-size:64px;font-weight:800;color:#fff;letter-spacing:-2px;line-height:1.05;text-shadow:0 8px 30px rgba(0,0,0,.6);opacity:0}
.sc-cinematic .sb{position:absolute;left:60px;right:60px;bottom:33%;font-size:26px;color:rgba(255,255,255,.85);opacity:0}
.sc-reveal{background:#000}.sc-reveal .rv{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px}
.sc-reveal .rl{width:120px;height:120px;object-fit:contain;opacity:0;margin-bottom:18px}.sc-reveal .rb{font-size:76px;font-weight:800;color:#fff;letter-spacing:-3px;line-height:1}.sc-reveal .rb span{display:inline-block;opacity:0}
.sc-reveal .rs{font-size:40px;color:#cfd0d6;font-weight:500;min-height:1.2em;letter-spacing:-.5px}.sc-reveal .rt{margin-top:26px;font-size:20px;color:#8a90a0;background:#15161c;border:1px solid #2a2b33;border-radius:999px;padding:8px 18px;opacity:0}
.sc-progress .pg{display:flex;flex-direction:column;gap:18px;height:calc(100% - 54px);padding:26px 30px}.sc-progress .pq{font-size:19px;color:#9aa0ad;line-height:1.45;background:#171a21;border:1px solid #262a33;border-radius:14px;padding:12px 16px}
.sc-progress .pcard{background:#171a21;border:1px solid #262a33;border-radius:18px;padding:26px;display:flex;flex-direction:column;align-items:center;gap:8px}.sc-progress .pct{font-size:64px;font-weight:800;color:#fff;letter-spacing:-2px;line-height:1}.sc-progress .plabel{font-size:17px;color:#9aa0ad}
.sc-progress .pbar{width:100%;height:6px;background:#262a33;border-radius:999px;margin-top:10px;overflow:hidden}.sc-progress .pfill{height:100%;background:ACC;border-radius:999px}
.sc-progress .pl{font-size:17px;color:#cfd3dc;padding:5px 0;opacity:0}.sc-progress .pl:before{content:'\\2713  ';color:ACC}
.sc-cards .body{display:flex;gap:18px;align-items:stretch;justify-content:center;height:100%;padding:28px}
.sc-cards .c{flex:1;background:#171a21;border:1px solid #2a2f3a;border-radius:22px;padding:22px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;opacity:0}
.sc-cards .c .e{font-size:64px;line-height:1}.sc-cards .c .t{font-size:30px;font-weight:700;color:#fff;margin-top:12px;letter-spacing:-.5px}.sc-cards .c .s{font-size:19px;color:#9aa0ad;margin-top:6px}
.sc-cards .c.acc{background:ACC;border-color:ACC}.sc-cards .c.acc .t{color:INK}.sc-cards .c.acc .s{color:INK}
.win{overflow:hidden;background:#111;transform-style:preserve-3d}
.win.sh{box-shadow:0 36px 80px -22px rgba(0,0,0,.6),0 10px 24px -10px rgba(0,0,0,.4);text-shadow:none}
.win.dark{border:5px solid #121212}
.win img{display:block;position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover}
.win.fitw img{height:auto}
.txt{white-space:nowrap;line-height:1;color:#fff}
.txt.em{color:ACC}
.card{display:flex;align-items:center;gap:22px;background:#fff;border-radius:40px;padding:26px 36px;box-shadow:0 30px 60px -24px rgba(0,0,0,.55);text-shadow:none;white-space:nowrap}
.card .k{font-size:30px;font-weight:600;color:#6B6A5E}.card .v{font-size:62px;letter-spacing:-1px;line-height:1;color:#111}
.card .chip{margin-left:12px;font-size:28px;color:#fff;background:#C62828;padding:12px 18px;border-radius:999px;transform:rotate(-4deg)}
.bgl.soft{-webkit-mask-image:linear-gradient(#000 78%,transparent 100%);mask-image:linear-gradient(#000 78%,transparent 100%)}
.bgl .scene>.body{position:absolute;left:0;right:0;top:0;transform:none;height:auto;max-height:33%;padding:36px 44px;overflow:hidden}
.win.bgl{background:linear-gradient(#0d1016,#05070b)}
.win.scrim:after{content:'';position:absolute;inset:0;background:linear-gradient(rgba(0,0,0,.55),rgba(0,0,0,.15) 45%,rgba(0,0,0,0) 70%);pointer-events:none}
.win.bgl img{filter:brightness(.55) saturate(.85)}   /* footage behind the speaker is dimmed so the person and the words read over it */
.bgl .sc-cinematic .hl{top:7%;bottom:auto}.bgl .sc-cinematic .sb{top:19%;bottom:auto}.bgl .sc-chat .body{gap:10px}
.bgl .sc-stats .tiles{flex-direction:row}.bgl .sc-timeline .tlb{height:auto}.bgl .sc-timeline .track{margin:70px 60px 70px}
.fx{pointer-events:none}.bars .bt,.bars .bb{position:absolute;left:0;right:0;background:#000}.bars .bt{top:0}.bars .bb{bottom:0}
.cur svg{filter:drop-shadow(0 3px 6px rgba(0,0,0,.45))}
.ph{position:absolute;left:0;top:0;width:1080px;height:1920px;pointer-events:none}
.ph .w{position:absolute;white-space:nowrap;opacity:0;transform-origin:50% 50%;text-shadow:0 4px 18px rgba(0,0,0,.45),0 1px 2px rgba(0,0,0,.35)}
.ph .hero{font-family:FONTHERO;font-weight:700;letter-spacing:-.055em;color:HERO;line-height:.9;text-shadow:HEROSH}
.ph .big{font-family:FONTHERO;font-weight:700;letter-spacing:-.05em;color:#fff;line-height:.9}
.ph .small{font-family:FONTHERO;font-weight:500;letter-spacing:-.01em;color:#fff}
.ph .serif{font-family:FONTSERIF;font-style:italic;font-weight:400;color:#fff;letter-spacing:-.01em}
.ph .ink{color:INK;text-shadow:none}
.ph svg{position:absolute;left:0;top:0;overflow:visible}
.leak{position:absolute;left:0;top:0;width:1080px;height:1920px;opacity:0;pointer-events:none}
.fontwarm{position:absolute;left:-9999px;top:0;opacity:0}""".replace("FONTHERO", FONT_HERO).replace("FONTSERIF", FONT_SERIF).replace("FONT", FONT)   # ACC / LIME / INK / BGC are filled per reel from the theme in page()

CURSOR_SVG = ("<svg viewBox='0 0 24 24' width='S' height='S'><path d='M4 2 L4 19 L8.6 14.8 L11.6 21.4 L14.6 20 L11.7 13.6 L18 13.4 Z' fill='#fff' stroke='#000' stroke-width='1.3' stroke-linejoin='round'/></svg>")

def circle_path(w, h, width):
    """Slightly irregular ellipse that overshoots a quarter turn, like a marker pen."""
    pts = []
    for k in range(0, 76):
        a = -0.9 + 2 * math.pi * 1.18 * k / 75
        wob = 1 + 0.045 * math.sin(a * 3 + 1.1) + 0.03 * math.cos(a * 5 + .4)
        pts.append((w / 2 + (w / 2 - width) * wob * math.cos(a), h / 2 + (h / 2 - width) * wob * math.sin(a)))
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    return (f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}' style='overflow:visible'><path class='d' d='{d}' fill='none' stroke='{RED}' "
            f"stroke-width='{width}' stroke-linecap='round' stroke-linejoin='round' pathLength='1'/></svg>")

def img_uri(p): return pathlib.Path(p).expanduser().resolve().as_uri()

def body(CFG, ITEMS, MEDIA):
    h = ""
    if CFG["title"]:
        T = CFG["title"]; ls = T["lines"]
        h += f"<div id='title' class='sh' style='top:{T.get('y', 270)}px;font-size:{T.get('size', 66)}px'>" + "<br>".join(
            f"<span class='{'l2' if i == T.get('accent_line', 1) else ''}'>{l}</span>" for i, l in enumerate(ls)) + "</div>"
    for it in ITEMS:
        k = it["kind"]
        if k == "sticker":
            src = it["src"]
            inner = src if src.lstrip().startswith("<svg") else (f"<img src='{img_uri(src)}'>" if "/" in src or src.lower().endswith((".svg", ".png", ".webp", ".jpg"))
                                                               else f"<span class='emo' style='font-size:{int(it['size']*.78)}px'>{src}</span>")
            W_, H_ = it.get("w", it["size"]), it.get("h", it["size"]); pad = 0 if it["plate"] in ("none", "round", "flag") else int(it["size"] * .16)
            rad = f"border-radius:{int(H_ * (.14 if it['plate'] == 'flag' else .28))}px;" if it["plate"] not in ("none", "round") else ""
            h += (f"<div class='it stk plate-{it['plate']}' id='{it['id']}' style='left:{it['x']-W_/2}px;top:{it['y']-H_/2}px;width:{W_}px;height:{H_}px;padding:{pad}px;{rad}'>{inner}</div>")
        elif k == "window":
            m = MEDIA[it["id"]]; cls = "it win" + (" sh" if it["shadow"] else "") + (" dark" if it["frame"] == "dark" else "") + (" fitw" if it["fit"] == "width" else "")
            inner = f"<div class='scene sc-{it['scene']['kind']}' id='{it['id']}_sc'></div>" if it["scene"] else f"<img id='{it['id']}_img' src='media/{it['id']}/00000.png'>"
            if it["w"] >= 1080 and it["h"] >= 1900: cls += " fullp"
            if it.get("push") and it["media"]: cls += " scrim"   # half-screen footage: a soft dark gradient at the top so the phrase stays readable on light films
            if it.get("person"): cls += " bgl" + (" soft" if it["h"] < 1900 else "")
            h += f"<div class='{cls}' id='{it['id']}' style='left:{it['x']}px;top:{it['y']}px;width:{it['w']}px;height:{it['h']}px;border-radius:{it['radius']}px'>{inner}</div>"
        elif k == "text":
            st = f"left:{it['x']}px;top:{it['y']}px;font-size:{it['size']}px;font-weight:{it['weight']}" + (f";color:{it['color']}" if it["color"] else "")
            if it["anchor"] == "center": st += ";transform:translateX(-50%)"
            h += f"<div class='it txt sh {'em' if it['em'] else ''}' id='{it['id']}' style='{st}'>{it['s']}</div>"
        elif k == "circle":
            h += f"<div class='it' id='{it['id']}' style='left:{it['x']-it['w']/2}px;top:{it['y']-it['h']/2}px'>{circle_path(it['w'], it['h'], it['width'])}</div>"
        elif k == "card":
            h += (f"<div class='it card' id='{it['id']}' style='left:{it['x']}px;top:{it['y']}px'><div><div class='k'>{it['label']}</div><div class='v'>{it['value']}</div></div>"
                  + (f"<div class='chip'>{it['chip']}</div>" if it["chip"] else "") + "</div>")
        elif k == "phrase":
            h += f"<div class='it ph' id='{it['id']}'></div>"
        elif k == "iconrow":
            n = len(it["icons"]); ws = [ic.get("w", it["size"]) for ic in it["icons"]]; total = sum(ws) + (n - 1) * it["gap"]; cx = it["x"] - total / 2
            cells = ""
            for j, ic in enumerate(it["icons"]):
                src = ic["src"]; pl = ic.get("plate", it["plate"]); pad = 0 if pl in ("none", "round", "flag") else int(it["size"] * .16)
                rad = f"border-radius:{int(it['size'] * (.14 if pl == 'flag' else .28))}px;" if pl not in ("none", "round") else ""
                inner = src if src.lstrip().startswith("<svg") else (f"<img src='{img_uri(src)}'>" if "/" in src or src.lower().endswith((".svg", ".png", ".webp", ".jpg")) else f"<span class='emo' style='font-size:{int(it['size']*.72)}px'>{src}</span>")
                cells += f"<div class='stk plate-{pl} ic' style='position:absolute;left:{cx}px;top:0;width:{ws[j]}px;height:{it['size']}px;padding:{pad}px;{rad}opacity:0'>{inner}</div>"; cx += ws[j] + it["gap"]
            h += f"<div class='it' id='{it['id']}' style='left:0;top:{it['y'] - it['size'] / 2}px;width:1080px;height:{it['size']}px'>{cells}</div>"
        elif k == "leak":
            h += f"<div class='it leak' id='{it['id']}'></div>"
        elif k == "fx":
            pass   # composited in ffmpeg (see fx_chain)
        elif k == "flash":
            h += f"<div class='it fx' id='{it['id']}' style='left:0;top:0;width:1080px;height:1920px;background:{it['color']}'></div>"
        elif k == "bars":
            h += (f"<div class='it bars' id='{it['id']}' style='left:0;top:0;width:1080px;height:1920px'><div class='bt' style='height:{it['size']}px'></div><div class='bb' style='height:{it['size']}px'></div></div>")
        elif k == "burst":
            h += f"<div class='it' id='{it['id']}' style='left:{it['x']-it['spread']}px;top:{it['y']-it['spread']}px;width:{it['spread']*2}px;height:{it['spread']*2}px'><canvas width='{it['spread']*2}' height='{it['spread']*2}' style='width:100%;height:100%'></canvas></div>"
        elif k == "punch":
            pass   # footage-only effect, handled in base_filter
        elif k == "cursor":
            h += f"<div class='it cur' id='{it['id']}' style='left:0;top:0;width:{it['size']}px;height:{it['size']}px'>{CURSOR_SVG.replace('S', str(it['size']))}</div>"
    h += f"<div id='cap' class='{'boxed' if CFG['cap_style'] == 'box' else 'sh'}'></div>"
    h += "<span class='fontwarm' style='font-family:NYI;font-style:italic'>warm</span><span class='fontwarm' style=\"font-family:'Helvetica Neue';font-weight:700\">warm</span>"
    return h

JS = r"""<script>
const CAPS=__CAPS__, ITEMS=__ITEMS__, CFG=__CFG__, MEDIA=__MEDIA__, SAFE=__SAFE__;
const cl=(v,a=0,b=1)=>Math.min(b,Math.max(a,v)), ease=p=>1-Math.pow(1-cl(p),3), eio=p=>{p=cl(p);return p<.5?4*p*p*p:1-Math.pow(-2*p+2,3)/2};
const OVER=(window.THEME||{}).over||1.7, AMP=(window.THEME||{}).amp??1;   // exaggeration comes from the reel's theme
const back=(p,c=OVER)=>{p=cl(p);return 1+(c+1)*Math.pow(p-1,3)+c*Math.pow(p-1,2)};
const r=v=>Math.round(v*1000)/1000, $=id=>document.getElementById(id);
const DIN={snap:.08,pop:.22,fade:.22,up:.38,down:.38,left:.42,right:.42,wipe:.28,none:0,zoom:.45,slam:.3,flip:.5,iris:.5,spin:.5,bounce:.6,blur:.4,rise:.45,type:0,dissolve:.55},
      DOUT={snap:.08,fade:.14,pop:.16,cut:0,up:.3,down:.3,left:.3,right:.3,none:0,zoom:.3,iris:.35,slam:.18,blur:.25,dissolve:.45};
const bounce=p=>{p=cl(p); const n1=7.5625,d1=2.75; return p<1/d1?n1*p*p:p<2/d1?n1*(p-=1.5/d1)*p+.75:p<2.5/d1?n1*(p-=2.25/d1)*p+.9375:n1*(p-=2.625/d1)*p+.984375};
function enter(it,t){const d=(DIN[it.anim]??.2)*(CFG.smooth||1), p=d?cl((t-it.a)/d):1, dist=it.dist||(it.kind==='window'?760:120);
  switch(it.anim){
    case 'snap': return [cl(p*1.6), `scale(${r(.985+.015*ease(p))})`];   // top-half insert: lands with the sliding footage, fast, no drift
    case 'pop': return [cl(p*3), `scale(${r(1-.8*AMP+.8*AMP*back(p))}) rotate(${r(-10*AMP*(1-ease(p)))}deg)`];   // exaggerated: from small, overshoot, a little twist
    case 'fade': return [ease(p), `scale(${r(.92+.08*ease(p))})`];
    case 'up': return [cl(p*4), `translateY(${r((1-ease(p))*dist)}px) rotate(${r((1-ease(p))*(it.kind==='window'?3:0))}deg)`];
    case 'down': return [cl(p*4), `translateY(${r(-(1-ease(p))*dist)}px)`];
    case 'left': return [cl(p*4), `translateX(${r(-(1-ease(p))*dist)}px) rotateY(${r(-(1-ease(p))*22)}deg)`];
    case 'right': return [cl(p*4), `translateX(${r((1-ease(p))*dist)}px) rotateY(${r((1-ease(p))*22)}deg)`];
    case 'wipe': return [cl(p*3), `translateX(${r(-(1-ease(p))*70)}px)`, `inset(0 0 0 ${r((1-ease(p))*100)}%)`];
    case 'zoom': return [cl(p*2.5), `scale(${r(1.7-.7*ease(p))})`, '', `blur(${r((1-ease(p))*14)}px)`];                      // push-in from big and soft
    case 'slam': return [cl(p*4), `scale(${r(2.6-1.6*ease(Math.min(1,p*1.15)))+(p>.85?.02*Math.sin((p-.85)*40):0)})`];     // drops onto the frame
    case 'flip': return [cl(p*3), `perspective(1400px) rotateX(${r(-80*(1-ease(p)))}deg)`];
    case 'iris': return [1, '', `circle(${r(ease(p)*75)}% at 50% 50%)`];
    case 'spin': return [cl(p*3), `rotate(${r(-240*(1-ease(p)))}deg) scale(${r(.3+.7*ease(p))})`];
    case 'bounce': return [cl(p*4), `translateY(${r(-(1-bounce(p))*260)}px)`];
    case 'blur': return [ease(p), '', '', `blur(${r((1-ease(p))*18)}px)`];
    case 'dissolve': return [eio(p), `scale(${r(1.04-.04*eio(p))})`, '', `blur(${r((1-eio(p))*6)}px)`];   // the smooth one: long eased cross-fade with a breath of scale
    case 'rise': return [cl(p*2.5), `translateY(${r((1-ease(p))*90)}px)`, '', `blur(${r((1-ease(p))*8)}px)`];
    default: return [1,''];
  }}
function exit_(it,t){const d=(DOUT[it.out]??.14)*(CFG.smooth||1), p=d?cl((it.b-t)/d):1;
  switch(it.out){
    case 'cut': return [1,''];
    case 'snap': return [cl(p*1.6), ''];
    case 'pop': return [cl(p*2), `scale(${r(.6+.4*p)})`];
    case 'up': return [cl(p*3), `translateY(${r(-(1-p)*500)}px)`];
    case 'down': return [cl(p*3), `translateY(${r((1-p)*700)}px)`];
    case 'left': return [cl(p*3), `translateX(${r(-(1-p)*900)}px)`];
    case 'right': return [cl(p*3), `translateX(${r((1-p)*900)}px)`];
    case 'zoom': return [p, `scale(${r(1+(1-p)*.6)})`, '', `blur(${r((1-p)*12)}px)`];
    case 'iris': return [1, '', `circle(${r(p*75)}% at 50% 50%)`];
    case 'slam': return [p, `scale(${r(1-(1-p)*.4)})`];
    case 'blur': return [p, '', '', `blur(${r((1-p)*16)}px)`];
    case 'dissolve': return [eio(p), `scale(${r(1+(1-eio(p))*.03)})`, '', `blur(${r((1-eio(p))*5)}px)`];
    default: return [p,''];
  }}
const typed=(str,n)=>n>=str.length?str:str.slice(0,Math.max(0,n))+"<span class='cur'></span>";
const esc=x=>String(x).replace(/&/g,'&amp;').replace(/</g,'&lt;');
const rnd=s=>()=>{s|=0;s=s+0x6D2B79F5|0;let t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296};
const grad=(g,W,H,stops,dir='v')=>{const G=dir==='v'?g.createLinearGradient(0,0,0,H):g.createLinearGradient(0,0,W,0); stops.forEach(([o,c])=>G.addColorStop(o,c)); g.fillStyle=G; g.fillRect(0,0,W,H);};
const glow=(g,x,y,r0,c0,c1='rgba(0,0,0,0)')=>{const G=g.createRadialGradient(x,y,0,x,y,r0); G.addColorStop(0,c0); G.addColorStop(1,c1); g.fillStyle=G; g.fillRect(x-r0,y-r0,r0*2,r0*2);};
const hills=(g,W,H,base,amp,freq,phase,col)=>{g.beginPath(); g.moveTo(0,H); for(let x=0;x<=W;x+=W/120){const y=base+Math.sin(x*freq/W*6.28+phase)*amp+Math.sin(x*freq*2.3/W*6.28+phase*1.7)*amp*.35; g.lineTo(x,y);} g.lineTo(W,H); g.closePath(); g.fillStyle=col; g.fill();};
const motes=(g,W,H,u,R,n,col,speed,size)=>{for(let i=0;i<n;i++){const x=((R()*W+Math.sin(u*.4+i)*18)%W+W)%W,y=((R()*H-u*speed*(0.5+R()))%H+H)%H,a=.25+.75*Math.abs(Math.sin(u*1.3+i)); g.globalAlpha=a; glow(g,x,y,size*(0.6+R()),col);} g.globalAlpha=1;};
const CIN={
  sunset:(g,W,H,u,R)=>{grad(g,W,H,[[0,'#141a3a'],[.45,'#6b3a5c'],[.62,'#e3774a'],[.75,'#ffcf7d']]); glow(g,W*.5,H*.66-u*6,W*.42,'rgba(255,214,140,.55)'); g.fillStyle='#ffe3a3'; g.beginPath(); g.arc(W*.5,H*.66-u*6,W*.085,0,6.28); g.fill();
    [['#4a2f44',.70,.03,1.2,0],['#2d1f33',.76,.04,1.6,1.2],['#1a1320',.84,.05,2.1,2.4],['#0e0a12',.92,.04,3,.8]].forEach(([c,b,a,f,ph],i)=>hills(g,W,H,H*b,H*a,f,ph+u*.03*(i+1),c)); motes(g,W,H,u,R,70,'rgba(255,220,150,.9)',22,W*.006);},
  forest:(g,W,H,u,R)=>{grad(g,W,H,[[0,'#0d1f1b'],[.5,'#27463c'],[.78,'#5d7d60'],[1,'#8aa07a']]); glow(g,W*.62,H*.3,W*.5,'rgba(255,240,200,.35)');
    for(let k=0;k<4;k++){g.globalAlpha=.07; g.fillStyle='#fff8dc'; g.beginPath(); const x0=W*(.35+k*.14)+Math.sin(u*.25+k)*W*.015; g.moveTo(x0,-H*.05); g.lineTo(x0+W*.1,-H*.05); g.lineTo(x0-W*.25,H*.85); g.lineTo(x0-W*.45,H*.85); g.fill();} g.globalAlpha=1;
    const tree=(x,base,h,w,col)=>{g.fillStyle=col; g.fillRect(x-w*.06,base-h*.2,w*.12,h*.2); for(let t=0;t<5;t++){const ty=base-h*(.15+t*.17),tw=w*(1-t*.17); g.beginPath(); g.moveTo(x-tw,ty); g.lineTo(x,ty-h*.26); g.lineTo(x+tw,ty); g.closePath(); g.fill();}};
    [['#1a2f29',.80,.55,8,.6],['#101f1b',.86,.75,7,1],['#070f0d',.94,1,6,1.6]].forEach(([col,base,sc,n,sp],L)=>{for(let i=0;i<n;i++){const x=(((i+.5)*W/n+u*sp*6+R()*W*.08)%(W*1.1))-W*.05,h=H*(.28+R()*.14)*sc,w=W*(.09+R()*.03)*sc; tree(x,H*base,h,w,col);} g.fillStyle=col; g.fillRect(0,H*base-2,W,H);});
    g.globalAlpha=.5; grad(g,W,H,[[.55,'rgba(190,210,200,0)'],[.8,'rgba(190,210,200,.45)'],[1,'rgba(190,210,200,0)']]); g.globalAlpha=1; motes(g,W,H,u,R,90,'rgba(255,245,200,.9)',14,W*.005);},
  stars:(g,W,H,u,R)=>{grad(g,W,H,[[0,'#02030a'],[1,'#0b1030']]); glow(g,W*.3,H*.4,W*.6,'rgba(90,60,160,.35)'); glow(g,W*.75,H*.7,W*.5,'rgba(40,120,180,.28)'); for(let i=0;i<260;i++){const x=(R()*W+u*3*(0.3+R()))%W,y=R()*H,s=R(),a=.4+.6*Math.abs(Math.sin(u*(1+s*2)+i)); g.globalAlpha=a; g.fillStyle='#fff'; g.beginPath(); g.arc(x,y,(0.6+s*1.8)*W/1080,0,6.28); g.fill();} g.globalAlpha=1;
    const sh=((u*.25)%1); g.strokeStyle='rgba(255,255,255,.7)'; g.lineWidth=2; g.beginPath(); g.moveTo(W*(.1+sh*.9),H*(.1+sh*.35)); g.lineTo(W*(.1+sh*.9)-W*.08,H*(.1+sh*.35)-H*.03); g.stroke();},
  aurora:(g,W,H,u,R)=>{grad(g,W,H,[[0,'#03060f'],[1,'#0a1a2a']]); for(let b=0;b<4;b++){g.globalAlpha=.22; const col=['#38f0b0','#4ad0ff','#a070ff','#60ffd0'][b]; g.fillStyle=col; g.beginPath(); for(let x=0;x<=W;x+=W/80){const y=H*(.25+b*.08)+Math.sin(x/W*4+u*.6+b)*H*.06+Math.sin(x/W*9-u*.9+b*2)*H*.03; g.lineTo(x,y);} for(let x=W;x>=0;x-=W/80){const y=H*(.25+b*.08)+Math.sin(x/W*4+u*.6+b)*H*.06+H*.22+Math.sin(x/W*6+u*.5)*H*.04; g.lineTo(x,y);} g.closePath(); g.filter=`blur(${W*.02}px)`; g.fill(); g.filter='none';} g.globalAlpha=1;
    hills(g,W,H,H*.82,H*.05,2,1,'#050810'); for(let i=0;i<120;i++){g.globalAlpha=.3+.7*R(); g.fillStyle='#fff'; g.fillRect(R()*W,R()*H*.7,1.5,1.5);} g.globalAlpha=1;},
  city:(g,W,H,u,R)=>{grad(g,W,H,[[0,'#07070f'],[.6,'#1a1030'],[1,'#3a1a2a']]); glow(g,W*.5,H*.62,W*.6,'rgba(255,120,80,.25)'); for(let L=0;L<3;L++){const col=['#1c1830','#100e1e','#070610'][L]; let x=-W*.05+((u*(2+L*3))%(W*.12)); while(x<W*1.1){const w=W*(.04+R()*.07),h=H*(.12+R()*.3)*(0.6+L*.25),y=H*.72-h+L*H*.06; g.fillStyle=col; g.fillRect(x,y,w,h); if(L===2){for(let wy=y+6;wy<H*.72;wy+=10){for(let wx=x+4;wx<x+w-4;wx+=8){if(R()<.35){g.fillStyle=`rgba(255,220,150,${.3+.7*Math.abs(Math.sin(u*2+wx+wy))})`; g.fillRect(wx,wy,3,4);}}}} x+=w+W*.015;}}
    g.fillStyle='#050408'; g.fillRect(0,H*.72,W,H); for(let i=0;i<30;i++){g.globalAlpha=.25; glow(g,R()*W,H*(.74+R()*.25),W*.03,['rgba(255,90,60,1)','rgba(90,160,255,1)','rgba(255,200,90,1)'][i%3]);} g.globalAlpha=1;},
  ocean:(g,W,H,u,R)=>{grad(g,W,H,[[0,'#0a1930'],[.5,'#1e4a6a'],[.52,'#2b6b85'],[1,'#071a26']]); glow(g,W*.5,H*.5,W*.5,'rgba(255,200,150,.35)'); for(let k=0;k<14;k++){const y=H*(.52+k*.035),a=.08+k*.03; g.strokeStyle=`rgba(255,255,255,${a})`; g.lineWidth=1+k*.3; g.beginPath(); for(let x=0;x<=W;x+=W/90){g.lineTo(x,y+Math.sin(x/W*10+u*(1.2+k*.1)+k)*H*.006*(1+k*.3));} g.stroke();} motes(g,W,H,u,R,40,'rgba(255,255,255,.8)',8,W*.004);},
  grid:(g,W,H,u,R)=>{grad(g,W,H,[[0,'#05030f'],[.5,'#1a0b2e'],[1,'#05030f']]); glow(g,W*.5,H*.5,W*.4,'rgba(255,80,160,.35)'); const hz=H*.5; g.strokeStyle='rgba(120,220,255,.7)'; g.lineWidth=1.5; for(let i=-12;i<=12;i++){g.beginPath(); g.moveTo(W*.5+i*W*.08,hz); g.lineTo(W*.5+i*W*.9,H); g.stroke();} for(let k=0;k<16;k++){const t=((k/16+u*.25)%1),y=hz+Math.pow(t,2.2)*(H-hz); g.globalAlpha=t; g.beginPath(); g.moveTo(0,y); g.lineTo(W,y); g.stroke();} g.globalAlpha=1; g.fillStyle='#fff'; for(let i=0;i<80;i++){g.globalAlpha=.3+.7*R(); g.fillRect(R()*W,R()*hz*.9,1.5,1.5);} g.globalAlpha=1;},
  particles:(g,W,H,u,R)=>{grad(g,W,H,[[0,'#07080e'],[1,'#0e1220']]); glow(g,W*.5,H*.5,W*.55,'rgba(212,255,63,.08)'); const P=[]; for(let i=0;i<70;i++){const sx=R(),sy=R(),vx=(R()-.5)*.03,vy=(R()-.5)*.03; P.push([((sx+vx*u)%1+1)%1*W,((sy+vy*u)%1+1)%1*H]);}
    for(let i=0;i<P.length;i++)for(let j=i+1;j<P.length;j++){const dx=P[i][0]-P[j][0],dy=P[i][1]-P[j][1],d=Math.hypot(dx,dy); if(d<W*.16){g.globalAlpha=(1-d/(W*.16))*.5; g.strokeStyle='#D4FF3F'; g.lineWidth=1; g.beginPath(); g.moveTo(P[i][0],P[i][1]); g.lineTo(P[j][0],P[j][1]); g.stroke();}} g.globalAlpha=1; P.forEach(([x,y],i)=>{glow(g,x,y,W*.012,'rgba(212,255,63,.9)'); g.fillStyle='#fff'; g.beginPath(); g.arc(x,y,2,0,6.28); g.fill();});},
};
const CURSOR="<svg viewBox='0 0 24 24' width='34' height='34'><path d='M4 2 L4 19 L8.6 14.8 L11.6 21.4 L14.6 20 L11.7 13.6 L18 13.4 Z' fill='#fff' stroke='#000' stroke-width='1.3' stroke-linejoin='round'/></svg>";
const TB=(title,extra='')=>`<div class='tb'><i style='background:#ff5f57'></i><i style='background:#febc2e'></i><i style='background:#28c840'></i><b>${esc(title||'')}</b>${extra}</div>`;
const SCENES={
  terminal:{build:(el,c)=>{el.innerHTML=TB(c.title||'Claude Code')+`<div class='body'><div class='cmd'></div>${(c.lines||[]).map((l,i,a)=>`<div class='ok ${i===a.length-1?'last':''}' style='opacity:0'>${esc(l)}</div>`).join('')}</div>`;},
    update:(el,c,u)=>{const d=c.delay??.2,cps=c.cps||28,cmd=c.cmd||'',n=Math.floor((u-d)*cps),tc=d+cmd.length/cps+.35,st=c.step||.45;
      el.querySelector('.cmd').innerHTML=n<0?"<span class='cur'></span>":typed(esc(cmd),n); let k=0;
      el.querySelectorAll('.ok').forEach((q,i)=>{const on=u>tc+i*st; q.style.opacity=on?1:0; if(on)k++;}); return `${Math.min(n,cmd.length)}|${k}`;}},
  chat:{build:(el,c)=>{el.innerHTML=`<div class='ch'><div class='av'>${c.avatar||'💬'}</div><div class='nm'><b>${esc(c.name||'Chat')}</b><span class='stt'>online</span></div><div class='dots'><i></i><i></i><i></i></div></div><div class='body'>${(c.history||[]).map(([w,s])=>`<div class='h ${w==='u'?'u':'a'}' style='display:block'>${esc(s)}</div>`).join('')}${c.history?.length?`<div class='day'>Today</div>`:''}${c.attachments?.length?`<div class='chips' style='opacity:0'>${c.attachments.map(a=>`<span class='chip'>📄 ${esc(a)}</span>`).join('')}</div>`:''}<div class='u live'></div><div class='ty'><i></i><i></i><i></i></div><div class='a live'></div></div><div class='cp'><span>${esc(c.placeholder||'Message')}</span><b>↑</b></div>`;},
    update:(el,c,u)=>{const d=.3,cps=c.cps||30,pr=c.prompt||'',n=Math.floor((u-d)*cps),tp=d+pr.length/cps+(c.reply_delay??.6),wps=c.wps||9,m=Math.floor((u-tp)*wps);
      const ch=el.querySelector('.chips'); if(ch) ch.style.opacity=u>.08?1:0; const U=el.querySelector('.u.live'); U.style.opacity=u>d-.1?1:0; U.innerHTML=typed(esc(pr),n);
      // reply streams word by word; **bold** segments are parsed first so markers never show while streaming
      const segs=[]; (c.reply||'').split(/(\*\*[^*]+\*\*)/).forEach(x=>{if(!x)return; const b=x.startsWith('**'); x.replace(/\*\*/g,'').split(' ').forEach(w=>{if(w)segs.push([w,b]);});});
      const shown=segs.slice(0,Math.max(m,0)), A=el.querySelector('.a.live');
      const typing=u>d+pr.length/cps+.1&&m<1; const TY=el.querySelector('.ty'); if(TY) TY.style.display=typing?'flex':'none'; const ST=el.querySelector('.stt'); if(ST) ST.textContent=typing?'typing…':'online';      A.style.display=m>0?'block':'none'; A.innerHTML=shown.map(([w,b])=>b?`<b>${esc(w)}</b>`:esc(w)).join(' ')+(m>0&&m<segs.length?"<span class='cur'></span>":''); return `${Math.min(Math.max(n,0),pr.length)}|${Math.min(Math.max(m,0),segs.length)}|${typing?1:0}`;}},
  doc:{build:(el,c)=>{el.innerHTML=TB(c.title||'PRD.md')+`<div class='body'><div class='h1'></div>${(c.lines||[]).map(l=>`<div class='${l.startsWith('## ')?'h2':'ln'}'></div>`).join('')}</div>`;},
    update:(el,c,u)=>{const cps=c.cps||40,all=[c.heading||''].concat(c.lines||[]),divs=el.querySelectorAll('.h1,.h2,.ln'); let budget=Math.floor((u-.15)*cps),key=0;
      all.forEach((l,i)=>{const t=l.replace(/^## /,''); if(budget>=t.length){divs[i].innerHTML=esc(t);budget-=t.length+6;key+=t.length;} else if(budget>0){divs[i].innerHTML=typed(esc(t),budget);key+=budget;budget=-1;} else divs[i].innerHTML=i===0&&budget>-1?"<span class='cur'></span>":'';}); return String(key);}},
  browser:{build:(el,c)=>{el.innerHTML=TB('',`<span class='url'>🔒 ${esc(c.url||'yoursite.app')}</span>`)+`<div class='hero'><h1 class='el'>${esc(c.heading||'')}</h1><p class='el'>${esc(c.sub||'')}</p>${c.button?`<span class='btn el'>${esc(c.button)}</span>`:''}</div><div class='cards'>${(c.cards||[]).map(x=>`<div class='cardx el'>${esc(x)}</div>`).join('')}</div>${c.toast?`<div class='toast'>${esc(c.toast)}</div>`:''}<div class='mcur'>${CURSOR}</div>`;},
    update:(el,c,u)=>{const st=c.step||.35,els=el.querySelectorAll('.el'); let key=''; els.forEach((q,i)=>{const p=cl((u-.1-i*st)/.3),e=1-Math.pow(1-p,3); q.style.opacity=e; q.style.transform=`translateY(${(1-e)*18}px)`; key+=Math.round(e*20);});
      const btn=el.querySelector('.btn'), cur=el.querySelector('.mcur'), t0=.1+els.length*st+.2;      // cursor flies in to the button once everything is up
      if(btn&&c.cursor!==false){const R=el.getBoundingClientRect(),B=btn.getBoundingClientRect(),W=R.width,H=R.height,bx=(B.left-R.left+B.width*.6)/(R.width/W),by=(B.top-R.top+B.height*.6)/(R.height/H);
        const p=eio(cl((u-t0)/.6)),x=W*.9+(bx-W*.9)*p,y=H*.95+(by-H*.95)*p,click=u>t0+.6&&u<t0+.85?.85:1; cur.style.opacity=u>t0?1:0; cur.style.transform=`translate(${r(x)}px,${r(y)}px) scale(${click})`;
        btn.style.transform=`translateY(0) scale(${r(click===1?1:.94)})`; key+=`|${r(p)}${click}`;}
      const T=el.querySelector('.toast'); if(T){const p=back(cl((u-t0-.9)/.4)); T.style.opacity=cl(p*2); T.style.transform=`translateX(-50%) translateY(${r((1-p)*40)}px)`; key+='|'+r(p);} return key;}},
  search:{build:(el,c)=>{el.innerHTML=`<div class='bar'><span></span></div><div class='res'>${(c.results||[]).map(r=>`<div class='r'><span>${esc(c.query||'')} </span>${esc(r)}</div>`).join('')}</div>`;},
    update:(el,c,u)=>{const d=.3,cps=c.cps||22,q=c.query||'',n=Math.floor((u-d)*cps),tq=d+q.length/cps+.25; el.querySelector('.bar span').innerHTML=typed(esc(q),Math.max(n,0)); let k=0;
      el.querySelectorAll('.r').forEach((r,i)=>{const p=cl((u-tq-i*.28)/.25); r.style.opacity=p; if(p>0)k++;}); el.querySelector('.res').style.opacity=u>tq?1:0; return `${Math.min(Math.max(n,0),q.length)}|${k}`;}},
  code:{build:(el,c)=>{el.innerHTML=TB(c.title||'app.tsx')+`<div class='body'>${(c.lines||[]).map((l,i)=>`<div class='ln'><span class='no'>${i+1}</span><span class='tx'></span></div>`).join('')}</div>`;},
    update:(el,c,u)=>{const cps=c.cps||55,lines=c.lines||[],tx=el.querySelectorAll('.tx'); let budget=Math.floor((u-.15)*cps),key=0;
      const hl=t=>esc(t).replace(/(\/\/.*$)|('[^']*'|"[^"]*"|`[^`]*`)|\b(const|let|return|import|from|export|default|function|async|await|if|else|new|class|def|for|in)\b|\b(\d+)\b/g,(m,c,st,kw,nu)=>c?`<span class='cm'>${c}</span>`:st?`<span class='st'>${st}</span>`:kw?`<span class='kw'>${kw}</span>`:`<span class='nu'>${nu}</span>`);
      lines.forEach((l,i)=>{if(budget>=l.length){tx[i].innerHTML=hl(l)||' ';budget-=l.length+3;key+=l.length;} else if(budget>0){tx[i].innerHTML=hl(l.slice(0,budget))+"<span class='cur'></span>";key+=budget;budget=-1;} else tx[i].innerHTML='';}); return String(key);}},
  chart:{build:(el,c)=>{const n=(c.bars||[]).length; el.innerHTML=`<div class='body'><div class='ct'>${esc(c.title||'')}</div><div class='bars'>${(c.bars||[]).map((b,i)=>`<div class='bw'><div class='bv'></div><div class='bar ${c.accent_last!==false&&i===n-1?'acc':''}'></div><div class='bl'>${esc(b.label||'')}</div></div>`).join('')}</div></div>`;},
    update:(el,c,u)=>{const bars=c.bars||[],mx=Math.max(...bars.map(b=>+b.value||0),1),st=c.step||.12; let key='';
      el.querySelectorAll('.bw').forEach((w,i)=>{const p=back(cl((u-.2-i*st)/.6),1+.5*AMP),v=(+bars[i].value||0)*cl(p); w.querySelector('.bar').style.height=Math.min(100,(+bars[i].value||0)*p/mx*100)+'%'; w.querySelector('.bv').style.transform=`scale(${r(1-.4*AMP+.4*AMP*back(cl((u-.2-i*st)/.5)))})`; w.querySelector('.bv').textContent=(bars[i].prefix||'')+Math.round(v).toLocaleString()+(bars[i].suffix||''); w.querySelector('.bv').style.opacity=p; key+=Math.round(p*40);}); return key;}},
  counter:{build:(el,c)=>{el.innerHTML=`<div class='body'><div class='big'></div><div class='lab'>${esc(c.label||'')}</div>${c.sub?`<div class='sub'>${esc(c.sub)}</div>`:''}</div>`;},
    update:(el,c,u)=>{const d=c.duration||1.2,p=1-Math.pow(1-cl((u-.1)/d),3),v=(+c.value||0)*p,dec=c.decimals||0; el.querySelector('.big').textContent=(c.prefix||'')+v.toFixed(dec).replace(/\B(?=(\d{3})+(?!\d))/g,',')+(c.suffix||'');
      el.querySelector('.big').style.transform=`scale(${r((1-.5*AMP+.5*AMP*back(cl((u-.1)/.45)))*(1+.16*AMP*Math.sin(Math.PI*cl((u-.1-d)/.35))))}) rotate(${r(-6*AMP*(1-ease(cl((u-.1)/.45))))}deg)`; const L=el.querySelector('.lab'); L.style.opacity=cl((u-.3)/.3); const S=el.querySelector('.sub'); if(S) S.style.opacity=cl((u-d)/.3); return v.toFixed(dec)+'|'+L.style.opacity+'|'+(S?S.style.opacity:'');}},
  phone:{build:(el,c)=>{el.innerHTML=`<div class='ph'><div class='notch'></div><div class='time'>${esc(c.time||'9:41')}</div><div class='wall'></div>${(c.notifications||[]).map(n=>`<div class='nt'><div class='ni ${n.icon?'im':''}'>${n.icon?`<img src='${n.icon}'>`:(n.emoji||'💬')}</div><div><div class='nh'><b>${esc(n.app||'')}</b><span>now</span></div><div class='nt1'>${esc(n.title||'')}</div><div class='nt2'>${esc(n.text||'')}</div></div></div>`).join('')}</div>`;},
    update:(el,c,u)=>{const st=c.step||.8; let key=''; el.querySelectorAll('.nt').forEach((n,i)=>{const p=cl((u-.3-i*st)/.45),e=back(p); n.style.opacity=cl(p*3); n.style.transform=`translateY(${r((1-e)*-120*AMP)}px) scale(${r(1-.1*AMP+.1*AMP*e)})`; key+=Math.round(p*30);}); return key;}},
  flow:{build:(el,c)=>{const N=(c.nodes||[]); el.innerHTML=`<div class='body fl'>${N.map((n,i)=>`${i?`<svg class='ar' viewBox='0 0 60 24'><path d='M2 12 H50 M42 4 L52 12 L42 20' fill='none' stroke='#D4FF3F' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round' pathLength='1'/></svg>`:''}<div class='nd ${i===N.length-1?'acc':''}'><div class='ne'>${n.icon?`<img src='${n.icon}'>`:(n.emoji||'')}</div><div class='nl'>${esc(n.label||'')}</div></div>`).join('')}</div>`;},
    update:(el,c,u)=>{const st=c.step||.45; let key=''; el.querySelectorAll('.nd').forEach((n,i)=>{const p=cl((u-.1-i*st)/.3); n.style.opacity=cl(p*2); n.style.transform=`scale(${r(1-.7*AMP+.7*AMP*back(p))}) rotate(${r((1-ease(p))*-8*AMP)}deg)`; key+=Math.round(p*20);});
      el.querySelectorAll('.ar path').forEach((a,i)=>{const p=1-Math.pow(1-cl((u-.1-(i+.6)*st)/.3),3); a.style.strokeDasharray=1; a.style.strokeDashoffset=r(1-p); key+=Math.round(p*20);}); return key;}},
  checklist:{build:(el,c)=>{el.innerHTML=TB(c.title||'Launch checklist')+`<div class='body'>${(c.items||[]).map(t=>`<div class='ck'><svg viewBox='0 0 32 32'><rect x='2' y='2' width='28' height='28' rx='8' fill='none' stroke='#5a6070' stroke-width='2.5'/><path class='tk' d='M8 16 L14 22 L24 10' fill='none' stroke='#D4FF3F' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round' pathLength='1'/></svg><span>${esc(t)}</span></div>`).join('')}<div class='pg'><div class='pf'></div></div></div>`;},
    update:(el,c,u)=>{const st=c.step||.5,items=el.querySelectorAll('.ck'); let done=0,key='';
      items.forEach((it,i)=>{const p=cl((u-.1-i*st)/.25),tp=1-Math.pow(1-cl((u-.1-i*st-.3)/.3),3); it.style.opacity=p; it.style.transform=`translateX(${r((1-back(p))*-70*AMP)}px) scale(${r(1-.15*AMP+.15*AMP*back(p))})`; it.querySelector('.tk').style.strokeDasharray=1; it.querySelector('.tk').style.strokeDashoffset=r(1-tp); it.classList.toggle('done',tp>=1); if(tp>=1)done++; key+=Math.round(p*10)+'.'+Math.round(tp*10);});
      el.querySelector('.pf').style.width=(items.length?done/items.length*100:0)+'%'; return key;}},
  stats:{build:(el,c)=>{el.innerHTML=`<div class='body st'>${c.title?`<div class='ct'>${esc(c.title)}</div>`:''}<div class='tiles'>${(c.tiles||[]).map(t=>`<div class='tile'><div class='tl'>${esc(t.label||'')}</div><div class='tv'></div>${t.delta?`<div class='td ${String(t.delta).startsWith('-')?'dn':'up'}'>${esc(t.delta)}</div>`:''}<svg class='sp' viewBox='0 0 100 30' preserveAspectRatio='none'><path d='${(t.spark||[3,5,4,7,6,9,8,12]).map((v,i,a)=>(i?'L':'M')+(i/(a.length-1)*100).toFixed(1)+' '+(30-v/Math.max(...a)*28).toFixed(1)).join(' ')}' fill='none' stroke='#D4FF3F' stroke-width='2.5' pathLength='1'/></svg></div>`).join('')}</div></div>`;},
    update:(el,c,u)=>{const T=c.tiles||[],st=c.step||.18; let key=''; el.querySelectorAll('.tile').forEach((q,i)=>{const p=cl((u-.1-i*st)/.35),e=back(p,1.2),cp=1-Math.pow(1-cl((u-.2-i*st)/1.1),3),v=(+T[i].value||0)*cp;
      q.style.opacity=cl(p*2); q.style.transform=`translateY(${r((1-back(p))*70*AMP)}px) scale(${r(1-.2*AMP+.2*AMP*back(p))})`; q.querySelector('.tv').textContent=(T[i].prefix||'')+v.toFixed(T[i].decimals||0).replace(/\B(?=(\d{3})+(?!\d))/g,',')+(T[i].suffix||''); const sp=q.querySelector('.sp path'); sp.style.strokeDasharray=1; sp.style.strokeDashoffset=r(1-cp); key+=Math.round(p*10)+'.'+v.toFixed(1);}); return key;}},
  timeline:{build:(el,c)=>{el.innerHTML=`<div class='body tlb'>${c.title?`<div class='ct'>${esc(c.title)}</div>`:''}<div class='track'><div class='fill'></div>${(c.points||[]).map((pt,i,a)=>`<div class='pt ${i===a.length-1?'acc':''}' style='left:${(a.length>1?i/(a.length-1)*100:50).toFixed(1)}%'><div class='dot'></div><div class='yr'>${esc(pt.label||'')}</div><div class='tx'>${esc(pt.text||'')}</div></div>`).join('')}</div></div>`;},
    update:(el,c,u)=>{const P=el.querySelectorAll('.pt'),st=c.step||.5,n=P.length; let key=''; P.forEach((q,i)=>{const p=cl((u-.15-i*st)/.3); q.style.opacity=cl(p*2); q.querySelector('.dot').style.transform=`scale(${r(back(p))})`; q.querySelector('.tx').style.transform=`translateY(${r((1-ease(p))*14)}px)`; key+=Math.round(p*20);});
      const fp=n>1?cl((u-.15)/(st*(n-1))):1; el.querySelector('.fill').style.width=(fp*100)+'%'; return key+'|'+r(fp);}},
  kanban:{build:(el,c)=>{const cols=c.columns||['To do','Doing','Done']; el.innerHTML=TB(c.title||'Board')+`<div class='body kb'>${cols.map((n,i)=>`<div class='col'><div class='ch'>${esc(n)}<span class='cnt'></span></div><div class='cards'></div></div>`).join('')}</div>`; el._cards=(c.cards||[]).map(x=>typeof x==='string'?{text:x}:x);},
    update:(el,c,u)=>{const cols=el.querySelectorAll('.col'),st=c.step||.55,C=el._cards; const cols_=cols.length; let key='';
      // each card appears in column 0, then moves one column every `step` until it reaches the last column
      cols.forEach(col=>col.querySelector('.cards').innerHTML='');
      C.forEach((cd,i)=>{const t0=.15+i*st*.6, k=Math.floor(cl((u-t0)/(st*(cols_-1)),0,.999)*(cols_-1)); if(u<t0){key+='x';return;} const col=cols[k].querySelector('.cards'), d=document.createElement('div'); d.className='kc'+(k===cols_-1?' done':''); d.innerHTML=`<span>${esc(cd.text)}</span>${cd.tag?`<i>${esc(cd.tag)}</i>`:''}`; const p=cl((u-t0-k*st*(cols_-1)/(cols_-1))/.25); d.style.opacity=cl(p*2+.4); d.style.transform=`translateX(${r((1-ease(p))*-18)}px)`; col.appendChild(d); key+=k;});
      cols.forEach(col=>col.querySelector('.cnt').textContent=col.querySelectorAll('.kc').length); return key;}},
  quote:{build:(el,c)=>{el.innerHTML=`<div class='body qb'><div class='qm'>“</div><div class='qt'></div><div class='qa'><div class='av'>${esc((c.name||'A')[0])}</div><div><div class='qn'>${esc(c.name||'')}</div><div class='qr'>${esc(c.role||'')}</div></div><div class='stars'>★★★★★</div></div></div>`;},
    update:(el,c,u)=>{const words=(c.text||'').split(' '),wps=c.wps||7,m=Math.floor((u-.2)*wps); el.querySelector('.qt').innerHTML=words.slice(0,Math.max(m,0)).join(' '); const A=el.querySelector('.qa'),p=cl((u-.2-words.length/wps)/.35); A.style.opacity=p; A.style.transform=`translateY(${r((1-ease(p))*16)}px)`; return `${Math.max(m,0)}|${r(p)}`;}},
  email:{build:(el,c)=>{el.innerHTML=TB(c.title||'Inbox',`<span class='url' style='max-width:160px'>🔍 Search</span>`)+`<div class='body eb'>${(c.messages||[]).map(mm=>`<div class='em'><div class='eav' style='background:${mm.color||'#4f6df5'}'>${esc((mm.sender||mm.from||'?')[0])}</div><div class='et'><div class='ef'>${esc(mm.sender||mm.from||'')}<span>${esc(mm.time||'now')}</span></div><div class='es'>${esc(mm.subject||'')}</div><div class='ep'>${esc(mm.preview||'')}</div></div>${mm.badge?`<div class='ebd'>${esc(mm.badge)}</div>`:''}</div>`).join('')}</div>`;},
    update:(el,c,u)=>{const st=c.step||.6; let key=''; el.querySelectorAll('.em').forEach((q,i)=>{const p=cl((u-.15-i*st)/.35),e=back(p,1.1); q.style.opacity=cl(p*2); q.style.transform=`translateY(${r((1-e)*-26)}px)`; key+=Math.round(p*20);}); return key;}},
  dashboard:{build:(el,c)=>{el.innerHTML=`<div class='db'><div class='side'><div class='lg'>${esc(c.brand||'Studio')}</div>${(c.nav||['Overview','Customers','Invoices','Settings']).map((n,i)=>`<div class='nv ${i===0?'on':''}'>${esc(n)}</div>`).join('')}</div><div class='main'><div class='hd'>${esc(c.title||'Overview')}<span class='pill'>${esc(c.period||'Last 30 days')}</span></div><div class='kp'>${(c.kpis||[]).map(k=>`<div class='k'><div class='kl'>${esc(k.label||'')}</div><div class='kv'></div></div>`).join('')}</div><div class='row'><div class='chart'><div class='cl'>${esc(c.chart_label||'Revenue')}</div><div class='bars'>${(c.bars||[6,9,7,12,14,11,18,22,20,27,31,36]).map(()=>`<div class='b'></div>`).join('')}</div></div><div class='list'>${(c.rows||[]).map(rw=>`<div class='lr'><span>${esc(rw[0]||'')}</span><b>${esc(rw[1]||'')}</b></div>`).join('')}</div></div></div></div>`;},
    update:(el,c,u)=>{const K=c.kpis||[],B=c.bars||[6,9,7,12,14,11,18,22,20,27,31,36],mx=Math.max(...B); let key='';
      el.querySelectorAll('.k').forEach((q,i)=>{const p=cl((u-.1-i*.15)/.35),cp=1-Math.pow(1-cl((u-.2-i*.15)/1.0),3),v=(+K[i].value||0)*cp; q.style.opacity=cl(p*2); q.style.transform=`translateY(${r((1-ease(p))*16)}px)`; q.querySelector('.kv').textContent=(K[i].prefix||'')+Math.round(v).toLocaleString()+(K[i].suffix||''); key+=Math.round(v);});
      el.querySelectorAll('.b').forEach((b,i)=>{const p=1-Math.pow(1-cl((u-.5-i*.06)/.5),3); b.style.height=(B[i]/mx*100*p)+'%'; b.classList.toggle('acc',i===B.length-1); key+='.'+Math.round(p*9);});
      el.querySelectorAll('.lr').forEach((q,i)=>{const p=cl((u-.9-i*.18)/.3); q.style.opacity=p; q.style.transform=`translateX(${r((1-ease(p))*-14)}px)`; key+='.'+Math.round(p*9);}); return key;}},
  cinematic:{build:(el,c)=>{el.innerHTML=`<canvas class='cv'></canvas><div class='grain'></div>${c.text?`<div class='hl'>${esc(c.text)}</div>`:''}${c.sub?`<div class='sb'>${esc(c.sub)}</div>`:''}`; const cv=el.querySelector('canvas'),R=el.getBoundingClientRect(); cv.width=Math.round(R.width*1.5); cv.height=Math.round(R.height*1.5);},
    update:(el,c,u)=>{const cv=el.querySelector('canvas'),g=cv.getContext('2d'),W=cv.width,H=cv.height; g.clearRect(0,0,W,H); (CIN[c.style]||CIN.sunset)(g,W,H,u,rnd(c.seed||7),c);
      const hl=el.querySelector('.hl'),sb=el.querySelector('.sb'),p=cl((u-(c.text_delay??.5))/.6); if(hl){hl.style.opacity=p;hl.style.transform=`translateY(${r((1-ease(p))*24)}px)`;} if(sb){const q=cl((u-(c.text_delay??.5)-.3)/.6); sb.style.opacity=q;} return r(u)+'|'+r(p);}},
  reveal:{build:(el,c)=>{el.innerHTML=`<div class='rv'>${c.logo?`<img class='rl' src='${c.logo}'>`:''}<div class='rb'>${esc(c.brand||'').split('').map(ch=>`<span>${ch===' '?'&nbsp;':esc(ch)}</span>`).join('')}</div><div class='rs'></div>${c.tag?`<div class='rt'>${esc(c.tag)}</div>`:''}</div>`;},
    update:(el,c,u)=>{const L=el.querySelectorAll('.rb span'),d=c.delay??.3,per=c.per??.045; let key=''; L.forEach((q,i)=>{const p=cl((u-d-i*per)/.35); q.style.opacity=p; q.style.transform=`translateY(${r((1-ease(p))*14)}px)`; key+=Math.round(p*9);});
      const t2=d+L.length*per+.25,sub=c.sub||'',n=Math.floor((u-t2)*(c.cps||26)); el.querySelector('.rs').innerHTML=typed(esc(sub),Math.max(n,0)); const lg=el.querySelector('.rl'); if(lg){const p=cl((u-.1)/.5); lg.style.opacity=p; lg.style.transform=`scale(${r(.8+.2*back(p))})`;}
      const T=el.querySelector('.rt'); if(T) T.style.opacity=cl((u-t2-sub.length/(c.cps||26)-.2)/.5); return key+'|'+Math.max(n,0);}},
  progress:{build:(el,c)=>{el.innerHTML=TB(c.title||'Claude',`<span class='url'>${esc(c.model||'Opus 5 · High')}</span>`)+`<div class='body pg'><div class='pq'>${esc(c.prompt||'')}</div><div class='pcard'><div class='pct'></div><div class='plabel'>${esc(c.label||'Generating')}</div><div class='pbar'><div class='pfill'></div></div></div><div class='plines'>${(c.lines||[]).map(l=>`<div class='pl'>${esc(l)}</div>`).join('')}</div></div>`;},
    update:(el,c,u)=>{const d=c.duration||3,to=c.to??100,p=1-Math.pow(1-cl(u/d),2),v=Math.round(to*p); el.querySelector('.pct').textContent=v+'%'; el.querySelector('.pfill').style.width=v+'%'; let key=String(v);
      el.querySelectorAll('.pl').forEach((q,i)=>{const s=cl((u-.4-i*(c.step||.6))/.3); q.style.opacity=s; q.style.transform=`translateX(${r((1-ease(s))*-12)}px)`; key+='.'+Math.round(s*9);}); return key;}},
  cards:{build:(el,c)=>{el.innerHTML=`<div class='body'>${(c.cards||[]).map((x,i,a)=>`<div class='c ${c.accent_last!==false&&i===a.length-1?'acc':''}'><div class='e'>${x.emoji||''}</div><div class='t'>${esc(x.title||'')}</div><div class='s'>${esc(x.sub||'')}</div></div>`).join('')}</div>`;},
    update:(el,c,u)=>{const st=c.step||.45; let key=''; el.querySelectorAll('.c').forEach((q,i)=>{const p=cl((u-.1-i*st)/.3); q.style.opacity=cl(p*2); q.style.transform=`scale(${r(1-.7*AMP+.7*AMP*back(p))}) rotate(${r((1-ease(p))*-6*AMP)}deg)`; key+=Math.round(p*20);}); return key;}},
};
const SC=k=>SCENES[k]||(window.MOTION&&window.MOTION[k])||SCENES.cards;
for(const it of ITEMS) if(it.kind==='window'&&it.scene){const el=$(it.id+'_sc'); const canvasKind=!SCENES[it.scene.kind]; el.style.zoom=canvasKind?1:(it.scene.zoom||(it.person?1.85:(it.w/(it.scene.kind==='phone'?300:720)))); SC(it.scene.kind).build(el,it.scene);}
const PH={};
function phraseLayout(it){
  const el=$(it.id), S=it.size*it.scale; el.innerHTML='';
  const blocks=[]; let cur={before:[],hero:null,after:[]};
  for(const w of it.words){ if(w.role==='hero'||w.role==='big'){ if(cur.hero){blocks.push(cur); cur={before:[],hero:null,after:[]};} cur.hero=w; } else if(cur.hero) cur.after.push(w); else cur.before.push(w); }
  blocks.push(cur);
  const mk=(w,cls,px)=>{const d=document.createElement('div'); d.className='w '+cls+(it.ink?' ink':''); d.style.fontSize=px+'px'; d.textContent=w.t; el.appendChild(d); w.el=d; return d;};
  // measure
  const all=[]; blocks.forEach(b=>{ b.before.forEach(w=>all.push([w,mk(w,w.role==='serif'?'serif':'small',w.role==='serif'?S*.4:S*.36)])); if(b.hero) all.push([b.hero,mk(b.hero,b.hero.role,S)]); b.after.forEach(w=>all.push([w,mk(w,w.role==='serif'?'serif':'small',w.role==='serif'?S*.4:S*.36)])); });
  all.forEach(([w,d])=>{ const r=d.getBoundingClientRect(); w.w=r.width/ (1080/document.body.getBoundingClientRect().width); w.h=r.height/(1080/document.body.getBoundingClientRect().width); });
  let cy=it.y, lines=[];
  blocks.forEach((b,bi)=>{
    const hw=b.hero?b.hero.w:S*3, hh=b.hero?b.hero.h:S;
    if(b.hero){ b.hero.cx=it.x; b.hero.cy=cy; }
    // before: a spread row above the hero, gaps grow with count
    const n=b.before.length; if(n){ const tot=b.before.reduce((a,w)=>a+w.w,0), gap=Math.min(S*.55, Math.max(S*.3,(hw*.95-tot)/Math.max(1,n-1))); const span=tot+gap*(n-1); let x0=it.x-span/2; b.before.forEach((w,i)=>{ w.cx=x0+w.w/2; w.cy=cy-hh*.62-S*.2-(i%2?S*.04:0); x0+=w.w+gap; }); }
    // after: small words below-left in a row, serif words below-right
    const smalls=b.after.filter(w=>w.role!=='serif'), serifs=b.after.filter(w=>w.role==='serif');
    let sx=it.x-hw/2+S*.1; smalls.forEach(w=>{ w.cx=sx+w.w/2; w.cy=cy+hh*.6+S*.12; sx+=w.w+S*.25; });
    const smallW=smalls.reduce((a,w)=>a+w.w,0)+Math.max(0,smalls.length-1)*S*.25, serW=serifs.reduce((a,w)=>a+w.w,0);
    const twoRows=smalls.length&&serifs.length&&(smallW+serW+S*.3>hw*1.1);
    let rx=it.x+hw/2-S*.05; serifs.slice().reverse().forEach(w=>{ w.cx=rx-w.w/2; w.cy=cy+hh*.6+S*(twoRows?.6:.14); rx-=w.w+S*.3; });
    cy+=hh*.6+S*(b.after.length?(twoRows?1.15:.75):.45)+hh*.55;
  });
  it.words.forEach(w=>{ if(w.dx!=null){ w.cx=it.x+w.dx; w.cy=it.y+w.dy; } });
  // SAFE ZONE: the composition must sit inside the Instagram-safe box. Scale down (once) if it cannot fit, then shift it in.
  const bx0=Math.min(...it.words.map(w=>w.cx-w.w/2)), bx1=Math.max(...it.words.map(w=>w.cx+w.w/2)), by0=Math.min(...it.words.map(w=>w.cy-w.h/2)), by1=Math.max(...it.words.map(w=>w.cy+w.h/2));
  const f=Math.min(1,(SAFE.x1-SAFE.x0)/(bx1-bx0+8),(SAFE.y1-SAFE.y0)/(by1-by0+8));
  if(f<.999&&!it._fit){ it._fit=true; it.scale*=f*.97; return phraseLayout(it); }
  const dx=bx0<SAFE.x0?SAFE.x0-bx0:bx1>SAFE.x1?SAFE.x1-bx1:0, dy=by0<SAFE.y0?SAFE.y0-by0:by1>SAFE.y1?SAFE.y1-by1:0;
  it.words.forEach(w=>{ w.cx+=dx; w.cy+=dy; w.el.style.left=(w.cx-w.w/2)+'px'; w.el.style.top=(w.cy-w.h/2)+'px'; });
  if(it.link){ const h=blocks[0].hero, prev=blocks[0].before[blocks[0].before.length-1]; if(h&&prev){ const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.setAttribute('width',1080); svg.setAttribute('height',1920); const x1=h.cx+h.w*.1,y1=h.cy-h.h*.5,x2=prev.cx,y2=prev.cy+prev.h*.6; const path=document.createElementNS('http://www.w3.org/2000/svg','path'); path.setAttribute('d',`M${x1} ${y1} Q${(x1+x2)/2+40} ${(y1+y2)/2} ${x2} ${y2}`); path.setAttribute('fill','none'); path.setAttribute('stroke','#fff'); path.setAttribute('stroke-width',4); path.setAttribute('stroke-dasharray','10 12'); path.setAttribute('stroke-linecap','round'); path.setAttribute('pathLength','1'); svg.appendChild(path); el.appendChild(svg); it.linkEl=path; } }
  PH[it.id]=true;
}
function phraseRender(it,t){ if(!PH[it.id]) phraseLayout(it); let key=''; const el=$(it.id); el.style.opacity=1; el.style.transform='';
  const xo=cl((it.b-t)/.14);
  const heroes=it.words.filter(w=>(w.role==='hero'||w.role==='big')&&t>=w.at); const lastH=heroes.length?heroes[heroes.length-1]:null; const bump=lastH?Math.sin(Math.PI*cl((t-lastH.at-.1)/.35)):0;   // neighbours react when a hero word lands
  it.words.forEach(w=>{ const p=cl((t-w.at)/(w.role==='hero'||w.role==='big'?.3:.22)), e=ease(p), b=back(p); const isH=w.role==='hero'||w.role==='big';
    w.el.style.opacity=r(Math.min(cl(p*2.5),xo));
    w.el.style.transform=isH?`scale(${r(1+.7*AMP*(1-b))}) rotate(${r(-5*AMP*(1-e))}deg)`:`translateY(${r((1-b)*34*AMP)}px) scale(${r(1-.3*AMP+.3*AMP*b+(w!==lastH?.1*AMP*bump:0))})`;
    w.el.style.filter=isH?`blur(${r((1-e)*10*AMP)}px) brightness(${r(1+1.4*AMP*(1-e))})`:''; key+=Math.round(p*20)+'.'+Math.round(bump*9); });
  if(it.linkEl){ const h=it.words.find(w=>w.role==='hero'||w.role==='big'); const p=ease(cl((t-(h?h.at:it.a)-.15)/.4)); it.linkEl.style.strokeDasharray='10 12'; it.linkEl.style.strokeDashoffset=0; it.linkEl.style.opacity=p; key+='L'+Math.round(p*9); }
  return key; }
function leakRender(it,t){ const el=$(it.id), p=cl((t-it.a)/it.dur), peak=Math.pow(Math.sin(p*Math.PI),.7); el.style.transform='';
  const warm=it.hue!=='cool'; const c1=warm?'255,60,160':'60,160,255', c2=warm?'255,240,120':'200,240,255', c3=warm?'255,120,40':'120,80,255';
  const mix=p<.5?c1:c3;
  el.style.background=`radial-gradient(ellipse at ${30+p*40}% ${40}%, rgba(${c2},${(peak*1.1).toFixed(3)}) 0%, rgba(${c2},${(peak*.9).toFixed(3)}) 35%, rgba(${mix},${(peak*.85).toFixed(3)}) 70%, rgba(${mix},${(peak*.6).toFixed(3)}) 100%)`;
  el.style.opacity=r(Math.min(1,peak*1.15)); return r(p); }
let lastCap=null, pending=[];
async function render(t,layer){
  if(!window._imgsReady){ window._imgsReady=true; const ims=[]; for(const it of ITEMS) if(it.kind==='window'&&it.scene) for(const v of Object.values(it.scene)) { const add=u=>{ if(typeof u==='string'&&u.startsWith('file:')){const im=new Image(); im.src=u; ims.push(im.decode().catch(()=>{}));} }; Array.isArray(v)?v.forEach(add):add(v); } await Promise.all(ims); }
  const K=[layer||'']; let capY=CFG.cap_y, hideCap=CFG.cap_mode==='off', fullUp=false;
  if(layer==='bg') hideCap=true;
  if(CFG.title){const T=CFG.title, el=$('title'), on=t>=T.t[0]&&t<T.t[1], pin=cl((t-T.t[0])/.25), pout=cl((T.t[1]-t)/.15);
    const op=on&&layer!=='bg'?Math.min(cl(pin*2),pout):0; el.style.opacity=r(op); el.style.transform=`scale(${r(.94+.06*back(pin))})`; K.push(r(op),el.style.transform);}
  for(const it of ITEMS){
    const el=$(it.id), on=t>=it.a&&t<it.b;
    if(!on){if(el){el.style.opacity=0;}K.push(0);continue;}
    if(!el) continue;
    if(layer&&((layer==='bg')!==!!it.person)){el.style.opacity=0;K.push('h');continue;}
    if(it.kind==='phrase'){ const cover=ITEMS.some(w=>w.kind==='window'&&!w.person&&!w.mini&&w.w>=1000&&w.y<=it.y+60&&w.y+w.h>=it.y-60&&t>=w.a-.3&&t<w.b);  /* a full or top-half insert covers the headline line: hide the headline for exactly that range (the insert carries the content; keep=True overrides) */ if(cover&&!it.keep){el.style.opacity=0;K.push('pf');continue;} K.push(phraseRender(it,t));continue;}
    if(it.kind==='leak'){K.push(leakRender(it,t));continue;}
    if(it.kind==='fx'){continue;}
    if(it.kind==='iconrow'){el.style.opacity=1; el.style.transform=''; const xo=cl((it.b-t)/.3); let key='';
      el.querySelectorAll('.ic').forEach((c,j)=>{const p=cl((t-it.icons[j].at)/(.3*(CFG.smooth||1))); c.style.opacity=r(Math.min(cl(p*2.5),xo)); c.style.transform=`scale(${r(.6+.4*back(p,1.3))}) translateY(${r((1-ease(p))*12)}px)`; key+=Math.round(p*20)+'.';}); K.push(key); continue;}
    let [eo,etf,clip,efl]=enter(it,t); const [xo,xtf,xclip,xfl]=exit_(it,t); clip=clip||xclip||''; const fl=efl||xfl||'';
    if(it.kind==='text'&&it.anim==='type'){const n=Math.floor((t-it.a)*(it.cps||18)); el.innerHTML=typed(esc(it.s),n); K.push(Math.min(n,it.s.length));}
    let base=''; if(it.kind==='window'&&it.tilt) base=`perspective(1600px) rotateY(${it.tilt}deg) `;
    if(it.kind==='sticker'&&it.rot) base+=`rotate(${it.rot}deg) `;
    if(it.kind==='text'&&it.anchor==='center') base='translateX(-50%) ';
    if(it.kind==='card') base='translate(-50%,-50%) ';
    if(it.kind==='window'&&it.tilt&&etf.includes('rotateY')) base=`perspective(1600px) `;
    let idle=''; if(it.kind==='sticker'&&it.idle&&t>it.a+(DIN[it.anim]??.2)){const q=t-it.a; idle=it.idle==='float'?` translateY(${r(Math.sin(q*2.2)*7)}px) rotate(${r(Math.sin(q*1.7)*2.5)}deg)`:it.idle==='pulse'?` scale(${r(1+.04*Math.sin(q*4))})`:it.idle==='wiggle'?` rotate(${r(Math.sin(q*9)*4)}deg)`:'';}
    el.style.opacity=r(Math.min(eo,xo)); el.style.transform=base+etf+' '+xtf+idle; el.style.clipPath=clip; el.style.filter=fl;
    K.push(el.style.opacity,el.style.transform,clip,fl);
    if(it.kind==='text'&&it.hide_cap) hideCap=true;
    if(it.kind==='window'){
      if(it.cap_y!=null) capY=it.cap_y; if(it.w>=1080&&it.h>=1900) fullUp=true;
      const m=MEDIA[it.id], img=$(it.id+'_img');
      if(img&&m.n>1){let f=Math.floor((t-it.a)*CFG.fps); f=it.loop?f%m.n:Math.min(f,m.n-1); const src=`media/${it.id}/${String(f).padStart(5,'0')}.png`;
        if(!img.getAttribute('src').endsWith(src)){img.src=src;pending.push(img);} K.push(f);}
      if(it.scroll){const [sp,dl]=it.scroll, maxY=Math.max(0,m.h-it.h), y=cl((t-it.a-dl)*sp,0,maxY); img.style.transform=`translateY(${r(-y)}px)`; K.push(r(y));}
      if(it.scene){K.push(SC(it.scene.kind).update($(it.id+'_sc'),it.scene,t-it.a));}
      if(it.drift){const inner=$(it.id+'_sc')||img, u=cl((t-it.a)/Math.max(1,it.b-it.a)), d=1+it.drift*u, px=(it.scene?0:-it.drift*220*u); if(inner){inner.style.transformOrigin='50% 40%'; inner.style.transform=(inner.style.transform.replace(/scale\([^)]*\)/,'').replace(/translateX\([^)]*\)/,'')+` translateX(${r(px)}px) scale(${r(d)})`).trim(); K.push(r(d));}}
    }
    if(it.kind==='phrase'){K.push(phraseRender(it,t));continue;}
    if(it.kind==='leak'){K.push(leakRender(it,t));continue;}
    if(it.kind==='flash'){const p=cl((t-it.a)/it.dur); el.style.opacity=r(Math.pow(1-p,2.2)); el.style.transform=''; K.push(el.style.opacity);}
    if(it.kind==='bars'){const p=ease(cl((t-it.a)/.45))*ease(cl((it.b-t)/.35)); el.style.opacity=1; el.style.transform=''; el.querySelector('.bt').style.transform=`translateY(${r(-(1-p)*100)}%)`; el.querySelector('.bb').style.transform=`translateY(${r((1-p)*100)}%)`; K.push(r(p));}
    if(it.kind==='burst'){const cv=el.querySelector('canvas'),g=cv.getContext('2d'),S=it.spread,u=cl((t-it.a)/.9),R=rnd(it.id.length*31+7); g.clearRect(0,0,S*2,S*2); el.style.opacity=1; el.style.transform='';
      for(let i=0;i<it.n;i++){const ang=R()*6.283,sp=(.5+R()*.5)*S,grav=S*.7,x=S+Math.cos(ang)*sp*ease(u),y=S+Math.sin(ang)*sp*ease(u)+grav*u*u,sz=(14+R()*22)*(1-u*.35),rot=u*R()*12; g.save(); g.translate(x,y); g.rotate(rot); g.globalAlpha=1-Math.pow(u,3); g.fillStyle=it.colors[i%it.colors.length]; g.shadowColor=g.fillStyle; g.shadowBlur=10; if(i%3) g.fillRect(-sz/2,-sz/4,sz,sz/2); else {g.beginPath(); g.arc(0,0,sz/2,0,6.283); g.fill();} g.restore();} K.push(r(u));}
    if(it.kind==='circle'){const p=ease((t-it.a)/.45); el.querySelectorAll('.d').forEach(q=>{q.style.strokeDasharray=1;q.style.strokeDashoffset=r(1-p);}); K.push(r(p));}
    if(it.kind==='cursor'){const P=it.path, segs=P.length-1, u=cl((t-it.a)/Math.max(.01,(it.b-it.a-.25)))*segs, i=Math.min(segs-1,Math.floor(u)), f=eio(u-i);
      const x=P[i][0]+(P[i+1][0]-P[i][0])*f, y=P[i][1]+(P[i+1][1]-P[i][1])*f, click=t>it.b-.25?1-.18*Math.sin(cl((t-(it.b-.25))/.2)*Math.PI):1;
      el.style.transform=`translate(${r(x)}px,${r(y)}px) scale(${r(click)})`; el.style.opacity=r(Math.min(cl((t-it.a)/.1),xo)); K.push(el.style.transform);}
  }
  const c=CAPS.find(c=>t>=c.s&&t<c.e), cap=$('cap');
  if(c!==lastCap){const inner=c?c.w.map(w=>`<span class='${w.em?'em':''}'>${w.t}</span>`).join(' '):''; cap.innerHTML=CFG.cap_style==='box'&&c?`<span class='box'>${inner}</span>`:inner;lastCap=c;}
  if(CFG.cap_mode==='full'&&!fullUp) hideCap=true;
  const cp=c&&CFG.cap_pop?cl((t-c.s)/.14):1; cap.style.opacity=c&&!hideCap?1:0; cap.style.fontSize=CFG.cap_size+'px';
  cap.style.top=(capY-CFG.cap_size*.6)+'px'; cap.style.transform=`scale(${r(1-.3*AMP+.3*AMP*back(cp,OVER+.3))})`;
  K.push(c?c.s:-1,cap.style.transform,capY,hideCap);
  if(pending.length){await Promise.all(pending.map(i=>i.decode().catch(()=>{})));pending=[];}

  return K.join('|');
}
</script>"""

def page(CFG, ITEMS, MEDIA, caps):
    cfg = dict(fps=CFG["fps"], cap_y=CFG["cap_y"], cap_size=CFG["cap_size"], cap_pop=CFG["cap_pop"], title=CFG["title"], cap_style=CFG["cap_style"], cap_mode=CFG["cap_mode"], smooth=CFG.get("smooth", 1.0))
    js = (JS.replace("__CAPS__", json.dumps([] if CFG.get("captions") is False else caps)).replace("__ITEMS__", json.dumps(ITEMS)).replace("__CFG__", json.dumps(cfg))
          .replace("__MEDIA__", json.dumps(MEDIA)).replace("__SAFE__", json.dumps(SAFE)))
    motion = (HERE / "motion.js").read_text() if (HERE / "motion.js").exists() else ""
    th = theme_of(CFG); css = (CSS.replace("ACC2", th["acc2"]).replace("HEROSH", th["heroshadow"]).replace("HERO", th["hero"]).replace("ACC", th["acc"]).replace("LIME", th["hero"])
                               .replace("INK", th["ink"]).replace("BGC", th["bg"]))
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body(CFG, ITEMS, MEDIA)}<script>window.THEME={json.dumps(th)}</script><script>{motion}</script>{js}</body></html>"

# ============================ SFX ============================
SYNTH = {   # ffmpeg recipes used when the library has no file for a name. Deliberately small, dark and short: UI sounds, not trailer hits.
    "tick":     "aevalsrc='sin(2*PI*(520*t-1400*t*t))*exp(-t*55)':s=48000:d=0.1",                       # soft 'tok' for stickers / words
    "pop":      "aevalsrc='sin(2*PI*(620*t-1800*t*t))*exp(-t*32)':s=48000:d=0.16",                      # rounder bubble pop
    "bubble":   "aevalsrc='sin(2*PI*(380*t-700*t*t))*exp(-t*16)':s=48000:d=0.3",
    "whoosh":   "anoisesrc=c=brown:r=48000:a=1:d=0.45:s=7,highpass=f=250,lowpass=f=2400,volume=volume='pow(sin(PI*pow(min(t/0.45,1),0.3)),2)':eval=frame",
    "swipe":    "anoisesrc=c=pink:r=48000:a=1:d=0.22:s=3,highpass=f=600,lowpass=f=3500,volume=volume='pow(sin(PI*pow(min(t/0.22,1),0.35)),2)':eval=frame",
    "intro":    "anoisesrc=c=brown:r=48000:a=1:d=0.8:s=5,highpass=f=150,lowpass=f=2800,volume=volume='pow(sin(PI*pow(min(t/0.8,1),0.35)),2)':eval=frame",
    "click":    "anoisesrc=c=white:r=48000:a=1:d=0.11:s=2,highpass=f=1200,lowpass=f=6000,volume=volume='if(lt(t,0.012),1,if(between(t,0.085,0.095),0.6,0))':eval=frame",  # mouse down + up
    "scribble": "anoisesrc=c=pink:r=48000:a=1:d=0.4:s=9,highpass=f=900,lowpass=f=4500,volume=volume='0.7*abs(sin(2*PI*11*t))':eval=frame",
    "hit":      "aevalsrc='sin(2*PI*(140*t-200*t*t))*exp(-t*12)+0.4*sin(2*PI*(900*t-6000*t*t))*exp(-t*45)':s=48000:d=0.38",   # trailer hit: sub thump + click
    "riser":    "aevalsrc='(0.55*sin(2*PI*(180*t+700*t*t))+0.35*sin(2*PI*(270*t+1050*t*t))+0.5*random(0)*pow(min(t/1.1\\,1)\\,2))*pow(min(t/1.1\\,1)\\,2.2)*(1-max(0\\,(t-1.02)/0.08))':s=48000:d=1.1",   # tension sweep into a hit
    "boom":     "aevalsrc='sin(2*PI*(70*t-40*t*t))*exp(-t*6)':s=48000:d=0.55",                           # cinematic sub boom
    "thud":     "aevalsrc='sin(2*PI*(95*t-120*t*t))*exp(-t*22)+0.25*sin(2*PI*(600*t-3000*t*t))*exp(-t*70)':s=48000:d=0.22",   # dark short hit: the serious 'pop'
    "tock":     "aevalsrc='sin(2*PI*(240*t-500*t*t))*exp(-t*60)':s=48000:d=0.08",                        # low wooden tick
    "swell":    "aevalsrc='(0.7*sin(2*PI*52*t)+0.3*sin(2*PI*104*t))*pow(min(t/0.9\\,1)\\,2.5)*(1-max(0\\,(t-0.86)/0.06))':s=48000:d=0.92",   # sub swell into a hit
}

_SND = "/System/Library/Components/CoreAudio.component/Contents/SharedSupport/SystemSounds"
MAC = {   # name: (file, start, length, extra filter). Real recordings beat synthesis for crispness; trimmed to the transient.
    "click":    ("/System/Library/Sounds/Tink.aiff", 0, .16, "highpass=f=700"),
    "bell":     ("/System/Library/Sounds/Glass.aiff", 0, .6, "highpass=f=600,volume=-4dB"),
    "pop":      ("/System/Library/Sounds/Pop.aiff", 0, .2, "highpass=f=300"),
    "tick":     (f"{_SND}/accessibility/Slow Keys, Key Registered.aif", 0, .14, "highpass=f=900"),
    "key":      (f"{_SND}/accessibility/Slow Keys, Key Registered.aif", 0, .07, "highpass=f=1500"),
    "whoosh":   (f"{_SND}/finder/move to trash.aif", 0, .34, "highpass=f=350"),
    "swipe":    (f"{_SND}/system/acknowledgment_sent.caf", 0, .29, "highpass=f=600"),
    "send":     (f"{_SND}/system/SentMessage.caf", 0, .32, "highpass=f=400"),
    "poof":     (f"{_SND}/dock/poof item off dock.aif", 0, .34, "highpass=f=500"),
    "scribble": (f"{_SND}/ink/InkSoundStroke3.aif", 0, .36, "highpass=f=800"),
    "intro":    (f"{_SND}/finder/move to trash.aif", 0, .6, "highpass=f=250"),
    "shutter":  (f"{_SND}/system/Grab.aif", 0, .22, "highpass=f=500"),
    "chime":    (f"{_SND}/system/Volume Mount.aif", 0, .4, "highpass=f=400"),
    "ding":     ("/System/Library/Sounds/Glass.aiff", 0, .45, "highpass=f=500"),                                  # bright win / emphasis
    "sparkle":  ("/System/Library/Sounds/Glass.aiff", 0, .3, "asetrate=48000*1.5,aresample=48000,highpass=f=1200"),   # icon pop-up glitter
    "hero":     ("/System/Library/Sounds/Hero.aiff", 0, .55, "highpass=f=300"),                                   # triumphant reveal
    "sub":      ("/System/Library/Sounds/Submarine.aiff", 0, .45, "lowpass=f=900"),                               # deep swell
}

SFX_LIB = {   # cue name -> (sfx/ category, max seconds). The collection (sound_collect.py) beats the macOS/synth fallbacks.
    "hit": ("impact", 1.2), "thud": ("impact", .6), "slam": ("impact", 1.0), "boom": ("sub", 1.6), "sub": ("sub", 1.2), "swell": ("riser", 1.6),
    "riser": ("riser", 3.5), "riser_long": ("riser", 7.0), "whoosh": ("whoosh", .8), "swipe": ("whoosh", .5), "intro": ("whoosh", 1.0),
    "hero": ("stinger", 2.0), "braam": ("braam", 2.5), "stinger": ("stinger", 2.5), "glitch": ("glitch", .6), "click": ("click", .3),
    "tick": ("click", .25), "tock": ("click", .25), "key": ("typing", .12), "pop": ("pop", .4), "sparkle": ("ding", .6), "ding": ("ding", 1.2),
    "chime": ("ding", 1.5), "bell": ("ding", 1.2), "send": ("pop", .5), "cash": ("cash", 1.5), "heartbeat": ("heartbeat", 3.0), "ticking": ("ticking", 4.0),
}

def lib_sound(name, CFG, OUT):
    """A trimmed, normalised copy of a library sound for this cue, or None. Rotates by reel name so repeats differ a little
    (CFG['sfx_variety'] picks how many variants rotate; 1 = always the top one)."""
    idx_f = HERE / "sfx" / "INDEX.json"
    if name not in SFX_LIB or not idx_f.exists(): return None
    cat, maxd = SFX_LIB[name]; idx = json.loads(idx_f.read_text()); srcs = CFG.get("sfx_sources", ("freesound", "bbc"))
    c = [v for v in idx.values() if v["cat"] == cat and v["src"] in srcs and (HERE / "sfx" / (("bbc_" if v["src"] == "bbc" else "") + cat) / v["file"]).exists()]
    if not c: return None
    c.sort(key=lambda v: (v["src"] != "freesound", v["file"])); n = max(1, min(len(c), CFG.get("sfx_variety", 3)))
    v = c[sum(map(ord, CFG["name"] + name)) % n]; src = HERE / "sfx" / (("bbc_" if v["src"] == "bbc" else "") + cat) / v["file"]
    d = OUT / "sfx_gen"; d.mkdir(parents=True, exist_ok=True); f = d / f"{name}.wav"
    if not f.exists():
        raw = d / f"_{name}.wav"
        # trim to the cue length from the loudest onset (silence before the transient is removed), fade the tail, normalise
        for thr in ("-45dB", None):   # drop the silence before the transient; if that eats the whole sound (very quiet subs), keep it as is
            sr = f"silenceremove=start_periods=1:start_threshold={thr}:start_silence=0.02," if thr else ""
            ff("-i", src, "-af", f"{sr}atrim=0:{maxd},afade=t=out:st={max(0, maxd - .12):.3f}:d=0.12,aresample=48000", "-ac", "2", "-c:a", "pcm_s16le", raw)
            d_ = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(raw)], capture_output=True, text=True).stdout.strip()
            if d_ not in ("", "N/A") and float(d_) > .05: break
        else: raw.unlink(missing_ok=True); return None
        det = subprocess.run(["ffmpeg", "-v", "info", "-i", str(raw), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
        m = re.search(r"max_volume: (-?[\d.]+) dB", det); peak = float(m.group(1)) if m else -1
        ff("-i", raw, "-af", f"volume={-1 - peak:.1f}dB", "-c:a", "pcm_s16le", f); raw.unlink()
    return f

def sfx_file(name, CFG, OUT):
    """A library file (CFG['sfx'][name], relative to CFG['sfx_lib']) or a synthesized fallback in out/sfx_gen/."""
    if name is None: return None
    p = pathlib.Path(name).expanduser()
    if p.suffix and p.exists(): return p
    rel = CFG["sfx"].get(name)
    if rel:
        q = pathlib.Path(rel).expanduser()
        if not q.is_absolute() and CFG["sfx_lib"]: q = pathlib.Path(CFG["sfx_lib"]).expanduser() / q
        if q.exists(): return q
        print(f"  sfx '{name}': {q} not found, using synthesized fallback")
    lib = lib_sound(name, CFG, OUT)
    if lib: return lib
    if name == "slam": name = "hit"
    if name in ("riser_long", "braam", "stinger", "cash", "heartbeat", "ticking", "glitch"): name = {"riser_long": "riser", "braam": "hit", "stinger": "hero", "cash": "ding", "heartbeat": "boom", "ticking": "tick", "glitch": "click"}[name]
    if name not in SYNTH and name not in MAC: print(f"  sfx '{name}': unknown, using 'tick'"); name = "tick"
    d = OUT / "sfx_gen"; d.mkdir(parents=True, exist_ok=True); f = d / f"{name}.wav"
    if not f.exists():   # a trimmed macOS recording when available, else synthesis; then normalise to -1 dBFS peak
        raw = d / f"_{name}.wav"; mac = MAC.get(name)
        if mac and pathlib.Path(mac[0]).exists():
            ff("-ss", mac[1], "-t", mac[2], "-i", mac[0], "-af", f"{mac[3]},afade=t=in:st=0:d=0.004,afade=t=out:st={mac[2] - .07:.3f}:d=0.07,aresample=48000", "-ac", "2", "-c:a", "pcm_s16le", raw)
        else: ff("-f", "lavfi", "-i", SYNTH[name], "-ac", "2", "-c:a", "pcm_s16le", raw)
        det = subprocess.run(["ffmpeg", "-v", "info", "-i", str(raw), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
        peak = float(re.search(r"max_volume: (-?[\d.]+) dB", det).group(1))
        ff("-i", raw, "-af", f"volume={-1 - peak:.1f}dB", "-c:a", "pcm_s16le", f); raw.unlink()
    return f

def scene_sounds(it):
    """Micro-sounds that follow a scene's own animation: soft key clicks while text is typed (10/s, varied), a tick per item/line
    that appears. Deterministic. Disable with item_sfx=False / type_sfx=False in the scene cfg."""
    sc, a, ev = it["scene"], it["a"], []; k = sc["kind"]
    def keys(start, n_chars, cps):
        if sc.get("type_sfx", True) is False or n_chars <= 0: return
        dur = min(n_chars / cps, it["b"] - it["a"] - .1); n = int(dur * 10)
        for i in range(n): ev.append(("key", a + start + i / 10 + ((i * 7919) % 23) / 1000, .22 + ((i * 104729) % 10) / 100))
    def ticks(start, n, step, name="tick", vol=.45):
        if sc.get("item_sfx", True) is False: return
        for i in range(n):
            t = a + start + i * step
            if t < it["b"] - .05: ev.append((name, t, vol))
    if k == "terminal":
        cmd = sc.get("cmd", ""); cps = sc.get("cps", 28); d = sc.get("delay", .2); keys(d, len(cmd), cps)
        ticks(d + len(cmd) / cps + .35, len(sc.get("lines", [])), sc.get("step", .45), vol=.4)
    elif k == "chat": keys(.3, len(sc.get("prompt", "")), sc.get("cps", 30))
    elif k in ("doc", "code"):
        n = sum(len(l) for l in sc.get("lines", [])) + len(sc.get("heading", "")); keys(.15, n, sc.get("cps", 40 if k == "doc" else 55))
    elif k == "search": keys(.3, len(sc.get("query", "")), sc.get("cps", 22))
    elif k == "cards": ticks(.1, len(sc.get("cards", [])), sc.get("step", .45), "pop", .5)
    elif k == "flow": ticks(.1, len(sc.get("nodes", [])), sc.get("step", .45))
    elif k == "checklist": ticks(.4, len(sc.get("items", [])), sc.get("step", .5))
    elif k == "phone": ticks(.3, len(sc.get("notifications", [])), sc.get("step", .8), "pop", .6)
    elif k == "timeline": ticks(.15, len(sc.get("points", [])), sc.get("step", .5))
    elif k == "stats": ticks(.1, len(sc.get("tiles", [])), sc.get("step", .18), vol=.35)
    elif k == "email": ticks(.15, len(sc.get("messages", [])), sc.get("step", .6), "pop", .45)
    elif k == "orgchart": ticks(.3, len(sc.get("roles", [1, 2, 3, 4])), sc.get("step", .55), "pop", .5)
    elif k == "reviews": ticks(.2, len(sc.get("items", [1, 2, 3])), sc.get("step", .55), "swipe", .5)
    elif k == "marketmap": ticks(.2, len(sc.get("dots", [1] * 7)), .14, "tick", .35); ev.append(("hit", a + .2 + len(sc.get("dots", [1] * 7)) * .14 + .2, .8))
    elif k == "assemble": ticks(.2, 8, sc.get("step", .22), "tick", .4); ev.append(("send", a + .2 + 8 * sc.get("step", .22) + .1, .6))
    elif k == "chess": ticks(.15, 16, .06, "tick", .3); ev.append(("whoosh", a + sc.get("flip", 1.7), .8)); ev.append(("hit", a + sc.get("flip", 1.7) + .9, .9))
    elif k == "headcount": ev.append(("swipe", a + sc.get("start", .5), .6)); ev.append(("hit", a + sc.get("start", .5) + sc.get("dur", 1.6), .9))
    elif k == "orbit": ticks(.2, len(sc.get("logos", [1] * 4)), .12, "tick", .4)
    elif k == "calendar": ev += [("key", a + i * .1, .3) for i in range(int(sc.get("dur", 1.5) * 10))]; ev.append(("hit", a + sc.get("dur", 1.5), 1.0))
    elif k == "carousel": ticks(0, len(sc.get("items", [1] * 5)), sc.get("step", .7), "swipe", .55)
    elif k == "waveform": ev.append(("swipe", a + sc.get("morph", .8), .6))
    elif k == "race": ev.append(("hit", a + sc.get("dur", 2.2), 1.0))
    elif k == "typo": ev.append(("hit", a, 1.0)); ev.append(("hit", a + sc.get("t2", .9), 1.0))
    elif k == "browser" and sc.get("cursor", True) is not False:
        n = 3 + len(sc.get("cards", [])) - (0 if sc.get("button") else 1); st = sc.get("step", .35)
        ev.append(("click", a + .1 + n * st + .2 + .6, .7))
        if sc.get("toast"): ev.append(("send", a + .1 + n * st + .2 + .9, .55))
    return ev

def sfx_events(CFG, ITEMS, EXTRA):
    """(name, time, volume) for every animated entrance, every micro-event inside scenes, plus SFX_EXTRA."""
    ev = []
    if CFG["intro_whoosh"]: ev.append(("intro", 0.0, .6))
    for it in ITEMS:
        if it.get("sfx"):
            t = it["b"] - .25 if it["kind"] == "cursor" else it["a"]
            ev.append((it["sfx"], t, it.get("vol", .9)))
        if it["kind"] == "window" and it.get("scene"): ev += scene_sounds(it)
        if it["kind"] == "iconrow" and it.get("sfx"):
            for ic in it["icons"]: ev.append((it["sfx"], ic["at"], it["vol"]))
        if it["kind"] == "phrase":
            for w in it["words"]:
                n = it["hero_sfx"] if w["role"] in ("hero", "big") else it["sfx"]
                if n: ev.append((n, w["at"], it["vol"] if w["role"] in ("hero", "big") else it["vol"] * .7))
        if it["kind"] == "text" and it.get("anim") == "type":
            for i in range(int(min(len(it["s"]) / it["cps"], it["b"] - it["a"]) * 10)): ev.append(("key", it["a"] + i / 10, .25))
    ev += [tuple(e) for e in EXTRA]
    pal = PALETTES.get(CFG.get("_tone", {}).get("tone", "warm"), {}) if CFG.get("palette", "auto") == "auto" else {}
    ev = [(pal.get(n, n), t, v) for n, t, v in ev]
    if CFG.get("sfx_style", "soft") == "soft":   # the default: rounded, low cues; a sharp click or glass ding pulls attention off the voice
        ev = [(SOFT.get(n, n), t, v * .8) for n, t, v in ev if SOFT.get(n, n) is not None]
    if CFG.get("emph_sfx") and CFG.get("_caps"):
        n, v = CFG["emph_sfx"]; ev += [(n, c["s"], v) for c in CFG["_caps"] if any(w["em"] for w in c["w"])]
    return sorted(ev, key=lambda e: e[1])

def sfx_wav(CFG, ITEMS, EXTRA, OUT, DUR):
    out = OUT / f"{CFG['name']}_sfx.wav"; ev = [(sfx_file(n, CFG, OUT), t, v) for n, t, v in sfx_events(CFG, ITEMS, EXTRA)]
    ev = [e for e in ev if e[0] and 0 <= e[1] < DUR]
    if not ev: ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", DUR, "-c:a", "pcm_s16le", out); return out
    ins = sum([["-i", f] for f, _, _ in ev], [])
    mix = ("".join(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={v},adelay={int(t*1000)}:all=1[a{k}];" for k, (_, t, v) in enumerate(ev))
           + "".join(f"[a{k}]" for k in range(len(ev))) + f"amix=inputs={len(ev)}:normalize=0:dropout_transition=0,volume={CFG['sfx_gain']},alimiter=limit=0.95:level=0,apad=whole_dur={DUR}[m]")
    ff(*ins, "-filter_complex", mix, "-map", "[m]", "-t", DUR, "-c:a", "pcm_s16le", out)
    return out

VOICE_PRE = "highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=8:release=150:makeup=4dB,equalizer=f=3200:t=q:w=1.2:g=2"

def voice_gain(CUT):
    """Measure the cleaned voice's integrated loudness once and return the fixed gain (dB) that lands it at -14 LUFS.
    A fixed gain is transparent; single-pass loudnorm in dynamic mode pumps on speech."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(CUT), "-vn", "-af", f"aresample=48000,{VOICE_PRE},ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r)
    return round(max(-20.0, min(20.0, -14.0 - float(m[-1]))), 1) if m else 0.0

def voice_tone(CFG, CUT, OUT, caps):
    """Pitch + pace of the speaker -> a tone that steers music and the SFX palette. Cached in out/tone.json.
    tone: intense (deep + fast), serious (deep + measured), energetic (higher + fast), warm (higher + measured), calm (slow)."""
    if CFG.get("tone") not in (None, "auto"): return dict(tone=CFG["tone"], f0=None, rate=None, note="set in config")
    cache = OUT / "tone.json"
    if cache.exists(): return json.loads(cache.read_text())
    try:
        import numpy as np, wave
        wav = OUT / "_tone16k.wav"; ff("-i", CUT, "-vn", "-ac", "1", "-ar", "16000", "-t", "120", wav)
        w = wave.open(str(wav)); sr = w.getframerate(); x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768; wav.unlink()
        win, hop = int(.04 * sr), int(.02 * sr); f0s = []
        for i in range(0, len(x) - win, hop):
            fr = x[i:i + win]
            if np.sqrt(np.mean(fr ** 2)) < .02: continue
            fr = fr - fr.mean(); ac = np.correlate(fr, fr, "full")[win - 1:]; ac /= ac[0] + 1e-9
            lo, hi = int(sr / 400), int(sr / 70); k = lo + int(np.argmax(ac[lo:hi]))
            if ac[k] > .5: f0s.append(sr / k)
        f0 = float(np.median(f0s)) if f0s else 0.0
    except Exception as e: f0 = 0.0
    words = [w for c in caps for w in c["w"]]; speech = sum(min(c["e"], c["s"] + 1.0) - c["s"] for c in caps) or 1
    rate = len(words) / speech if caps else 0.0
    deep = 0 < f0 < 135; fast = rate > 3.3
    tone = "calm" if 0 < rate < 2.2 else "intense" if deep and fast else "serious" if deep else "energetic" if fast else "warm"
    if not f0 and not caps: tone = "warm"
    r = dict(tone=tone, f0=round(f0), rate=round(rate, 2)); cache.write_text(json.dumps(r)); return r

SOFT = dict(hit="thud", slam="thud", braam="boom", stinger="boom", ding="chime", sparkle=None, click="click", bell="chime", tick="tock", key=None, shutter=None,
            scribble=None, send="tock", pop="thud", hero="boom", cash="cash", riser="riser", riser_long="riser_long", glitch=None)   # sfx_style="soft"
PALETTES = {   # generic cue name -> the sound that fits the speaker's tone
    "intense":   dict(sparkle="thud", pop="thud", bubble="thud", ding="hit", hero="boom", riser="swell", tick="tock", chime="sub", send="tock", intro="swell"),
    "serious":   dict(sparkle="thud", pop="thud", bubble="thud", ding="hit", hero="boom", riser="swell", tick="tock", chime="sub", send="tock", intro="swell"),
    "calm":      dict(hit="thud", boom="sub", hero="chime", riser="swell", ding="chime", sparkle="chime", pop="bubble"),
    "energetic": {}, "warm": {},
}
PREFER = {   # track tags to favour / avoid per mood (scored against music/INDEX.json)
    "trailer":   (["epic", "trailer", "cinematic", "hybrid", "percussion", "action", "tension"], ["corporate", "happy", "kids", "christmas", "wedding"]),
    "hiphop":    (["trap", "hip hop", "hip-hop", "beat", "drill", "phonk", "dark"], ["corporate", "happy", "kids", "christmas", "lofi"]),
    "dramatic":  (["suspense", "suspense", "suspense", "tension", "tension", "tension", "building", "trailer", "dramatic", "cinematic", "epic"], ["horror", "scary", "creepy", "spooky", "eerie", "halloween"]),   # repeated = weighted: suspense first
    "upbeat":    (["hip hop", "trap", "funk", "energetic", "sport", "house"], ["corporate", "kids", "children", "funny", "comedy", "christmas", "ukulele"]),
    "tech":      (["technology", "electronic", "future", "minimal"], ["kids", "funny"]),
    "lofi":      (["lofi", "chill", "study"], ["sad"]),
    "cinematic": (["inspiring", "emotional", "piano", "cinematic"], ["horror", "scary"]),
}

MOOD_WORDS = {
    "upbeat":    ["startup", "launch", "business", "money", "sales", "growth", "clients", "revenue", "win", "fast", "hack", "tips"],
    "tech":      ["ai", "code", "claude", "gpt", "prompt", "app", "build", "automate", "agent", "tool", "api", "software", "model"],
    "lofi":      ["how to", "step", "tutorial", "guide", "setup", "simple", "learn", "routine", "study", "workflow"],
    "cinematic": ["story", "journey", "dream", "life", "changed", "believe", "future", "world", "imagine", "beautiful", "video", "film"],
    "dramatic":  ["mistake", "never", "warning", "lose", "fail", "truth", "wrong", "stop", "danger", "problem"],
}

def pick_mood(caps, tone="warm"):
    """Content words give a candidate; the speaker's tone decides the register. Beds are never 'corporate': a deep, driving voice gets
    trailer / dark hip hop, an energetic one gets hip hop, a measured one cinematic, a slow one lofi."""
    text = " ".join(w["t"].lower() for c in caps for w in c["w"])
    score = {m: sum(text.count(k) for k in ks) for m, ks in MOOD_WORDS.items()}
    best = max(score, key=score.get); best = best if score[best] else "upbeat"
    if tone == "intense": return "trailer" if best in ("dramatic", "cinematic") else "hiphop"
    if tone == "serious": return "trailer" if best in ("dramatic", "upbeat", "tech") else "cinematic"
    if tone == "energetic": return "hiphop" if best in ("upbeat", "tech", "dramatic") else best
    if tone == "calm": return "lofi" if best in ("lofi", "upbeat", "tech") else "cinematic"
    return {"upbeat": "upbeat", "tech": "tech", "lofi": "lofi", "cinematic": "cinematic", "dramatic": "trailer"}.get(best, "hiphop")

def liked_track(CFG, DUR, mood, force=False):
    """A LICENSED file the user placed in <skill>/music/liked/ whose TASTE.json moods include `mood` (any liked track when force).
    The skill never downloads commercial recordings; this folder is where the user's own licensed copies live."""
    d = HERE / "music" / "liked"; audio = [f for f in d.glob("*") if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".aif", ".aiff", ".flac")] if d.exists() else []
    if not audio: return None
    try: taste = json.loads((d / "TASTE.json").read_text()).get("tracks", [])
    except Exception: taste = []
    def moods(f): return next((tr["moods"] for tr in taste if tr["title"].lower() in f.stem.lower()), [])
    fit = [f for f in audio if mood in moods(f)] or ([f for f in audio if moods(f) and mood in ("upbeat", "lofi", "tech", "cinematic") and set(moods(f)) & {"upbeat", "lofi", "tech", "cinematic"}])
    pool = fit or (audio if force else [])
    if not pool: return None
    durs = {f: duration(f) for f in pool}; ranked = sorted(pool, key=lambda f: (durs[f] < DUR, -durs[f]))
    return ranked[sum(map(ord, CFG["name"])) % min(3, len(ranked))]

def music_bed(CFG, OUT, DUR, caps):
    """The background music file for this reel, looped/trimmed to DUR. CFG['music']: None/False (no music: the user adds a licensed song
    in the Instagram app), 'auto' (mood from the transcript; the user's licensed tracks in music/liked/ win when their moods fit),
    'liked' (force a liked track), a mood name, or a path to a track. A real track from CFG['music_lib']/<mood>/ wins over the composer."""
    m = CFG.get("music")
    if not m: return None, None
    p = pathlib.Path(str(m)).expanduser()
    tone = CFG.get("_tone", {}).get("tone", "warm")
    liked = liked_track(CFG, DUR, pick_mood(caps, tone) if m in ("auto", "liked") else str(m), force=(m == "liked"))
    if p.suffix and p.exists(): src, label = p, p.name
    elif liked: src, label = liked, f"liked: {liked.name} (the user's preferred track)"
    else:
        if m == "liked": print("music: no licensed file in music/liked/ fits; falling back to the collection (never downloading the original)")
        mood = pick_mood(caps, tone) if m in ("auto", "liked") else str(m)
        libs = [pathlib.Path(CFG["music_lib"]).expanduser()] if CFG.get("music_lib") else []
        libs += [HERE / "music", pathlib.Path("~/reel-music").expanduser()]          # the skill's Pixabay collection, then the user's own
        tracks = sorted({f for lib in libs for f in (lib / mood).glob("*") if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".aif", ".aiff", ".flac")} if True else [])
        if tracks:
            # score by tags (favour / avoid lists), prefer tracks at least as long as the reel (no loop seam), rotate among the top 3 by reel name
            idx = json.loads((HERE / "music" / "INDEX.json").read_text()) if (HERE / "music" / "INDEX.json").exists() else {}
            tags = {v["file"]: (v.get("name", "") + " " + v.get("tags", "")).lower() for v in idx.values()}
            fav, avoid = PREFER.get(mood, ([], []))
            def sc(f):
                tg = tags.get(f.name, f.stem.replace("-", " ")); return sum(k in tg for k in fav) - 3 * sum(k in tg for k in avoid)
            durs = {f: duration(f) for f in tracks}; ranked = sorted(tracks, key=lambda f: (-sc(f), durs[f] < DUR, -durs[f]))
            top = [f for f in ranked if sc(f) == sc(ranked[0])][:3]   # rotate only among tracks that fit equally well
            src = top[sum(map(ord, CFG["name"])) % len(top)]; label = f"{mood}: {src.name}"
        else:
            sys.path.insert(0, str(HERE)); import music as _music
            src = OUT / f"music_{mood}.wav"; label = f"{mood} (composed)"
            if not src.exists(): _music.write_wav(src, _music.compose(mood, DUR + 1, seed=sum(map(ord, CFG["name"]))))
    out = OUT / f"{CFG['name']}_music.wav"
    # loop to length, fade in/out, gentle low-pass so it never masks consonants, level to -16 LUFS before the mixer's offset
    ff("-stream_loop", "-1", "-i", src, "-t", DUR, "-af", f"aformat=sample_rates=48000:channel_layouts=stereo,lowpass=f=9000,afade=t=in:st=0:d=1.2,afade=t=out:st={max(0, DUR - 2):.2f}:d=2,loudnorm=I=-16:TP=-2:LRA=9",
       "-c:a", "pcm_s16le", out)
    print(f"music: {label}, {CFG['music_db']} dB under the voice, ducked while speaking")
    return out, label

def voice_mix(CFG, vin, sin, gain_db=0.0, min_=None):
    """Voice first: high-pass rumble, gentle compression, a little presence, fixed gain to -14 LUFS, true-peak limit ~-1.5 dB.
    Then the SFX bus is side-chain ducked by the voice so clicks and whooshes sit under speech instead of on top of it."""
    v = (f"[{vin}]aresample=48000,{VOICE_PRE},volume={gain_db}dB,alimiter=limit=0.84:level=0:attack=3:release=80" if CFG["voice"] else f"[{vin}]aresample=48000")
    if min_ is not None:   # music: -16 LUFS bed -> music_db below the (-14 LUFS) voice, then ducked another ~6 dB while the voice speaks
        mg = CFG["music_db"] + 2
        mus = (f"[{min_}]volume={mg}dB[m0];[vk2][m0]sidechaincompress=threshold=0.03:ratio=2.5:attack=25:release=500:level_sc=1:makeup=1[m];" if CFG["duck"]
               else f"[{min_}]volume={mg}dB[m];")
        if CFG["duck"]:
            return (v + "[v0];[v0]asplit=3[v][vk][vk2];" + f"[{sin}][vk]sidechaincompress=threshold=0.06:ratio=3:attack=5:release=250:level_sc=1[s];"
                    + mus.replace("[vk2][m0]", "[m0][vk2]") + "[v][s][m]amix=inputs=3:normalize=0:duration=first,alimiter=limit=0.97:level=0:attack=3:release=60[a]")
        return v + "[v];" + mus + f"[v][{sin}][m]amix=inputs=3:normalize=0:duration=first,alimiter=limit=0.97:level=0:attack=3:release=60[a]"
    if CFG["duck"]:
        return (v + "[v0];[v0]asplit[v][vk];" + f"[{sin}][vk]sidechaincompress=threshold=0.06:ratio=3:attack=5:release=250:level_sc=1[s];"
                "[v][s]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.97:level=0:attack=3:release=60[a]")
    return v + f"[v];[v][{sin}]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.97:level=0:attack=3:release=60[a]"

# ============================ rendering ============================
def open_page(p, CFG, ITEMS, MEDIA, caps, OUT, W):
    pf = OUT / "overlay.html"; pf.write_text(page(CFG, ITEMS, MEDIA, caps))
    br = p.chromium.launch(executable_path=CFG["chrome"], args=["--allow-file-access-from-files"])
    pg = br.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=W / 1080 * CFG.get("render_scale", 1.0))   # supersampled, downscaled at composite
    pg.goto(pf.as_uri()); pg.wait_for_load_state("networkidle")
    pg.evaluate("Promise.all([document.fonts.load('italic 40px NYI'), document.fonts.load(\"700 40px 'Helvetica Neue'\"), document.fonts.ready])"); pg.wait_for_timeout(300)
    return br, pg

def frames(CFG, ITEMS, MEDIA, caps, OUT, W, H, DUR, layer=None):
    """Overlay PNGs at the cut's resolution. Frames whose DOM state is unchanged are hard-linked, not re-shot. The cache is keyed on the
    rendered page, so any config change re-renders. layer='bg'/'fg' renders only the behind-the-person windows / everything else."""
    from playwright.sync_api import sync_playwright
    import hashlib, shutil
    FPS = CFG["fps"]; fr = OUT / f"frames{'_' + layer if layer else ''}_{W}x{H}"; n = round(DUR * FPS)
    sig = hashlib.sha1((page(CFG, ITEMS, MEDIA, caps) + str(layer)).encode()).hexdigest()
    if fr.exists() and (fr / "page.sig").read_text() != sig if (fr / "page.sig").exists() else fr.exists():
        if os.environ.get("REEL_KEEP_CACHE"):   # one-spot fix: the caller deleted the affected frames by hand, keep the rest
            print("  config changed, REEL_KEEP_CACHE set: keeping unaffected frames"); (fr / "page.sig").write_text(sig)
        else: print("  config changed, dropping the frame cache"); shutil.rmtree(fr)
    if fr.exists() and len(list(fr.glob("*.png"))) == n: return fr
    fr.mkdir(parents=True, exist_ok=True); (fr / "page.sig").write_text(sig); prev = None; shot = 0
    with sync_playwright() as p:
        br, pg = open_page(p, CFG, ITEMS, MEDIA, caps, OUT, W)
        for i in range(n):
            key = pg.evaluate(f"render({i / FPS}, {json.dumps(layer)})"); f = fr / f"{i:05d}.png"
            if f.exists(): prev = None; continue
            if key == prev: os.link(fr / f"{i-1:05d}.png", f)
            else: pg.screenshot(path=f, omit_background=True); shot += 1
            prev = key
            if i % 300 == 0: print(f"  frame {i}/{n}{' ' + layer if layer else ''}")
        br.close()
    print(f"frames {n}, screenshots {shot}, {W}x{H}{' ' + layer if layer else ''}")
    return fr

def person_ranges(ITEMS): return [(it["a"], it["b"]) for it in ITEMS if it["kind"] == "window" and it.get("person")]

def segment_bin():
    b = HERE / "bin" / "segment"
    if not b.exists():
        b.parent.mkdir(exist_ok=True); print("  compiling segment.swift (Vision person matte)")
        subprocess.run(["swiftc", "-O", "-o", str(b), str(HERE / "segment.swift")], check=True, capture_output=True)
    return b

def mattes(ITEMS, CUT, OUT, FPS, DUR, W, H, at=None):
    """Person mattes (Apple Vision, on-device) for the frames inside behind-window ranges, half resolution. Frames outside the ranges
    link to a black matte so the sequence is continuous. at=t makes a single matte for one still."""
    import shutil
    d = OUT / "matte"; d.mkdir(exist_ok=True); n = round(DUR * FPS)
    sig = f"{pathlib.Path(CUT).stat().st_mtime}_{pathlib.Path(CUT).stat().st_size}"; sf = d / "cut.sig"
    if sf.exists() and sf.read_text() != sig: shutil.rmtree(d); d.mkdir()   # the cut changed (new take): old mattes are wrong
    sf.write_text(sig)
    black = d / "black.png"
    if black.exists() and probe(black, "pix_fmt").get("pix_fmt") != "rgb24": black.unlink()
    if not black.exists(): ff("-f", "lavfi", "-i", f"color=c=black:s={W // 2}x{H // 2}", "-frames:v", "1", "-pix_fmt", "rgb24", black)   # same format as the Vision mattes: a format change mid-sequence re-inits the ffmpeg graph and drops frames
    bi = black.stat().st_ino
    def have(i): f = d / f"{i:05d}.png"; return f.exists() and f.stat().st_ino != bi   # a frame hard-linked to black is a placeholder, not a matte
    if at is not None:   # a still: cut the speaker out only where the final does (inside a behind window), else the still would hide the pan
        rg = [(max(0, at - .02), at + .05)] if any(a <= at < b for a, b in person_ranges(ITEMS)) else []
    else: rg = person_ranges(ITEMS)
    for a, b in rg:
        need = [i for i in range(int(a * FPS), min(n, int(b * FPS) + 1)) if not have(i)]
        for i in need: (d / f"{i:05d}.png").unlink(missing_ok=True)
        if need: subprocess.run([str(segment_bin()), str(CUT), f"{a:.3f}", f"{min(DUR, b + .05):.3f}", str(FPS), str(d), "0.5"], check=True, capture_output=True)
    if at is None:
        inrange = lambda i: any(int(a * FPS) <= i <= int(b * FPS) + 1 for a, b in rg)
        for i in range(n):
            f = d / f"{i:05d}.png"
            if f.exists() and not inrange(i) and f.stat().st_ino != bi: f.unlink()   # a real matte left by a still outside the ranges: back to the placeholder
            if not f.exists(): os.link(black, f)
    return d

def fx_resolve(it):
    """Clip path + key for an fx item (category names come from the collection index)."""
    c = it["clip"]; key = it["key"]
    if "/" not in c and not pathlib.Path(c).suffix:
        idx = json.loads((HERE / "fx" / "INDEX.json").read_text()) if (HERE / "fx" / "INDEX.json").exists() else {}
        cands = sorted([v for v in idx.values() if v["cat"] == c and (HERE / "fx" / c / v["file"]).exists()], key=lambda v: -v.get("likes", 0))
        if not cands: sys.exit(f"fx '{c}': nothing in {HERE / 'fx' / c}; run python3 pixabay_fx.py {c} 4")
        v = cands[0]; path = HERE / "fx" / c / v["file"]; key = key or v.get("detected") or detect_key(path)
    else: path = pathlib.Path(c).expanduser()
    if key is None: key = "alpha" if path.suffix.lower() in (".gif", ".png", ".apng") else detect_key(path)
    if path.suffix.lower() in (".mp4",) and key == "green" and it["key"] is None: key = detect_key(path)   # trust the clip over the category
    return path, key

def detect_key(path):
    """green if the clip's border is green-dominant, screen if it is dark, else alpha. Cached in fx/INDEX.json when the clip is from the collection."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(path), "-frames:v", "1", "-vf", "scale=32:32,format=rgb24", "-f", "rawvideo", "-"], capture_output=True).stdout
    if len(raw) < 32 * 32 * 3: return "alpha"
    px = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]; border = [px[i] for i in range(1024) if i < 32 or i >= 992 or i % 32 in (0, 31)]
    r, g, b = (sum(p_[k] for p_ in border) / len(border) for k in range(3))
    return "green" if g > 90 and g > r * 1.6 and g > b * 1.3 else "screen" if max(r, g, b) < 60 else "alpha"

def fx_inputs(ITEMS, FPS, at=None):
    """Extra ffmpeg inputs for fx items (looped, optionally seeked for a still)."""
    args = []
    for it in ITEMS:
        if it["kind"] != "fx": continue
        path, key = fx_resolve(it)
        if at is not None:
            if not (it["a"] <= at < it["b"]): continue
            d = duration(path) if path.suffix.lower() not in (".png",) else 1e9
            args += ["-ss", f"{(it['offset'] + (at - it['a']) * it['speed']) % max(.1, d):.3f}", "-i", str(path)]
        else: args += ["-ss", f"{it['offset']:.3f}", "-t", f"{(it['b'] - it['a']) * it['speed'] + .5:.3f}", "-i", str(path)]   # no -stream_loop: a looped input keeps ffmpeg alive forever; a range longer than the clip just ends early
    return args

def fx_chain(ITEMS, W, H, first_idx, cur, at=None):
    """[cur] + fx inputs -> [fxout]. green: chromakey+despill+overlay; screen: blend screen full-frame; alpha: overlay."""
    parts = []; k = first_idx; sc = W / 1080
    for it in ITEMS:
        if it["kind"] != "fx": continue
        if at is not None and not (it["a"] <= at < it["b"]): continue
        path, key = fx_resolve(it); x, y, w, h = (int(v * sc) // 2 * 2 for v in (it["x"], it["y"], it["w"], it["h"]))
        en = "" if at is not None else f":enable='between(t\\,{it['a']:.3f}\\,{it['b']:.3f})'"
        tm = "" if at is not None else f"trim=duration={it['b'] - it['a']:.3f},setpts=PTS/{it['speed']}+{it['a']:.3f}/TB,"
        op = f",colorchannelmixer=aa={it['opacity']}" if it["opacity"] < 1 else ""
        if key == "green":
            parts.append(f"[{k}:v]{tm}scale={w}:{h},format=rgba,chromakey=0x00FF00:0.32:0.12,despill=type=green{op}[f{k}];{cur}[f{k}]overlay={x}:{y}:eof_action=pass{en}[o{k}]")
        elif key == "screen":
            lv = f",colorlevels=rimax={1 / max(.05, it['opacity']):.3f}:gimax={1 / max(.05, it['opacity']):.3f}:bimax={1 / max(.05, it['opacity']):.3f}" if it["opacity"] < 1 else ""
            parts.append(f"[{k}:v]{tm}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},format=gbrp{lv}[f{k}];{cur}format=gbrp[c{k}];[c{k}][f{k}]blend=all_mode=screen:eof_action=pass{en},format=yuv420p[o{k}]")
        else:
            parts.append(f"[{k}:v]{tm}scale={w}:{h},format=rgba{op}[f{k}];{cur}[f{k}]overlay={x}:{y}:eof_action=pass{en}[o{k}]")
        cur = f"[o{k}]"; k += 1
    return ";".join(parts), cur, k

def compose_chain(CFG, ITEMS, W, H, HDR, OUT, V, idx_fg, idx_bg=None, idx_mt=None, at=None):
    """[0:v] footage + overlay inputs -> [v]. Order: graded footage -> push/blur -> behind-layer PNGs -> person cutout -> foreground PNGs."""
    base = base_filter(ITEMS, W, H, at=at)   # [0:v] -> [b] (grade is inside, first)
    rs = CFG.get("render_scale", 1.0); down = f"scale={W}:{H}:flags=lanczos," if rs != 1.0 else ""
    if HDR:
        def prep(i, lbl): return f"[{i}:v]{down}format=rgba64le,lut3d=file='{gamut_lut(OUT)}',scale=out_color_matrix=bt2020:out_range=tv,format=yuva444p10le[{lbl}]"
        ovf = ":format=yuv420p10"
    else:
        def prep(i, lbl): return f"[{i}:v]{down}format=rgba[{lbl}]" if down else f"[{i}:v]null[{lbl}]"
        ovf = ""
    parts = [base]; cur = "[b]"
    if idx_bg is not None:
        parts.append(prep(idx_bg, "ovbg")); parts.append(f"{cur}[ovbg]overlay=0:0{ovf}:shortest=1[x1]"); cur = "[x1]"
        parts.append(f"[{idx_mt}:v]scale={W}:{H}:flags=bicubic,format=gray,gblur=sigma={max(1.5, 2.2 * W / 1080):.1f}[mt];[gp][mt]alphamerge[person]")
        parts.append(f"{cur}[person]overlay=0:0{ovf}:shortest=1[x2]"); cur = "[x2]"
    nfx = sum(1 for it in ITEMS if it["kind"] == "fx" and (at is None or it["a"] <= at < it["b"]))
    if nfx:
        first = (idx_mt if idx_mt is not None else idx_fg) + 1
        fxp, cur, _ = fx_chain(ITEMS, W, H, first, cur, at=at); parts.append(fxp)
    parts.append(prep(idx_fg, "ovfg")); parts.append(f"{cur}[ovfg]overlay=0:0{ovf}:shortest=1[v]")
    return ";".join(parts)

def blur_ranges(ITEMS): return [(it["a"], it["b"]) for it in ITEMS if it["kind"] == "window" and it["blur"] and not it.get("push")]
PY_DOUT = dict(snap=.08, fade=.14, pop=.16, cut=0, up=.3, down=.3, left=.3, right=.3, none=0, zoom=.3, iris=.35, slam=.18, blur=.25, dissolve=.45)
PY_DIN = dict(snap=.08, pop=.22, fade=.22, up=.38, down=.38, left=.42, right=.42, wipe=.28, none=0, zoom=.45, slam=.3, flip=.5, iris=.5, spin=.5, bounce=.6, blur=.4, rise=.45, type=0, dissolve=.55)
SMOOTH = 1.0

PAN_GAP = 60   # px between the insert's bottom edge and the highest head position inside the window (the user wants little air over the head)

def head_profile(CFG, CUT, OUT, at):
    """Head top, chin and face centre (1920-scale px) at time `at`, from the Vision person matte: top = first row with the person,
    chin = the narrowest row (the neck) between top+200 and top+700, face = midway. CFG["head_top"]/CFG["chin"] override; cached per cut and time."""
    if CFG.get("head_top"): top = float(CFG["head_top"]); chin = float(CFG.get("chin", top + 470)); return dict(top=top, chin=chin, face=(top + chin) / 2)
    f = OUT / "face.json"; sig = f"{pathlib.Path(CUT).stat().st_mtime}_{pathlib.Path(CUT).stat().st_size}"
    try: cache = json.loads(f.read_text())
    except Exception: cache = {}
    if cache.get("sig") != sig: cache = {"sig": sig}
    key = f"{at:.2f}"
    if key in cache: return cache[key]
    top, chin = 250.0, 720.0
    try:
        import tempfile, shutil
        tmp = pathlib.Path(tempfile.mkdtemp())
        subprocess.run([str(segment_bin()), str(CUT), f"{at:.2f}", f"{at + .05:.2f}", "1", str(tmp), "1"], check=True, capture_output=True)
        m = next(tmp.glob("*.png")); NW = 48
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(m), "-vf", f"format=gray,scale={NW}:ih:flags=area", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
        n = len(raw) // NW; rows = [raw[i * NW:(i + 1) * NW] for i in range(n)]
        bright = [i for i, r in enumerate(rows) if max(r) > 110]
        if bright:
            top = bright[0] / n * 1920
            width = [sum(1 for v in r if v > 110) for r in rows]
            lo, hi = int((top + 200) / 1920 * n), min(n - 1, int((top + 700) / 1920 * n))
            if hi > lo:
                neck = min(range(lo, hi), key=lambda i: width[i]); chin = neck / n * 1920 - 20
            else: chin = top + 470
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e: print(f"  head: Vision matte failed at {at:.2f}s ({e}), assuming top 250 / chin 720")
    prof = dict(top=round(top), chin=round(chin), face=round((top + chin) / 2)); cache[key] = prof; f.write_text(json.dumps(cache)); return prof

def face_y(CFG, CUT, OUT, W, H, at):
    pr = head_profile(CFG, CUT, OUT, at); return dict(face=pr["face"], top=pr["top"])

def pan_setup(CFG, ITEMS, CUT, OUT, W, H):
    """The standard top-half layout: the footage keeps its full width and slides down by T px (never scaled, never side-cropped). For
    every top-half window the head is measured at three moments (start, middle, end); the slide puts the HIGHEST head position PAN_GAP px
    under the insert, so the head is never clipped and never has much air above it; the subtitle sits under the lowest chin, inside the
    safe area. T is clamped to the insert's bottom edge so no gap opens between B-roll and footage."""
    pans = [it for it in ITEMS if it["kind"] == "window" and it.get("push") == "pan"]
    if not pans: return
    rep = []
    for it in pans:
        bottom = it["y"] + it["h"]
        ts = [it["a"] + .1, (it["a"] + it["b"]) / 2, max(it["a"] + .1, it["b"] - .1)]
        profs = [head_profile(CFG, CUT, OUT, s) for s in ts]
        top = min(pr["top"] for pr in profs); chin = max(pr["chin"] for pr in profs)
        T = int(max(0, min(bottom, bottom + PAN_GAP - top)))
        it["pan"] = T
        if it.get("cap_y") is None or it["cap_y"] == 1420: it["cap_y"] = int(min(1535, max(1100, chin + T + 70)))
        rep.append(f"{it['id']}: head {top:.0f}-{chin:.0f} -> slide {T}px, air over head {top + T - bottom:.0f}px, subtitle y {it['cap_y']}")
    CFG["_pan"] = {it["id"]: it["pan"] for it in pans}
    print("layout: top-half windows slide the footage down at full width (" + f"{PAN_D}s): " + "; ".join(rep))

def push_ranges(ITEMS):
    """Footage-shrink ranges per push factor. The layout change never overlaps the window's own fade: the footage shrinks BEFORE the
    window appears and grows back only AFTER the window has fully gone (otherwise the fading window and the moving footage double-expose,
    which reads as a flicker). Windows closer than 0.8 s are merged so the footage does not bounce back between them."""
    d = {}
    for it in ITEMS:
        if it["kind"] == "window" and it.get("push"):
            a = max(0.0, it["a"] - PUSH_D - PY_DIN.get(it.get("anim", "fade"), .2) * SMOOTH * .5)
            b = it["b"] + PY_DOUT.get(it.get("out", "fade"), .14) * SMOOTH
            if it["push"] == "pan": a, b = max(0.0, it["a"] - .03), it["b"]   # slide and insert start together; slide back under the insert's exit
            key = ("pan", int(it.get("pan", 0))) if it["push"] == "pan" else float(it["push"])
            d.setdefault(key, []).append((a, b))
    for k, rg in d.items():
        rg.sort(); merged = []
        for a, b in rg:
            if merged and a - merged[-1][1] < .8: merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else: merged.append((a, b))
        d[k] = merged
    return d

PAN_D = .24    # seconds for the full-width slide (pan): fast, never scaled by smooth; the insert snaps in during it
PUSH_D = .38   # seconds for the footage to shrink / grow back (matches the window's slide-down); scaled by CFG smooth in grade_setup

def _ramp(rg, at=None, D=None):
    """max over ranges of smoothstep(in) * smoothstep(out): 0 outside, 1 fully pushed, eased at both ends. ffmpeg expr or a float."""
    D = D or PUSH_D
    if at is not None:
        v = 0.0
        for a, b in rg:
            pi, po = min(1, max(0, (at - a) / D)), min(1, max(0, (b - at) / D)); x = pi * po; v = max(v, x * x * (3 - 2 * x))
        return v
    terms = [f"st(0\\,clip((t-{a:.3f})/{D}\\,0\\,1)*clip(({b:.3f}-t)/{D}\\,0\\,1))*0+ld(0)*ld(0)*(3-2*ld(0))" for a, b in rg]
    e = terms[0]
    for t_ in terms[1:]: e = f"max({e}\\,{t_})"
    return e

def base_filter(ITEMS, W, H, at=None):
    """[0:v] -> [b]. Two footage edits, both time-limited: 'push' windows shrink the footage to the bottom of the frame over a blurred
    copy (top-half B-roll layout) with an animated shrink/grow; 'blur' windows blur the footage behind them. at=None builds timeline
    filters for the whole video; at=t builds the static chain for one still."""
    sigma = round(24 * W / 1080, 1); parts = []; cur = "[0:v]"
    g = GRADE.get("filter")
    if person_ranges(ITEMS):   # the person cutout needs the graded footage too
        parts.append(f"{cur}{g + ',' if g else ''}split[g0][gp]"); cur = "[g0]"
    elif g: parts.append(f"{cur}{g}[g0]"); cur = "[g0]"
    def en(rg): return "" if at is not None else ":enable='" + "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})" for a, b in rg) + "'"
    def active(rg): return at is None or any(a <= at < b for a, b in rg)
    for k, (sc, rg) in enumerate(push_ranges(ITEMS).items()):
        if not active(rg): continue
        if isinstance(sc, tuple):   # pan: the footage keeps its full width and slides down by T px so the face sits in the bottom section
            T = sc[1] * H / 1920
            y = f"{T * _ramp(rg, at, PAN_D):.1f}" if at is not None else f"'{T:.1f}*({_ramp(rg, None, PAN_D)})'"
            # the strip above the sliding footage is a dark panel (the insert's own backdrop arriving), not a blurred copy of the room
            parts.append(f"{cur}split[p{k}a][p{k}b];[p{k}a]drawbox=c=0x0f1115:t=fill{en(rg)}[p{k}g];"
                         f"[p{k}g][p{k}b]overlay=x=0:y={y}:eval=frame{en(rg)}[p{k}]"); cur = f"[p{k}]"
            continue
        if at is not None:
            f = 1 - (1 - sc) * _ramp(rg, at); sw, sh = int(W * f) // 2 * 2, int(H * f) // 2 * 2
            scale = f"scale={sw}:{sh}"
        else:
            scale = f"scale=w='trunc(iw*(1-{1 - sc:.4f}*({_ramp(rg)}))/2)*2':h='trunc(ih*(1-{1 - sc:.4f}*({_ramp(rg)}))/2)*2':eval=frame"
        parts.append(f"{cur}split[p{k}a][p{k}b];[p{k}b]{scale}[p{k}s];[p{k}a]gblur=sigma={sigma * 1.3:.1f}:steps=2{en(rg)}[p{k}g];"
                     f"[p{k}g][p{k}s]overlay=x=(W-w)/2:y=H-h:eval=frame{en(rg)}[p{k}]"); cur = f"[p{k}]"
    P = [it for it in ITEMS if it["kind"] == "punch"]
    if P and (at is None or any(it["a"] <= at < it["b"] for it in P)):
        def bump(it): return f"({it['amount']}*sin(PI*clip((t-{it['a']:.3f})/{it['dur']}\\,0\\,1)))"
        if at is not None:
            z = 1 + sum(it["amount"] * math.sin(math.pi * min(1, max(0, (at - it["a"]) / it["dur"]))) for it in P if it["a"] <= at < it["b"])
            parts.append(f"{cur}scale={int(W*z)//2*2}:{int(H*z)//2*2},crop={W}:{H}[z]")
        else:
            zexpr = "1+" + "+".join(bump(it) for it in P)
            parts.append(f"{cur}scale=w='trunc(iw*({zexpr})/2)*2':h='trunc(ih*({zexpr})/2)*2':eval=frame,crop={W}:{H}[z]")
        cur = "[z]"
    rg = blur_ranges(ITEMS)
    if rg and active(rg): parts.append(f"{cur}gblur=sigma={sigma}:steps=2{en(rg)}[b]")
    else: parts.append(f"{cur}null[b]")
    return ";".join(parts)

GRADE = {}

def skin_stats(f, t, scale=270):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(f), "-frames:v", "1", "-vf", f"scale={scale}:-2,format=rgb24", "-f", "rawvideo", "-"], capture_output=True).stdout
    n = len(raw) // 3; ys = []
    for i in range(0, n, 3):
        r, g, b = raw[3 * i], raw[3 * i + 1], raw[3 * i + 2]
        if r > g > b and r - b > 35 and 90 < r < 235 and g > 50: ys.append(.299 * r + .587 * g + .114 * b)
    return (sum(ys) / len(ys), len(ys)) if len(ys) > 40 else (None, 0)

def smooth_setup(CFG):
    global PUSH_D, SMOOTH; SMOOTH = CFG.get("smooth", 1.0); PUSH_D = round(.38 * SMOOTH, 3)

def grade_setup(CFG, CUT, OUT, DUR):
    """CFG['grade']: None, or dict(temp=7400, sat=.95, yellow=-.2, lift=.04, gamma=1.03, match=True). Builds the ffmpeg chain and,
    with match=True, measures skin brightness per shot (scene cuts) and adds a per-shot brightness offset so the face reads the same
    across the whole reel. Cached in out/grade.json."""
    G = CFG.get("grade")
    if not G: return
    if G is True or G == "auto": G = {}
    G = dict(dict(temp=7400, sat=.95, yellow=-.2, lift=.04, gamma=1.03, match=True), **G)
    chain = [f"colortemperature=temperature={G['temp']}:mix=1"]
    if G["yellow"]: chain.append(f"selectivecolor=yellows=0 0 {G['yellow']} 0:reds=0 -0.04 {G['yellow'] / 3:.2f} 0")
    chain.append(f"eq=saturation={G['sat']}:brightness={G['lift']}:gamma={G['gamma']}")
    if G["match"]:
        cache = OUT / "grade.json"
        if cache.exists(): segs = json.loads(cache.read_text())
        else:
            r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(CUT), "-vf", "select='gt(scene,0.3)',showinfo", "-f", "null", "-"], capture_output=True, text=True).stderr
            cuts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", r)]; bounds = [0.0] + cuts + [DUR]; segs = []
            for a, b in zip(bounds, bounds[1:]):
                if b - a < .4: continue
                vals = [skin_stats(CUT, a + (b - a) * q) for q in (.2, .5, .8)]; vals = [v for v, k in vals if v]
                segs.append(dict(a=a, b=b, y=sum(vals) / len(vals) if vals else None))
            ys = sorted(v["y"] for v in segs if v["y"]); target = ys[len(ys) // 2] if ys else None
            for v in segs: v["gain"] = round(max(-.08, min(.08, (target - v["y"]) / 255)), 4) if v["y"] and target else 0
            cache.write_text(json.dumps(segs, indent=1))
        for v in segs:
            if abs(v["gain"]) >= .004: chain.append(f"eq=brightness={v['gain']}:enable='between(t\\,{v['a']:.3f}\\,{v['b']:.3f})'")
        print("grade: " + ", ".join(f"{v['a']:.1f}-{v['b']:.1f}s {v['gain']:+.3f}" for v in segs))
    GRADE["filter"] = ",".join(chain)

def broll_report(ITEMS, DUR):
    """The B-roll standard: ~20-36% of the runtime in FEW windows (2-6 s each, as long as the words they illustrate and no longer; at most
    one per 12 s of runtime), the first one right after the hook and in context with it; half-screen
    is the main layout (40-100%), full-screen <= 40%, behind <= 25%; downloaded technology video first (real >= 50%), the skill's
    animations for the rest; never an image; never upscaled (a 1080p landscape film fits a half-screen window, not a full-screen one)."""
    W_ = [it for it in ITEMS if it["kind"] == "window" and not it.get("mini")] + [dict(kind="window", a=it["a"], b=it["b"], w=0, h=0, person=False, scene=True, media=None, id=it["id"]) for it in ITEMS if it["kind"] == "card"]
    EX = (globals().get("_CFG_FOR_REPORT") or {}).get("existing") or []   # CFG["existing"] = [(a, b, "full"|"half"|"behind"|"logo"|"title"), ...]: graphics already burned into the cut
    W_ += [dict(kind="window", a=a, b=b, w=1080 if k == "full" else 540, h=1920 if k == "full" else 880, person=(k == "behind"), scene=False, media="existing", id=f"existing@{a}") for a, b, k in EX if k in ("full", "half", "behind")]
    if EX: print(f"existing graphics in the cut: {len(EX)} ({sum(1 for *_, k in EX if k in ('full', 'half', 'behind'))} B-roll, counted below)")
    if not W_: print("B-roll: none"); return
    def lay(it): return "behind" if it.get("person") else "full" if it["w"] >= 1080 and it["h"] >= 1900 else "half"
    def union(iv):
        iv = sorted(iv); out = []
        for a, b in iv:
            if out and a <= out[-1][1]: out[-1][1] = max(out[-1][1], b)
            else: out.append([a, b])
        return sum(b - a for a, b in out)
    tot = union([(it["a"], it["b"]) for it in W_]); cov = tot / DUR * 100
    L = {k: sum(it["b"] - it["a"] for it in W_ if lay(it) == k) for k in ("half", "full", "behind")}; ls = sum(L.values()) or 1
    real = sum(it["b"] - it["a"] for it in W_ if it.get("media")); anim = sum(it["b"] - it["a"] for it in W_ if not it.get("media")); rs = real + anim or 1
    flags = []
    if not 20 <= cov <= 36: flags.append(f"coverage {cov:.0f}% (standard 25-30%)")
    if len(W_) > max(3, round(DUR / 8)): flags.append(f"{len(W_)} windows (standard <= {max(3, round(DUR / 8))} for {DUR:.0f}s)")
    if anim / rs * 100 < 30: flags.append(f"motion-graphic B-roll {anim / rs * 100:.0f}% (the skill's set pieces are B-roll too: >= 30%, ~half)")
    short = [it["id"] for it in W_ if it["b"] - it["a"] < 1.9]; long_ = [it["id"] for it in W_ if it["b"] - it["a"] > 6.1]
    if short: flags.append("shorter than 2 s: " + ", ".join(short))
    if long_: flags.append("longer than 6 s: " + ", ".join(long_))
    caps_ = globals().get("_CAPS_FOR_REPORT") or []
    hook_end = next((c["e"] for c in caps_ if c["e"] > 1.0 and c.get("end")), None) or next((c["e"] for c in caps_ if c["e"] > 2.5), 3.5)   # end of the first spoken sentence
    if not any(it["a"] <= hook_end + 1.5 and not it.get("person") for it in W_): flags.append("no motion graphic right after the hook (a window must start within 1.5 s of the first sentence ending)")
    if L["half"] / ls * 100 < 40: flags.append(f"half-screen {L['half'] / ls * 100:.0f}% (the main layout, >= 40%)")
    if L["full"] / ls * 100 > 40: flags.append(f"full-screen {L['full'] / ls * 100:.0f}% (<= 40%)")
    if L["behind"] / ls * 100 > 25: flags.append(f"behind {L['behind'] / ls * 100:.0f}% (<= 25%)")
    if L["full"] + L["behind"] == 0: flags.append("no full-screen or behind-the-speaker window (at least one per reel)")
    ours = [it for it in W_ if it.get("media") != "existing"]
    if EX and not ours: flags = []   # the creator's own B-roll is kept as cut; the standard governs what this edit adds
    rmin = (globals().get("_CFG_FOR_REPORT") or {}).get("broll_real_min", 45)
    if EX and not ours: rmin = 0
    if real / rs * 100 < rmin: flags.append(f"real video {real / rs * 100:.0f}% (downloaded technology video comes first, ~half, >= {rmin}%; a script that names no technology may set broll_real_min lower and say so in the cue sheet)")
    for it in W_:   # HD check: the window must not upscale its source
        if not it.get("media"): continue
        try: v = probe(pathlib.Path(it["media"]).expanduser(), "width,height"); sw, sh = v["width"], v["height"]
        except Exception: continue
        up = max(it["w"] / sw, it["h"] / sh) if it.get("fit", "cover") == "cover" else it["w"] / sw
        if up > 1.15: flags.append(f"{it['id']} upscaled x{up:.2f} ({sw}x{sh} into {it['w']}x{it['h']}): use half-screen or a 4K/portrait source")
        if min(sw, sh) < 2160 and max(sw, sh) < 3840: flags.append(f"{it['id']} source is {sw}x{sh}, not ultra HD (B-roll sources must be 4K: brand_collect.py fetches 2160p first)")
    print(f"B-roll: {tot:.1f}s of {DUR:.1f}s = {cov:.0f}% | {len(W_)} windows, {min(it['b'] - it['a'] for it in W_):.1f}-{max(it['b'] - it['a'] for it in W_):.1f}s | half {L['half'] / ls * 100:.0f}% full {L['full'] / ls * 100:.0f}% behind {L['behind'] / ls * 100:.0f}% | real {real / rs * 100:.0f}% animation {anim / rs * 100:.0f}%")
    print("B-roll standard: OK" if not flags else "B-roll standard: FIX -> " + "; ".join(flags))

def logo_report(ITEMS, caps):
    """Rule: when a brand, product, car, person or place with a mark in the logo library is spoken, its real mark (logo()) is on
    screen within 1.5 s of the word, never an emoji or a generic icon in its place."""
    ix = _logo_index(); words = [(c["s"], x["t"]) for c in caps for x in c["w"]]   # captions() chunks: s/e + w=[{t, em}]
    shown = [(it["a"], it["b"], pathlib.Path(it["src"]).name) for it in ITEMS if it["kind"] == "sticker"]
    shown += [(ic["at"], it["b"], pathlib.Path(ic["src"]).name) for it in ITEMS if it["kind"] == "iconrow" for ic in it["icons"]]
    films = [(it["a"], it["b"], pathlib.Path(str(it["media"])).parent.name) for it in ITEMS if it["kind"] == "window" and str(it.get("media", "")).startswith(str(HERE / "brand"))]   # a brand film IS the brand's mark
    flags = []
    for slug, e in ix.items():
        names = {re.sub(r"[^a-z0-9]", "", e["query"].split("(")[0].split(",")[0].lower()), slug.replace("-", "")}
        names = {n for n in names if len(n) >= 3}
        files = {e["file"], e.get("cutout")}
        for s, w in words:
            wn = re.sub(r"[^a-z0-9]", "", w.lower())
            if wn in names and not any(a - 1.5 <= s <= b + .2 and f in files for a, b, f in shown) and not any(a - 1.5 <= s <= b + .2 and (slug in topic or topic in slug) for a, b, topic in films):
                flags.append(f"{e['query']} named at {s:.2f}s without its real mark: accent(..., logo('{slug}'), {s:.2f}, ...)   (rule: real logo / flag / portrait, never an icon)")
    emoji_acc = [it for it in ITEMS if it.get("accent") and not ("/" in it["src"] or it["src"].lstrip().startswith("<svg"))]
    print(f"Logos: {len(set(f for _, _, f in shown) & set(e['file'] for e in ix.values()) | set(f for _, _, f in shown) & set(e.get('cutout') for e in ix.values()))} real marks on screen, "
          f"{len(emoji_acc)} emoji accents (concepts only, never a brand) -> " + ("OK" if not flags else "\n  - " + "\n  - ".join(flags)))

def motion_report(ITEMS, DUR):
    """Animation budget: typography is free; every other animated element counts. Standard: <= 1 extra element per 4 s of runtime,
    <= 3 punches, <= 3 stickers, leaks only on inserts. Also flags items placed outside SAFE."""
    kinds = ("sticker", "punch", "flash", "bars", "burst", "fx", "leak", "text", "circle", "cursor", "card", "iconrow")
    acc = [it for it in ITEMS if it.get("accent")]; minis = [it for it in ITEMS if it.get("mini")]
    extra = [it for it in ITEMS if it["kind"] in kinds and not it.get("accent")] + minis
    n = {k: sum(1 for it in extra if it["kind"] == k and not it.get("mini")) for k in kinds}; n["accent"] = len(acc); n["motion"] = len(minis)
    if n["text"] > 2: flags_text = f"{n['text']} kinetic text items: in-between animations are motion graphics or images (motion/iconrow/accent), kinetic text only for <= 2 single hero words"
    else: flags_text = None
    flags = [flags_text] if flags_text else []
    if len(extra) > DUR / 3: flags.append(f"{len(extra)} animated extras for {DUR:.0f}s (standard <= {int(DUR / 3)})")
    # engagement: something new must land on screen at least every 5 s (windows, icons, kinetic words, punches, bursts, hero headline words)
    EX = (globals().get("_CFG_FOR_REPORT") or {}).get("existing") or []
    ev = sorted({round(a, 2) for a, b, k in EX} | {round(b, 2) for a, b, k in EX} | {round(it["a"], 2) for it in ITEMS if it["kind"] in ("window", "sticker", "text", "card", "punch", "burst", "iconrow", "circle", "cursor")}
                | {round(it["b"], 2) for it in ITEMS if it["kind"] == "window"}
                | {round(ic["at"], 2) for it in ITEMS if it["kind"] == "iconrow" for ic in it["icons"]}
                | {round(w["at"], 2) for it in ITEMS if it["kind"] == "phrase" for w in it["words"] if w["role"] in ("hero", "big")})
    gaps = [(a, b) for a, b in zip([0.0] + ev, ev + [DUR]) if b - a > 5.0]
    gaps = [(a, b) for a, b in gaps if not any(xa - .1 <= a and b <= xb + .1 for xa, xb, k in EX if k in ("full", "half", "behind"))]   # a creator's moving UI insert is on screen the whole time
    if gaps: flags.append("nothing new on screen for > 5 s at " + ", ".join(f"{a:.1f}-{b:.1f}" for a, b in gaps))
    kinds_used = {it["kind"] if not it.get("mini") else "motion:" + it["scene"]["kind"] for it in extra} | ({"accent"} if acc else set())
    mk = [it["scene"]["kind"] for it in minis]
    if len(mk) != len(set(mk)): flags.append("the same mini motion graphic kind used twice: vary them (" + ", ".join(k for k in set(mk) if mk.count(k) > 1) + ")")
    if len(kinds_used) < 3 and len(extra) + len(acc) > 4: flags.append(f"only {sorted(kinds_used)} used: vary the devices (kinetic words, icons, windows, punches)")
    if n["punch"] > 3: flags.append(f"{n['punch']} punches (<= 3)")
    if n["sticker"] > 3: flags.append(f"{n['sticker']} stickers (<= 3)")
    if len(acc) > DUR / 6: flags.append(f"{len(acc)} accent icons for {DUR:.0f}s (standard <= {int(DUR / 6)})")
    wins = [(it["a"], it["b"]) for it in ITEMS if it["kind"] == "window" and not it.get("person") and not it.get("mini")]
    over = [it["id"] for it in acc if any(a - .2 < it["a"] < b for a, b in wins)]
    if over: flags.append("accent over a B-roll window: " + ", ".join(over))
    out = [it["id"] for it in ITEMS if it["kind"] in ("sticker", "text", "card") and not (SAFE["x0"] <= it["x"] <= SAFE["x1"] and SAFE["y0"] <= it["y"] <= SAFE["y1"])]
    if out: flags.append("outside the safe zone: " + ", ".join(out))
    print(f"Motion: {len(extra)} extras ({', '.join(f'{k} {v}' for k, v in n.items() if v and k != 'accent')}) + {len(acc)} accent icons; phrases {sum(1 for it in ITEMS if it['kind'] == 'phrase')} (free)" + (f"; minis: {', '.join(mk)}" if mk else ""))
    print("Motion standard: OK" if not flags else "Motion standard: FIX -> " + "; ".join(flags))

def footage_edits(ITEMS): return bool(blur_ranges(ITEMS) or push_ranges(ITEMS) or person_ranges(ITEMS) or GRADE.get("filter") or any(it["kind"] == "punch" for it in ITEMS))

def gamut_lut(OUT):
    """sRGB graphics -> BT.2020 primaries, same sRGB curve. Without it, sRGB colours read as BT.2020 look over-saturated
    on HDR footage (yellow turns orange). Brightness stays as-is: a 75% HLG white mapping made overlays look dark."""
    f = OUT / "gamut_709_to_2020.cube"
    if f.exists(): return f
    M = [[0.6274, 0.3293, 0.0433], [0.0691, 0.9195, 0.0114], [0.0164, 0.0880, 0.8956]]
    lin = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    enc = lambda v: 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    N = 33; g = [lin(i / (N - 1)) for i in range(N)]; rows = [f"LUT_3D_SIZE {N}"]
    for b in range(N):
        for gg in range(N):
            for rr in range(N):
                rgb = (g[rr], g[gg], g[b])
                rows.append(" ".join(f"{enc(min(1, max(0, sum(M[i][j] * rgb[j] for j in range(3))))):.6f}" for i in range(3)))
    f.write_text("\n".join(rows) + "\n"); return f

def strip_metadata(f):
    """Final step: rewrite the container with no tags at all (no title/artist/encoder/handler names/creation time/cover art/data tracks),
    bitexact so ffmpeg writes no version strings. Stream copy, so no quality change. Verified afterwards; the file is replaced in place.
    Note: this removes tool fingerprints in the file, not any watermark inside the picture or audio."""
    tmp = f.with_name(f.stem + "_clean" + f.suffix)
    codec = probe(f, "codec_name").get("codec_name", "")
    sei = ["-bsf:v", "filter_units=remove_types=6"] if codec == "h264" else ["-bsf:v", "filter_units=remove_types=39|40"] if codec == "hevc" else []   # drop SEI: x264/encoder signatures live there
    ff("-i", f, "-map", "0:v:0", "-map", "0:a:0?", *sei, "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
       "-metadata:s:v", "handler_name=Video", "-metadata:s:a", "handler_name=Sound",   # the hdlr box is mandatory; neutral names instead of ffmpeg's defaults
       "-movflags", "+faststart", "-c", "copy", tmp)
    left = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags:stream_tags", "-of", "json", str(tmp)], capture_output=True, text=True).stdout
    tags = json.loads(left); found = dict(tags.get("format", {}).get("tags", {}))
    for st in tags.get("streams", []): found.update({f"s{k}": v for k, v in st.get("tags", {}).items()})
    found = {k: v for k, v in found.items() if k not in ("major_brand", "minor_version", "compatible_brands", "slanguage") and v not in ("Video", "Sound")}   # structural boxes, not metadata
    sig = subprocess.run(["sh", "-c", f"strings -n 5 '{tmp}' | grep -c -E 'Lavc[0-9]|Lavf[0-9]|x264 - core|x265 \\(build|ffmpeg|HandBrake|Adobe Premiere|DaVinci|CapCut' || true"], capture_output=True, text=True).stdout.strip()
    tmp.replace(f); print(f"metadata: {'clean' if not found and sig == '0' else 'LEFT ' + str(found) + f' / {sig} encoder strings'}")

def verify(f, DUR, FPS):
    errs = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-f", "null", "-"], capture_output=True, text=True).stderr.strip()
    raw = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(f)],
                         capture_output=True, text=True).stdout
    n = int(re.sub(r"[^0-9]", "", raw) or 0)   # newer ffprobe prints a trailing comma
    print(f"{f.name}: decode errors {len(errs.splitlines()) if errs else 0}, frames {n} (cut ~{round(DUR * FPS)})")
    if errs: sys.exit("decode errors, do not deliver")

def main(argv):
    if not argv or argv[0].startswith("--"): sys.exit(__doc__)
    CFG, ITEMS, EXTRA = load_reel(argv[0]); argv = argv[1:]
    CUT, OUT, FPS = CFG["cut"], CFG["out"], CFG["fps"]; OUT.mkdir(parents=True, exist_ok=True)
    V = probe(CUT, "width,height,color_transfer,pix_fmt"); W, H = V["width"], V["height"]; DUR = duration(CUT)
    HDR = V.get("color_transfer") in ("arib-std-b67", "smpte2084"); name = CFG["name"]
    caps = captions(CFG, DUR); (OUT / "captions.json").write_text(json.dumps(caps, indent=1)); CFG["_caps"] = caps
    CFG["_tone"] = voice_tone(CFG, CUT, OUT, caps)
    print(f"voice tone: {CFG['_tone']['tone']} (F0 {CFG['_tone'].get('f0')} Hz, {CFG['_tone'].get('rate')} words/s) -> music {pick_mood(caps, CFG['_tone']['tone']) if CFG.get('music') == 'auto' else CFG.get('music')}, SFX palette {CFG['_tone']['tone']}")
    if "--dry" in argv:
        if not caps: print("no transcript yet:", CFG["whisper"])
        for c in caps: print(f"{c['s']:6.2f}-{c['e']:6.2f}  " + " ".join(f"*{w['t']}*" if w["em"] else w["t"] for w in c["w"]))
        return
    pan_setup(CFG, ITEMS, CUT, OUT, W, H); TH = theme_of(CFG); print(f"theme: {TH['name']} ({TH['label']}); accent {TH['acc']}, overshoot {TH['over']}, amplitude {TH['amp']}")
    if "--cue" in argv:
        print(f"{name}: {W}x{H} {FPS}fps {DUR:.2f}s {'HDR' if HDR else 'SDR'}; title {CFG['title'] and CFG['title'].get('t')}")
        for it in sorted(ITEMS, key=lambda i: i["a"]):
            pos = {"sticker": lambda i: f"centre ({i['x']},{i['y']}) size {i['size']}", "window": lambda i: f"box ({i['x']},{i['y']}) {i['w']}x{i['h']}{' BLUR' if i['blur'] else ''}",
                   "text": lambda i: f"'{i['s']}' at ({i['x']},{i['y']}) {i['size']}px{' accent' if i['em'] else ''}", "circle": lambda i: f"around ({i['x']},{i['y']}) {i['w']}x{i['h']}",
                   "cursor": lambda i: f"path {i['path']}", "card": lambda i: f"'{i['label']} / {i['value']}' centre ({i['x']},{i['y']})",
                   "flash": lambda i: f"full-frame {i['color']}", "punch": lambda i: f"footage zoom +{int(i['amount']*100)}%", "bars": lambda i: f"letterbox {i['size']}px",
                   "burst": lambda i: f"confetti at ({i['x']},{i['y']})", "iconrow": lambda i: " ".join(ic["src"] for ic in i["icons"]) + f" row at y {i['y']}", "phrase": lambda i: " ".join(("*" + w["t"] + "*") if w["role"] in ("hero", "big") else w["t"] for w in i["words"]) + f" @({i['x']},{i['y']})",
                   "leak": lambda i: f"film burn {i['hue']}", "fx": lambda i: f"overlay {pathlib.Path(i['clip']).name} key={i['key']}"}[it["kind"]](it)
            print(f"{it['a']:6.2f}-{it['b']:6.2f}  {it['kind']:7} {it['id']:14} {pos}  in={it.get('anim','-')} out={it.get('out','-')} sfx={it.get('sfx')}")
        print("SFX:", ", ".join(f"{n}@{t:.2f}" for n, t, v in sfx_events(CFG, ITEMS, EXTRA)))
        globals()["_CAPS_FOR_REPORT"] = caps; globals()["_CFG_FOR_REPORT"] = CFG; broll_report(ITEMS, DUR); motion_report(ITEMS, DUR); logo_report(ITEMS, caps)
        return
    MEDIA = {it["id"]: (prep_media(it, OUT, FPS, W / 1080 * CFG.get("render_scale", 1.0)) if it["media"] else dict(n=0, h=0, kind="scene")) for it in ITEMS if it["kind"] == "window"}
    grade_setup(CFG, CUT, OUT, DUR); smooth_setup(CFG)
    for it in ITEMS:   # headshot:// markers -> circular PNG cutouts of the speaker
        if it["kind"] == "window" and it.get("scene"):
            for k, v in list(it["scene"].items()):
                if isinstance(v, str) and v.startswith("headshot://"):
                    t_, x_, y_, w_, h_ = (float(q) for q in v[11:].split(",")); d = OUT / "headshot"; d.mkdir(exist_ok=True)
                    out = d / f"{t_:.2f}_{int(x_)}_{int(y_)}_{int(w_)}_{int(h_)}.png"
                    if not out.exists():
                        md = mattes(ITEMS, CUT, OUT, FPS, DUR, W, H, at=t_); mt = md / f"{round(t_ * FPS):05d}.png"
                        sc = W / 1080; cx, cy, cw, chh = (int(q * sc) // 2 * 2 for q in (x_, y_, w_, h_))
                        ff("-ss", f"{t_:.3f}", "-i", CUT, "-i", mt, "-filter_complex", f"[1:v]scale={W}:{H},format=gray,gblur=sigma=1.5[m];[0:v]{GRADE.get('filter') or 'null'}[g];[g][m]alphamerge,crop={cw}:{chh}:{cx}:{cy},scale=800:800[c]",
                           "-map", "[c]", "-frames:v", "1", out)
                    it["scene"][k] = img_uri(out)
    two = bool(person_ranges(ITEMS))
    if "--still" in argv:
        from playwright.sync_api import sync_playwright
        ts = [float(x) for x in argv[argv.index("--still") + 1:]]
        with sync_playwright() as p:
            br, pg = open_page(p, CFG, ITEMS, MEDIA, caps, OUT, W)
            for t in ts:
                for layer in (("bg", "fg") if two else (None,)):
                    pg.evaluate(f"render({t}, {json.dumps(layer)})"); pg.screenshot(path=OUT / f"ov_{t}{'_' + layer if layer else ''}.png", omit_background=True)
            br.close()
        for t in ts:
            if two:
                md = mattes(ITEMS, CUT, OUT, FPS, DUR, W, H, at=t); mt = md / f"{round(t * FPS):05d}.png"
                if not mt.exists(): mt = md / "black.png"
                ff("-ss", t, "-i", CUT, "-loop", "1", "-i", OUT / f"ov_{t}_fg.png", "-loop", "1", "-i", OUT / f"ov_{t}_bg.png", "-loop", "1", "-i", mt, *fx_inputs(ITEMS, FPS, at=t), "-filter_complex",
                   compose_chain(CFG, ITEMS, W, H, False, OUT, V, 1, 2, 3, at=t) + ";[v]scale=405:-2[s]", "-map", "[s]", "-frames:v", 1, OUT / f"st_{t}.png")
            else:
                ff("-ss", t, "-i", CUT, "-loop", "1", "-i", OUT / f"ov_{t}.png", *fx_inputs(ITEMS, FPS, at=t), "-filter_complex", compose_chain(CFG, ITEMS, W, H, False, OUT, V, 1, at=t) + ";[v]scale=405:-2[s]", "-map", "[s]", "-frames:v", 1, OUT / f"st_{t}.png")
        ff(*sum([["-i", OUT / f"st_{t}.png"] for t in ts], []), "-filter_complex", (f"hstack=inputs={len(ts)}" if len(ts) > 1 else "null"), OUT / "stills.png")
        print("look at", OUT / "stills.png"); return
    if two:
        fr = frames(CFG, ITEMS, MEDIA, caps, OUT, W, H, DUR, "fg"); fr_bg = frames(CFG, ITEMS, MEDIA, caps, OUT, W, H, DUR, "bg"); md = mattes(ITEMS, CUT, OUT, FPS, DUR, W, H)
        print(f"person matte: {sum(1 for _ in md.glob('*.png')) - 1} frames")
    else: fr = frames(CFG, ITEMS, MEDIA, caps, OUT, W, H, DUR); fr_bg = md = None
    sfx = sfx_wav(CFG, ITEMS, EXTRA, OUT, DUR)
    vg = voice_gain(CUT) if CFG["voice"] else 0.0
    mus, _ = music_bed(CFG, OUT, DUR, caps)
    if CFG["voice"]: print(f"voice: fixed gain {vg:+.1f} dB to reach -14 LUFS")
    vin = ["-framerate", FPS, "-i", fr / "%05d.png"] + (["-framerate", FPS, "-i", fr_bg / "%05d.png", "-framerate", FPS, "-i", md / "%05d.png"] if two else []) + fx_inputs(ITEMS, FPS)
    nfx = sum(1 for it in ITEMS if it["kind"] == "fx")
    chain = compose_chain(CFG, ITEMS, W, H, HDR, OUT, V, 1, 2 if two else None, 3 if two else None)
    if "--final" in argv:
        final = OUT / f"{name}_final.mp4"; vid = OUT / "_video_only.mp4"
        if HDR:   # match the HDR source: 10-bit HEVC with the same HLG/PQ tags, overlay mapped into BT.2020
            enc = ["-c:v", "hevc_videotoolbox", "-b:v", "20M", "-pix_fmt", "p010le", "-profile:v", "main10", "-tag:v", "hvc1",
                   "-color_primaries", "bt2020", "-color_trc", V["color_transfer"], "-colorspace", "bt2020nc"]
        else: enc = ["-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p"]
        # video first, audio in a second pass: one videotoolbox pass with amix produced corrupt NAL units
        # cfr: the animated top-half shrink reconfigures the filter graph when the frame size changes; cfr keeps the frame count exact
        # -t: looped fx inputs (-stream_loop -1) never end on their own; without an output duration ffmpeg keeps spinning after the last frame
        ff("-i", CUT, *vin, "-filter_complex", chain, "-map", "[v]", "-an", "-fps_mode", "cfr", "-r", FPS, "-t", f"{DUR:.3f}", *enc, vid)
        ff("-i", vid, "-i", CUT, "-i", sfx, *(["-i", mus] if mus else []), "-filter_complex", voice_mix(CFG, "1:a", "2:a", vg, "3:a" if mus else None),
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-flags:a", "+bitexact", "-fflags", "+bitexact", "-movflags", "+faststart", final)   # bitexact: the AAC encoder otherwise stamps its version into every fill element
        vid.unlink(); strip_metadata(final); verify(final, DUR, FPS); print("done:", final); return
    mov = OUT / f"{name}_overlay.mov"
    ff("-framerate", FPS, "-i", fr / "%05d.png", "-i", sfx, "-map", "0:v", "-map", "1:a", "-c:v", "prores_ks", "-profile:v", "4444",
       "-pix_fmt", "yuva444p10le", "-c:a", "pcm_s16le", mov)
    ai = (4 if two else 2) + nfx
    ff("-i", CUT, *vin, "-i", sfx, *(["-i", mus] if mus else []), "-filter_complex", chain + ";[v]scale=1080:-2[vs];" + voice_mix(CFG, "0:a", f"{ai}:a", vg, f"{ai + 1}:a" if mus else None),
       "-map", "[vs]", "-map", "[a]", "-t", f"{DUR:.3f}", "-c:v", "libx264", "-crf", "26", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-flags:a", "+bitexact", "-fflags", "+bitexact", "-movflags", "+faststart",
       OUT / f"{name}_preview.mp4")
    strip_metadata(OUT / f"{name}_preview.mp4")
    if footage_edits(ITEMS): print("note: grade / blur / push / person layer live only in the preview and --final; the transparent MOV carries the foreground graphics")
    print("done:", mov, OUT / f"{name}_preview.mp4")

if __name__ == "__main__":
    main(sys.argv[1:])
