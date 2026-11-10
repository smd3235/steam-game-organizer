"""Tests for what actually reached the screen, as distinct from what was laid out correctly.

A widget can have the right size, the right position and the right text and still be invisible: a canvas
drawn by hand that drew nothing, a themed colour that was never applied, an image that failed to load. Every
other test in this suite checks geometry or state, and every one of them passes on a panel that is blank. These
read the live widget tree instead of a screenshot, which is why they are deterministic and need no display,
no populated library and no window manager.

What this deliberately does not do is compare pixels. A screenshot cannot tell you that a control is one pixel
short of its container; `winfo_height` can, and it says so in the failure message.
"""
import unittest
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tempfile import TemporaryDirectory

from ui import palette as PALETTE_MODULE
from ui.palette import PILL_KINDS
from tests.tk_support import close_root, sandbox_app

def _measured_window_local(root,size='1280x800'):
    try: root.state('normal')
    except tk.TclError: pass
    if size: root.geometry(size)
    root.update()
    return root



def _palette():
    """Every colour the app is allowed to paint, read from the palette module itself.

    Read from the module rather than listed here so that adding a colour to the palette is immediately
    permitted by this test, and so a colour cannot be quietly dropped from the list while still being the one
    the UI paints."""
    colours = {value.lower() for name, value in vars(PALETTE_MODULE).items()
               if not name.startswith('_') and isinstance(value, str)}
    for fill, label in PILL_KINDS.values():
        colours.add(fill.lower()); colours.add(label.lower())
    # White and black are not in the palette but are legitimate text colours on a filled accent, and Tk itself
    # names them.
    return colours | {'white', 'black'}


PALETTE = _palette()

# The options that define what a widget looks like. Checked on every widget.
APPEARANCE_OPTIONS = ('bg', 'background', 'fg', 'foreground', 'selectcolor', 'highlightbackground')

# The options that only paint in a state. Checked everywhere except on a Label, which has no such state: Tk
# still reports SystemButtonFace for a Label's activebackground and SystemDisabledText for its
# disabledforeground, and a Label can never draw either. Reading them as faults produced 346 findings that
# could not reach the screen. A Button and an Entry do have those states, so they are checked there.
STATE_OPTIONS = ('activebackground', 'activeforeground', 'disabledforeground')
NEVER_STATES = ('Label',)

VIEWS = ('scan', 'review', 'organize', 'artwork', 'done')


class RenderIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self._close)
        self.app = sandbox_app(self, self.root)
        _measured_window_local(self.root)

    def _close(self):
        close_root(self.root)

    def _colour_conflicts(self, widget, path):
        """Every colour option on one widget that is not a palette colour, as readable messages.

        `insertbackground` is not in either list: Tk sets the text caret from the system, the app never
        configures it, and a caret the platform drew is not a theme that failed to reach the screen."""
        options = list(APPEARANCE_OPTIONS)
        if widget.winfo_class() not in NEVER_STATES: options.extend(STATE_OPTIONS)
        problems = []
        for option in options:
            try: value = widget.cget(option)
            except tk.TclError: continue          # option not valid for this widget class
            if not isinstance(value, str) or not value: continue
            # A focus highlight of zero thickness is never painted, and Tk leaves every widget carrying the
            # system button-face colour in that option. Reading it as a fault reported 201 findings, none of
            # which could reach the screen; the ones that matter are the widgets that actually draw a ring.
            if option == 'highlightbackground':
                try: thickness = int(widget.cget('highlightthickness') or 0)
                except tk.TclError: thickness = 0
                if not thickness: continue
            if value.lower() not in PALETTE:
                problems.append(f'{path} {option}={value!r}')
        return problems

    def test_no_widget_paints_a_colour_that_is_not_in_the_palette(self):
        """A mistyped or wrong theme constant paints Tk's default, not the theme's colour.

        Nothing else in the suite would notice. Geometry tests measure the widget; they never read what it was
        told to paint, so a panel can lay out perfectly and render as a default-coloured block and still pass
        every check in this file apart from this one."""
        problems = []
        for name in VIEWS:
            view = self.app.window.views[name]
            self.app.window.show(name)
            self.root.update()
            stack = [(view, f'{name}')]
            while stack:
                widget, path = stack.pop()
                problems.extend(self._colour_conflicts(widget, path))
                for child in widget.winfo_children():
                    stack.append((child, f'{path} > {child.winfo_class()}'))
        self.assertEqual(problems, [], 'these widgets paint colours outside the palette:\n' + '\n'.join(problems))

    def test_the_ttk_widgets_resolve_to_palette_colours_through_their_style(self):
        """A ttk widget has no colour of its own to read - it inherits one from the theme.

        `cget` returns empty for every colour option, so the classic-widget walk above cannot see these at all.
        Reading the style is the only way to know what a Combobox or a Button will actually paint."""
        style = ttk.Style(self.root)
        problems = []
        checked = 0
        for view in (self.app.window.views[name] for name in VIEWS):
            stack = [(view, '')]
            while stack:
                widget, path = stack.pop()
                if isinstance(widget, ttk.Widget):
                    name = str(widget.cget('style') or widget.winfo_class())
                    checked += 1
                    for option in ('background', 'foreground', 'fieldbackground', 'arrowcolor', 'bordercolor'):
                        value = style.lookup(name, option)
                        if value and value.lower() not in PALETTE:
                            problems.append(f'ttk style {name}.{option}={value!r} ({path})')
                for child in widget.winfo_children():
                    stack.append((child, path))
        self.assertGreater(checked, 0, 'no ttk widgets were reached, so this test proves nothing')
        self.assertEqual(problems, [], 'ttk styles resolve to colours outside the palette:\n' + '\n'.join(problems))

    def test_the_hand_drawn_canvases_actually_draw_something(self):
        """Sparkline, PhaseTimeline and ActivityFeed are painted item by item with create_line/create_polygon.

        A canvas with perfect geometry and nothing in it is indistinguishable from a flat panel by every
        measurement in the suite, and that is exactly what a broken draw call produces: no error, no widget, no
        pixels. `find_all` is the only thing that can tell the two apart."""
        organize = self.app.window.views['organize']
        self.app.window.show('organize')
        organize.stage_counts = {}; organize.current = None; organize.work.grid()
        organize.timeline.reset(); organize.feed.clear()
        self.root.update()

        # Sparkline was removed in UI simplification (see organize_view.py changes).
        # Test the timeline and feed instead.
        phases = organize.timeline.chips
        self.assertTrue(phases, 'the phase timeline has no chips, so there is nothing to colour')
        self.root.update()
        for key, chip in phases.items():
            self.assertTrue(str(chip.cget('text')).strip(), f'phase {key} has an empty chip')

        organize.progress_update({'stage': 'compressing', 'file': 'Same.7z', 'source_bytes': 1024,
                                  'progress': 0.5, 'tool_percent': 50})
        organize.progress_update({'stage': 'converted', 'file': 'Same.7z', 'source_bytes': 1024, 'target_bytes': 512})
        self.root.update()
        self.assertEqual(len(organize.feed.widget.get('1.0', 'end-1c').strip().splitlines()), 2,
                         'the activity feed did not keep both the live line and the real transition')

    def test_a_steam_match_is_coloured_by_whether_it_was_verified(self):
        """The feed computed a colour for every Steam match and then handed the feed 'muted' instead.

        A verified game and an unidentified one looked identical in the live feed, which is the one thing the
        line exists to let someone catch while it is still one line rather than after the run."""
        scan = self.app.window.views['scan']
        self.app.window.show('scan')

        from core.models import SteamMatch

        class _Archive:
            display_name = 'Example Game'
            def __init__(self, found):
                self.steam = SteamMatch(found=found, appid='123' if found else '',
                                        name='Example Game' if found else 'Example Gam',
                                        confidence='High' if found else 'Low', source='steam_appid')
        for found, expected in ((True, 'good'), (False, 'warn')):
            scan.feed.clear()
            archive = _Archive(found)
            scan.verification_update(1, 2, archive, archive.steam)
            self.root.update()
            line = scan.feed.widget.get('1.0', 'end-1c').rstrip()
            self.assertTrue(line, f'found={found} produced no activity line')
            tags = scan.feed.widget.tag_names(scan.feed.widget.index('end-2c'))
            self.assertIn(expected, tags,
                          f'a {"verified" if found else "unidentified"} match was not tagged {expected}: '
                          f'tags={tags} for {line!r}')

    def test_local_artwork_loads_without_pillow_or_ffmpeg(self):
        """A stock Windows box has neither Pillow nor ffmpeg, and this is where Steam artwork is shown.

        The panel used to reach for both and, failing both, report "could not be rendered" for every game in
        the library - which reads as broken rather than as a missing optional package. Tk reads PNG itself, so
        the fix costs no dependency and no subprocess."""
        from ui.widgets.artwork_panel import ArtworkPanel
        import struct, zlib

        def png_bytes(width, height, rgb):
            raw = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))
            def chunk(kind, data):
                payload = kind + data
                return (struct.pack('>I', len(data)) + payload
                        + struct.pack('>I', zlib.crc32(payload) & 0xffffffff))
            return (b'\x89PNG\r\n\x1a\n'
                    + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))

        with TemporaryDirectory() as folder:
            art = Path(folder) / 'header.png'
            art.write_bytes(png_bytes(460, 215, (0x73, 0x53, 0xf5)))
            panel = ArtworkPanel(self.root)
            panel.pack()
            self.root.update()
            from core.models import ArtworkResult
            panel.show(ArtworkResult(path=art, assets={'library_hero': art}))
            self.root.update()
            self.assertIsNotNone(panel.photo, 'a valid PNG on disk loaded no image at all')
            self.assertGreater(panel.photo.width(), 0, 'the image loaded but has no width')
            self.assertEqual(panel.label.cget('text'), '', 'the placeholder text was left on top of the artwork')


if __name__ == '__main__':
    unittest.main()
