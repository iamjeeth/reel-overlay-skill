# reel-overlay (Claude Code skill)

Edits a finished 9:16 talking-head cut the way top creator reels are edited, in two registers:
- **Kinetic**: one-word captions with accent words, two-line title, official logo stickers, kinetic word lists, red-circle and cursor
  annotations, cards, and B-roll the renderer generates itself from the transcript (terminal, chat, doc, code, browser, search, cards,
  chart, counter, phone, flow, checklist, stats, timeline, kanban, quote, email, dashboard, progress, reveal) in floating windows,
  the top-half split layout (footage shrinks to the bottom) and full-screen inserts.
- **Editorial** (premium founder/brand reels): no captions; the spoken words land as lime/white/serif typography compositions,
  yellow and black full-screen cards, film-burn transitions, falling-cash/confetti overlays, risers into every card.
- **Cinematic**: 2-word boxed captions, full-screen footage inserts (Pexels via `stock()`, procedural `cinematic` scenes, app shots,
  brand reveals) that replace the speaker for a phrase at a time.
Voice is cleaned and levelled first; SFX are trimmed macOS UI recordings and a music bed (your tracks or a composed one) sits under the voice, both ducked while speaking. The final file is written with all metadata stripped. Rendered with Chrome + ffmpeg.

## Install
1. Clone it into your skills folder:
   ```
   git clone https://github.com/iamjeeth/reel-overlay-skill ~/.claude/skills/reel-overlay
   ```
2. Install the tools:
   ```
   brew install ffmpeg
   python3.11 -m pip install playwright openai-whisper
   ```
   Google Chrome must be in /Applications (Playwright drives it, no browser download).
3. Optional: your own SFX mapped in `CFG["sfx"]`; otherwise trimmed macOS system sounds are used.
4. Optional: a free Pexels key in `~/.config/reel-overlay/pexels_key` for real stock footage (`stock("golden hour meadow")`).
   Music, sounds and overlays ship in the repo: `music/` (~85 Pixabay tracks by mood), `sfx/` (impacts, risers, whooshes, braams,
   stingers from Freesound CC0 + the BBC archive), `fx/` (green-screen / black-background overlay clips). Grow them with
   `python3 pixabay_music.py <mood> 12`, `python3 sound_collect.py <category> 8`, `python3 pixabay_fx.py <category> 4`.
   BBC sounds are personal/educational licence: set `sfx_sources=("freesound",)` in a commercial reel's config.
5. In Claude Code: drop your cut in ~/Downloads and say "edit my reel" (or `/reel-overlay`).

## Files
- `SKILL.md`: workflow, the measured look, storyboarding rules, safe zones
- `overlay.py`: the renderer (`--dry`, `--cue`, `--still t...`, default overlay+preview, `--final`)
- `reel_example.py`: annotated per-reel config to copy as `reel.py`
- `sfx/`: cinematic sound library (impacts, risers, whooshes, braams, stingers...) from Freesound CC0 + BBC archive; `sound_collect.py` refreshes it
- `fx/`: green-screen / black-background overlay clips (money, confetti, leaks, sparkles...); `pixabay_fx.py` refreshes it
- `music/`: the royalty-free track collection by mood (Pixabay), `music/INDEX.json` = titles/authors/links; `pixabay_music.py` refreshes it
- `motion.js`: the motion-graphics set pieces (chess, headcount, orgchart, orbit, reviews, marketmap, assemble, calendar, carousel, waveform, race, typo)
- `music.py`: fallback composed beds when a mood folder is empty
- `brand/` + `brand_collect.py`: brand / technology showcase videos downloaded from online (yt-dlp), the first-choice B-roll via `brand(topic)`
- `pixabay_stock.py`: real stock footage and photos without an API key (used by `stock()`)
- `capture.py`: website screenshots (`shot --full`) and scroll recordings (`record`) for B-roll windows
- `segment.swift` (+ `bin/segment`): Apple Vision person matte for the behind-the-speaker layout
- `grab_frame.swift`: HDR-correct still grab for covers

Style defaults (font, accent colour, presets, animation timings) are at the top of `overlay.py`; the rules that decide what
appears when are in SKILL.md. Change both to match your brand.

## Brands, places, people: fetched per script

`brand/` ships empty. When a script names something, its real mark and showcase film are fetched on demand (brand logos, car marques, flags, cut-out portraits; official launch films; landmark footage):

```
python3 logo_collect.py add moz "Moz" --kind brand --domain moz.com
python3 logo_collect.py add india "India" --kind place
python3 logo_collect.py add elon-musk "Elon Musk" --kind person
python3 logo_collect.py sheet      # brand/logos/sheet.png
```

In a storyboard: `accent("m", logo("moz"), 12.3)`. Emoji are for concepts only; a named brand always gets its original logo.

## When in doubt, it asks

Anything about the edit that is not clear from the footage or the transcript (hook, B-roll choice, images, icons, captions, sound) is put to you as three suggestions plus a custom option before anything is rendered.
