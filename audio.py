"""Sound for the job videos.

  python3 audio.py split VOICE.wav N [LINES.json] -> prints JSON: N speech segments [{"s":..,"e":..}], cut at the pauses
                                                     that fit where each line should end
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


PAUSE_W = 1.0   # how much a longer pause counts against being far from where the line should end


def speech_units(line):
    """Rough speaking length of a line: letters and Devanagari signs count 1, a digit about 2.5 (numbers are said in words)."""
    u = 0.0
    for ch in line:
        if ch.isdigit():
            u += 2.5
        elif ch.isalpha() or '\u0900' <= ch <= '\u097f':
            u += 1.0
    return max(u, 4.0)


def split(path, n, weights=None):
    """The voice cut into n pieces, one per line, at the pauses between the lines.

    Pauses inside a sentence (commas, breaths) can be as long as the pause between two lines, so the longest pauses
    alone are not enough. Each cut goes to the pause that is long AND close to where that line should end (from the
    length of the lines), chosen together so the cuts stay in order."""
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
    first, last = int(idx[0]), int(idx[-1]) + 1
    t0, t1 = first * 0.02, last * 0.02
    if n <= 1:
        return [{"s": round(t0, 3), "e": round(t1, 3)}]
    # pauses: runs of quiet frames inside the speech, at least 60 ms
    gaps, i = [], first
    while i < last:
        if not loud[i]:
            j = i
            while j < last and not loud[j]:
                j += 1
            if (j - i) >= 3:
                gaps.append((i * 0.02, j * 0.02))
            i = j
        else:
            i += 1
    w = [float(v) for v in (weights or [1.0] * n)][:n]
    w += [w[-1] if w else 1.0] * (n - len(w))
    tot = sum(w)
    cum = np.cumsum(w)[:-1] / tot
    # where each line should end: the point where that share of the speaking time (pauses left out) has been said
    spoken = np.cumsum(loud[first:last]) * 0.02
    want = [t0 + float(np.searchsorted(spoken, c * spoken[-1])) * 0.02 for c in cum]
    k = n - 1
    if len(gaps) >= k:
        # dynamic programming: cuts in order, each piece at least 0.35 s, cost = distance - PAUSE_W x pause length
        m = len(gaps)
        INF = 1e9
        cost = [[INF] * m for _ in range(k)]
        back = [[-1] * m for _ in range(k)]
        for j, (gs, ge) in enumerate(gaps):
            c = (gs + ge) / 2
            if gs - t0 >= 0.35:
                cost[0][j] = abs(c - want[0]) - PAUSE_W * (ge - gs)
        for q in range(1, k):
            for j, (gs, ge) in enumerate(gaps):
                c = (gs + ge) / 2
                here = abs(c - want[q]) - PAUSE_W * (ge - gs)
                best, bi = INF, -1
                for i2 in range(j):
                    if cost[q - 1][i2] < INF and gs - gaps[i2][1] >= 0.35 and cost[q - 1][i2] < best:
                        best, bi = cost[q - 1][i2], i2
                if bi >= 0:
                    cost[q][j], back[q][j] = best + here, bi
        ends = [j for j in range(m) if cost[k - 1][j] < INF and t1 - gaps[j][1] >= 0.35]
        if ends:
            j = min(ends, key=lambda e: cost[k - 1][e])
            chosen = []
            for q in range(k - 1, -1, -1):
                chosen.append(gaps[j])
                j = back[q][j]
            chosen.reverse()
            cuts = [t0] + [v for g in chosen for v in g] + [t1]
            return [{"s": round(cuts[a], 3), "e": round(cuts[a + 1], 3)} for a in range(0, len(cuts), 2)]
    # too few pauses: share the speech by the length of each line
    edges = [t0] + want + [t1]
    return [{"s": round(edges[a], 3), "e": round(edges[a + 1], 3)} for a in range(n)]


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
        lines = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
        print(json.dumps(split(sys.argv[2], int(sys.argv[3]), [speech_units(l) for l in lines] if lines else None)))
    elif sys.argv[1] == 'mix':
        mix(sys.argv[2], sys.argv[3])
