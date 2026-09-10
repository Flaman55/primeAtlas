"""Standalone live tone engine, ported from Structural Sieve ToneSynth.js.

Integration contract: on each advancing animation tick, call on_frame with
hit (active-list index, prime) pairs and the HUD's tracked-LCM resonance flag.
Redraws/goto/pan are silent (advancing=False). The generic resonance flash is
NOT an audio event. No renderer traversal or prime generation happens here.

NumPy synthesis is testable without audio hardware. sounddevice is lazy and
optional. start() returns False on unavailable devices; drawing can continue.
The bounded queue never waits on the render thread. At saturation new tones
are dropped; high pitches/partials at Nyquist are omitted, never aliased down.
Waveforms use at most 32 band-limited harmonics, an approximation of browser
oscillators. Choir intentionally bypasses pan, as the JS reference does.
Output is clipped to the device range. This is not a hard-real-time engine.
"""
from dataclasses import dataclass
import math
from queue import Empty, Full, Queue

import numpy as np

BASE_TONES_HZ = (130.81, 146.83, 164.81, 196., 220., 261.63, 293.66,
                 329.63, 392., 440., 523.25, 587.33, 659.25, 783.99, 880.)
INSTRUMENTS = ('sine', 'triangle', 'square', 'sawtooth', 'bell', 'choir', 'mute')


@dataclass(frozen=True)
class Instruments:
    low: str = 'sine'
    prime: str = 'triangle'
    lcm: str = 'choir'

    def __post_init__(self):
        if any(name not in INSTRUMENTS for name in (self.low, self.prime, self.lcm)):
            raise ValueError('Unknown instrument')


@dataclass(frozen=True)
class Tone:
    frequency: float
    pan: float
    duration: float
    volume: float
    instrument: str

    def __post_init__(self):
        if (not all(math.isfinite(v) for v in (self.frequency, self.pan, self.duration, self.volume))
                or self.frequency <= 0 or not -1 <= self.pan <= 1
                or not 0 < self.duration <= 6 or not 0 <= self.volume <= 1.5
                or self.instrument not in INSTRUMENTS):
            raise ValueError('Invalid tone parameters')


def ring_hit_params(index, prime, instruments=Instruments()):
    if not isinstance(index, int) or index < 0 or prime < 2:
        raise ValueError('Expected a nonnegative active-list index and prime >=2')
    frequency = BASE_TONES_HZ[index] if index < len(BASE_TONES_HZ) else 130 + index * 40
    low = prime <= 7
    return Tone(frequency, -0.7 if index % 2 == 0 else 0.7,
                0.25 if low else 0.75, 0.2, instruments.low if low else instruments.prime)


def resonance_chime_params(instruments=Instruments()):
    return Tone(220., 0., 6., 1.5, instruments.lcm)


def _wave(phase, frequency, rate, instrument):
    if instrument == 'sine':
        return np.sin(phase)
    maximum = min(32, int(np.nextafter(rate / 2, 0) / frequency))
    wave = np.zeros_like(phase)
    for harmonic in range(1, maximum + 1):
        if instrument in ('triangle', 'square') and harmonic % 2 == 0:
            continue
        if instrument == 'triangle':
            coefficient = 8 / math.pi**2 * (-1)**((harmonic-1)//2) / harmonic**2
        elif instrument == 'square':
            coefficient = 4 / math.pi / harmonic
        else:
            coefficient = 2 / math.pi * (-1)**(harmonic+1) / harmonic
        wave += coefficient * np.sin(harmonic * phase)
    return wave


def render_tone(tone, offset, frames, sample_rate=48000):
    """Return a contiguous stereo float32 block; offset is in sample frames."""
    if offset < 0 or frames < 0 or sample_rate < 8000:
        raise ValueError('Invalid sample bounds/rate')
    output = np.zeros((frames, 2), dtype=np.float32)
    if tone.instrument == 'mute' or tone.volume == 0:
        return output
    if tone.instrument == 'choir':
        partials = [(ratio, .3, tone.duration, 'triangle') for ratio in (1,1.125,1.25,1.5,2,3)]
    elif tone.instrument == 'bell':
        partials = [(1,1,tone.duration,'sine'),(2.41,.35,tone.duration*.4,'sine')]
    else:
        partials = [(1,1,tone.duration,tone.instrument)]
    times = (offset + np.arange(frames, dtype=np.float64)) / sample_rate
    pan = ((1.,1.) if tone.instrument == 'choir' else
           (math.cos((tone.pan+1)*math.pi/4), math.sin((tone.pan+1)*math.pi/4)))
    for ratio, scale, duration, instrument in partials:
        frequency = tone.frequency * ratio
        if frequency >= sample_rate / 2:
            continue
        amplitude = tone.volume * scale
        envelope = amplitude * np.exp(math.log(.00001/amplitude) * np.minimum(times,duration)/duration)
        envelope[times >= duration] = 0
        samples = _wave(2*math.pi*frequency*times, frequency, sample_rate, instrument) * envelope
        output[:,0] += samples * pan[0]
        output[:,1] += samples * pan[1]
    return output


class ToneMixer:
    """Single callback consumer; producer submits at most max_events per tick."""
    def __init__(self, sample_rate=48000, max_voices=8, max_events=8):
        if sample_rate < 8000 or max_voices < 1 or max_events < 1:
            raise ValueError('Invalid mixer limits')
        self.sample_rate = sample_rate
        self.max_voices = max_voices
        self.max_events = max_events
        self.pending = Queue(maxsize=max_voices)
        self.voices = []
        self.dropped = 0

    def submit(self, tone):
        if tone.instrument == 'mute' or tone.frequency >= self.sample_rate/2:
            return False
        try:
            self.pending.put_nowait(tone)
            return True
        except Full:
            self.dropped += 1
            return False

    def render(self, frames):
        # Drain at most queue capacity even when producers run concurrently.
        for _ in range(self.max_voices):
            try:
                tone = self.pending.get_nowait()
            except Empty:
                break
            if len(self.voices) < self.max_voices:
                self.voices.append((tone,0))
            else:
                self.dropped += 1
        output = np.zeros((frames,2),dtype=np.float32)
        remaining = []
        for tone, offset in self.voices:
            output += render_tone(tone,offset,frames,self.sample_rate)
            if offset+frames < math.ceil(tone.duration*self.sample_rate):
                remaining.append((tone,offset+frames))
        self.voices = remaining
        return np.clip(output,-1,1,out=output)


class LiveAudio:
    def __init__(self, instruments=Instruments(), sample_rate=48000, max_voices=8,
                 max_events=8, stream_factory=None):
        self.instruments = instruments
        self.mixer = ToneMixer(sample_rate,max_voices,max_events)
        self.stream_factory = stream_factory
        self.stream = None
        self.error = None
        self.callback_status_count = 0

    def start(self):
        if self.stream is not None:
            return True
        stream = None
        try:
            factory = self.stream_factory
            if factory is None:
                import sounddevice
                factory = sounddevice.OutputStream
            stream = factory(samplerate=self.mixer.sample_rate, channels=2, dtype='float32',
                             blocksize=512, callback=self._callback)
            stream.start()
            self.stream = stream
            self.error = None
            return True
        except Exception as exc:
            self.error = str(exc)
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            return False

    def _callback(self,outdata,frames,time_info,status):
        if status:
            self.callback_status_count += 1
        try:
            outdata[:] = self.mixer.render(frames)
        except Exception as exc:
            outdata.fill(0)
            self.error = str(exc)

    def on_frame(self, hits=(), *, advancing, tracked_resonance=False):
        """hits must be ordered (active-list index, prime), never all rings."""
        if not advancing or self.stream is None:
            return
        # Same ordering as JS: chime first, followed by ring hits.
        if tracked_resonance:
            self.mixer.submit(resonance_chime_params(self.instruments))
        from itertools import islice
        for index, prime in islice(hits, self.mixer.max_events):
            self.mixer.submit(ring_hit_params(int(index),int(prime),self.instruments))

    def close(self):
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.close()
            except Exception as exc:
                self.error = str(exc)
        self.mixer = ToneMixer(self.mixer.sample_rate,self.mixer.max_voices,self.mixer.max_events)
