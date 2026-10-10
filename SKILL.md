---
name: reel-overlay
description: Use when the user sends a finished 9:16 reel cut (Instagram Reels, TikTok, Shorts) and wants it edited like a top creator reel - one-word captions, title, logo stickers, generated animated B-roll (terminal, chat, document, browser, charts, phone, flow) and screen recordings in floating windows with blurred background, top-half split layout, kinetic text lists, red-circle / cursor annotations, meme clips, cards, synced pop and whoosh SFX - burned into the final video (or as a transparent overlay). Triggers: "edit my reel", "make the overlay", "add captions and b-roll", "here's the cut", "/reel-overlay". Not for cutting the footage, zooms, or colour grading.
---

# Reel overlay

Takes a finished vertical talking-head cut and adds the full creator-style motion layer: a two-line title, one word at a time
captions with accent words, logo stickers that pop in when a tool is named, B-roll windows (screen recordings, screenshots,
memes) floating over a blurred copy of the footage, kinetic word lists, hand-drawn red circles and a gliding cursor, cards,
and an SFX track with one sound per entrance. The look is modelled frame by frame on a reference reel (see "The look").

Files in this skill: `overlay.py` (renderer), `capture.py` (website screenshots / scroll recordings), `reel_example.py`
(annotated config to copy), `grab_frame.swift` (HDR-correct still for covers).

Output, per reel, in `<build>/out/`:
- `<NAME>_final.mp4` (`--final`): everything burned in, matches the cut's HDR/SDR format. **This is the deliverable.**
- `<NAME>_preview.mp4`: small H.264 preview to send to a phone.
- `<NAME>_overlay.mov`: transparent ProRes 4444 with the SFX as audio (no background blur, that needs the footage).

## Requirements (macOS)
- `ffmpeg` (Homebrew), `ffprobe`; Google Chrome in /Applications
- `python3.11 -m pip install playwright openai-whisper` (Playwright drives the installed Chrome, no browser download)
- Optional SFX library folder. Anything missing is synthesized (pop, bubble, whoosh, swipe, intro, click, scribble, hit), so the
  skill never runs silent. Real samples sound better: map them in `CFG["sfx"]`.
- The user's asset folder: logos (SVG/PNG, transparent), people cutouts, memes/GIFs, screen recordings, screenshots.

## Visual theme: chosen per reel, asked every time
The look of headlines, caption accents, generated scenes and canvas set pieces comes from `CFG["theme"]`. Nothing is hardcoded;
the skill proposes the fit for THIS video (tone, topic, speaker, brands) and asks the user with AskUserQuestion, three options plus
custom, before storyboarding. Sometimes simple is right.
- `lime`: lime #D4FF3F and white on near-black, one hot coral accent, bold kinetic type, exaggerated overshoot (over 2.3, amp 1.0).
- `duotone`: electric yellow #FFE600 stages with violet #5B3DF5 accents, inverted per scene, loudest motion (over 2.6, amp 1.2).
- `brand`: dark base, accent taken from the product being discussed (`CFG["brand_color"]`), text colour auto by luminance (over 2.0).
- `simple`: the calm premium reference: pale yellow accents, yellow editorial cards, soft pops (over 1.7, amp .5).
Headline hero words react: they slam in with a flash and the neighbouring words bump; captions pop; bars, counters, flow nodes and
cards overshoot. All of it scales with the theme's amplitude, so `simple` stays quiet and `duotone` shouts. `--cue` prints the theme.

## Music the user likes (music/liked/)
`music/liked/TASTE.json` lists the user's preferred songs with the skill moods they stand in for (dreamy indie R&B and soft synth ->
lofi / upbeat / tech; Skyfall, Deep Space Samurai, Dimensions, Runaway -> trailer / cinematic). The skill NEVER downloads commercial
recordings (copyright; the reel would be muted or taken down). When the user has placed a LICENSED file of one of them in
`music/liked/`, `music="auto"` prefers it whenever the reel's mood matches and `music="liked"` forces it. Otherwise the royalty-free
collection is used in that register, or the reel is rendered with `music=None` and the user adds the song in the Instagram app,
which carries the licence. Say which of these happened in the cue sheet.

## Thumb rule: when in doubt, ask (before spending tokens)
Whenever something about the video is unclear or two directions look equally right (which cut is the hook, which B-roll film or
scene, which image or icon, caption style or wording, headline copy, which music mood or SFX palette, where a window may sit,
whether an existing graphic should stay), do NOT guess. Ask the user with the AskUserQuestion tool: the top 3 suggestions you
believe are right, with one line each on why, the first marked "(Recommended)", and the automatic 4th "Other" for the user's own
answer. One question per real doubt, asked at the moment it blocks the storyboard (ideally all doubts of a reel in one call), then
build exactly what was chosen. A wrong guess costs a full re-render; a question costs one line.

## Workflow (keep tokens low)
0. **Pick the register** from the content and the speaker (see the three registers): founder / brand / interview -> editorial; fast
   tool explainer with lists -> kinetic; product demo with footage -> cinematic. Say which in the first message.
1. **Find the cut**: newest .mp4/.mov in ~/Downloads that is the 9:16 export, not the raw camera file. `ffprobe` it: resolution, fps, HDR
   (`color_transfer` = arib-std-b67 or smpte2084). Ask only if unclear.
2. **Build folder** inside the skill repo's gitignored `out/<NAME>_build/` (not next to the cut: users tidy their media folders and the
   transcript, assets and stills vanish with it; it happened twice). Copy `reel_example.py` there as `reel.py`; set `name`, `cut`, asset folder.
3. **Transcript**: `ffmpeg -i cut -vn -ac 1 -ar 16000 audio.wav` then
   `whisper audio.wav --model small --language en --word_timestamps True --output_format json --output_dir .`
   The renderer refuses a transcript older than the cut (a replaced file means new words); re-run whisper then.
   Run `python3 <skill>/overlay.py reel.py --dry`, read every word, fix mishearings with `fixes` (single word) and `merges`
   (token runs, e.g. `(("design","md"), "Design.md")`). Product names, URLs, numbers and the comment keyword are where whisper fails.
4. **Look at the footage cheaply**: ONE contact sheet (a frame every 2 s: `-vf fps=0.5,scale=135:240,tile=15x2`) plus scene cuts
   (`-vf "select='gt(scene,0.2)',showinfo" -f null -`). Note where the head, hands and laptop sit so windows and stickers don't cover the face.
5. **Title**: two short lines, line 2 is the accent line (the payoff: "Websites With AI"). Offer 3 options (widest audience /
   practitioner / money angle), let the user pick. Shown from 0:00 until the first B-roll section ends or ~5 s. Never ship an unapproved title.
6. **Storyboard = cue sheet.** Run the four heads (editor, designer, animator, sound) over the transcript sentence by sentence and give every
   beat a visual (rules below). In the editorial register every sentence is a `phrase(...)`: choose the hero word (the noun or number the
   sentence exists for), 0-2 serif words (the soft qualifier), the rest small; then decide which beats leave the speaker for a card. Write it as
   `ITEMS` in `reel.py`, run `--cue`, and show the user the printed cue sheet plus the asset list you still need. Get a yes.
7. **B-roll is generated, not found.** Default to `scene(...)` windows: the renderer draws animated UIs from content you write out of the
   transcript (see "Generated B-roll"). Never pull clips, screenshots or images from the user's disk unless they point you at them. Logos:
   `logo("semrush")` returns the REAL mark from the on-demand logo cache (`brand/logos/`, filled per script by `logo_collect.py`:
   Wikidata/Commons SVG logo, flag, emblem or official portrait; Simple Icons and the brand's own site as fallbacks); list the brands used in the
   cue sheet. Concepts without a brand get an Apple emoji sticker (`sticker("r", "🚀", ...)`), which reads as a glossy 3D icon. Only when the
   user supplies real screen recordings / screenshots do they go in a `window(...)`; `capture.py` is for sites the user asks to show.
8. **Stills check**: `--still t1 t2 ...` at every entrance time -> ONE `out/stills.png`. Check: face not covered, caption not over a window,
   nothing in the Instagram UI zones (below), accent words right. Fix, re-still.
9. **Render**: `python3 overlay.py reel.py --final` (a 45 s reel takes ~1.5 min at 720p, ~4 min at 1080p). Frames whose DOM state did not
   change are hard-linked; video windows re-shoot every frame. Send the preview or final to the user. Report decode errors and frame count.

## Work as a four-person team
Before placing anything, run the reel through four heads and write each one's plan into the cue sheet:
- **Editor** (cuts, rhythm): where are the breaths, the cuts, the payoff; what hides a splice (a `leak`), what earns a full-screen card,
  where the viewer might leave (every ~7 s something new must land; a riser must be building toward the ending).
- **Graphics designer** (type, cards, palette): one register for the whole reel, labels in the speaker's words, every card readable in
  one glance, hierarchy = size + colour (lime hero, white support, serif italic for the soft word).
- **Animator** (motion): every element enters, lives and exits; big words land with a punch; nothing pops without a reason; stagger by
  the spoken word, not by a timer.
- **Sound designer** (impacts, risers, whooshes, music): a sound per entrance, an impact per hero word, a riser into every card and
  into the final payoff, a bed that matches the voice's tone, never a sound that fights the voice.

## Three registers (pick one per reel, say which in the cue sheet)
- **Editorial** (`cap_mode="off"` + `phrase()`; the premium reference): no bottom captions. The spoken words appear as typography
  compositions above the head: a lime hero word (`#EEFB00`, Helvetica Neue Bold, tracking -5.5%), white support words in a spread row
  above it, small words below-left, a New York Italic word below-right, optional dashed connector. Each word lands on its spoken time
  with a tick (small) or impact (hero) and the composition clears at the sentence end. Explainer beats cut to full-screen cards on
  yellow `#FED400` with ink `#231D23` (`ring`, `steps`, `bigtype`, `growth`, `profile`) or black (`podium`, `bigtype dark=True`,
  `calendar`, `orgchart`), entering with `anim="wipe"` and leaving with `out="iris"`. Every cut gets a `leak` (film burn). Overlay
  clips (`fx`: falling money on "budget", confetti on the win) are used once or twice, never as wallpaper. This is the default for
  founder / brand / interview reels. **It does not replace the B-roll layouts**: every register carries B-roll per the standard below
  (~30% of runtime, 50/30/10-20 layout split, half real video half animation), with the phrase typography on top; the yellow/black cards
  count toward the animation half.
- **Kinetic** (`style="kinetic"`; reference 1): one-word 96 px captions with yellow accents, stickers, kinetic word lists, windows
  with blur, top-half scenes. For energetic explainers with lists and tool names.
- **Cinematic** (`style="cinematic"`; reference 2): the visuals are full-screen inserts that REPLACE the speaker for 2-6 s (real footage
  via `stock()`, procedural `cinematic` scenes, full-screen app `progress`/`browser`/`chat`, a black-screen brand `reveal`), 2-word captions
  at 58 px bold in a black rounded box at y 1480 with no pop, no stickers, no kinetic words, SFX at 0.7. Cut to the insert exactly on the
  word that names it, hold through the phrase, cut back on the next sentence. 40-60% of the runtime can be inserts. For product demos,
  "look what it made", story-driven reels. Both registers share the engine; the config switch sets the caption defaults.

## The look (measured on the reference reels, 1080x1920 canvas)
- **Font**: SF Pro Display Bold (`-apple-system`) everywhere. Pale yellow accent `#FDF29E`. White `#FFFFFF`. No boxes behind text,
  a soft shadow only (`0 4px 16px rgba(0,0,0,.55)`).
- **Captions**: ONE word at a time, 96 px, centred, white; accent words in yellow. Centre line y ~1100 (chest / mic level), moves to ~1290
  while a `mid` B-roll window is up. A word stays until the next starts (no flicker); tiny 0.1 s pop on each word. Kinetic text replaces the
  caption while it is up.
- **Title**: two lines, 66 px, line 1 white, line 2 yellow, top ~270 px, 0:00 to ~5 s, soft shadow, quick 0.25 s pop at 0.
- **Real marks, never icons**: whenever the speaker names a brand, product, tool, car, famous person, city, state or country, the
  element on screen is its ORIGINAL mark: `accent(id, logo("moz"), t)` / `iconrow([(logo("ahrefs"), t), ...])` / `sticker(logo("elon-musk"))`.
  NOTHING is pre-shipped: `brand/` is an empty cache. At storyboard time, for EVERY name in the transcript, fetch on demand:
  `python3 logo_collect.py add <slug> "<official name>" --kind brand|car|place|person` (logo / flag / cut-out portrait) and, for a
  product or technology, `python3 brand_collect.py add <topic> "<official launch film query>"` (its 4K showcase film for B-roll);
  for a place, `python3 pixabay_stock.py video "<landmark>" <build>/stock` (real footage) plus its flag. Then look at
  `brand/logos/sheet.png` and the film sheet. Adidas -> official logo SVG + adidas channel films; Paris -> city flag + Eiffel Tower
  footage; a small company with nothing official online -> no icon at all, the headline carries the name. Plates pick themselves from the kind (white card for logos, bordered flag, round avatar for a cut-out
  portrait) and size themselves to the mark's shape (wide wordmarks get a wide card). Emoji are for concepts only (money, time,
  shrug). `--cue` prints a `Logos:` line that flags any library brand spoken without its mark within 1.5 s. A name with no mark
  online (a small company) gets no icon at all; the headline carries it.
- **Stickers**: 130-170 px official logos (`logo()`), flat like the reference, or Apple emoji for concepts. Pop in with overshoot (0.22 s),
  stay still, fade out (or `out="pop"` when the next logo replaces it on the same spot). Spots: `tr`/`tl` beside the head, `chest` under the
  caption, `l`/`r`. `plate="glass"|"white"|"dark"` puts a squircle behind a logo that needs contrast.
- **B-roll windows**: rounded 36 px, deep soft shadow, `fade` in 0.22 s (scale .92 -> 1). Full B-roll uses `preset="mid"` + `blur=True`: the
  footage behind becomes a 24 px gaussian blur for exactly that time range and the caption drops under the window. Other presets: `top`
  (screenshot above the head), `bar` (a short UI bar), `laptop` (slides `up` onto the laptop screen), `card` (portrait card slides `up` from
  the bottom), `topright`/`topleft` (meme clip, radius 10), `stackA/B/C` (three-screen gallery, `frame="dark"`, no blur). A scrolling site
  is a tall screenshot with `scroll=(260, .5)` (px/s, delay). `tilt=-8` + `anim="left"` gives the 3D slide-in. Exit `out="cut"` when the
  footage cuts at the same time, else `fade`.
- **Generated B-roll (`scene`)**: the renderer's own animated UIs in the same window system (presets, blur, push, entrances). Kinds:
  `terminal` (command typed, results tick in), `chat` (attachments, prompt typed, reply streams), `doc` (markdown typing itself), `code`
  (syntax-coloured typing), `browser` (hero + button + cards assemble, a cursor flies in, clicks, a toast pops), `search` (query typed,
  results drop in), `cards` (then/now board, last card accent), `chart` (bars grow, numbers count), `counter` (big number counts up), `phone`
  (notifications slide in), `flow` (nodes pop, arrows draw), `checklist` (items tick, progress fills), `progress` (an AI app generating:
  big % counting up, shot list ticking), `reveal` (black screen, brand letters land one by one, sub-line types, like "runway / Connector"),
  `cinematic` (procedural footage: sunset, forest, stars, aurora, city, ocean, grid, particles), `stats` (KPI tiles with sparklines and
  counting numbers), `timeline` (points light up along a track), `kanban` (cards travel To do -> Doing -> Done), `quote` (testimonial types in,
  avatar and stars land), `email` (inbox messages arrive), `dashboard` (sidebar, KPIs, growing chart, filling table: the "real product" shot).
  Dark UI, accent yellow, SF type; text scales with the window. Every scene moves within its first 0.3 s and keeps moving until it leaves,
  and every typed character / arriving item has its own soft sound (automatic).
- **Editorial cards (`motion.js`)**: `ring` (title + italic sub, central stat with pulsing disc, emoji icons orbiting a thin ring),
  `steps` (circle icons connected by a line sliding in one by one), `bigtype` (intro line, one BIG word, sub, italic tail; `dark=True`
  for the black variant), `podium` (three classical pillars, brand circle on #1, "Top 3 ... IN INDIA"), `growth` (black card with a
  drawn line chart on yellow), `profile` (circular `headshot(t, x, y, w, h)` of the speaker cut out with the Vision matte, name pill,
  role pills, logo chips). Transitions: `leak(t)` film burn on the cut, `anim="wipe"` in, `out="iris"` out.
- **Set pieces (`motion.js`)**: designed motion-graphics scenes drawn per frame, one per idea in the script. They are the first choice
  for B-roll; the UI scenes above are for literal "here is the tool" moments. Kinds: `chess` (board flips, one piece remains: "the game
  changed"), `headcount` (50 lit people go dark to one: "zero employees"), `orgchart` (roles + salary tags, payroll counter: "you needed a
  team"), `orbit` (tool logos orbit one founder in 3D: "one person with AI"), `reviews` (one-star complaints with what people pay: "who is
  frustrated"), `marketmap` (competitors scatter, the empty region pulses: "the gap"), `assemble` (a website builds itself out of depth,
  light sweep, "live": "build the first version"), `calendar` (180 days burn to 4: "days not months"), `carousel` (assets on a 3D ring, one
  per spoken item), `waveform` (robotic signal morphs into a human one: "sound like you"), `race` (heavy team vs solo, solo wins: "who is
  faster"), `typo` (word slams, gets struck through, the answer lands below). Each has depth (scale/blur by z), a light sweep or glow,
  vignette and grain; each reads in one glance and keeps moving until it leaves; each carries its own ticks/hits in the SFX bus.
  Rule: invent the picture from the sentence (what would a title designer draw for THIS line?), then pick the kind; write the labels in the
  speaker's words. If no kind fits, compose one from the helpers in motion.js (stage, glow, sweep, rr, pill, avatar, person, grid3d).
- **Top-half layout** (`preset="tophalf"`) is the main B-roll device (half of all B-roll time). The scene fills the top 880 px; the footage
  shrinks to 72% at the bottom over a blurred copy with an animated shrink, the window slides down in sync, the caption moves to y 1560.
  2-4 windows of 2-3 s in a 50 s reel, different content each time. The speaker stays visible and the viewer gets a full-width screen.
- **Full-screen inserts** (`preset="full"`): the scene covers the whole frame, speaker hidden, caption at y 1560 (kinetic) / 1480 (cinematic).
  1-2.5 s each, 2-3 per reel (30% of B-roll time), one-glance scenes (`stats`, `counter`, `timeline`, `cards`, `marketmap`, `calendar`)
  or a real clip on the noun being described.
  Footage for inserts, in order of preference: (1) clips the user hands over, (2) real stock: `stock("developer coding laptop night")`
  (Pexels with a key, otherwise Pixabay through Chrome with no key; vertical results first, AI-generated filtered out; prefetch with
  `stock_many([...])` at the top of reel.py so one browser session fetches everything), (3) `scene(..., "cinematic", style=...)`:
  procedural parallax landscapes/skies/cities with light, particles and film grain. Real footage is the default: a reel with no real
  images or clips in it is unfinished. Never silent-cut to black; `anim="fade"` 0.22 s in, `out="fade"`, and a `whoosh`/`swipe` on the cut.
- **Behind the speaker** (`preset="behind"`, or `behindtop` to keep the real room below the chest): the B-roll becomes the background and the
  speaker, cut out with Apple Vision person segmentation (`segment.swift`, compiled to `bin/segment` on first use, on-device, ~35 fps),
  stands in front of it. Canvas set pieces draw in the top 36% (above the head); `cinematic` fills the frame. The classiest layout in the kit, and the rarest (10-20% of B-roll time): one 1.5-3 s use on a reflective line ("the advantage isn't...", "ask AI who's
  frustrated"), with `cinematic`, `chat`, `stats` or `timeline` scenes; scene content is auto-zoomed 1.85x so it reads above the head.
  Our words/captions render in a foreground layer above the person. The matte is 1/2 resolution, feathered 2 px; hair edges are good,
  fast hand motion can ghost for a frame, so avoid moments with big gestures. Not combinable with `blur`/`push` on the same range.
- **Grade** (`CFG["grade"]`, off by default): warm tungsten rooms read yellow on phones. `grade=dict(temp=7400, sat=.95, yellow=-.2,
  lift=.04, gamma=1.03, match=True)` cools the white balance, pulls yellow out of yellows/reds, lifts a touch, and with `match=True`
  measures skin brightness per shot (scene cuts) and adds a per-shot offset so the face reads the same across the whole reel (printed
  as `grade: 0.0-5.6s +0.035 ...`). Check a before/after frame; skin R/B should land ~1.3-1.4, walls ~1.1.
- **Smoothness**: `CFG["smooth"]` (1.0) multiplies every entrance/exit duration and the top-half footage shrink; 1.3-1.5 reads
  calmer and more premium, 0.8 snappier. `anim="dissolve"` / `out="dissolve"` is the soft transition (eased cross-fade with a breath of
  scale and blur) for stock footage windows and full inserts; keep `slam`/`pop` for stickers and hero words only. Film-burn `leak()` goes
  on hard cuts in the footage, not on every window.
- **Drift**: windows on `tophalf`/`full` zoom 3.5% over their life so a finished scene still breathes. Combine with scenes that keep moving.
- **Direction (think like a trailer editor)**: every beat has an entrance, a hold with motion, and an exit; the big words land with a
  camera `punch(t)` (footage zooms 6-8% and back, with a `hit`); full-screen inserts open on a `flash` and can carry letterbox `bars`;
  wins get a `burst` (confetti) with a `ding`; the hook gets a `riser` (1.1 s sweep in SFX_EXTRA) that lands on a `hit`. Entrances:
  `pop`, `slam` (drops from 2.6x), `zoom` (push-in from soft), `iris`, `flip`, `spin`, `bounce`, `blur`, `rise`, `type` (text); exits
  `fade`, `pop`, `zoom`, `iris`, `slam`, `blur`, `cut`. Vary them: no two consecutive items with the same entrance. Stickers are 200-240 px,
  on `plate="glass"|"dark"` when the mark needs contrast, with `idle="float"|"pulse"|"wiggle"` so they never sit dead.
- **Already-edited sources**: if the cut has burned-in captions/title/chips, do not add a second caption layer. Set `title=None`,
  `cap_mode="full"` (ours shows only while a full-screen insert hides theirs), and place windows/stickers around their graphics
  (grab 3 full-res frames first to see where they sit). No `blur=True` there either: it would blur their captions.
- **Kinetic text**: a small white word (84 px, `pop`) then the big yellow one (100 px, `anim="wipe"`) just below and offset; the next pair
  lands in a different corner; all stay until the list ends, then clear together. For "all the components" style lists, scatter single
  words diagonally, last one yellow and bigger.
- **Annotations**: `circle(...)` draws a red marker ellipse over 0.45 s around the button being talked about (0.3-0.5 s after the window
  appears). `cursor(path=[...])` glides a macOS arrow and clicks at the end, for "drop / click / drag" moments.
- **Cards**: `card("cta", "comment", "STYLE", chip="free")` white pill, slides up. Use for comment keyword, stats, "share this with".
- **Sound**: the voice comes first.
  SFX are trimmed macOS UI recordings (Tink, Pop, key click, Finder swoosh, ink strokes), high-passed so they stay crisp under speech;
  synthesis is only the fallback when a file is missing. `--final` and the preview run the voice through high-pass 80 Hz, gentle compression, a touch of
  presence and a measured fixed gain to -14 LUFS with a -1.5 dB true-peak limit (what Reels normalises to anyway), so the speaker is clear and consistent.
  Emphasis sounds, louder (0.9-1.0): `hit` (trailer thump + click) on punches and slams, `ding` (bright glass) on wins and bursts,
  `hero` (triumphant) on the payoff reveal, `riser` into a hook, `boom` (sub) under a full-screen cut, `sparkle` when an icon pops.
  Every recorded sound is trimmed to 0.16-0.45 s with a 70 ms tail (only `riser` and `hero` are longer), so cues read as crisp transients, never as a sound effect playing. Sizes: a `sparkle` on stickers, a `tick` on words, a short dark `whoosh` on windows and cards, `swipe` on wipes,
  a real two-part mouse `click` with the cursor, `scribble` with the circle, a low `hit` for a stat (via `SFX_EXTRA`), and no opening whoosh unless `intro_whoosh=True`. Default volumes are 0.5-0.8 with a mouse click on every sticker, the bus has a master `sfx_gain` (0.85) and is side-chain ducked by the voice, so sounds
  land in the gaps between words instead of on top of them. Every synthesized sound peaks within its first 60 ms so the transient sits on
  the first frame of the animation. If the user wants it punchier, raise `sfx_gain`; if they want silence under speech, keep `duck=True`.
  Set `voice=False` to leave the voice untouched.
- **Fonts**: the editorial register uses Helvetica Neue Bold (installed on every Mac) for hero/support words and New York Italic
  (Apple, loaded from /System/Library/Fonts via @font-face) for the serif accents; both are also available inside canvas scenes
  (`HERO()`, `SERIF()`). The kinetic register keeps SF Pro Display.

## Sound library and retention (impacts, risers, no corporate beds)
- `sfx/` holds real cinematic sounds by category (impact, riser, whoosh, sub, braam, stinger, glitch, click, pop, ding, typing, cash,
  heartbeat, ticking) with `sfx/INDEX.json`. `python3 sound_collect.py` fills it from Freesound (CC0 only) and the BBC Sound Effects
  archive. **Licence**: BBC RemArc is personal / educational / research only; for a commercial or sponsored reel set
  `sfx_sources=("freesound",)` in CFG. Cue names map to categories in `SFX_LIB`; the macOS / synth sounds are only the fallback.
- **Risers are the retention tool.** A `riser` (1.5-3 s) ends exactly on every full-screen card and on every hero reveal, and a
  `riser_long` (3-7 s) builds into the final payoff so the ear expects an ending and stays for it. A riser always resolves into an
  `impact`, `braam` or `stinger` on the first frame of what it announced; a riser that resolves into nothing is a broken promise.
- **Music is never corporate.** Moods: `trailer` (epic hybrid), `hiphop` (dark trap / drill), `upbeat` (hip hop, funk, sport),
  `tech`, `lofi`, `cinematic`, `dramatic`. Tone mapping: intense -> trailer/hiphop, serious -> trailer/cinematic, energetic -> hiphop,
  calm -> lofi. Tags "corporate", "happy", "kids", "ukulele" are penalised. `python3 pixabay_music.py <mood> 12` grows a mood.
- **FX overlays** (`fx/`, `python3 pixabay_fx.py`): green-screen and black-background clips (money, confetti, leak, burn, sparkle,
  smoke, fire, rain, dust, arrow, check, like). `fx("cash", "money", t=(a, b))` keys and composites in ffmpeg; `key="screen"` for
  black-background clips, `key="green"` for chroma, `key="alpha"` for GIF/WebM with transparency. A user's own GIF is a path.

## Voice tone drives the sound (automatic)
Before any sound is placed the renderer measures the speaker: median pitch (autocorrelation F0) and pace (words per second of speech).
It prints `voice tone: intense (F0 128 Hz, 3.97 words/s) -> music dramatic, SFX palette intense`. Tones: **intense** (deep + fast),
**serious** (deep + measured), **energetic** (higher + fast), **warm** (higher + measured), **calm** (slow). Consequences:
- Music mood: intense/serious -> `dramatic` (suspense, tension, trailer tracks; horror tags avoided) or `cinematic`; calm -> `lofi`/
  `cinematic`; energetic/warm -> the content mood (upbeat/tech/...). Within a mood, tracks are scored by tags (`PREFER`).
- SFX palette: for intense/serious every bright or playful cue is swapped for a dark one (sparkle/pop -> `thud`, ding -> `hit`,
  hero -> `boom`, riser -> `swell`, tick -> `tock`). Calm swaps hits for thuds and chimes. Energetic/warm keep the bright set.
  Override with `tone="serious"` or `palette="off"` in CFG. Never put a comic or glittery sound under a serious delivery.

## Music and the final pass
- **Music bed** (`CFG["music"]`, default `"auto"`): a real track runs under the whole reel. The skill ships a collection in `music/<mood>/`
  (Pixabay Content License, free for commercial use, no attribution needed; filtered to tracks without YouTube Content ID and not
  AI-generated; `music/INDEX.json` has titles, authors and page links). Mood comes from the transcript (upbeat / tech / lofi / cinematic /
  dramatic; `pick_mood`), or set it, or give a file path. The renderer prefers a track at least as long as the reel (no loop seam) and
  rotates by reel name so consecutive reels differ. Refresh or grow the set with `python3 pixabay_music.py [mood N]` (drives Chrome,
  no key). `music.py` composes a fallback bed only if a mood folder is empty. Level: normalised to -16 LUFS, `music_db` (-4) below the
  -14 LUFS voice, low-passed at 9 kHz, side-chain ducked ~4 dB while the voice speaks, fade in 1.2 s / out 2 s. Name the track in the
  cue sheet; `music=None` for silence.
- **Metadata**: the last step of `--final` and the preview rewrites the file with no tags (title, artist, encoder, handler names,
  creation time, cover art and data tracks all gone, bitexact so no library version strings) and verifies the result prints
  `metadata: clean`. This removes tool fingerprints from the file; it cannot remove anything a model infers from the picture or sound.

## B-roll must show THE THING ITSELF (context rule)
When the speaker names a product, a tool or a technology, the B-roll is that thing: its own showcase video. Source priority, always:
1. **Brand / technology motion-graphics video downloaded from online** (`brand("claude")`): the official launch or showcase film
   ("Introducing Claude Code", "Introducing GPT-6 in ChatGPT"), fetched once with `python3 brand_collect.py <topic>` (yt-dlp, official
   channels first, 10-300 s) into `brand/<topic>/`. Pick the segment with `window(..., offset=seconds)`; 2-3 s excerpts, in a
   half-screen or full window. Add a topic with `brand_collect.py add <topic> "<query>" ...`. Name the source in the cue sheet; these
   are the brands' marketing films and the user decides whether that use fits their channel.
2. **The skill's own UI animations** (`scene`: terminal, search, calendar, chart...) for processes with no brand.
3. **Stock footage** (Pixabay/Pexels) only for literal physical subjects with no people in frame (cash, a city, a keyboard).
Never: stock people for tech/business talk, metaphor clips (rockets, chess, sprinters), recording websites yourself, or building a
motion graphic by hand when a showcase video of the technology exists online.
- **Enumerations get mini images**: "a developer, a designer, a marketer, a sales guy" -> `iconrow([("👨‍💻", 7.16), ("🎨", 7.84), ...])`,
  one icon popping on each word, in the safe zone under the phrase. One extra for the whole row.
- A window ends naturally: it fades on its own while the layout stays still. The footage shrink happens before the window appears
  and the grow-back starts only after the window has fully faded (automatic); a fade over a moving layout double-exposes and reads as
  a flicker. Never stack a window exit on another window's entrance unless the second one is full-screen.
- **A cut that already carries the creator's own layer** (burned-in subtitles, titles, logo stickers, UI B-roll): add only what is
  missing. `captions=False` (keep the transcript for timing and tone, draw no subtitles), no headlines where their titles sit, list
  their graphics in `CFG["existing"]=[(a, b, "full"|"half"|"behind"|"logo"|"title"), ...]` so the B-roll and 5-second checks count them
  (their B-roll is kept as cut, the standard governs only what you add), put minis in the bare moments beside the head, and sync soft
  sounds to their entrances with `SFX_EXTRA`. Never place a window over their inserts.
- A generated scene must FILL its window: a chat insert is a whole chat screen (header with name and status, typing dots, the question
  and reply bubbles, composer), not one bubble over a blank panel; charts fill the top half; nothing ships with dead area.
- A landscape film whose frame IS the content (a wordmark, a UI screenshot, a title card) must not be cover-cropped into 9:16: give it a
  full-width 16:9 window (`window(..., x=0, y=100, w=1080, h=608, push=.72, radius=0)`) so nothing is clipped; cover-crop only
  footage that survives it (abstract motion, textures, centred subjects).
- Context headlines hide automatically while a full-screen or top-half insert covers their line (the insert carries its own content;
  `keep=True` on a phrase overrides). Never let a headline ghost through a dissolving window.
- One-spot fix after a code or config change: delete the affected frames in `out/frames_fg_*` and run with `REEL_KEEP_CACHE=1`
  so the untouched frames are reused.
- **Top-half layout standard (`preset="tophalf"`)**: the B-roll fills the top 800 px and the FOOTAGE SLIDES DOWN AT FULL WIDTH,
  never shrunk, never side-cropped. For EVERY top-half window the head is measured at three moments (Vision matte: top and chin);
  the slide distance puts the highest head position 60 px under the insert (`PAN_GAP`), so the footage is cropped at the top as
  well as the bottom, the head is never clipped and there is no air above it (the user's limit: well under 15% of the half screen);
  the subtitle sits 70 px under the lowest chin, inside the safe area. Speakers drift between windows, so one measurement is not enough. The insert CUTS in and out (`anim`/`out` are forced to "cut" for pan windows) and the
  footage glides into place in 0.24 s entirely UNDER the opaque insert, so no fade ever overlaps moving footage: no flicker, no
  blurred or dark strip, no lag. On the way back the glide happens during the insert's last 0.24 s, then the insert cuts away
  with the footage already home. The user rejected the old shrink with
  blurred side bars and the slow blurred lead-in; `push=<factor>` remains only for a deliberate special case. `--cue` prints the
  head line and each window's slide distance; `CFG["face_y"]` / `CFG["head_top"]` override.
- Half-screen footage windows carry a soft dark gradient at the top (automatic) so the phrase stays readable over light films.
- **Transitions on B-roll**: `dissolve` only. No `leak()` (film burns are off by default; the user dislikes the light wash), no flashes.

## The B-roll standard (hard rules, checked by `--cue`)
- **B-roll is video or animation, never an image.** `window()` refuses .jpg/.png media.
- **Few, and as long as the words.** A window runs **2-6 s: exactly the stretch of speech it illustrates**, ending when the speaker moves
  on (a 6 s film under a 2 s idea drags; a 2 s cut under a 6 s explanation flickers). A 50 s reel has **3 windows**, never one every few
  seconds (<= 1 per 8 s of runtime, so 5-6 in a 50 s reel including the motion-graphic ones); total coverage 20-36% of the runtime.
  Set the window's in/out on the first and last word of the idea, then pick a film segment of that length.
- **Selection is precise work, no compromise.** For every named technology: download 3-5 candidate films (`brand_collect.py <topic> 5`),
  render their contact sheets (`brand_collect.py sheet <topic>`), and choose by eye a stretch of the window's length that is (a) the product itself, no
  presenters, no hands, (b) in motion for the whole window, (c) legible at half-screen, (d) on the exact words being said. Write the film,
  the segment and why into the cue sheet. If no candidate meets all four, search again with other queries before settling.
- **Half-screen is the main layout** (`tophalf`, 40-100% of B-roll time); full-screen <= 40%; behind the speaker <= 25%; and **at least
  one full-screen or behind-the-speaker window per reel** (a 4K or portrait source, or a set piece), so the layout changes once.
- **Two sources, roughly half each.** Downloaded technology video (`brand()`, >= 50% of B-roll time) whenever a product is named, and
  **the skill's motion graphics as B-roll in their own right** (>= 30%): `scene("...", "calendar"|"race"|"headcount"|"chart"|
  "marketmap"|"orbit"|"flow"..., preset="tophalf"|"full")` on the idea beats (days not months, who is faster, zero employees, the gap).
  Stock only for literal physical subjects with no people. When the script names no technology with a 4K film (an opinion piece, a
  story), motion graphics may carry most of the B-roll: set `broll_real_min` (default 45) lower in CFG and say why in the cue sheet.
- **ULTRA HD, always.** Every B-roll source is 4K (2160 lines): `brand_collect.py` fetches the 2160p rendition first and `brand()`
  picks the highest-resolution film of a topic; `--cue` flags any film window whose source is below 4K. Animations (set pieces, minis,
  icons, typography) are rendered supersampled (`render_scale` 1.5, downscaled with Lanczos at composite) so they stay crisp.
  Never upscaled: A 1920x1080 landscape film fits a half-screen window with no
  upscaling; it must NOT be cover-cropped into a full-screen window (x1.8 upscale, visibly soft). Full-screen needs a 4K or a portrait
  source. `--cue` flags any window that upscales its source by more than 15%.
- `--cue` prints `B-roll: 12.2s of 50.0s = 24% | 3 windows, 4.0-4.1s | half 100% ...` and `B-roll standard: OK` or `FIX -> ...`.
  Do not render with a FIX line.

## Storyboarding rules (what gets a visual)
Target one new visual event every 2-4 s; never more than 4 s of bare talking head after the title. Plan the reel in three layers before
placing anything: (1) 3-5 `tophalf` scenes on the main claims, different kinds, 3-6 s each; (2) 2-4 `full` inserts on the breaths;
(3) stickers, kinetic words and cards in between. Every scene tells the speaker's own story (their product, their numbers, their names),
and the scene kinds progress like a product demo: problem (search, cards) -> plan (flow, doc) -> build (terminal, code, kanban) -> result
(dashboard, stats, chart, email, quote) -> ask (phone, card). Sentence by sentence:
- A **tool / brand / person named** -> sticker pops on the word, stays 1.5-3 s. Two tools in one sentence: `tr` then `tl`.
  The same tools named again later -> on the `chest`, replacing each other with `out="pop"`.
- A **file, prompt, message or doc** being used -> window on the `laptop` preset sliding `up`, or a `bar` for a chat/search input.
- "**Look at this / here's how it looks**" -> full B-roll: `mid` window, `blur=True`, 2.5-4 s; `out="cut"` if the footage cuts. Generated:
  `browser` for a product/site, `cards` for then-vs-now, `chart`/`counter` for numbers, `search` for "what people struggle with".
- "**Build / code / run / deploy**" -> `terminal` or `code` in `tophalf`. "**Write / draft / document**" -> `doc` typing above the head.
  "**Ask the AI / prompt it**" -> `chat`. "**Step 1, 2, 3 / the process**" -> `flow`. "**Everything you need**" -> `checklist`.
  "**DM / comment / message**" -> `phone` with the notification sliding in.
- "**Go to X, download / click Y**" -> `top` window with the page, then `circle` around the button 0.4 s later.
- A **list spoken aloud** (typography, spacing, colours) -> kinetic text pairs, one per item, on the item's word.
- A **joke, frustration, "ugh"** -> meme/GIF `topright`, 2-3 s, radius 10.
- A **result / proof / number** -> `card` preset window or `card(...)` with the number, `hit` SFX.
- A **CTA** ("comment STYLE") -> `card` with the keyword during the sentence.
- The **first 1.5 s**: title up, caption going, and a motion element (cursor, sticker) by 0.6 s. Hooks need movement.
Scene content is copywriting: concrete nouns and numbers from the speaker's own example (invoice chaser, 20 users, day 3/7/14), never
lorem ipsum or "Feature 1". A command the viewer could type, a reply that sounds like the speaker, a chart whose last bar is the point.
Keep each scene to what can be read in its time on a phone: 5-6 terminal lines, 3 cards, 4 search results, 60-90 chars of prompt.
Stickers and windows never cover the face; put them beside the head, on the chest, or over the laptop. One sticker per 3 s max.

## Safe zone (Instagram Reels UI, 1080x1920 frame). ALWAYS.
Measured from the user's Instagram guide: the visible black area is **x 10-915, y 250-1535**. The top 250 px is the header, the right
165 px the like/comment/share column, the bottom 385 px the username/caption/audio. Every word, card and sticker lives inside
`SAFE` = x 70-905, y 270-1500 with no exceptions: `phrase()` compositions are measured and shifted (scaled down once if needed)
into the box automatically; `--cue` flags any `text`/`sticker`/`card` placed outside it (`Motion standard: FIX -> outside the safe zone`).
Footage windows may fill the frame (they are pictures, not reading matter), but their own text should sit in the box too. Check the
stills against the box before every render.

## Animation budget and the 5-second rule
Typography is the core and is free. Everything else is an extra and must earn its place: **at most one extra per 3 s of runtime**
(a 50 s reel: ~16 extras), **<= 3 camera punches** (the three most important words), **<= 3 stickers** (only when a tool is named),
**<= 1 accent icon per 6 s** (icons alone read as clutter), and **something new must land on screen at least every 5 s**: a window, a
kinetic word pair, an icon, a hero headline word, a punch, a burst. Vary the device: never two of the same kind in a row, and at least
three kinds across the reel. `--cue` flags gaps over 5 s and reels that lean on one device.
`leak()` only on full-screen inserts, no confetti/flash/bars unless the line is a genuine win. Entrances are soft by default
(`smooth` 1.3, `dissolve` for windows, hero words scale from 1.1 not 1.25); `slam`/`spin`/`bounce` are for a single deliberate moment.
`--cue` prints `Motion: N extras ...` and `Motion standard: OK/FIX`; fix before rendering.

## Sound (soft by default)
`sfx_style="soft"` is the default: sharp cues are replaced by rounded, low ones (hit -> thud, braam/stinger -> boom, ding -> chime,
click/tick -> tock), typing clicks, sparkles, shutters and scribbles are dropped, phrase support words are silent and only the hero
word gets a soft thud, the bus runs at `sfx_gain` 0.7 under a ducked bed. Risers stay (a sweep is not sharp) and still resolve into a
low boom. `sfx_style="punchy"` restores the full palette for reels that want it.

## Quality (lessons from real reels)
- **Phone HDR footage** (HEVC Main10, BT.2020, HLG) must stay 10-bit HDR. `--final` encodes `hevc_videotoolbox` 20 Mbps Main10 with the
  source tags; overlay graphics go through a 3D LUT into BT.2020 primaries (without it yellow turns orange). Brightness stays as-is.
- **Encode video first (`-an`), then mux audio** with `-c:v copy`: one videotoolbox pass with amix produced corrupt NAL units.
- Blur is `gblur` with a timeline `enable`, so it costs nothing outside the B-roll ranges. Blur ranges come from windows with `blur=True`.
- The frame cache is keyed on the rendered page (config, captions, media), so any change re-renders automatically. A manual one-spot fix is still possible: delete only the affected frames in `out/frames_WxH/` (frame = seconds x fps) and re-run.
  After changing a window's media, delete `out/media/<id>/` too.
- Media prep scales recordings to the window width at device pixels; feed 2x captures (capture.py does) so text in windows stays crisp.
- Colour checks happen on the phone. Don't judge HDR colour from numbers read off a frame grab.
- Some phone editors show alpha video as black (Instagram Edits, Oct 2026). Deliver `--final` for those.

## Re-theming a finished reel (brand colour swap, audio untouched)
When the user hands over a finished motion-graphics reel and wants it in their brand colour: do NOT re-animate. Build a 3D LUT that
remaps only the source hue range (e.g. greens, hue 70-175 deg, saturation > .06 with a soft edge) onto the brand hue (violet 263 deg
for Tcipher, lighter tones leaning to 271), keep value and saturation, apply with `lut3d=...:interp=tetrahedral`. Cover the creator's
end logo with a white box + the brand logo fading in (`drawbox` + `overlay` with `fade=alpha`). Audio: `-c:a copy`, then verify the
audio stream is bit-identical (`md5` of the copied AAC) and strip metadata. Check a frame of every section: faint glows and anti-aliased
edges need the low saturation threshold. (Done for ~/Desktop/test.mp4 -> test_purple.mp4; LUT in Desktop/test_build/green2violet.cube.)

## Cover (custom thumbnail)
1080x1920 JPG: best expression frame from a close-up, the title style a bit bigger, one sticker. Check the 3:4 grid crop (y 240-1680).
HDR still: `swift grab_frame.swift <cut> <seconds> out.png` (Apple's conversion). Hand-rolled HLG->sRGB math blows out highlights.

## Never
- Cut, zoom or grade the footage; the only footage edits are the blur behind B-roll and the SFX mix.
- Ship a title or cue sheet the user did not approve.
- Use files found on the user's machine as B-roll unless they handed them to you. Generate instead.
- Text baked into image assets; put words in `text()`/`card()` so they stay editable.
- Em dashes in on-screen text.
