"""Per-reel config. Copy this next to the cut as reel.py and edit. Run: python3 <skill>/overlay.py reel.py [--dry|--cue|--still t..|--final]
Helpers available without import: scene, sticker, logo, window, text, card, circle, cursor, PRESETS, SPOTS, ACCENT.
B-roll is generated with scene(...) by default; window(...) is for recordings/screenshots the user hands you.
All positions are on a 1080x1920 canvas. Times are seconds in the cut."""
from pathlib import Path
A = Path("~/reel-assets").expanduser()          # the user's logos / cutouts / memes / screen recordings

CFG = dict(
    name="REEL01",
    cut="~/Downloads/my_cut.mp4",                # the finished 9:16 export
    # whisper="audio.json",                      # default: audio.json next to this file (whisper --word_timestamps True)
    fps=30,
    title=dict(lines=["How To Build Incredible", "Websites With AI"], t=(0.0, 5.2)),   # line 2 is accent-coloured
    emph={"Design", "reusable", "skill", "activate"},   # caption words shown in the accent colour (case-insensitive)
    cap_y=1100, cap_size=96,                      # caption centre line and font size; windows with cap_y move it
    merges=[(("design", "md"), "Design.md")],    # whisper token runs -> one word (lowercase, no punctuation)
    fixes={"cloud": "Claude"},                   # single-word mishearings (lowercase key works too)
    sfx_lib="~/reel-sfx",                        # optional library; names missing here are synthesized
    sfx=dict(pop="pops/bloop.wav", whoosh="whoosh/fast.wav", intro="whoosh/cinematic.wav"),
    intro_whoosh=False,                          # set True for a soft whoosh at 0:00
    sfx_gain=.85, voice=True, duck=True,         # SFX bus level; voice clean-up + loudness; SFX ducked under speech
    music="auto", music_db=-4,
    # grade=dict(temp=7400, sat=.95, yellow=-.2, lift=.04, gamma=1.03, match=True),   # cool a warm room, match face exposure across shots                  # bed: auto mood from the transcript | "upbeat"/"tech"/"lofi"/"cinematic"/"dramatic" | a file | None
)

ITEMS = [
    # cursor glides from the laptop to her hand while she says "one file you can drop", then the file window slides up
    cursor("drag", path=[(900, 1550), (430, 1000)], t=(0.6, 1.35)),
    window("design_md", A / "design_md.png", preset="laptop", t=(1.35, 3.2), anim="up", out="cut", sfx="swipe"),
    sticker("claude", logo("claude", "#D97757"), spot="tr", size=140, t=(1.9, 3.2)),     # real marks from brand/logos (logo_collect.py); the colour arg is ignored
    sticker("rocket", "🚀", spot="tl", size=140, t=(2.4, 3.2)),                            # Apple emoji = glossy icon for concepts without a brand
    # generated B-roll (no files): a landing page assembling with a cursor click + toast, blurred footage, caption below
    scene("site", "browser", preset="mid", blur=True, t=(3.2, 6.2), out="cut", url="invoicechaser.app", heading="Stop chasing invoices.",
          sub="Polite reminders on autopilot.", button="Start free", cards=["Connect Stripe", "Day 3 / 7 / 14", "Who owes what"], toast="🚀 Deployed"),
    # top-half layout: terminal fills the top, footage shrinks to the bottom
    scene("build", "terminal", preset="tophalf", t=(29.0, 32.2), cmd="Build the first version from PRD.md",
          lines=["Created app/page.tsx", "Stripe webhook: unpaid invoices", "Deployed → invoicechaser.app"]),
    # a user-supplied screen recording still works the same way
    window("refero", A / "refero_scroll.mp4", preset="mid", t=(6.5, 10.0), blur=True, anim="left", tilt=-8, out="cut", frame="dark"),
    # a screenshot above the head with a hand-drawn circle around the button she talks about
    window("md_file", A / "design_md_page.png", preset="top", t=(10.0, 13.0), anim="fade"),
    circle("dl", x=905, y=345, w=90, h=50, t=(10.5, 13.0)),
    # a tall full-page screenshot that scrolls inside the window (capture.py shot URL out.png --full)
    window("blog", A / "blog_full.png", preset="top", t=(40.0, 42.4), anim="down", scroll=(260, .5)),
    # logos on the chest while she names the tools
    sticker("gpt", logo("openai", "#ffffff"), spot="chest", size=170, t=(15.5, 16.5), out="pop"),
    sticker("claude2", logo("claude", "#D97757"), spot="chest", size=150, t=(16.5, 17.6)),
    # meme / reaction clip top right
    window("meme", A / "office_worst.gif", preset="topright", t=(20.3, 22.6), radius=10, anim="pop", sfx="pop"),
    # kinetic list: "Your / Typography", "Your / Spacing", "Your / Colors" (words accumulate, then clear)
    text("t1", "Your", x=250, y=380, size=84, t=(23.1, 25.6), anim="pop"),
    text("t2", "Typography", x=150, y=460, size=100, em=True, t=(23.35, 25.6), anim="wipe", sfx="swipe"),
    text("s1", "Your", x=560, y=1230, size=84, t=(24.0, 25.6), anim="pop"),
    text("s2", "Spacing", x=560, y=1310, size=100, em=True, t=(24.25, 25.6), anim="wipe", sfx="swipe"),
    # B-roll behind the speaker (person cut out automatically): a city skyline while the big line lands
    scene("adv", "cinematic", preset="behind", t=(41.0, 44.0), style="city"),
    # a portrait card sliding up from the bottom
    window("sol", A / "sol_card.png", preset="card", t=(38.5, 40.0), anim="up", radius=28),
    # optional CTA / end cards in the same type style
    # card("cta", "comment", "STYLE", y=1300, t=(41.0, 42.4)),
]

SFX_EXTRA = [            # (name or file, time, volume) on top of the automatic one-per-entrance sounds
    # ("hit", 28.8, .45),
]
