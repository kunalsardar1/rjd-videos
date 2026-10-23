"""Sound for the job videos.

  python3 audio.py split VOICE.wav N             -> prints JSON: N speech segments [{"s":..,"e":..}] found at the pauses
  python3 audio.py mix PLAN.json OUT.wav         -> slow lo-fi music + sound effects + the voice (music dips under the voice)

PLAN.json: {"end": seconds, "sfx": [{"t","type","g"}], "voice": "voice.wav" or null,
            "pieces": [{"from": s, "to": e, "at": t}, ...]}   (voice pieces placed at their scene times)
All sounds are made here, so there is nothing to license.
"""
import json, sys
import numpy as np
from scipy.signal import butter, sosfilt, resample_poly
from scipy.io import wavfile

SR = 44100
rng = np.random.default_rng(11)


def bq(x, kind, f, o=2):
    return sosfilt(butter(o, f, btype=kind, fs=SR, output='sos'), x)


def env(n, a, d):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(a, 1e-4)) * np.exp(-np.maximum(0, t - a) / d)


def read_voice(path):
    sr, x = wavfile.read(path)
    x = x.astype(np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x /= 32768.0 if np.abs(x).max() > 1.5 else 1.0
    if sr != SR:
        from math import gcd
        g = gcd(sr, SR)
        x = resample_poly(x, SR // g, sr // g)
    return x


def split(path, n):
    x = read_voice(path)
    hop = int(0.02 * SR)
    rms = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2)) for i in range(0, len(x) - hop, hop)])
    if not len(rms):
        return []
    thr = max(1e-4, 0.08 * np.percentile(rms, 95))
    loud = rms > thr
    idx = np.where(loud)[0]
    if not len(idx):
        return []
    first, last = idx[0], idx[-1]
    runs, i = [], first
    while i <= last:
        if not loud[i]:
            j = i
            while j <= last and not loud[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    runs = [r for r in runs if (r[1] - r[0]) * 0.02 >= 0.12]
    runs = sorted(sorted(runs, key=lambda r: r[1] - r[0], reverse=True)[:max(0, n - 1)])
    cuts = [first] + [x for r in runs for x in r] + [last + 1]
    segs = [{"s": round(cuts[k] * 0.02, 3), "e": round(cuts[k + 1] * 0.02, 3)} for k in range(0, len(cuts), 2)]
    return segs


# ---------------- music: slow lo-fi, 72 bpm ----------------
def midi(n):
    return 440 * 2 ** ((n - 69) / 12)


def epiano(freq, dur, vel=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * 2 * freq * t) * np.exp(-t * 3) + 0.12 * np.sin(2 * np.pi * 3 * freq * t) * np.exp(-t * 6)
    return s * (1 + 0.12 * np.sin(2 * np.pi * 4.5 * t)) * env(n, 0.006, 0.9) * vel


def kick():
    n = int(0.4 * SR)
    t = np.arange(n) / SR
    f = 45 + 70 * np.exp(-t * 25)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.003, 0.12)


def snare():
    n = int(0.25 * SR)
    return bq(rng.standard_normal(n), 'band', [700, 4000]) * env(n, 0.004, 0.07) * 0.8 + np.sin(2 * np.pi * 190 * np.arange(n) / SR) * env(n, 0.002, 0.04) * 0.5


def hat():
    n = int(0.05 * SR)
    return bq(rng.standard_normal(n), 'high', 7500) * env(n, 0.001, 0.012)


class Bus:
    def __init__(self, L):
        self.x = np.zeros((L, 2))
        self.L = L

    def add(self, sig, t, g=1.0, pan=0.0):
        i = int(t * SR)
        if i < 0 or i >= self.L:
            return
        sig = sig[:self.L - i]
        l = np.cos((pan + 1) * np.pi / 4) * 1.414
        r = np.sin((pan + 1) * np.pi / 4) * 1.414
        self.x[i:i + len(sig), 0] += sig * g * l
        self.x[i:i + len(sig), 1] += sig * g * r


def music(L, end):
    m = Bus(L)
    beat = 60 / 72
    bar = 4 * beat
    CH = [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59]]
    ROOT = [41, 40, 38, 36]
    t, b = 0.0, 0
    while t < end:
        ci = b % 4
        for k, nn in enumerate(CH[ci]):
            m.add(epiano(midi(nn), bar * 1.05, 0.22), t + k * 0.012, 0.6, (k - 1.5) * 0.25)
            m.add(epiano(midi(nn + 12), beat * 1.6, 0.08), t + 2 * beat + 0.02 + k * 0.01, 0.5, (k - 1.5) * 0.3)
        n = int(bar * SR)
        tt = np.arange(n) / SR
        m.add(np.sin(2 * np.pi * midi(ROOT[ci]) * tt) * np.minimum(1, tt / 0.03) * np.exp(-tt / 1.6), t, 0.35)
        for q in range(4):
            bt = t + q * beat
            if q in (0, 2):
                m.add(kick(), bt, 0.5)
            if q in (1, 3):
                m.add(snare(), bt + 0.015, 0.14)
            m.add(hat(), bt, 0.05, 0.3)
            m.add(hat(), bt + beat * 0.62, 0.035, -0.3)
        t += bar
        b += 1
    crack = np.zeros(L)
    for i in rng.integers(0, L, int(end * 9)):
        crack[i] = rng.uniform(-1, 1)
    crack = bq(crack, 'band', [1000, 6000]) * 0.9 + bq(rng.standard_normal(L), 'band', [300, 2500]) * 0.012
    m.x[:, 0] += crack * 0.25
    m.x[:, 1] += np.roll(crack, 37) * 0.25
    m.x = bq(m.x.T, 'low', 5200).T
    fi = int(0.6 * SR)
    m.x[:fi] *= np.linspace(0, 1, fi)[:, None]
    return m.x


# ---------------- sound effects ----------------
def click():
    n = int(0.04 * SR)
    t = np.arange(n) / SR
    return (bq(rng.standard_normal(n), 'high', 3000) * 0.6 + np.sin(2 * np.pi * 2200 * t)) * env(n, 0.0005, 0.006)


def typ():
    n = int(0.035 * SR)
    t = np.arange(n) / SR
    return (bq(rng.standard_normal(n), 'band', [1500, 6000]) * 0.7 + np.sin(2 * np.pi * rng.uniform(900, 1400) * t) * 0.4) * env(n, 0.0006, 0.007)


def sweep(dur, f0, f1, width=0.45):
    n = int(dur * SR)
    x = rng.standard_normal(n)
    y = np.zeros(n)
    seg = 441
    for k in range(0, n, seg):
        fc = f0 * (f1 / f0) ** (k / n)
        y[k:k + seg] = bq(x[k:k + seg], 'band', [max(60, fc * (1 - width)), min(19000, fc * (1 + width))], 1)
    tt = np.arange(n) / SR
    return y * np.sin(np.pi * np.clip(tt / dur, 0, 1)) ** 1.4


def swoosh():
    s = sweep(0.7, 5000, 350)
    n = int(0.9 * SR)
    tt = np.arange(n) / SR
    boom = np.sin(2 * np.pi * np.cumsum(38 + 40 * np.exp(-tt * 6)) / SR) * env(n, 0.02, 0.35)
    out = np.zeros(n)
    out[:len(s)] += s * 0.8
    out[int(0.3 * SR):] += boom[:n - int(0.3 * SR)] * 0.9
    return out


def whoosh():
    return sweep(0.6, 300, 6000, 0.5)


def thud():
    n = int(0.6 * SR)
    tt = np.arange(n) / SR
    low = np.sin(2 * np.pi * np.cumsum(55 + 60 * np.exp(-tt * 30)) / SR) * env(n, 0.002, 0.12)
    clink = sum(a * np.sin(2 * np.pi * f * tt) for f, a in [(2093, 1), (3721, .6), (5123, .4), (6911, .25)]) * env(n, 0.001, 0.18) * 0.35
    return low + clink


def pop():
    n = int(0.12 * SR)
    tt = np.arange(n) / SR
    f = 420 * (1 + 1.2 * np.exp(-tt * 45))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.003, 0.03)


def ding():
    n = int(2.0 * SR)
    tt = np.arange(n) / SR
    return sum(a * np.sin(2 * np.pi * 880 * m * tt) for m, a in [(1, 1), (2, .45), (3.01, .2), (4.17, .1)]) * env(n, 0.003, 0.6)


SF = {'click': (click, 0.5), 'type': (typ, 0.28), 'swoosh': (swoosh, 0.7), 'whoosh': (whoosh, 0.55), 'thud': (thud, 0.75), 'pop': (pop, 0.45), 'ding': (ding, 0.3)}


def mix(plan_path, out_path):
    plan = json.load(open(plan_path))
    end = float(plan['end'])
    L = int(SR * (end + 0.05))
    fx = Bus(L)
    for e in plan['sfx']:
        if e['type'] not in SF:
            continue
        f, g = SF[e['type']]
        fx.add(f(), e['t'], g * e.get('g', 1), rng.uniform(-0.25, 0.25) if e['type'] in ('type', 'click') else 0.0)
    mus = music(L, end)
    voice = np.zeros(L)
    if plan.get('voice'):
        v = read_voice(plan['voice'])
        v = v / (np.abs(v).max() + 1e-9) * 0.9
        for p in plan['pieces']:
            a, b, at = int(p['from'] * SR), int(p['to'] * SR), int(p['at'] * SR)
            seg = v[a:b]
            fade = min(len(seg) // 4, int(0.02 * SR))
            if fade > 0:
                seg = seg.copy()
                seg[:fade] *= np.linspace(0, 1, fade)
                seg[-fade:] *= np.linspace(1, 0, fade)
            seg = seg[:max(0, L - at)]
            voice[at:at + len(seg)] += seg
    # music dips under the voice
    hop = int(0.05 * SR)
    venv = np.array([np.abs(voice[i:i + hop]).max() if i < L else 0 for i in range(0, L, hop)])
    duck = np.repeat(np.where(venv > 0.02, 0.35, 1.0), hop)[:L]
    duck = np.convolve(duck, np.ones(int(0.15 * SR)) / int(0.15 * SR), mode='same')
    out = mus * 0.55 * duck[:, None] + fx.x * (0.8 if plan.get('voice') else 1.0) + voice[:, None] * 1.25
    fo = int(0.6 * SR)
    out[-fo:] *= np.linspace(1, 0, fo)[:, None]
    out = np.tanh(out * 1.1) / np.tanh(1.1)
    out = out / (np.abs(out).max() + 1e-9) * 0.9
    wavfile.write(out_path, SR, (out * 32767).astype(np.int16))


if __name__ == '__main__':
    if sys.argv[1] == 'split':
        print(json.dumps(split(sys.argv[2], int(sys.argv[3]))))
    elif sys.argv[1] == 'mix':
        mix(sys.argv[2], sys.argv[3])
