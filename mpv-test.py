#!/usr/bin/env python3

import unittest
from unittest import mock
import math
import threading
from contextlib import contextmanager
import gc
import os.path
import time

import mpv


TESTVID = os.path.join(os.path.dirname(__file__), 'test.webm')
MPV_ERRORS = [ l(ec) for ec, l in mpv.ErrorCode.EXCEPTION_DICT.items() if l ]

class TestProperties(unittest.TestCase):
    @contextmanager
    def swallow_mpv_errors(self, exception_exceptions=[]):
        try:
            yield
        except Exception as e:
            if any(e.args[:2] == ex.args for ex in MPV_ERRORS):
                if e.args[1] not in exception_exceptions:
                    raise
            else:
                raise

    def setUp(self):
        self.m = mpv.MPV()

    def tearDown(self):
        self.m.terminate()

    def test_sanity(self):
        for name, (ptype, access, *_args) in mpv.ALL_PROPERTIES.items():
            self.assertTrue('r' in access or 'w' in access)
            self.assertRegex(name, '^[-0-9a-z]+$')
            # Types and MpvFormat values
            self.assertIn(ptype, [bool, int, float, str, bytes, mpv._commalist] + list(range(10)))

    def test_completeness(self):
        ledir = dir(self.m)
        options = { o.strip('*') for o in self.m.options }
        for prop in self.m.property_list:
            if prop in ('stream-path', 'demuxer', 'current-demuxer', 'mixer-active'):
                continue # Property is deemed useless by man mpv(1)
            if prop in ('osd-sym-cc', 'osd-ass-cc', 'working-directory'):
                continue # Property is deemed useless by me
            if prop in ('clock', 'colormatrix-gamma', 'cache-percent', 'tv-scan', 'aspect', 'hwdec-preload', 'ass',
                'audiofile', 'cursor-autohide-delay', 'delay', 'dvdangle', 'endpos', 'font', 'forcedsubsonly', 'format',
                'lua', 'lua-opts', 'name', 'ss', 'media-keys', 'status-msg'):
                continue # Property is undocumented in man mpv(1) and we don't want to risk it
            if prop in ('hwdec-active', 'hwdec-detected', 'drop-frame-count', 'vo-drop-frame-count', 'fps',
                'mouse-movements', 'msgcolor', 'msgmodule', 'noar', 'noautosub', 'noconsolecontrols', 'nosound',
                'osdlevel', 'playing-msg', 'spugauss', 'srate', 'stop-xscreensaver', 'sub-fuzziness', 'subcp',
                'subdelay', 'subfile', 'subfont', 'subfont-text-scale', 'subfps', 'subpos', 'tvscan', 'autosub',
                'autosub-match', 'idx', 'forceidx', 'ass-use-margins', 'input-unix-socket'):
                continue # Property/option is deprecated
            if any(prop.startswith(prefix) for prefix in ('sub-', 'ass-')):
                continue # Property/option is deprecated
            if prop.replace('_', '-') in options: # corrector for b0rked mixed_-formatting of some property names
                continue # Property seems to be an aliased option
            if prop in ('ad-spdif-dtshd', 'softvol', 'heartbeat-cmd', 'input-x11-keyboard',
                'vo-vdpau-queuetime-windowed', 'demuxer-max-packets', '3dlut-size', 'right-alt-gr',
                'mkv-subtitle-preroll', 'dtshd', 'softvol-max'):
                continue # Property seems to be an aliased option that was forgotten in MPV.options
            prop = prop.replace('-', '_')
            self.assertTrue(prop in ledir, 'Property {} not found'.format(prop))

    def test_read(self):
        self.m.loop = 'inf'
        self.m.play(TESTVID)
        while self.m.core_idle:
            time.sleep(0.05)
        for name, (ptype, access, *_args) in sorted(mpv.ALL_PROPERTIES.items()):
            if 'r' in access:
                name =  name.replace('-', '_')
                with self.subTest(property_name=name), self.swallow_mpv_errors([
                    mpv.ErrorCode.PROPERTY_UNAVAILABLE,
                    mpv.ErrorCode.PROPERTY_ERROR,
                    mpv.ErrorCode.PROPERTY_NOT_FOUND]):
                    rv = getattr(self.m, name)
                    if rv is not None and callable(ptype):
                        # Technically, any property can return None (even if of type e.g. int)
                        self.assertEqual(type(rv), type(ptype()))

    def test_write(self):
        self.m.loop = 'inf'
        self.m.play(TESTVID)
        while self.m.core_idle:
            time.sleep(0.05)
        for name, (ptype, access, *_args) in sorted(mpv.ALL_PROPERTIES.items()):
            if 'w' in access:
                name =  name.replace('-', '_')
                with self.subTest(property_name=name), self.swallow_mpv_errors([
                        mpv.ErrorCode.PROPERTY_UNAVAILABLE,
                        mpv.ErrorCode.PROPERTY_ERROR,
                        mpv.ErrorCode.PROPERTY_FORMAT,
                        mpv.ErrorCode.PROPERTY_NOT_FOUND]): # This is due to a bug with option-mapped properties in mpv 0.18.1
                    if ptype == int:
                        setattr(self.m, name, 0)
                        setattr(self.m, name, 1)
                        setattr(self.m, name, -1)
                    elif ptype == float:
                        setattr(self.m, name, 0.0)
                        setattr(self.m, name, 1)
                        setattr(self.m, name, 1.0)
                        setattr(self.m, name, -1.0)
                        setattr(self.m, name, float('nan'))
                    elif ptype == str:
                        setattr(self.m, name, 'foo')
                        setattr(self.m, name, '')
                        setattr(self.m, name, 'bazbazbaz'*1000)
                    elif ptype == bytes:
                        setattr(self.m, name, b'foo')
                        setattr(self.m, name, b'')
                        setattr(self.m, name, b'bazbazbaz'*1000)
                    elif ptype == bool:
                        setattr(self.m, name, True)
                        setattr(self.m, name, False)

    def test_option_read(self):
        self.m.loop = 'inf'
        self.m.play(TESTVID)
        while self.m.core_idle:
            time.sleep(0.05)
        for name in sorted(self.m):
            with self.subTest(option_name=name), self.swallow_mpv_errors([
                mpv.ErrorCode.PROPERTY_UNAVAILABLE, mpv.ErrorCode.PROPERTY_NOT_FOUND, mpv.ErrorCode.PROPERTY_ERROR]):
                self.m[name]


class ObservePropertyTest(unittest.TestCase):
    def test_observe_property(self):
        handler = mock.Mock()

        m = mpv.MPV()
        m.loop = 'inf'

        m.observe_property('loop', handler)

        m.loop = 'no'
        self.assertEqual(m.loop, 'no')

        m.loop = 'inf'
        self.assertEqual(m.loop, 'inf')

        time.sleep(0.02)
        m.unobserve_property('loop', handler)

        m.loop = 'no'
        m.loop = 'inf'
        m.terminate() # needed for synchronization of event thread
        handler.assert_has_calls([mock.call('loop', 'no'), mock.call('loop', 'inf')])

    def test_property_observer_decorator(self):
        handler = mock.Mock()

        m = mpv.MPV()
        m.loop = 'inf'
        m.mute = True

        @m.property_observer('mute')
        @m.property_observer('loop')
        def foo(*args, **kwargs):
            handler(*args, **kwargs)

        m.mute = False
        m.loop = 'no'
        self.assertEqual(m.mute, False)
        self.assertEqual(m.loop, 'no')

        m.mute = True
        m.loop = 'inf'
        self.assertEqual(m.mute, True)
        self.assertEqual(m.loop, 'inf')

        time.sleep(0.02)
        foo.unobserve_mpv_properties()

        m.mute = False
        m.loop = 'no'
        m.mute = True
        m.loop = 'inf'
        m.terminate() # needed for synchronization of event thread
        handler.assert_has_calls([
            mock.call('mute', False),
            mock.call('loop', 'no'),
            mock.call('mute', True),
            mock.call('loop', 'inf')])

class TestLifecycle(unittest.TestCase):
    def test_create_destroy(self):
        thread_names = lambda: [ t.name for t in threading.enumerate() ]
        self.assertNotIn('MPVEventHandlerThread', thread_names())
        m = mpv.MPV()
        self.assertIn('MPVEventHandlerThread', thread_names())
        del m
        gc.collect()
        self.assertNotIn('MPVEventHandlerThread', thread_names())

    def test_flags(self):
        with self.assertRaises(AttributeError):
            mpv.MPV('this-option-does-not-exist')
        m = mpv.MPV('no-video', 'cursor-autohide-fs-only', 'fs')
        self.assertTrue(m.fullscreen)
        self.assertEqual(m.cursor_autohide, '1000')
        m.terminate()

    def test_options(self):
        with self.assertRaises(AttributeError):
            mpv.MPV(this_option_does_not_exists=23)
        m = mpv.MPV(osd_level=0, loop='inf', deinterlace='no')
        self.assertEqual(m.osd_level, 0)
        self.assertEqual(m.loop, 'inf')
        self.assertEqual(m.deinterlace, 'no')
        m.terminate()

    def test_event_callback(self):
        handler = mock.Mock()
        m = mpv.MPV('no-video')
        m.register_event_callback(handler)
        m.play(TESTVID)
        m.wait_for_playback()

        m.unregister_event_callback(handler)
        handler.assert_has_calls([
                mock.call({'reply_userdata': 0, 'error': 0, 'event_id': 6, 'event': None}),
                mock.call({'reply_userdata': 0, 'error': 0, 'event_id': 9, 'event': None}),
                mock.call({'reply_userdata': 0, 'error': 0, 'event_id': 7, 'event': {'reason': 4}}),
            ], any_order=True)
        handler.reset_mock()

        m.terminate()
        handler.assert_not_called()

    def test_log_handler(self):
        handler = mock.Mock()
        m = mpv.MPV('no-video', log_handler=handler)
        m.play(TESTVID)
        m.wait_for_playback()
        m.terminate()
        handler.assert_any_call('info', 'cplayer', 'Playing: test.webm')


class RegressionTests(unittest.TestCase):

    def test_unobserve_property_runtime_error(self):
        """
        Ensure a `RuntimeError` is not thrown within
        `unobserve_property`.
        """
        handler = mock.Mock()

        m = mpv.MPV()
        m.observe_property('loop', handler)

        try:
            m.unobserve_property('loop', handler)
        except RuntimeError:
            self.fail(
                """
                "RuntimeError" exception thrown within
                `unobserve_property`
                """,
            )
        finally:
            m.terminate()

    def test_instance_method_property_observer(self):
        """
        Ensure that bound method objects can be used as property observers.
        See issue #26
        """
        handler = mock.Mock()
        m = mpv.MPV()

        class T(object):
            def t(self, *args, **kw):
                handler(*args, **kw)
        t =  T()

        m.loop = 'inf'

        m.observe_property('loop', t.t)

        m.loop = 'no'
        self.assertEqual(m.loop, 'no')
        m.loop = 'inf'
        self.assertEqual(m.loop, 'inf')

        time.sleep(0.02)
        m.unobserve_property('loop', t.t)

        m.loop = 'no'
        m.loop = 'inf'
        m.terminate() # needed for synchronization of event thread
        handler.assert_has_calls([mock.call('loop', 'no'), mock.call('loop', 'inf')])


if __name__ == '__main__':
    unittest.main()
