#!/usr/bin/env python3
"""
build_plantilla.py — Genera 'Plantilla turnos.PNG' (diseño "Marcador", 814×1446).

Dibuja solo la parte fija: título, marco de la pizarra, encabezado de columnas,
botones y logo. La fecha y las filas de turnos las dibujan genera_flyer.py y
generarImagenFlyer() en index.html.

Uso:
    python3 scripts/build_plantilla.py

Requiere: pip install Pillow
"""

import os
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS    = os.path.join(BASE_DIR, 'fonts')
OUT      = os.path.join(BASE_DIR, 'Plantilla turnos.PNG')
LOGO     = os.path.join(BASE_DIR, 'assets', 'logo-negro.png')

W, H = 814, 1446

BG     = (15, 15, 13)
PANEL  = (22, 22, 19)
EDGE   = (42, 42, 37)
IVORY  = (242, 238, 227)
AMBER  = (255, 178, 26)
GREY   = (138, 134, 122)

def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)

def spaced(draw, xy, text, fnt, fill, tracking, align='left'):
    """Texto con letter-spacing (en px). xy = (x, baseline)."""
    widths = [fnt.getlength(ch) for ch in text]
    total  = sum(widths) + tracking * (len(text) - 1)
    x, y   = xy
    if align == 'center':
        x -= total / 2
    elif align == 'right':
        x -= total
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=fnt, fill=fill, anchor='ls')
        x += w + tracking


def build():
    img  = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)

    mono = font('ChivoMonoMedium.ttf', 20)

    # Franja superior
    spaced(draw, (60, 86), 'NEGRO PÁDEL', mono, AMBER, 2.8)
    spaced(draw, (754, 86), 'TURNOS DE 90 MIN', mono, GREY, 2.8, align='right')
    draw.rectangle([60, 104, 754, 105], fill=EDGE)

    # Título
    draw.text((56, 250), 'TURNOS', font=font('ArchivoCondensedBlack.ttf', 158), fill=IVORY, anchor='ls')
    spaced(draw, (62, 322), 'LIBRES HOY', font('ArchivoExtraBold.ttf', 62), AMBER, 1.2)

    # La fecha del día (y≈394) la dibuja cada flyer, entre el título y la pizarra

    # Pizarra
    draw.rounded_rectangle([60, 420, 754, 1082], radius=10, fill=PANEL, outline=EDGE, width=2)
    head = font('ChivoMonoMedium.ttf', 19)
    for x, label in ((92, 'HORA'), (371, 'HASTA'), (551, 'ESTADO')):
        spaced(draw, (x, 464), label, head, GREY, 2.7)

    # Botón "Reservá tu turno" (izquierda) + espacio en blanco para el sticker de link de Instagram
    draw.rounded_rectangle([60, 1126, 390, 1202], radius=8, fill=IVORY)
    spaced(draw, (225, 1172), 'RESERVÁ TU TURNO →', font('ArchivoExtraBold.ttf', 21), BG, 2.0, align='center')
    draw.rounded_rectangle([406, 1126, 754, 1202], radius=8, fill=IVORY)

    # WhatsApp
    spaced(draw, (407, 1248), 'ESCRIBINOS POR WHATSAPP', mono, AMBER, 2.8, align='center')

    # Logo
    logo = Image.open(LOGO).convert('RGBA')
    lh   = 70
    lw   = round(logo.width * lh / logo.height)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    img.paste(logo, ((W - lw) // 2, 1316), logo)

    img.save(OUT)
    print(f'✓ Plantilla generada: {OUT}')


if __name__ == '__main__':
    build()
