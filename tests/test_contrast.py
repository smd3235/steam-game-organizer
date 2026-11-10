"""Contrast audit for the theme.

Geometry checks cannot tell whether text is readable. These are WCAG 2.1 relative-luminance ratios for every
colour pair the app actually paints, which is what catches a label that renders but cannot be read.

Run directly for a report:  python3 tests/test_contrast.py
"""
import os, sys, unittest

import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.palette import (BG, PANEL, PANEL2, PANEL3, TEXT, MUTED, ACCENT, ACCENT_HOVER, ACCENT_HI, CYAN, GREEN, ORANGE, RED,
                          PINK, SKY, PILL_KINDS, DANGER, DANGER_TEXT, ENTRY_BG)

# WCAG AA for normal text. The pills and buttons use small bold type, so 4.5:1 applies rather than the 3:1
# large-text allowance.
AA_NORMAL = 4.5

def _channel(value):
    value /= 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

def luminance(rgb):
    red, green, blue = rgb
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)

def contrast(foreground, background):
    a, b = luminance(foreground), luminance(background)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)

NAMED = {'white': (255, 255, 255)}

def rgb(value):
    if value in NAMED: return NAMED[value]
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

PAIRS = [('body text on background', TEXT, BG),
         ('body text on panel', TEXT, PANEL),
         ('body text on raised panel', TEXT, PANEL2),
         ('body text on chip', TEXT, PANEL3),
         ('muted text on background', MUTED, BG),
         ('muted text on panel', MUTED, PANEL),
         ('muted text on raised panel', MUTED, PANEL2),
         ('muted text on chip', MUTED, PANEL3),
         ('accent heading on background', ACCENT_HI, BG),
         ('accent heading on panel', ACCENT_HI, PANEL),
         ('cyan on panel', CYAN, PANEL),
         ('success on panel', GREEN, PANEL),
         ('success on raised panel', GREEN, PANEL2),
         ('warning on raised panel', ORANGE, PANEL2),
         ('chart bar fill on track', PINK, PANEL2),
         ('chart bar fill on track alt', SKY, PANEL2),
         ('danger on panel', RED, PANEL),
         ('danger on raised panel', RED, PANEL2),
         ('primary button label', 'white', ACCENT),
         ('primary button label on hover', 'white', ACCENT_HOVER),
         # The destructive button and the text entry are audited for the same reason as everything else: they
         # used to be typed into theme.py rather than named here, which is exactly how a colour ends up
         # shipping without ever being checked. Moving them into the palette is only half the fix.
         ('danger button label', DANGER_TEXT, DANGER),
         ('entry text', TEXT, ENTRY_BG),
         ('entry text when locked', MUTED, ENTRY_BG)]

def all_pairs():
    """Every foreground/background pair the app paints, as (label, fg, bg, minimum)."""
    pairs = [(label, rgb(fg), rgb(bg)) for label, fg, bg in PAIRS]
    for kind, (bg, fg) in PILL_KINDS.items():
        pairs.append((f'{kind} pill label', rgb(fg), rgb(bg)))
    return pairs

def failures():
    return [(label, fg, bg, ratio) for label, fg, bg in all_pairs()
            if (ratio := contrast(fg, bg)) < AA_NORMAL]

def main():
    print(f'WCAG AA threshold for normal text: {AA_NORMAL}:1\n')
    print(f'{"pair":<38}{"ratio":>7}  verdict')
    worst = None
    for label, fg, bg in all_pairs():
        ratio = contrast(fg, bg)
        verdict = 'PASS' if ratio >= AA_NORMAL else 'FAIL'
        print(f'{label:<38}{ratio:7.2f}  {verdict}')
        if worst is None or ratio < worst[1]: worst = (label, ratio)
    problems = failures()
    print(f'\nlowest: {worst[0]} at {worst[1]:.2f}:1')
    if problems:
        print(f'\n=== {len(problems)} FAILING PAIR(S) ===')
        for label, fg, bg, ratio in problems:
            print(f'  {label}: {ratio:.2f}:1 (fg={fg} bg={bg})')
        return 1
    print('\nAll pairs meet WCAG AA.')
    return 0

@pytest.mark.notkinter
@pytest.mark.notkinter
class ContrastTests(unittest.TestCase):
    """The audit as part of the suite, so it cannot quietly stop running.

    This file was a script with a main(), which discovery collected but ran no tests from: the suite reported
    a clean result while the contrast check nobody had been shown was not part of it. A colour could be added
    to the palette and never be looked at. It fails the suite now."""

    def test_every_painted_pair_meets_wcag_aa(self):
        problems = failures()
        self.assertEqual(problems, [], '\n'.join(
            f'  {label}: {ratio:.2f}:1 (fg={fg} bg={bg}) - below {AA_NORMAL}:1'
            for label, fg, bg, ratio in problems))

    def test_the_audit_actually_covers_the_pairs(self):
        """A pair list that lost an entry would otherwise pass for ever."""
        self.assertGreaterEqual(len(all_pairs()), len(PAIRS) + len(PILL_KINDS))
        for label, _fg, _bg in PAIRS:
            self.assertIn(label, [pair[0] for pair in all_pairs()])


if __name__ == '__main__':
    sys.exit(main())
