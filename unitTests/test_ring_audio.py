"""Reference parameter parity, block synthesis, bounded load and device failure."""
import importlib.util
from pathlib import Path
import sys
import unittest
import time
from unittest.mock import patch
import numpy as np

path = Path(__file__).resolve().parents[1]/'primeatlas/ring_viz/audio.py'
spec = importlib.util.spec_from_file_location('ring_audio_under_test',path)
audio = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audio
spec.loader.exec_module(audio)


class FakeStream:
    def __init__(self,**kwargs):
        self.kwargs = kwargs
        self.closed = False
    def start(self):
        pass
    def close(self):
        self.closed = True


class AudioTests(unittest.TestCase):
    def test_renderer_hook_and_cleanup(self):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(root/'prime_sieve'))
        from primeatlas.ring_viz import renderer
        from primeatlas.ring_viz.audio import LiveAudio
        from types import SimpleNamespace
        live = LiveAudio(stream_factory=FakeStream)
        live.start()
        active = np.array([2,3,5,7,11])
        mask = np.array([True,True,False,False,False])
        renderer.emit_audio_tick(live,active,mask,{'to_resonance':0},False)
        self.assertEqual(live.mixer.pending.qsize(),0)
        renderer.emit_audio_tick(live,active,mask,{'to_resonance':0},True)
        self.assertEqual(live.mixer.pending.qsize(),3)
        self.assertEqual(live.mixer.pending.get_nowait().duration,6)
        live.close()
        args = SimpleNamespace(audio=True,sound_low='sine',sound_prime='bell',sound_lcm='choir')
        with patch('primeatlas.ring_viz.audio.LiveAudio',return_value=live), \
             patch.object(renderer,'_run_visualization',side_effect=RuntimeError('GL failure')):
            with self.assertRaises(RuntimeError):
                renderer.run(args)
        self.assertIsNone(live.stream)
        def unavailable(**kwargs):
            raise RuntimeError('No device')
        live = LiveAudio(stream_factory=unavailable)
        with patch('primeatlas.ring_viz.audio.LiveAudio',return_value=live), \
             patch.object(renderer,'_run_visualization') as draw:
            renderer.run(args)
            draw.assert_called_once_with(args,None)

    def test_audio_launch_arguments(self):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0,str(root))
        sys.path.insert(0,str(root/'prime_sieve'))
        from primeatlas.rings_tab import build_renderer_argv
        self.assertNotIn('--audio',build_renderer_argv('/tmp',100))
        args=build_renderer_argv('/tmp',100,audio=True,sound_low='mute',sound_prime='bell',sound_lcm='sine')
        self.assertIn('--audio',args)
        for key,value in [('low','mute'),('prime','bell'),('lcm','sine')]:
            self.assertEqual(args[args.index('--sound-'+key)+1],value)

    def test_default_choir_load_benchmark(self):
        mixer = audio.ToneMixer()
        for _ in range(mixer.max_voices):
            mixer.submit(audio.resonance_chime_params())
        started = time.perf_counter()
        for _ in range(100):
            block = mixer.render(512)
            self.assertTrue(np.isfinite(block).all())
        milliseconds = (time.perf_counter()-started)*10
        print(f'Audio benchmark: {mixer.max_voices} choir voices, {milliseconds:.3f} ms/block; '
              f'device block budget {512/mixer.sample_rate*1000:.3f} ms')

    def test_reference_parameters(self):
        self.assertEqual(audio.ring_hit_params(0,2),audio.Tone(130.81,-.7,.25,.2,'sine'))
        self.assertEqual(audio.ring_hit_params(15,53),audio.Tone(730,.7,.75,.2,'triangle'))
        self.assertEqual(audio.resonance_chime_params(),audio.Tone(220,0,6,1.5,'choir'))

    def test_block_continuity_instruments_and_decay(self):
        for instrument in audio.INSTRUMENTS:
            tone = audio.Tone(220,-.7,.25,.2,instrument)
            full = audio.render_tone(tone,0,2048)
            blocks = np.concatenate([audio.render_tone(tone,0,777),audio.render_tone(tone,777,1271)])
            np.testing.assert_array_equal(full,blocks)
            self.assertTrue(np.isfinite(full).all())
            self.assertFalse(audio.render_tone(tone,12000,512).any())
            if instrument == 'mute':
                self.assertFalse(full.any())
            elif instrument != 'choir':
                self.assertGreater(np.linalg.norm(full[:,0]),np.linalg.norm(full[:,1]))
            else:
                np.testing.assert_array_equal(full[:,0],full[:,1])
        sine = audio.render_tone(audio.Tone(220,0,.25,.2,'sine'),0,2048)
        bell = audio.render_tone(audio.Tone(220,0,.25,.2,'bell'),0,2048)
        self.assertFalse(np.allclose(sine,bell))

    def test_nyquist_and_bounded_load(self):
        mixer = audio.ToneMixer(max_voices=2)
        self.assertFalse(mixer.submit(audio.ring_hit_params(10000000,99999999)))
        tone = audio.resonance_chime_params()
        for _ in range(100):
            mixer.submit(tone)
        self.assertEqual(mixer.pending.qsize(),2)
        self.assertEqual(mixer.dropped,98)
        output = mixer.render(512)
        self.assertLessEqual(np.abs(output).max(),1)
        self.assertEqual(len(mixer.voices),2)

    def test_tick_contract_and_shutdown(self):
        live = audio.LiveAudio(stream_factory=FakeStream,max_events=2)
        live.on_frame([(0,2)],advancing=True)
        self.assertEqual(live.mixer.pending.qsize(),0)
        self.assertTrue(live.start())
        stream = live.stream
        live.on_frame([(0,2)],advancing=False,tracked_resonance=True)
        self.assertEqual(live.mixer.pending.qsize(),0)
        live.on_frame(((i,11) for i in range(10000000)),advancing=True,tracked_resonance=True)
        self.assertEqual(live.mixer.pending.qsize(),3)
        live.close()
        live.close()
        self.assertTrue(stream.closed)
        self.assertEqual(live.mixer.pending.qsize(),0)

    def test_unavailable_device(self):
        def fail(**kwargs):
            raise RuntimeError('No audio device')
        live = audio.LiveAudio(stream_factory=fail)
        self.assertFalse(live.start())
        self.assertIn('No audio device',live.error)
        live.on_frame([(0,2)],advancing=True)
        live.close()


if __name__=='__main__':
    unittest.main()
