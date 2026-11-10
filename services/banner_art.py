"""Generated category banner art for the offline HTML catalog.

The catalog is built to make no external requests, so banners are drawn here as inline SVG data URIs rather
than downloaded. That also means there is no licence to track and no attribution file to keep correct: the art
is produced from the category name, so it is stable across regenerations and identical on every machine.

Real game artwork still wins where it exists. This is the layer underneath, which guarantees every category has
a distinct banner even when no game in it has ever had art fetched.
"""
from __future__ import annotations

import hashlib
from urllib.parse import quote

WIDTH, HEIGHT = 1200, 300

# Hue anchors. Each banner picks two by hash so adjacent categories never land on the same gradient. The list
# is long enough that two unrelated names landing on an identical pair is vanishingly unlikely; with a 12-entry
# list "Adventure" and "Indie" collided outright.
_HUES=(212, 268, 322, 18, 42, 96, 140, 186, 246, 292, 340, 66,
       200, 232, 254, 280, 305, 350, 8, 30, 58, 78, 118, 158)


def _seed(name:str)->int:
    """Stable per category. Uses the name only, so renaming a category changes its art deliberately."""
    return int(hashlib.sha256(str(name).strip().casefold().encode('utf-8')).hexdigest()[:12], 16)


def _hsl_to_hex(hue:float,saturation:float,lightness:float)->str:
    hue=hue%360
    chroma=(1-abs(2*lightness-1))*saturation
    secondary=chroma*(1-abs((hue/60)%2-1))
    steam_match=int(hue//60)%6
    table=[(chroma,secondary,0),(secondary,chroma,0),(0,chroma,secondary),(0,secondary,chroma),(secondary,0,chroma),(chroma,0,secondary)]
    red,green,blue=table[steam_match]
    offset=lightness-chroma/2
    return '#%02x%02x%02x'%tuple(max(0,min(255,round((channel+offset)*255))) for channel in (red,green,blue))


def _motif(seed:int,accent:str)->str:
    """One of several geometric treatments, chosen by hash, all drawn behind the category name."""
    kind=seed%5
    parts=[]
    if kind==0:                                   # concentric rings
        for step in range(7):
            radius=34+step*46
            parts.append(f'<circle cx="{940-step*8}" cy="40" r="{radius}" fill="none" stroke="{accent}" stroke-opacity="{0.46-step*0.045:.2f}" stroke-width="{2 if step%2 else 6}"/>')
    elif kind==1:                                 # diagonal ribbons
        for step in range(16):
            offset=step*84-260
            parts.append(f'<path d="M{offset} {HEIGHT} L{offset+300} 0" stroke="{accent}" stroke-opacity="{0.09+0.08*(step%3):.2f}" stroke-width="{6+(step%4)*9}"/>')
    elif kind==2:                                 # dot field, denser toward the right
        for row in range(7):
            for column in range(20):
                radius=1.5+((row*20+column+seed)%4)
                parts.append(f'<circle cx="{34+column*58}" cy="{24+row*40}" r="{radius}" fill="{accent}" fill-opacity="0.50"/>')
    elif kind==3:                                 # mountain peaks
        for step in range(5):
            base=HEIGHT-18-step*26
            span=300+step*90
            parts.append(f'<path d="M{-40+step*150} {HEIGHT} L{span/2+step*150} {base} L{span+step*150} {HEIGHT} Z" fill="{accent}" fill-opacity="{0.26-step*0.038:.2f}"/>')
    else:                                         # isometric grid
        for step in range(26):
            offset=step*54
            parts.append(f'<path d="M{offset} {HEIGHT} L{WIDTH*0.35+offset} 0" stroke="{accent}" stroke-opacity="0.15" stroke-width="2"/>')
            parts.append(f'<path d="M{WIDTH-offset} {HEIGHT} L{WIDTH*0.65-offset} 0" stroke="{accent}" stroke-opacity="0.15" stroke-width="2"/>')
    return ''.join(parts)


def banner_svg(name:str)->str:
    """A wide, colourful banner. Bright enough that two categories do not read as the same dark smear: the
    sheet's own scrim darkens the lower band the category name sits on, so the art underneath is free to be
    light. The previous values were tuned for a title drawn directly on the art, and left every banner close
    to black once the scrim was applied on top."""
    seed=_seed(name)
    base=_HUES[seed%len(_HUES)]
    partner=_HUES[(seed//len(_HUES))%len(_HUES)]
    if partner==base: partner=_HUES[(seed//len(_HUES)+7)%len(_HUES)]
    accent=_hsl_to_hex(partner,0.66,0.68)
    top=_hsl_to_hex(base,0.55,0.44)
    bottom=_hsl_to_hex((base+26)%360,0.64,0.21)
    # Gradient angle and glow position vary too, so even an identical hue pair still yields different art.
    angle=15+(seed>>7)%75
    gx=52+(seed>>11)%42
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}">'
        f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0.4" y2="1" gradientTransform="rotate({angle} 0.5 0.5)">'
        f'<stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>'
        f'<radialGradient id="glow" cx="{gx/100:.2f}" cy="0.18" r="0.7">'
        f'<stop offset="0" stop-color="{accent}" stop-opacity="0.46"/><stop offset="1" stop-color="{accent}" stop-opacity="0"/>'
        f'</radialGradient></defs>'
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#bg)"/>'
        f'{_motif(seed,accent)}'
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="url(#glow)"/>'
        f'</svg>')


def banner_data_uri(name:str)->str:
    """Percent-encoded so the '#' in hex colours and the quotes cannot break out of the CSS url() it sits in."""
    return 'data:image/svg+xml,'+quote(banner_svg(name),safe='')