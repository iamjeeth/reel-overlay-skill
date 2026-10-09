---
name: reel-overlay
description: Use when the user sends a finished 9:16 reel cut (Instagram Reels, TikTok, Shorts) and wants an overlay on top - captions, title, image assets (logos, people cutouts), comment-keyword card, "share this with" end card, sound effects - either as a transparent overlay file or burned into the final video. Triggers: "make the overlay", "add captions and assets", "here's the cut", "/reel-overlay". Not for cutting/editing the footage itself, zooms, or colour grading.
---

# Reel overlay

Takes a finished vertical cut and adds a motion-graphics layer: word-timed captions, a title, image assets that pop in, a red cross that draws over a logo, a comment-keyword card, a "share this with" end card, and a synced SFX track.

Output, per reel, in `out/`:
- `<NAME>_overlay.mov`: transparent ProRes 4444, full frame, SFX as its audio, starts at 0:00 of the cut
- `<NAME>_preview.mp4`: small H.264 preview (under ~30 MB, so it can go to a phone)
- `<NAME>_final.mp4` (with `--final`): overlay + SFX burned into the cut, matching the cut's HDR/SDR format

## Requirements (macOS)
- `ffmpeg` with `libvmaf` (Homebrew build), `ffprobe`
- Python 3 with `playwright` and `Pillow`, plus Google Chrome at `/Applications` (Playwright drives your installed Chrome, so no browser download)
- `openai-whisper` (`pip install openai-whisper`) for local word timestamps
- An SFX library folder (whoosh, pops, buzzer, bell). Paths in the `SFX` block are relative to `CFG["sfx"]`.
- Optional: `swift` (Xcode CLT) for `grab_frame.swift`

## Steps (keep tokens low)
1. **Find the cut**: newest .mp4/.mov in ~/Downloads that is the 9:16 export (e.g. 1080x1920), not the raw camera file. Ask only if it's still unclear. `ffprobe` it: resolution, fps, and whether it's HDR (`color_transfer` = arib-std-b67 or smpte2084).
2. **Work folder**: copy `overlay.py` into a per-reel build folder. Edit the CONFIG block: `name`, `cut`, `sfx`, `chrome`.
3. **Transcript**: `ffmpeg -i cut.mp4 -vn -ac 1 -ar 16000 audio.wav`, then `whisper audio.wav --model small --language en --word_timestamps True --output_format json`. Check `--dry` output and fix mishearings with `fixes` (one word) and `merges` (token runs, e.g. `("bing", ".com") -> "bing.com"`). Product names, URLs, numbers with % and the comment keyword are where whisper goes wrong most.
4. **Look at frames cheaply**: ONE contact sheet, a frame every 2s (`-vf fps=0.5,scale=135:240,tile=15x2`) + scene cuts (`-v info -vf "select='gt(scene,0.2)',showinfo" -f null -`). Put the cut times in `cuts`. Never go frame by frame.
5. **Title**: 2 short balanced lines + an optional subtitle with an emoji. Offer the user 3 options (widest audience / practitioner / money angle) in plain words, and let them pick. Never ship a title you made up alone.
6. **Cue sheet**: write what appears where and when as text (asset, x/y, in/out, SFX) and get a yes. Assets are images only (logos, people cutouts) from the user's own asset folder; simple shapes can be inline SVG. Ask before downloading any logo.
7. **Stills check**: `python3 overlay.py --still t1 t2 t3` composites the overlay on the cut at those times into one `out/stills.png`. Look at that ONE image, then fix placements before the full render.
8. **Render**: `python3 overlay.py` makes the overlay MOV + preview. Frames whose DOM state hasn't changed are hard-linked, not re-shot, so a 60s reel takes ~2-3 min. Send the preview to the user.
9. **Final (optional)**: `python3 overlay.py --final` burns it in and checks the result for decode errors and frame count. Report both.

## Default style (change to your brand)
- **Captions**: ONE fixed zone for the whole reel (top ~1270px). Boxed: Inter Tight 700 68px, white on a rgba(15,15,15,.72) rounded box; emphasis words (`emph`) in the accent colour, same size. Max 3 words / 20 chars per chunk; breaks on punctuation, pauses > .35s and scene cuts. Chunks that only say "comment KEYWORD" are dropped (the card says it).
- **Title**: accent-coloured boxes, Inter Tight 800 112px, 2 short lines, subtitle 58px. Shown ~0-4s at top 290px. Side margins >= 120px: shrink the font before letting a line go wider.
- **Assets**: white rounded 240px tiles for logos, cutouts for people, in the top band (y 220-500) above the speaker's head. Pop in, then stay still (no float). When the speaker says "doesn't / does not / never" about a tool, the red X draws over its logo with a buzzer.
- **Comment card** (comment / KEYWORD + red chip) during the spoken CTA, just above the captions. **End card** "share this with / <who>" slides in for the last ~2s.
- **SFX**: always a whoosh at 0:00 at full volume (softer ones go unnoticed). One pop per asset entrance (a "bloop" for logos/cards, a softer bubble for people). Buzzer with every cross, a hard pop on big stats. Trim long files with the 4th SFX field.
- No em dashes in on-screen text.

## Safe zone (Instagram Reels UI, 1080x1920 frame)
Nothing outside **x 10-915, y 115-1500**. Off limits: the top ~115px, the right ~165px (like/comment/share column), the bottom ~420px (username, caption, audio). Centre on the full frame (x 540) and keep >= 40px clear of the edges of that box, so a centred element is at most ~670px wide (x 205-875) and sits between y ~155 and ~1460. Check every element's box in the stills step. Positions in `ITEMS` are on the 1080x1920 canvas; the script scales to the cut's resolution.

## Quality (lessons from real reels)
- **Phone HDR footage** (iPhone: HEVC Main10, BT.2020, HLG) must stay 10-bit HDR. Never deliver 8-bit H.264 on HDR footage; it looks visibly worse after Instagram compression. `--final` handles this: `hevc_videotoolbox` 20 Mbps Main10 with the source's colour tags.
- **Gamut**: overlay graphics are sRGB. On HDR footage they are mapped into BT.2020 primaries with a 3D LUT (generated by the script); without it, a yellow like #FFD60A shows ORANGE on the phone. Keep the brightness as-is: mapping graphics white to 75% HLG (BT.2408) made them look dark.
- **Encode video first (`-an`), then mux the audio** with `-c:v copy`. Doing videotoolbox + an amix audio filter in one pass produced files with corrupt NAL units.
- Optional proof: VMAF vs the source (`libvmaf` with `n_subsample=10`); a good encode scores ~99 mean.
- Colour checks happen on the phone. Don't judge HDR colour from numbers read off a frame grab.
- **Mobile editors and alpha**: some phone editors (Instagram's Edits app, tested Oct 2026) show ANY alpha video (ProRes 4444 and HEVC-with-alpha) as black. For those, deliver the `--final` composite and let the user finish in the app (colour, export). Green-screen chunks (< 30s each for Edits' background removal) work but look worse.

## Cover (custom thumbnail)
1080x1920 JPG: the best expression frame from a close-up, the title style a bit bigger, one image asset. Check the 3:4 grid crop (y 240-1680). To get a still from HDR footage, use `swift grab_frame.swift <cut> <seconds> out.png` (Apple's own conversion, matches Photos). Hand-rolled HLG->sRGB math blows out the highlights.

## Never
- Zooms, cuts or colour grades: the overlay can't touch the main track. For a mobile editor, give adjust values (warmth/contrast/shadows/saturation), not a LUT.
- Re-render the whole reel for a one-spot fix: delete only the affected frames from `out/frames_WxH/` (they re-render, the rest come from cache).
- Text baked into image assets: the user types text in their editor; you provide images.
