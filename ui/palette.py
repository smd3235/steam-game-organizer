"""Colour palette, kept free of any tkinter import.

The contrast audit in tests/test_contrast.py is pure WCAG arithmetic and must be able to run where there is no
display or no tkinter at all. Keeping the values here means theme.py and the audit read one definition, and a
colour can never pass review in the audit while differing from the colour the UI actually paints.
"""

BG="#0f1117"; PANEL="#171b24"; PANEL2="#1e2430"; PANEL3="#252d3a"
TEXT="#f4f7fb"; MUTED="#9aa6b7"; BORDER="#303949"

# ACCENT is darkened and its hover is kept deliberately shallow. The old #7c5cff gave white text only 4.35:1,
# and hovering lightened it to #9b82ff at 2.99:1, so the primary button's label became hard to read exactly
# when the user moved onto it. Both now clear WCAG AA (4.5:1) for small bold text.
ACCENT="#7353f5"; ACCENT_HOVER="#785af7"; ACCENT_HI="#9b82ff"
CYAN="#39c6d8"; GREEN="#48d597"; ORANGE="#ffb454"; RED="#ff667d"

# Chart fills for the category breakdown. These are fills rather than text, but they still get contrast-audited
# against the track they sit on, because a bar nobody can distinguish from its background reads as no data.
PINK="#f472b6"; SKY="#38bdf8"

# Chart fill rotation, ordered so adjacent categories stay distinguishable.
CHART_COLORS=(ACCENT,CYAN,GREEN,ORANGE,PINK,SKY)

# Pill label colours: each pairs a fill with the text drawn on it, and each pair is contrast-audited.
PILL_KINDS={"accent":(ACCENT,"white"),"good":(GREEN,"#071b12"),"warn":(ORANGE,"#211705"),"bad":(RED,"#260a10"),"info":(CYAN,"#061b20"),"muted":(PANEL3,MUTED)}

# The destructive button and the text entry. These were typed straight into theme.py, which is the only place a
# theme colour could avoid the contrast audit and the palette - a colour nobody could find or change in one
# place. DANGER is a dark red panel rather than RED itself so that RED, which is a text colour, stays legible on
# BG; the pair is audited against each other by tests/test_contrast.py.
DANGER="#48202b"; DANGER_HOVER="#602b39"; DANGER_TEXT="#ffb2bd"
ENTRY_BG="#11151c"