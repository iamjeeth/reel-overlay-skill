"""Grab B-roll from a website with the installed Chrome (no browser download).

  python3 capture.py shot   URL out.png  [--width 1440] [--height 900] [--full] [--dark] [--wait 2]
      viewport screenshot; --full = whole page (tall PNG, for a scrolling window: window(..., scroll=(220, .4)))
  python3 capture.py record URL out.mp4  [--width 1440] [--height 900] [--seconds 6] [--scroll 1800] [--wait 2]
      records the live page (animations, hover states) while smooth-scrolling `--scroll` px over `--seconds`
  python3 capture.py demo URL out.mp4 --type "Write a PRD for an invoice reminder app" [--into "textarea"] [--cps 14] [--send] [--seconds 8]
      records a real product page while a prompt is typed into its input (first visible textarea / contenteditable by default),
      optionally pressed Enter (--send), then holds. This is how "Claude / ChatGPT doing the work" B-roll is made: a real site, real typing.

Output is only as good as the page: close cookie banners with --wait + a selector-free page, or ask the user for a
real screen recording when the site needs a login. Never record anything the user is not allowed to show."""
import argparse, pathlib, shutil, subprocess, sys, tempfile, time
from playwright.sync_api import sync_playwright

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["shot", "record", "demo"]); ap.add_argument("url"); ap.add_argument("out")
    ap.add_argument("--type", default=""); ap.add_argument("--into", default=""); ap.add_argument("--cps", type=float, default=14); ap.add_argument("--send", action="store_true")
    ap.add_argument("--hold", type=float, default=2.5); ap.add_argument("--profile", default="")
    ap.add_argument("--width", type=int, default=1440); ap.add_argument("--height", type=int, default=900); ap.add_argument("--full", action="store_true")
    ap.add_argument("--dark", action="store_true"); ap.add_argument("--wait", type=float, default=2.0); ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--scroll", type=int, default=1800); a = ap.parse_args()
    out = pathlib.Path(a.out).expanduser(); out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=CHROME, headless=False, args=["--disable-blink-features=AutomationControlled"])   # real sites hide their UI from headless bots
        tmp = tempfile.mkdtemp() if a.mode in ("record", "demo") else None
        ctx = br.new_context(viewport={"width": a.width, "height": a.height}, device_scale_factor=2 if a.mode == "shot" else 1,
                             color_scheme="dark" if a.dark else "light", user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                             **({"record_video_dir": tmp, "record_video_size": {"width": a.width, "height": a.height}} if tmp else {}))
        pg = ctx.new_page(); pg.goto(a.url, wait_until="load"); pg.wait_for_timeout(int(a.wait * 1000))
        if a.mode == "shot":
            pg.screenshot(path=out, full_page=a.full); print("saved", out)
        elif a.mode == "demo":
            for sel in ([a.into] if a.into else ["textarea", "[contenteditable='true']", "input[type='text']", "input"]):
                loc = pg.locator(sel).first
                try:
                    if loc.count() and loc.is_visible(): break
                except Exception: continue
            else: sys.exit("demo: no input field found; pass --into <selector>")
            loc.click(); pg.wait_for_timeout(400)
            for ch in a.type: pg.keyboard.type(ch); pg.wait_for_timeout(int(1000 / a.cps * (0.6 + 0.8 * (hash(ch) % 10) / 10)))
            pg.wait_for_timeout(500)
            if a.send: pg.keyboard.press("Enter")
            pg.wait_for_timeout(int(a.hold * 1000 + (a.seconds * 1000 if a.send else 0)))
            vid = pg.video.path(); ctx.close()
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", vid, "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", "30", str(out)], check=True)
            shutil.rmtree(tmp, ignore_errors=True); print("saved", out)
        else:
            steps = int(a.seconds * 30); t0 = time.time()
            for i in range(steps):   # ease-in-out scroll so it reads like a person scrolling
                u = i / max(1, steps - 1); e = u * u * (3 - 2 * u)
                pg.evaluate(f"window.scrollTo(0, {int(a.scroll * e)})"); pg.wait_for_timeout(max(0, int((t0 + (i + 1) / 30 - time.time()) * 1000)))
            pg.wait_for_timeout(600); vid = pg.video.path(); ctx.close()
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", vid, "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-pix_fmt", "yuv420p", "-r", "30", str(out)], check=True)
            shutil.rmtree(tmp, ignore_errors=True); print("saved", out)
        br.close()

if __name__ == "__main__":
    main()
