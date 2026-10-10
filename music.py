"""Procedural background music for reels: a loopable bed composed from a mood, rendered to WAV with numpy.

  python3 music.py upbeat 50 out.wav [seed]

Moods (tempo, feel): upbeat (driving pop/trap-ish, bright chords), tech (clean electronic pulse, arps), lofi (slow swung beat, warm
chords, vinyl hiss), cinematic (no drums: pads, sub pulse, swelling strings), dramatic (dark minor, pulsing bass, sparse hits).
Every bed is deterministic for a (mood, seed) pair, mixed to -16 LUFS-ish before the reel mixer pulls it under the voice.
It is a bed, not a song: nothing in it fights a voice (no vocals, no lead above 2 kHz, rhythm steady), which is what a reel needs.
Real tracks (Pixabay, Uppbeat, Epidemic) still beat it: drop them in ~/reel-music/<mood>/ and the renderer prefers them."""
import math, struct, sys, wave
import numpy as np

SR = 48000
MOODS = {
    "upbeat":    dict(bpm=104, prog=[[0, 4, 7], [-4, 0, 3], [-7, -3, 0], [-5, -1, 2]], root=57, drums="pop", pad=.55, arp=.35, bass=.9, bright=1.0, swing=0),
    "tech":      dict(bpm=112, prog=[[0, 3, 7], [-2, 2, 5], [-4, 0, 3], [-2, 2, 5]], root=55, drums="tech", pad=.4, arp=.6, bass=.8, bright=1.1, swing=0),
    "lofi":      dict(bpm=78,  prog=[[0, 3, 7, 10], [-2, 2, 5, 8], [-4, 0, 3, 7], [-7, -3, 0, 3]], root=53, drums="lofi", pad=.7, arp=.15, bass=.7, bright=.6, swing=.12),
    "cinematic": dict(bpm=72,  prog=[[0, 3, 7], [-4, 0, 3], [-5, -1, 2], [-2, 2, 5]], root=50, drums="none", pad=1.0, arp=.2, bass=.6, bright=.8, swing=0),
    "dramatic":  dict(bpm=92,  prog=[[0, 3, 7], [-1, 3, 6], [-4, 0, 3], [-3, 0, 4]], root=48, drums="sparse", pad=.8, arp=.25, bass=1.0, bright=.7, swing=0),
}

def midi(n): return 440.0 * 2 ** ((n - 69) / 12)

def env(n, a, d, s_level, r, total):
    """ADSR over `total` samples."""
    e = np.zeros(total); a, d, r = int(a * SR), int(d * SR), int(r * SR)
    if a + d + r > total:   # short note: squeeze the envelope proportionally
        k = total / (a + d + r); a, d, r = int(a * k), int(d * k), max(0, total - int(a * k) - int(d * k))
    sus = max(0, total - a - d - r)
    e[:a] = np.linspace(0, 1, a, endpoint=False)
    e[a:a + d] = np.linspace(1, s_level, d, endpoint=False)
    e[a + d:a + d + sus] = s_level
    e[a + d + sus:a + d + sus + r] = np.linspace(s_level, 0, min(r, total - a - d - sus), endpoint=False)
    return e[:total]

def tone(freq, n, detune=(0, .003, -.003), shape="saw", lp=1.0):
    t = np.arange(n) / SR; out = np.zeros(n)
    for d in detune:
        f = freq * (1 + d)
        if shape == "saw": out += sum(np.sin(2 * math.pi * f * k * t) / k for k in range(1, 7)) * (1 / 1.6)
        elif shape == "tri": out += sum(((-1) ** ((k - 1) // 2)) * np.sin(2 * math.pi * f * k * t) / k ** 2 for k in range(1, 8, 2))
        else: out += np.sin(2 * math.pi * f * t)
    return out / len(detune)

def onepole_lp(x, cutoff):
    a = math.exp(-2 * math.pi * cutoff / SR); y = np.zeros_like(x); acc = 0.0
    for i in range(len(x)):   # small arrays only; vectorised below for the long buffers
        acc = a * acc + (1 - a) * x[i]; y[i] = acc
    return y

def lowpass(x, cutoff):
    """Fast one-pole low-pass via scipy-free recursion using lfilter-like cumulative trick."""
    a = math.exp(-2 * math.pi * cutoff / SR)
    y = np.empty_like(x); y[0] = x[0] * (1 - a)
    # recursive filter: implement with a loop in chunks for speed (numpy has no lfilter); 50 s at 48 kHz is 2.4 M samples: use iterative numba-free approach
    coef = (1 - a)
    # Use the closed form through an IIR implemented in float64 with Python loop over chunks of 2048 using np.frompyfunc? Simpler: use scipy if present.
    try:
        from scipy.signal import lfilter
        return lfilter([coef], [1, -a], x)
    except Exception:
        acc = 0.0
        for i in range(len(x)):
            acc = a * acc + coef * x[i]; y[i] = acc
        return y

def kick(n, punch=1.0):
    t = np.arange(n) / SR
    f = 48 + 170 * np.exp(-t * 28); return np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-t * 7) * punch

def snare(n, rng, tone_mix=.4):
    t = np.arange(n) / SR; noise = rng.standard_normal(n) * np.exp(-t * 22)
    body = np.sin(2 * math.pi * 190 * t) * np.exp(-t * 30) * tone_mix
    return (noise * .8 + body)

def hat(n, rng, open_=False):
    t = np.arange(n) / SR; x = rng.standard_normal(n) * np.exp(-t * (14 if open_ else 70))
    return x - np.roll(x, 1)   # crude high-pass

def compose(mood, duration, seed=1):
    M = MOODS.get(mood, MOODS["upbeat"]); rng = np.random.default_rng(seed)
    bpm = M["bpm"]; beat = 60 / bpm; bar = beat * 4; n = int(duration * SR) + SR
    t = np.arange(n) / SR; out = np.zeros(n)
    nbars = int(math.ceil(duration / bar)) + 1
    # ---- pads: one chord per bar, slow attack, detuned saws, low-passed
    pad_cut = 900 * M["bright"]
    for b in range(nbars):
        chord = M["prog"][b % len(M["prog"])]; s0 = int(b * bar * SR); ln = int(bar * SR * 1.05)
        if s0 >= n: break
        ln = min(ln, n - s0); seg = np.zeros(ln)
        for iv in chord: seg += tone(midi(M["root"] + iv), ln, shape="saw") * .33
        seg *= env(ln, .35, .4, .8, .6, ln); out[s0:s0 + ln] += seg * M["pad"] * .22
    out = lowpass(out, pad_cut)
    # ---- bass: root per bar, octave below, with eighth-note pulse (sidechain-like dip on kicks later)
    bass = np.zeros(n)
    for b in range(nbars):
        chord = M["prog"][b % len(M["prog"])]; f = midi(M["root"] + chord[0] - 24)
        for e in range(8):
            s0 = int((b * bar + e * beat / 2) * SR); ln = int(beat / 2 * SR * .95)
            if s0 >= n: break
            ln = min(ln, n - s0); tt = np.arange(ln) / SR
            bass[s0:s0 + ln] += (np.sin(2 * math.pi * f * tt) + .3 * np.sin(2 * math.pi * 2 * f * tt)) * env(ln, .005, .1, .7, .08, ln)
    out += bass * .28 * M["bass"]
    # ---- arp: 16ths over the chord, soft tri, low-passed, quiet
    if M["arp"] > 0:
        arp = np.zeros(n)
        for b in range(nbars):
            chord = M["prog"][b % len(M["prog"])]; notes = [M["root"] + iv + 12 for iv in chord] + [M["root"] + chord[0] + 24]
            for k in range(16):
                if rng.random() < .25: continue
                s0 = int((b * bar + k * beat / 4) * SR); ln = int(beat / 4 * SR * 1.6)
                if s0 >= n: break
                ln = min(ln, n - s0); arp[s0:s0 + ln] += tone(midi(notes[k % len(notes)]), ln, detune=(0,), shape="tri") * env(ln, .004, .12, .3, .1, ln)
        out += lowpass(arp, 1800 * M["bright"]) * .16 * M["arp"]
    # ---- drums
    D = M["drums"]
    if D != "none":
        drums = np.zeros(n); kl, sl, hl = int(.35 * SR), int(.25 * SR), int(.12 * SR)
        for b in range(nbars):
            for k in range(16):
                pos = b * bar + k * beat / 4 + (M["swing"] * beat / 4 if k % 2 else 0); s0 = int(pos * SR)
                if s0 >= n: break
                kick_on = {"pop": k in (0, 8) or (k == 11 and b % 2), "tech": k in (0, 4, 8, 12), "lofi": k in (0, 7, 8), "sparse": k in (0,) or (k == 10 and b % 4 == 3)}[D]
                snare_on = {"pop": k in (4, 12), "tech": k in (4, 12), "lofi": k in (4, 12), "sparse": k == 8 and b % 2}[D]
                hat_on = {"pop": k % 2 == 0, "tech": True, "lofi": k % 2 == 0, "sparse": k % 4 == 0}[D]
                if kick_on: ln = min(kl, n - s0); drums[s0:s0 + ln] += kick(ln) * .9
                if snare_on: ln = min(sl, n - s0); drums[s0:s0 + ln] += snare(ln, rng) * (.35 if D == "lofi" else .45)
                if hat_on: ln = min(hl, n - s0); drums[s0:s0 + ln] += hat(ln, rng, open_=(k == 14 and D == "tech")) * (.09 if D == "lofi" else .13)
        out += drums
        # sidechain pump: dip everything briefly on each kick for groove
        pump = np.ones(n)
        for b in range(nbars):
            for k in range(16):
                kick_on = {"pop": k in (0, 8), "tech": k in (0, 4, 8, 12), "lofi": k in (0, 8), "sparse": k == 0}[D]
                if not kick_on: continue
                s0 = int((b * bar + k * beat / 4) * SR); ln = min(int(.22 * SR), n - s0)
                if s0 >= n: break
                pump[s0:s0 + ln] *= 1 - .45 * np.exp(-np.arange(ln) / SR * 12)
        out *= pump
    if D == "lofi": out += rng.standard_normal(n) * .006   # vinyl hiss
    if D == "none":  # cinematic: slow sub pulse and a swelling high string
        out += np.sin(2 * math.pi * midi(M["root"] - 24) * t) * (.5 + .5 * np.sin(2 * math.pi * t / bar)) * .12
    out = out[:int(duration * SR)]
    # fades + soft clip + level
    f = int(1.2 * SR); out[:f] *= np.linspace(0, 1, f); out[-int(2 * SR):] *= np.linspace(1, 0, int(2 * SR))
    out = np.tanh(out * 1.6) / 1.6
    out *= 0.5 / max(1e-6, np.max(np.abs(out)))
    return out

def write_wav(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())

if __name__ == "__main__":
    mood, dur, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]; seed = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    write_wav(out, compose(mood, dur, seed)); print("wrote", out)
