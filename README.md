# reel-overlay (Claude Code skill)

Turns a finished 9:16 reel into one with captions, a title, image assets, comment/share cards and synced SFX, rendered by Claude Code.

## Install
1. Unzip, rename the folder to `reel-overlay` and move it to `~/.claude/skills/` (so the path is `~/.claude/skills/reel-overlay/SKILL.md`).
2. Install the tools:
   ```
   brew install ffmpeg
   pip3 install playwright pillow openai-whisper
   ```
   Google Chrome must be in /Applications.
3. Have an SFX folder (whooshes, pops, a buzzer) and set `CFG["sfx"]` in `overlay.py` to it.
4. In Claude Code: drop your cut in ~/Downloads and say "make the overlay" (or `/reel-overlay`).

## Files
- `SKILL.md`: the workflow + style + quality rules Claude follows
- `overlay.py`: the renderer (`--dry`, `--still t...`, default, `--final`)
- `grab_frame.swift`: HDR-correct still grab for covers

Style defaults (fonts, accent colour, positions) are in `overlay.py` CSS and in SKILL.md. Change both to match your brand.
