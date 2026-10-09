"""Reel overlay renderer: captions, title, image assets, comment card, share card and SFX for a finished 9:16 cut.

Modes (run from this folder):
  python3 overlay.py --dry            print the caption chunks (check whisper fixes first)
  python3 overlay.py --still 1 5.2    render overlay PNGs at those seconds, composited on the cut -> out/stills.png
  python3 overlay.py                  transparent ProRes 4444 overlay MOV (SFX as its audio) + small preview MP4
  python3 overlay.py --final          burn the overlay + SFX into the cut, matching its HDR/SDR format, then verify

Edit the CONFIG, ITEMS and SFX blocks for each reel. Everything is laid out on a 1080x1920 canvas and
scaled to the cut's real resolution at render time."""
import json, os, pathlib, re, subprocess, sys
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).parent

# ============================== CONFIG (edit per reel) ==============================
CFG = dict(
    name="REEL01",
    cut=pathlib.Path("~/Downloads/my_cut.mp4").expanduser(),       # the finished 9:16 export
    whisper=HERE/"audio.json",                                     # whisper --word_timestamps True --output_format json
    out=HERE/"out",
    chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    sfx=pathlib.Path("~/reel-sfx").expanduser(),                   # your SFX library
    fps=30,
    title=["Short line one", "short line two"], subtitle="Hook line 🙄", title_t=(0.0, 4.0),
    cta=dict(keyword="KEYWORD", chip="free steps", t=(55.0, 58.3)),   # None to skip the comment card
    share=dict(who="your marketing guy", t=58.4),                       # None to skip the end card
    cuts=[],                       # scene-cut times: captions never span a cut
    emph={"Google", "free"},       # words shown in the accent colour (match after fixes, punctuation included)
    merges=[(("bing", ".com"), "bing.com")],   # whisper token runs -> one word (lowercase, compared without punctuation)
    fixes={"fell": "fall"},        # single-word mishearings
)
ACCENT = "#FFD60A"
# id, html, left, top, in, out, anim ("pop" or "draw" for the red cross). Keep inside the safe box (see SKILL.md).
def img(p): return pathlib.Path(p).expanduser().as_uri()
def tile(inner): return f"<div class='tile'>{inner}</div>"
CROSS = ("<svg width='300' height='300' viewBox='0 0 300 300'><path class='d' d='M45 45 L255 255' stroke='#E02424' stroke-width='30' stroke-linecap='round' fill='none' pathLength='1'/>"
         "<path class='d' d='M255 45 L45 255' stroke='#E02424' stroke-width='30' stroke-linecap='round' fill='none' pathLength='1'/></svg>")
ITEMS = [
    # ("logo", tile(f"<img src='{img('~/assets/logos/google.svg')}' width='140'>"), 420, 250, 6.0, 9.0, "pop"),
    # ("logox", CROSS, 390, 220, 7.2, 9.0, "draw"),
    # ("person", f"<img src='{img('~/assets/people/someone_cutout.png')}' width='250'>", 110, 220, 2.0, 5.0, "pop"),
]
# file, start, volume, max length (None = full)
S = CFG["sfx"]
SFX = [
    (S/"whoosh-swoosh/cinematic-whoosh-fast-transition.wav", 0.0, 1.0, None),
    # (S/"pops-cute/bloop.wav", 6.0, .8, None),           # one pop per asset entrance
    # (S/"buzzer.wav", 7.2, .5, None),                    # with every red cross
]
# ====================================================================================

def probe(f, entries):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", f"stream={entries}", "-of", "json", str(f)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)["streams"][0]

CUT, OUT, FPS = CFG["cut"], CFG["out"], CFG["fps"]
V = probe(CUT, "width,height,nb_frames,color_transfer,pix_fmt")
W, H = V["width"], V["height"]
DUR = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(CUT)],
                           capture_output=True, text=True, check=True).stdout)
HDR = V.get("color_transfer") in ("arib-std-b67", "smpte2084")

# ---------------- captions: whisper words -> fixed chunks ----------------
def bare(t): return re.sub(r"[^\w.%/]", "", t.lower())

def captions():
    W_ = [dict(t=w["word"].strip(), s=w["start"], e=w["end"]) for seg in json.load(open(CFG["whisper"]))["segments"] for w in seg["words"]]
    i = 0
    while i < len(W_):
        for toks, rep in CFG["merges"]:
            n = len(toks)
            if tuple(bare(w["t"]) for w in W_[i:i+n]) == toks:
                W_[i:i+n] = [dict(t=rep, s=W_[i]["s"], e=W_[i+n-1]["e"])]; break
        i += 1
    for w in W_: w["t"] = CFG["fixes"].get(w["t"], w["t"])
    cta_words = {CFG["cta"]["keyword"].lower(), "comment"} if CFG["cta"] else set()
    chunks, cur = [], []
    for w in W_:
        if cur and (len(cur) >= 3 or len(" ".join(x["t"] for x in cur + [w])) > 20 or w["s"] - cur[-1]["e"] > .35
                    or any(cur[0]["s"] < c <= w["s"] for c in CFG["cuts"])):
            chunks.append(cur); cur = []
        cur.append(w)
        if re.search(r"[,!?]$|(?<!\w\.\w)\.$", w["t"]): chunks.append(cur); cur = []
    if cur: chunks.append(cur)
    k = 0
    while k < len(chunks):   # fold chunks shorter than .35s into the previous one (max 4 words)
        if k and chunks[k][-1]["e"] - chunks[k][0]["s"] < .35 and len(chunks[k-1]) + len(chunks[k]) <= 4:
            chunks[k-1] += chunks.pop(k); continue
        k += 1
    caps = []
    for j, c in enumerate(chunks):
        if all(bare(x["t"]).strip(".") in cta_words for x in c): continue   # the comment card says it
        s = c[0]["s"]; e = min(chunks[j+1][0]["s"] if j + 1 < len(chunks) else DUR, c[-1]["e"] + .6)
        caps.append(dict(s=round(s, 3), e=round(e, 3), w=[dict(t=re.sub(r"[.,]$", "", x["t"]), em=x["t"] in CFG["emph"]) for x in c]))
    return caps

# ---------------- page ----------------
CSS = """@import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@600;700;800&display=swap');
*{margin:0;box-sizing:border-box}html,body{background:transparent}body{width:1080px;height:1920px;overflow:hidden;position:relative;font-family:'Inter Tight'}
.it{position:absolute;opacity:0;transform-origin:50% 50%}
.tile{width:240px;height:240px;border-radius:54px;background:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 30px 60px -24px rgba(0,0,0,.6)}
#title{position:absolute;left:120px;right:120px;top:290px;text-align:center;transform-origin:50% 0}
#title span{display:inline-block;letter-spacing:-2px;border-radius:14px;white-space:nowrap;background:ACC;color:#111}
#title .m{font-weight:800;font-size:112px;line-height:1;padding:10px 26px;margin:0 0 10px}
#title .s{font-weight:700;font-size:58px;line-height:1;padding:10px 22px;margin-top:8px}
#cap{position:absolute;left:205px;right:205px;top:1270px;text-align:center;line-height:1.25;font-size:68px;word-spacing:4px;transform-origin:50% 50%}
#cap .box{display:inline;background:rgba(15,15,15,.72);padding:8px 22px;border-radius:18px;box-decoration-break:clone;-webkit-box-decoration-break:clone}
#cap b{font:700 68px 'Inter Tight';color:#fff;letter-spacing:-1px}#cap b.em{color:ACC}
.card{position:absolute;left:205px;right:205px;top:1080px;background:#fff;border-radius:36px;padding:24px 30px;display:flex;align-items:center;gap:22px;
 box-shadow:0 30px 60px -24px rgba(0,0,0,.6);opacity:0}
.card .k{font:600 30px 'Inter Tight';color:#6B6A5E}.card .v{font:800 60px 'Inter Tight';color:#111;letter-spacing:-1px;line-height:1}
.dot{width:84px;height:84px;border-radius:50%;background:ACC;flex:none;display:flex;align-items:center;justify-content:center}""".replace("ACC", ACCENT)

def body():
    t = CFG
    h = "<div id='title'>" + "<br>".join(f"<span class='m'>{l}</span>" for l in t["title"]) + (f"<br><span class='s'>{t['subtitle']}</span>" if t["subtitle"] else "") + "</div>"
    h += "".join(f"<div class='it' id='{i}' style='left:{x}px;top:{y}px'>{html}</div>" for i, html, x, y, a, b, k in ITEMS) + "<div id='cap'></div>"
    if t["cta"]:
        h += ("<div class='card' id='pill'><div class='dot'><svg width='46' height='46' viewBox='0 0 24 24'><path d='M21 12a8.5 8.5 0 0 1-12.6 7.4L3 21l1.6-5.2A8.5 8.5 0 1 1 21 12z' fill='none' stroke='#111' stroke-width='2.4' stroke-linejoin='round'/></svg></div>"
              f"<div><div class='k'>comment</div><div class='v'>{t['cta']['keyword']}</div></div>"
              f"<div id='free' style='margin-left:auto;font:800 28px Inter Tight;color:#fff;background:#C62828;padding:12px 18px;border-radius:999px;white-space:nowrap'>{t['cta']['chip']}</div></div>")
    if t["share"]:
        h += ("<div class='card' id='share'><div class='dot' id='plane'><svg width='48' height='48' viewBox='0 0 24 24'><path d='M22 3 L2 10.5 L10 13 L13 21 Z M10 13 L22 3' fill='none' stroke='#111' stroke-width='2.2' stroke-linejoin='round'/></svg></div>"
              f"<div><div class='k'>share this with</div><div class='v' style='font-size:52px'>{t['share']['who']}</div></div></div>")
    return h

JS = """<script>
const CAPS=__CAPS__, ITEMS=__ITEMS__, T=__T__, P=__P__, S=__S__;
const cl=(v,a=0,b=1)=>Math.min(b,Math.max(a,v)), ease=p=>1-Math.pow(1-cl(p),3);
const back=p=>{p=cl(p);const c=1.7;return 1+(c+1)*Math.pow(p-1,3)+c*Math.pow(p-1,2)};
const r=v=>Math.round(v*1000)/1000, $=id=>document.getElementById(id);
let last=null;
function render(t){
  const K=[];
  const ti=$('title'), ta=t<T[0]?0:t<T[1]-.2?1:cl((T[1]-t)/.2), ts=.7+.3*back((t-T[0])/.35);
  ti.style.opacity=ta; ti.style.transform=`scale(${r(ts)})`; K.push(r(ta),r(ts));
  for(const it of ITEMS){
    const el=$(it.id), on=t>=it.a&&t<it.b, pin=(t-it.a)/.35, out=cl((it.b-t)/.15);
    let op=on?Math.min(cl(pin*2),out):0, sc=on?(.55+.45*back(pin)):1;
    if(it.k==='draw'){ sc=1; el.querySelectorAll('.d').forEach((p,i)=>{p.style.strokeDasharray=1;p.style.strokeDashoffset=r(1-ease((t-it.a-i*.15)/.18));}); K.push(r(t<it.a+.5?t:0)); }
    el.style.opacity=r(op); el.style.transform=`scale(${r(sc)})`; K.push(r(op),r(sc));
  }
  const c=CAPS.find(c=>t>=c.s&&t<c.e), cap=$('cap');
  if(c!==last){cap.innerHTML=c?`<span class='box'>${c.w.map(w=>`<b class='${w.em?'em':''}'>${w.t}</b>`).join(' ')}</span>`:'';last=c;}
  const cp=c?(t-c.s)/.12:0; cap.style.opacity=c?r(cl(cp*1.5)):0; cap.style.transform=`scale(${r(c?.9+.1*back(cp):1)})`;
  K.push(c?c.s:-1,cap.style.opacity,cap.style.transform);
  if(P){ const pl=$('pill'),pin=(t-P[0])/.4,pout=(P[1]-t)/.2, po=t>=P[0]&&t<P[1]?cl(Math.min(pin*2,pout)):0; pl.style.opacity=r(po);
    pl.style.transform=`translateY(${r(60*(1-ease(pin)))}px) scale(${r(.9+.1*back(pin))})`;
    const fs=cl(back((t-P[0]-.45)/.3),0,2); $('free').style.transform=`scale(${r(fs)}) rotate(-4deg)`; K.push(r(po),pl.style.transform,r(fs)); }
  if(S!==null){ const sh=$('share'),sp=(t-S)/.45, so=t>=S?cl(sp*2):0; sh.style.opacity=r(so);
    sh.style.transform=`translateX(${r(-700*(1-ease(sp)))}px) rotate(${r(-6*(1-ease(sp)))}deg)`;
    const pp=(t-S-.35)/.5, wig=t>S+.85?Math.sin((t-S)*9)*4:0;
    $('plane').style.transform=`scale(${r(cl(back(pp),0,2))}) rotate(${r(wig-20*(1-ease(pp)))}deg)`; K.push(r(so),sh.style.transform,$('plane').style.transform); }
  return K.join('|');
}
</script>"""

def page(caps):
    js = (JS.replace("__CAPS__", json.dumps(caps)).replace("__T__", json.dumps(CFG["title_t"]))
          .replace("__P__", json.dumps(CFG["cta"]["t"] if CFG["cta"] else None)).replace("__S__", json.dumps(CFG["share"]["t"] if CFG["share"] else None))
          .replace("__ITEMS__", json.dumps([dict(id=i, a=a, b=b, k=k) for i, h, x, y, a, b, k in ITEMS])))
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body()}{js}</body></html>"

def open_page(p, caps):
    pf = OUT/"overlay.html"; pf.write_text(page(caps))
    br = p.chromium.launch(executable_path=CFG["chrome"], args=["--allow-file-access-from-files"])
    pg = br.new_page(viewport={"width": 1080, "height": 1920}, device_scale_factor=W / 1080)
    pg.goto(pf.as_uri()); pg.wait_for_load_state("networkidle"); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(300)
    return br, pg

def ff(*a): subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, a)], check=True)

def frames(caps):
    """Overlay PNGs at the cut's resolution. Frames whose DOM state is unchanged are hard-linked, not re-shot.
    Cached: existing frames are kept. After a visual change delete the folder, or only the affected frames (frame = seconds * fps)."""
    fr = OUT/f"frames_{W}x{H}"; n = round(DUR * FPS)
    if fr.exists() and len(list(fr.glob("*.png"))) == n: return fr
    fr.mkdir(parents=True, exist_ok=True); prev = None; shot = 0
    with sync_playwright() as p:
        br, pg = open_page(p, caps)
        for i in range(n):
            key = pg.evaluate(f"render({i / FPS})"); f = fr/f"{i:05d}.png"
            if f.exists(): prev = None; continue
            if key == prev: os.link(fr/f"{i-1:05d}.png", f)
            else: pg.screenshot(path=f, omit_background=True); shot += 1
            prev = key
        br.close()
    print(f"frames {n}, screenshots {shot}, {W}x{H}")
    return fr

def sfx_wav():
    out = OUT/f"{CFG['name']}_sfx.wav"
    ins = sum([["-i", f] for f, _, _, _ in SFX], [])
    mix = "".join(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo,{f'atrim=0:{d},afade=t=out:st={d-.15:.2f}:d=0.15,' if d else ''}volume={v},adelay={int(t*1000)}:all=1[a{k}];"
                  for k, (_, t, v, d) in enumerate(SFX)) + "".join(f"[a{k}]" for k in range(len(SFX))) + f"amix=inputs={len(SFX)}:normalize=0,apad=whole_dur={DUR}[m]"
    ff(*ins, "-filter_complex", mix, "-map", "[m]", "-t", DUR, "-c:a", "pcm_s16le", out)
    return out

def gamut_lut():
    """sRGB graphics -> BT.2020 primaries, same sRGB curve. Without it, sRGB colours read as BT.2020 look over-saturated
    on HDR footage (yellow turns orange). Brightness stays as-is: a 75% HLG white mapping made overlays look dark."""
    f = OUT/"gamut_709_to_2020.cube"
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

def verify(f):
    errs = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-f", "null", "-"], capture_output=True, text=True).stderr.strip()
    n = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(f)],
                           capture_output=True, text=True).stdout)
    src = round(DUR * FPS)
    print(f"{f.name}: decode errors {len(errs.splitlines()) if errs else 0}, frames {n} (cut ~{src})")
    if errs: sys.exit("decode errors, do not deliver")

def main(argv):
    OUT.mkdir(parents=True, exist_ok=True); caps = captions(); name = CFG["name"]
    (OUT/"captions.json").write_text(json.dumps(caps, indent=1))
    if "--dry" in argv:
        for c in caps: print(f"{c['s']:6.2f}-{c['e']:6.2f}  " + " ".join(f"*{w['t']}*" if w["em"] else w["t"] for w in c["w"]))
        return
    if "--still" in argv:
        ts = [float(x) for x in argv[argv.index("--still") + 1:]]
        with sync_playwright() as p:
            br, pg = open_page(p, caps)
            for t in ts: pg.evaluate(f"render({t})"); pg.screenshot(path=OUT/f"ov_{t}.png", omit_background=True)
            br.close()
        for t in ts:
            ff("-ss", t, "-i", CUT, "-i", OUT/f"ov_{t}.png", "-filter_complex", "[0:v][1:v]overlay,scale=360:-2", "-frames:v", 1, OUT/f"st_{t}.png")
        ff(*sum([["-i", OUT/f"st_{t}.png"] for t in ts], []), "-filter_complex", (f"hstack=inputs={len(ts)}" if len(ts) > 1 else "null"), OUT/"stills.png")
        print("look at", OUT/"stills.png"); return
    fr = frames(caps); sfx = sfx_wav()
    if "--final" in argv:
        final = OUT/f"{name}_final.mp4"; vid = OUT/"_video_only.mp4"
        if HDR:   # match the HDR source: 10-bit HEVC with the same HLG/PQ tags, overlay mapped into BT.2020
            ov = f"[1:v]format=rgba64le,lut3d=file='{gamut_lut()}',scale=out_color_matrix=bt2020:out_range=tv,format=yuva444p10le[o];[0:v][o]overlay=0:0:format=yuv420p10:shortest=1[v]"
            enc = ["-c:v", "hevc_videotoolbox", "-b:v", "20M", "-pix_fmt", "p010le", "-profile:v", "main10", "-tag:v", "hvc1",
                   "-color_primaries", "bt2020", "-color_trc", V["color_transfer"], "-colorspace", "bt2020nc"]
        else:
            ov = "[0:v][1:v]overlay=0:0:shortest=1[v]"
            enc = ["-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p"]
        # video first, audio in a second pass: one videotoolbox pass with amix produced corrupt NAL units
        ff("-i", CUT, "-framerate", FPS, "-i", fr/"%05d.png", "-filter_complex", ov, "-map", "[v]", "-an", *enc, vid)
        ff("-i", vid, "-i", CUT, "-i", sfx, "-filter_complex", "[1:a]aresample=48000[ca];[ca][2:a]amix=inputs=2:normalize=0:duration=first[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", final)
        vid.unlink(); verify(final); return
    mov = OUT/f"{name}_overlay.mov"
    ff("-framerate", FPS, "-i", fr/"%05d.png", "-i", sfx, "-map", "0:v", "-map", "1:a", "-c:v", "prores_ks", "-profile:v", "4444",
       "-pix_fmt", "yuva444p10le", "-c:a", "pcm_s16le", mov)
    ff("-i", CUT, "-i", mov, "-filter_complex", "[1:v]scale=1080:-2[o];[0:v]scale=1080:-2[b];[b][o]overlay=0:0[v];[0:a][1:a]amix=inputs=2:normalize=0[a]",
       "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "26", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
       OUT/f"{name}_preview.mp4")
    print("done:", mov, OUT/f"{name}_preview.mp4")

if __name__ == "__main__":
    main(sys.argv[1:])
