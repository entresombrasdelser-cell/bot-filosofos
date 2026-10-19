"""Pista de rock melódico original (sintetizada, sin copyright) de 30 s, en estéreo.

Estilo: hard rock alternativo oscuro y melódico, afinación grave (re menor), 112 bpm.
Estructura (14 compases = 30 s):
    0-1   intro      arpegio limpio
    2-5   estrofa    Dm Dm Bb C   (riff con palm-mute / arpegios según tema)
    6-9   estribillo Bb F C Dm    (power chords + gancho de guitarra lead)
    10-13 estribillo 2            (lead armonizado, crash, cierre sobre Dm)

Sonido: cuerdas Karplus-Strong -> amplificador (saturación) -> altavoz (filtros), doble pista
panoramizada, batería con humanización, reverb por convolución.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
BPM = 112
BEAT = 60.0 / BPM
BARS = 14
BAR = 4 * BEAT


def midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


# ------------------------------------------------------------------ utilidades

def _t(n: float) -> np.ndarray:
    return np.arange(int(n * SR)) / SR


def _add(buf: np.ndarray, start: float, sig: np.ndarray, gain: float = 1.0) -> None:
    i = int(max(start, 0) * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def _filter(x: np.ndarray, lo: float | None = None, hi: float | None = None, order: int = 4) -> np.ndarray:
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    g = np.ones_like(f)
    if lo:
        g *= 1 / (1 + (lo / np.maximum(f, 1e-3)) ** order)
    if hi:
        g *= 1 / (1 + (f / hi) ** order)
    return np.fft.irfft(X * g, len(x))


def _reverb(x: np.ndarray, rng, secs: float = 1.4, wet: float = 0.25) -> np.ndarray:
    n = int(secs * SR)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / SR / (secs / 5))
    ir[: int(0.01 * SR)] *= np.linspace(0, 1, int(0.01 * SR))
    ir = _filter(ir, 200, 6000)
    ir /= np.sqrt((ir ** 2).sum())
    size = 1 << int(np.ceil(np.log2(len(x) + n)))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
    return x * (1 - wet) + y * wet * 2.2


def _delay(x: np.ndarray, secs: float, fb: float, taps: int = 4) -> np.ndarray:
    out = x.copy()
    for k in range(1, taps + 1):
        d = int(secs * SR * k)
        out[d:] += x[:-d] * (fb ** k)
    return out


# ------------------------------------------------------------------ guitarra

def _ks(freq: float, dur: float, decay: float, rng, bright: float = 0.5) -> np.ndarray:
    """Cuerda pulsada (Karplus-Strong vectorizado por periodos)."""
    P = max(int(round(SR / freq)), 2)
    n = int(dur * SR)
    out = np.zeros(n + P + 2)
    noise = rng.uniform(-1, 1, P)
    k = max(int(P * (1 - bright) * 0.25), 1)  # pulsación más/menos brillante
    noise = np.convolve(np.r_[noise, noise[:k]], np.ones(k) / k, mode="valid")[:P]
    out[1:P + 1] = noise
    i = P + 1
    while i < n + 1:
        m = min(P, len(out) - i)
        out[i:i + m] = decay * 0.5 * (out[i - P:i - P + m] + out[i - P - 1:i - P - 1 + m])
        i += P
    return out[1:n + 1]


def _amp(x: np.ndarray, gain: float, lo=85, hi=4800) -> np.ndarray:
    x = _filter(x, 120, None, 2)  # evita que los graves ahoguen la saturación
    y = np.tanh(x * gain)
    y = np.tanh(y * 2.2) * 0.7  # segunda etapa
    return _filter(y, lo, hi)


def _chord(root_midi: float, dur: float, decay: float, rng, shift: float = 0.0, gain: float = 14.0,
           bright: float = 0.5, mute: bool = False) -> np.ndarray:
    freqs = [midi(root_midi + shift), midi(root_midi + 7 + shift), midi(root_midi + 12 + shift)]
    sig = sum(_ks(f, dur, decay, rng, bright) * a for f, a in zip(freqs, (1.0, 0.9, 0.7)))
    if mute:
        sig = _filter(sig, None, 1800, 2)
    return _amp(sig / 2.6, gain)


def _clean(f: float, dur: float, rng) -> np.ndarray:
    return _ks(f, dur, 0.9993, rng, 0.35) * 0.9


def _lead(f: float, dur: float, vib_delay: float = 0.28, bend: bool = True) -> np.ndarray:
    t = _t(dur)
    vib = np.where(t > vib_delay, np.sin(2 * np.pi * 5.4 * (t - vib_delay)) * 0.0075 * np.minimum((t - vib_delay) * 3, 1), 0)
    scoop = (-0.035 * np.exp(-t * 28)) if bend else 0
    ph = np.cumsum(f * (1 + vib + scoop)) / SR
    sig = np.sin(2 * np.pi * ph) * 0.55 + (2 * (ph % 1) - 1) * 0.35 + np.sin(4 * np.pi * ph) * 0.2
    sig = np.tanh(sig * 4.5) * 0.8
    env = np.minimum(t / 0.012, 1) * (0.7 + 0.3 * np.exp(-t * 2.2)) * np.minimum((dur - t) / 0.09, 1)
    return _filter(sig * env, 300, 6800)


def _bass(f: float, dur: float) -> np.ndarray:
    t = _t(dur)
    ph = (t * f) % 1
    sig = (2 * ph - 1) * 0.6 + np.sin(2 * np.pi * f * t) * 0.8
    sig = np.tanh(sig * 2.4)
    env = np.minimum(t / 0.004, 1) * (0.35 + 0.65 * np.exp(-t * 5)) * np.minimum((dur - t) / 0.03, 1)
    return _filter(sig * env, 35, 900)


# ------------------------------------------------------------------ batería

def _kick(rng, vel=1.0) -> np.ndarray:
    t = _t(0.38)
    f = 48 + 110 * np.exp(-t * 32)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
    click = rng.standard_normal(len(t)) * np.exp(-t * 400) * 0.35
    return (body * 1.15 + _filter(click, 2000, 9000)) * vel


def _snare(rng, vel=1.0) -> np.ndarray:
    t = _t(0.34)
    noise = _filter(rng.standard_normal(len(t)), 900, 9000) * np.exp(-t * 17)
    tone = (np.sin(2 * np.pi * 185 * t) + 0.5 * np.sin(2 * np.pi * 330 * t)) * np.exp(-t * 26)
    return (noise * 0.95 + tone * 0.55) * vel


def _hat(rng, vel=1.0, open_=False) -> np.ndarray:
    d = 0.32 if open_ else 0.07
    t = _t(d)
    n = np.diff(rng.standard_normal(len(t) + 1))
    return _filter(n, 6000, None) * np.exp(-t * (14 if open_ else 65)) * 0.5 * vel


def _tom(f0: float, rng, vel=1.0) -> np.ndarray:
    t = _t(0.5)
    f = f0 * (1 + 0.5 * np.exp(-t * 18))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7) * vel


def _crash(rng) -> np.ndarray:
    t = _t(2.2)
    n = _filter(rng.standard_normal(len(t)), 3500, 14000) * np.exp(-t * 2.1)
    return n * 0.7


# ------------------------------------------------------------------ composición

# estribillo: Bb F C Dm  (nota MIDI, longitud en tiempos, inicio dentro del compás)
HOOK = [
    [(0, 74, 1.5), (1.5, 74, 0.5), (2, 72, 1), (3, 70, 1)],      # Bb:  D5 D5 C5 Bb4
    [(0, 69, 1.5), (1.5, 69, 0.5), (2, 72, 1), (3, 69, 1)],      # F:   A4 A4 C5 A4
    [(0, 72, 1.5), (1.5, 72, 0.5), (2, 74, 1), (3, 76, 1)],      # C:   C5 C5 D5 E5
    [(0, 77, 2.5), (2.5, 76, 0.5), (3, 74, 0.5), (3.5, 72, 0.5)],  # Dm: F5 ... E5 D5 C5
]
# estrofa (riff de lead suave): Dm Dm Bb C
VERSE_LEAD = [
    [(0, 69, 1), (1, 69, 0.5), (1.5, 72, 0.5), (2, 74, 2)],
    [(0, 72, 1), (1, 70, 0.5), (1.5, 69, 0.5), (2, 67, 2)],
    [(0, 70, 1), (1, 70, 0.5), (1.5, 74, 0.5), (2, 72, 2)],
    [(0, 72, 1), (1, 76, 1), (2, 74, 1), (3, 72, 1)],
]
VERSE_ROOTS = [50, 50, 46, 48]    # D3 D3 Bb2 C3 (MIDI)
CHORUS_ROOTS = [46, 53, 48, 50]   # Bb2 F3 C3 D3


def make_track(theme: str, seed: int = 0, out_path: Path | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed + 11)
    n = int(BARS * BAR * SR)
    heavy = theme != "espiritual"
    L = np.zeros(n); R = np.zeros(n)         # guitarras (doble pista)
    bass = np.zeros(n); drums = np.zeros(n); snr = np.zeros(n); lead = np.zeros(n)
    eighth = BEAT / 2

    def human(sec=0.006):
        return float(rng.normal(0, sec))

    for b in range(BARS):
        t0 = b * BAR
        section = "intro" if b < 2 else "verse" if b < 6 else "chorus" if b < 10 else "chorus2"
        if section in ("intro", "verse"):
            root = 50 if section == "intro" else VERSE_ROOTS[(b - 2) % 4]
        else:
            root = CHORUS_ROOTS[(b - 6) % 4]
        play_heavy = (section != "intro") and (heavy or section in ("chorus", "chorus2"))

        # ---- guitarra rítmica (doble pista: L y R con tomas distintas)
        if not play_heavy:
            arp = [0, 7, 12, 15, 19, 15, 12, 7]
            for k, st in enumerate(arp):
                f = midi(root + 12 + st)
                _add(L, t0 + k * eighth + human(0.004), _clean(f, 1.8, rng), 0.55)
                _add(R, t0 + k * eighth + human(0.004), _clean(f * 1.0008, 1.8, rng), 0.55)
        elif section == "verse":
            pat = [1, 1, 0, 1, 1, 0, 1, 1] if b % 2 == 0 else [1, 1, 0, 1, 0, 1, 1, 0]
            for k, on in enumerate(pat):
                if on:
                    for track in (L, R):
                        _add(track, t0 + k * eighth + human(), _chord(root, 0.2, 0.972, rng, mute=True, gain=16), 0.9)
        else:  # estribillo: acordes abiertos con strum de corcheas en los tiempos fuertes
            hits = [(0, 1.5), (1.5, 0.5), (2, 1.0), (3, 1.0)]
            for (pos, ln) in hits:
                for track in (L, R):
                    _add(track, t0 + pos * BEAT + human(0.004),
                         _chord(root, ln * BEAT + 0.35, 0.9992, rng, gain=11, bright=0.6), 0.85)

        # ---- bajo
        if play_heavy:
            f = midi(root - 12)
            for k in range(8):
                _add(bass, t0 + k * eighth + human(0.003), _bass(f, eighth * 0.92), 0.95 if k % 2 == 0 else 0.7)
        else:
            _add(bass, t0, _bass(midi(root - 12), BAR), 0.55)

        # ---- batería
        verse_like = section == "verse"
        if section == "intro":
            if b == 1:
                for tp in (2.0, 3.0, 3.5):
                    _add(drums, t0 + tp * BEAT, _tom(150 - 25 * (tp - 2), rng, 0.55))
        elif not heavy and verse_like and b < 4:
            _add(drums, t0, _kick(rng, 0.6))
            _add(drums, t0 + 2 * BEAT, _kick(rng, 0.5))
        else:
            ks = [0, 1.5, 2, 2.5] if verse_like else [0, 1.5, 2, 2.5]
            for kp in ks:
                _add(drums, t0 + kp * BEAT + human(0.004), _kick(rng, rng.uniform(0.85, 1.0)))
            for sp in (1, 3):
                _add(snr, t0 + sp * BEAT + human(0.004), _snare(rng, rng.uniform(0.85, 1.0)))
            for k in range(8):
                open_ = (not verse_like) and k == 7
                _add(drums, t0 + k * eighth + human(0.003), _hat(rng, (1.0 if k % 2 == 0 else 0.65) * rng.uniform(0.85, 1.0), open_))
            if b in (5, 9, 13) and b != 13:  # redoble antes del estribillo
                for tp, f0 in ((3.0, 190), (3.25, 160), (3.5, 130), (3.75, 105)):
                    _add(drums, t0 + tp * BEAT, _tom(f0, rng, 0.9))
        if b in (6, 10, 13):
            _add(drums, t0, _crash(rng), 0.9)

        # ---- lead
        if section == "verse" and b >= 4:
            for (pos, m, ln) in VERSE_LEAD[b - 2]:
                _add(lead, t0 + pos * BEAT, _lead(midi(m), ln * BEAT * 0.97), 0.35)
        if section in ("chorus", "chorus2"):
            phrase = HOOK[(b - 6) % 4]
            for (pos, m, ln) in phrase:
                _add(lead, t0 + pos * BEAT, _lead(midi(m), ln * BEAT * 0.98), 0.62)
                if section == "chorus2":  # armonía una tercera por debajo
                    _add(lead, t0 + pos * BEAT, _lead(midi(m - 3), ln * BEAT * 0.98), 0.32)
        if b == 13:  # nota final larga
            _add(lead, t0 + 2 * BEAT, _lead(midi(74), 2 * BEAT + 0.8), 0.5)

    # ---- mezcla
    gL = _filter(L, 90, 6500); gR = _filter(R, 90, 6500)
    if not heavy:
        gL = _delay(gL, 0.30, 0.35, 3); gR = _delay(gR, 0.38, 0.35, 3)
    lead = _delay(lead, BEAT * 0.75, 0.38, 4)
    lead_r = _reverb(lead, rng, 1.6, 0.3)
    snr_r = _reverb(snr, rng, 1.1, 0.28)
    dr = drums + snr_r
    bass = _filter(bass, 35, 700)

    left = gL * 0.95 + bass * 0.9 + dr * 0.9 + lead_r * 0.85
    right = gR * 0.95 + bass * 0.9 + dr * 0.9 + lead_r * 0.85
    mix = np.stack([left, right], axis=1)

    # master: compresión suave + fundidos + normalización
    mix = np.tanh(mix * 1.15) / 1.0
    fi, fo = int(1.5 * SR), int(2.5 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
    mix = mix / np.max(np.abs(mix)) * 0.8

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((mix * 32767).astype(np.int16).tobytes())
    return mix
