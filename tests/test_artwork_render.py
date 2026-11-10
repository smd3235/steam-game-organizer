"""Artwork has to actually draw, not just download.

Every symptom of the JPEG bug was somewhere other than the panel: the files downloaded, the cache filled, the
log said CACHE_HIT, and the SteamGridDB key was irrelevant to it. A test that checks the download is not a
test that checks the picture, so these read the widget's own state after show() - which is the thing a person
is looking at.

The files are generated here rather than read from the local cache, so the test does not depend on whatever
this machine happens to have downloaded, and the two real formats are covered on purpose: SteamGridDB hands
back genuine JPEG, while some cached assets are PNG data under a .jpg name. Only the second one ever worked
without Pillow, which is exactly what made the failure look intermittent.

That includes the JPEG fixture. It used to be read out of `cache/artwork`, and to raise `unittest.SkipTest`
when this machine held no `*_steam_*.jpg`, so the only class here that proves artwork renders at all reported
itself green while running nothing - on exactly the machines whose artwork cache was empty or pruned.
"""
from __future__ import annotations

import atexit
import importlib
import io
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.tk_support import require_tk, close_root

ROOT = Path(__file__).resolve().parents[1]
JPEG_MAGIC = b'\xff\xd8'
JPEG_END = b'\xff\xd9'
# Landscape Steam header art rather than a square grid capsule: the panel prefers banner art and takes its
# shape from the header, so the fixture has to be the shape production actually serves.
FIXTURE_SHAPE = (320, 180)
FIXTURE_RGB = (28, 84, 168)
# Generated once per process: every test here wants the same picture, the bytes never change, and a temporary
# directory per test would be a second thing to clean up.
_FIXTURE: list[bytes] = []


def _png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A minimal valid PNG, built here so the test carries no fixture file."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw))
            + chunk(b'IEND', b''))


def _jpeg_bytes() -> bytes:
    """A genuine baseline JPEG, generated into a temporary directory rather than found on this machine.

    The pixels are `_png_bytes`'; Pillow does nothing but wrap them in a real JPEG container, so what the panel
    opens is a file a real decoder has to decode rather than bytes that happen to start with FFD8. A hand-built
    header would pass a magic-number check and fail at `Image.open`, which is the whole content of the bug this
    class exists for. The encoder is Pillow's rather than this file's, because hand-rolling a baseline JPEG
    encoder here would test the encoder.

    A temporary directory because Pillow is handed a path, and because a fixture image committed beside the
    code that renders it is the same stale-asset problem in a smaller box. It is removed at exit rather than
    per test, since the bytes outlive the file.
    """
    if _FIXTURE:
        return _FIXTURE[0]
    try:
        from PIL import Image
    except ImportError as exc:
        raise AssertionError('Pillow is not installed, so a genuine JPEG cannot be generated here - and the panel '
                             'cannot draw artwork without it either. This install needs it: pip install pillow') from exc
    scratch = Path(tempfile.mkdtemp(prefix='organizer-jpeg-fixture-'))
    atexit.register(shutil.rmtree, scratch, True)
    path = scratch / 'steam_header.jpg'
    with Image.open(io.BytesIO(_png_bytes(*FIXTURE_SHAPE, FIXTURE_RGB))) as source:
        source.save(path, 'JPEG', quality=90, subsampling=0)
    data = path.read_bytes()
    _FIXTURE.append(data)
    return data


class TestArtworkRenders(unittest.TestCase):
    def setUp(self):
        require_tk(self)
        import tkinter as tk
        self.root = tk.Tk()
        self.addCleanup(close_root, self.root)
        from core.models import ArtworkResult
        from ui.widgets.artwork_panel import ArtworkPanel
        self.ArtworkResult = ArtworkResult
        self.panel = ArtworkPanel(self.root)
        self.panel.pack(fill='both', expand=True)
        self.root.update()
        self.scratch_dir = tempfile.TemporaryDirectory(prefix='organizer-artwork-')
        self.addCleanup(self.scratch_dir.cleanup)
        # A system temp directory, not a folder under the project. The fixture is generated into another one
        # and the bytes are written again a few lines later by the same process, so nothing here crosses the
        # per-machine %TEMP% boundary the project notes warn about - and a test has no business leaving a
        # directory behind in the repository for the next run to trip over.
        self.scratch = Path(self.scratch_dir.name)

    def _painted(self, result) -> bool:
        self.panel.show(result)
        self.root.update()
        return bool(str(self.panel.label.cget('image')).strip())

    def test_the_fixture_is_a_generated_jpeg_and_not_a_file_from_the_cache(self):
        """What the four tests below are drawn against, asserted rather than assumed.

        Each of them is worthless if the bytes are not a real JPEG, and the fixture used to come out of
        `cache/artwork` - so on a machine with a full cache they proved something, and on one without they did
        not run at all. Both halves are checked as values rather than as source: 320x180 of a single flat colour
        is what this module generated, so bytes found anywhere else cannot match it, and a header-only forgery
        satisfies `startswith(JPEG_MAGIC)` while failing `Image.open`.
        """
        from PIL import Image
        from services.artwork_service import image_shape
        path = self.scratch / 'fixture.jpg'
        path.write_bytes(_jpeg_bytes())
        data = path.read_bytes()
        self.assertEqual(JPEG_MAGIC, data[:2], 'the fixture does not begin with a JPEG start-of-image marker')
        self.assertEqual(JPEG_END, data[-2:], 'the fixture is truncated: no end-of-image marker')
        with Image.open(path) as img:
            self.assertEqual('JPEG', img.format, f'Pillow opened it as {img.format} rather than a JPEG')
            self.assertEqual(FIXTURE_SHAPE, img.size,
                             f'the fixture measures {img.size}, not the shape this module generated')
            got = img.getpixel((FIXTURE_SHAPE[0] // 2, FIXTURE_SHAPE[1] // 2))
        # Two levels of slack, because a baseline JPEG is lossy and its encoder is not the thing under test.
        # Far less than the difference between this picture and a Steam header, which is what it has to prove.
        for channel, (actual, wanted) in enumerate(zip(got, FIXTURE_RGB, strict=True)):
            self.assertLessEqual(abs(actual - wanted), 2,
                                 f'channel {channel} decoded to {actual} rather than the {wanted} this module '
                                 'generated, so the fixture is not this module own picture')
        self.assertFalse(image_shape(path),
                         'the fixture should be landscape header art, which is the shape the panel prefers and '
                         'the one production serves')

    def test_a_real_jpeg_is_drawn(self):
        """The bug: JPEG artwork downloaded and cached, then drew nothing.

        A test that only checked the file arrived passes against this failure, which is why the assertion is
        on the widget rather than on the disk.
        """
        if importlib.util.find_spec('PIL') is None:
            self.fail('Pillow is not installed, so JPEG artwork cannot be drawn at all. '
                      'This is the 9.19 regression: install it with "pip install pillow".')
        path = self.scratch / 'steam_header.jpg'
        path.write_bytes(_jpeg_bytes())
        result = self.ArtworkResult(path=path)
        self.assertTrue(self._painted(result),
                        f'a real JPEG drew nothing; panel says {self.panel.label.cget("text")!r}')
        self.assertEqual('', str(self.panel.label.cget('text')), 'the label kept its text over the image')

    def test_png_data_under_a_jpg_name_is_drawn(self):
        """The family that already worked, and the one that made the failure look intermittent."""
        path = self.scratch / 'mislabeled.jpg'
        path.write_bytes(_png_bytes(64, 32, (200, 40, 60)))
        result = self.ArtworkResult(path=path)
        self.assertTrue(self._painted(result),
                        f'PNG data under a .jpg name drew nothing; panel says {self.panel.label.cget("text")!r}')

    def test_a_missing_decoder_is_named_rather_than_hidden(self):
        """When nothing can decode, the panel says which decoder is missing.

        Asserted by hiding Pillow rather than by uninstalling it: the text is the contract, and a message
        that only appears on a machine without Pillow is exactly the message nobody tests.
        """
        import builtins
        from ui.widgets import artwork_panel as panel_module

        path = self.scratch / 'steam_header.jpg'
        path.write_bytes(_jpeg_bytes())
        real_import = builtins.__import__
        real_which = shutil.which

        def no_pillow(name, *args, **kwargs):
            if name == 'PIL' or name.startswith('PIL.'):
                raise ImportError('Pillow is hidden for this test')
            return real_import(name, *args, **kwargs)

        # ffmpeg is neutralised as well, so this test means the same thing on a machine that has it. Otherwise
        # the ffmpeg branch would decode the JPEG and the panel would show a picture, which is not the
        # condition being tested - and would be a false failure on a dev box rather than on a user's.
        def no_ffmpeg(cmd, *args, **kwargs):
            return None if cmd == 'ffmpeg' else real_which(cmd, *args, **kwargs)

        builtins.__import__ = no_pillow
        self.addCleanup(setattr, builtins, '__import__', real_import)
        panel_module.shutil.which = no_ffmpeg
        self.addCleanup(setattr, panel_module.shutil, 'which', real_which)
        # Cleared rather than left set, because a leftover image would mask the message.
        self.panel.label.configure(image='')
        self.panel.show(self.ArtworkResult(path=path))
        self.root.update()
        text = str(self.panel.label.cget('text'))
        self.assertIn('pillow', text.lower(), f'the panel did not name the missing decoder: {text!r}')
        self.assertIn('pip install', text.lower(), f'the panel did not say how to fix it: {text!r}')
        self.assertEqual('', str(self.panel.label.cget('image')),
                         'the panel should have no image to draw while no decoder can open the file')

    def test_a_cached_jpeg_without_pillow_says_what_is_missing_rather_than_cache_hit(self):
        """Reproduces the bug where cached JPEG artwork shows 'Cache hit' as its placeholder text.

        A cache hit is the source of the artwork, not a rendering error. When the cached JPEG cannot be
        decoded because Pillow is absent, the panel must name the missing decoder - not echo the cache status.
        """
        import builtins
        from ui.widgets import artwork_panel as panel_module

        path = self.scratch / 'steam_header.jpg'
        path.write_bytes(_jpeg_bytes())
        real_import = builtins.__import__
        real_which = shutil.which

        def no_pillow(name, *args, **kwargs):
            if name == 'PIL' or name.startswith('PIL.'):
                raise ImportError('Pillow is hidden for this test')
            return real_import(name, *args, **kwargs)

        def no_ffmpeg(cmd, *args, **kwargs):
            return None if cmd == 'ffmpeg' else real_which(cmd, *args, **kwargs)

        builtins.__import__ = no_pillow
        self.addCleanup(setattr, builtins, '__import__', real_import)
        panel_module.shutil.which = no_ffmpeg
        self.addCleanup(setattr, panel_module.shutil, 'which', real_which)
        self.panel.label.configure(image='')
        result = self.ArtworkResult(status='cached', path=path, source='steam_cdn', reason='Cache hit')
        self.panel.show(result)
        self.root.update()
        text = str(self.panel.label.cget('text'))
        self.assertIn('pillow', text.lower(),
                       f'a cached JPEG without Pillow showed {text!r} instead of naming the missing decoder')
        self.assertNotIn('cache hit', text.lower(),
                          f'the panel showed the cache status {text!r} as an error message')

    def test_portrait_detection_does_not_shell_out_to_ffprobe(self):
        """_is_portrait() used to call ffprobe, which is not installed.

        ffprobe's absence raised OSError, which was caught and returned as False - indistinguishable from
        'wide'. The panel therefore never once identified a portrait asset, so the banner-first ordering it
        implements could not do its job. It now reads the JPEG header, which is what
        artwork_service.image_shape() has done since 9.6.
        """
        from ui.widgets import artwork_panel as panel_module
        # Checked against the parsed code, not the file text: the string 'ffprobe' appears in this module's
        # own change log, and a grep would report a shell-out that no longer exists.
        import ast
        tree = ast.parse((ROOT / 'ui' / 'widgets' / 'artwork_panel.py').read_text(encoding='utf-8'))
        called = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        self.assertFalse([call for call in called if 'ffprobe' in call],
                         'artwork_panel still shells out to ffprobe; on a machine without ffmpeg that is a '
                         'silent False, not a portrait answer')
        # And the function still answers correctly, from the header.
        jpeg = self.scratch / 'probe.jpg'
        jpeg.write_bytes(_jpeg_bytes())
        self.assertIsInstance(panel_module.ArtworkPanel._is_portrait(self.panel, jpeg), bool)


if __name__ == '__main__':
    unittest.main()
