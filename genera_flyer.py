#!/usr/bin/env python3
"""
genera_flyer.py — Genera imagen de turnos disponibles y la envía por mail.

Muestra los turnos libres de HOY a partir del primer turno de la tarde
(14:30 hasta el 31/10/2026, 14:00 desde el 01/11/2026).

Uso:
    python3 genera_flyer.py              # genera imagen, la envía si EMAIL_* está config.
    python3 genera_flyer.py --out f.png  # ruta personalizada
    python3 genera_flyer.py --no-mail    # genera imagen sin enviar mail

Credenciales de mail en /Users/fernandoravagnani/padellive/.env:
    EMAIL_FROM=tucuenta@gmail.com
    EMAIL_PASSWORD=xxxx xxxx xxxx xxxx   # App Password de Google
    EMAIL_TO=destino@gmail.com

Requiere: pip install Pillow requests
"""

import os
import sys
import ssl
import smtplib
import requests
from datetime import datetime, timedelta, timezone

# Siempre hora Argentina (UTC-3), sin importar en qué servidor corra
ART = timezone(timedelta(hours=-3))
def now_art() -> datetime:
    return datetime.now(ART).replace(tzinfo=None)
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── Rutas ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
TEMPLATE   = os.path.join(BASE_DIR, 'public', 'Plantilla turnos.PNG')
if not os.path.exists(TEMPLATE):
    TEMPLATE = os.path.join(BASE_DIR, 'Plantilla turnos.PNG')
OUTPUT_DIR = os.path.join(BASE_DIR, 'flyers')
FONTS_DIR  = os.path.join(BASE_DIR, 'fonts')
FONT_MONO_BOLD = os.path.join(FONTS_DIR, 'ChivoMonoExtraBold.ttf')
FONT_MONO      = os.path.join(FONTS_DIR, 'ChivoMonoMedium.ttf')
FONT_DATE      = os.path.join(FONTS_DIR, 'ArchivoExtraBold.ttf')

# ── API ───────────────────────────────────────────────────────────────────────
API_URL = 'https://admin-reservas-seven.vercel.app/exec'
# Grilla de turnos (90 min) según la fecha. Cada entrada rige desde 'desde' (inclusive)
# hasta que empieza la siguiente. Mantener igual en api/exec.js e index.html.
HORARIOS = [
    {'desde': '0000-01-01', 'inicio_flyer': '14:30',
     'slots': ['09:30','11:00','12:30','14:30','16:00','17:30','19:00','20:30','22:00']},
    {'desde': '2026-11-01', 'inicio_flyer': '14:00',
     'slots': ['09:30','11:00','12:30','14:00','15:30','17:00','18:30','20:00','21:30','23:00']},
]
DIAS_FDS    = ['SÁBADO', 'DOMINGO']
DIAS_SEMANA = ['LUNES', 'MARTES', 'MIÉRCOLES', 'JUEVES', 'VIERNES', 'SÁBADO', 'DOMINGO']
MONTH_NAMES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']

def horario_for_date(fecha: str) -> dict:
    return [h for h in HORARIOS if h['desde'] <= fecha][-1]

def hora_inicio_hoy() -> str:
    """Primer turno a incluir en el flyer de hoy."""
    return horario_for_date(now_art().strftime('%Y-%m-%d'))['inicio_flyer']

# ── Diseño "Marcador" (plantilla 814×1446, ver scripts/build_plantilla.py) ────
ROWS_Y1, ROWS_Y2 = 480, 1056          # zona de filas dentro de la pizarra
COL_X  = (92, 371, 551)               # HORA · HASTA · ESTADO
ROW_X2 = 722

# ── Colores ───────────────────────────────────────────────────────────────────
BG       = (15, 15, 13)
IVORY    = (242, 238, 227)
AMBER    = (255, 178, 26)
GREY     = (138, 134, 122)
UNTIL    = (183, 178, 165)
ROW_LINE = (36, 36, 31)
FLAP_TOP = (38, 38, 31)
FLAP_BOT = (28, 28, 24)
DIM_TXT  = (74, 72, 64)
DIM_ST   = (111, 107, 96)


# ── Cargar .env ───────────────────────────────────────────────────────────────
def load_env(path: str) -> None:
    """Carga variables de entorno desde un archivo .env simple."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, val = line.partition('=')
            os.environ.setdefault(key.strip(), val.strip())


# ── Helpers ───────────────────────────────────────────────────────────────────
def _slot_end(fecha: str, hora: str) -> datetime:
    y, m, d = map(int, fecha.split('-'))
    h, mn   = map(int, hora.split(':'))
    return datetime(y, m, d, h, mn) + timedelta(minutes=90)

def turno_finalizado(fecha: str, hora: str) -> bool:
    return now_art() > _slot_end(fecha, hora)

def turno_en_curso(fecha: str, hora: str) -> bool:
    ini = _slot_end(fecha, hora) - timedelta(minutes=90)
    return ini <= now_art() <= _slot_end(fecha, hora)

def get_price(precios, dia: str, hora: str) -> int:
    if not precios:
        return 20000
    bloque = precios.get('finDeSemana' if dia in DIAS_FDS else 'semana', {})
    return bloque.get(hora, 20000)

def fmt_price(n: int) -> str:
    return f"${n:,}".replace(",", ".")


# ── Fetch API ─────────────────────────────────────────────────────────────────
def fetch_api() -> dict:
    resp = requests.get(f"{API_URL}?action=getTodo", timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data.get('success'):
        raise RuntimeError(data.get('error', 'API devolvió error'))
    return data['data']

def get_libre_slots(api_data: dict) -> list:
    """Devuelve los turnos libres de HOY a partir del inicio del flyer."""
    precios = api_data.get('precios')
    hoy     = now_art().date()
    slots   = []

    for day in api_data.get('week', []):
        fecha = f"{day['year']}-{day['month'].zfill(2)}-{day['date'].zfill(2)}"
        if datetime.strptime(fecha, '%Y-%m-%d').date() != hoy:
            continue
        horario = horario_for_date(fecha)
        for hora in horario['slots']:
            if hora < horario['inicio_flyer']:
                continue
            if turno_en_curso(fecha, hora) or turno_finalizado(fecha, hora):
                continue
            if day['slots'].get(hora):
                continue
            slots.append({
                'dia'   : day['day'],
                'fecha' : fecha,
                'date'  : day['date'],
                'month' : day['month'],
                'hora'  : hora,
                'precio': get_price(precios, day['day'], hora),
            })
    return slots


# ── Generar imagen ────────────────────────────────────────────────────────────
def _spaced(draw, x, baseline, text, fnt, fill, tracking, align='left'):
    """Texto con letter-spacing en px, anclado a la línea base."""
    widths = [fnt.getlength(ch) for ch in text]
    total  = sum(widths) + tracking * (len(text) - 1)
    if align == 'right':
        x -= total
    for ch, w in zip(text, widths):
        draw.text((x, baseline), ch, font=fnt, fill=fill, anchor='ls')
        x += w + tracking

def _cap_baseline(fnt, cy):
    """Línea base que centra verticalmente mayúsculas/dígitos en cy."""
    top = fnt.getbbox('0', anchor='ls')[1]
    return cy - top / 2

def _draw_flaps(draw, x, cy, hora, size, color):
    """Hora en fichas tipo pizarra de aeropuerto; x = borde izquierdo."""
    fnt   = ImageFont.truetype(FONT_MONO_BOLD, size)
    tile_w, tile_h = 0.7 * size, 1.24 * size
    top   = cy - tile_h / 2
    split = max(2, round(tile_h * 0.016))
    base  = _cap_baseline(fnt, cy)
    for ch in hora:
        if ch == ':':
            w = 0.32 * size
            draw.text((x + w / 2, base), ':', font=fnt, fill=GREY, anchor='ms')
            x += w
            continue
        box = [x, top, x + tile_w, top + tile_h]
        r   = 0.08 * size
        draw.rounded_rectangle(box, radius=r, fill=FLAP_BOT)
        draw.rounded_rectangle([x, top, x + tile_w, cy], radius=r, fill=FLAP_TOP, corners=(True, True, False, False))
        draw.rectangle([x, cy - split / 2, x + tile_w, cy + split / 2], fill=BG)
        draw.text((x + tile_w / 2, base), ch, font=fnt, fill=color, anchor='ms')
        x += tile_w + 0.07 * size

def _draw_dot(img, cx, cy, color, glow):
    r = 7
    if glow:
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse([cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4], fill=color + (150,))
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(8)))
    ImageDraw.Draw(img).ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

def generate_flyer(slots: list, output_path: str) -> None:
    img  = Image.open(TEMPLATE).convert('RGBA')
    draw = ImageDraw.Draw(img)

    # Fecha del día entre el título y la pizarra: "SÁBADO 17 DE OCTUBRE"
    hoy   = now_art()
    dia   = slots[0]['dia'] if slots else DIAS_SEMANA[hoy.weekday()]
    label = f"{dia} {hoy.day} DE {MONTH_NAMES[hoy.month - 1].upper()}"
    size_f = 44
    while True:   # achicar si no entra en el ancho (ej. MIÉRCOLES 30 DE SEPTIEMBRE)
        fnt_f = ImageFont.truetype(FONT_DATE, size_f)
        if fnt_f.getlength(label) + (len(label) - 1) <= 694 or size_f <= 28:
            break
        size_f -= 2
    _spaced(draw, 60, 388, label, fnt_f, IVORY, 1)

    n = len(slots)
    if n:
        rows = [(s['hora'], _slot_end(s['fecha'], s['hora']).strftime('%H:%M'), 'LIBRE') for s in slots]
        # hasta 8 turnos entran en la pizarra (576 px de alto)
        size = 74 if n <= 3 else 64 if n <= 5 else 52 if n <= 6 else 46
        pad  = 26 if n <= 3 else 14 if n <= 6 else 6
    else:
        rows = [('--:--', '--:--', 'COMPLETO')] * 3
        size, pad = 70, 22

    tile_h = 1.24 * size
    row_h  = 2 + 2 * pad + tile_h
    y      = ROWS_Y1 + max(0, (ROWS_Y2 - ROWS_Y1 - row_h * len(rows)) / 2)

    fnt_until = ImageFont.truetype(FONT_MONO, 30 if n <= 6 else 26)
    fnt_state = ImageFont.truetype(FONT_MONO_BOLD, 26 if n <= 6 else 22)
    for hora, hasta, estado in rows:
        draw.rectangle([COL_X[0], y, ROW_X2, y + 1], fill=ROW_LINE)
        cy = y + 2 + pad + tile_h / 2
        _draw_flaps(draw, COL_X[0], cy, hora, size, IVORY if n else DIM_TXT)
        draw.text((COL_X[1], _cap_baseline(fnt_until, cy)), hasta, font=fnt_until,
                  fill=UNTIL if n else DIM_TXT, anchor='ls')
        st_color = AMBER if n else DIM_ST
        _draw_dot(img, COL_X[2] + 7, cy, st_color, glow=bool(n))
        draw = ImageDraw.Draw(img)
        _spaced(draw, COL_X[2] + 24, _cap_baseline(fnt_state, cy), estado, fnt_state, st_color, 2.6)
        y += row_h

    _save(img, output_path)
    print(f"✓ Imagen generada: {output_path}")

def _save(img, path: str) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    img.save(path)


# ── Enviar mail ───────────────────────────────────────────────────────────────
def send_mail(image_path: str, slots: list) -> None:
    email_from = os.environ.get('EMAIL_FROM', '').strip()
    email_pass = os.environ.get('EMAIL_PASSWORD', '').strip()
    email_to   = os.environ.get('EMAIL_TO', '').strip()

    if not all([email_from, email_pass, email_to]):
        print("⚠️  Mail no configurado (falta EMAIL_FROM / EMAIL_PASSWORD / EMAIL_TO en .env)")
        return

    hoy      = now_art()
    dia_str  = hoy.strftime('%d/%m/%Y')
    n_libres = len(slots)

    if n_libres == 0:
        asunto  = f"Negro Padel — Sin turnos disponibles ({dia_str})"
        cuerpo  = f"No hay turnos disponibles para hoy {dia_str} desde las {hora_inicio_hoy()}."
    else:
        horas   = ', '.join(s['hora'] for s in slots)
        asunto  = f"Negro Padel — {n_libres} turno(s) disponible(s) hoy ({dia_str})"
        cuerpo  = (
            f"Turnos libres para hoy {dia_str} desde las {hora_inicio_hoy()}:\n\n"
            + '\n'.join(f"  • {s['hora']}  —  {fmt_price(s['precio'])}" for s in slots)
            + f"\n\nEl flyer está adjunto."
        )

    # Armar el mensaje
    msg = MIMEMultipart()
    msg['From']    = email_from
    msg['To']      = email_to
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))

    # Adjuntar imagen
    if n_libres > 0 and os.path.exists(image_path):
        with open(image_path, 'rb') as f:
            part = MIMEBase('image', 'png')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        filename = os.path.basename(image_path)
        part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
        msg.attach(part)

    # Enviar via Gmail SMTP
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as server:
        server.login(email_from, email_pass)
        server.sendmail(email_from, email_to, msg.as_string())

    print(f"✓ Mail enviado a {email_to}")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    load_env(os.path.join(BASE_DIR, '.env'))

    no_mail = '--no-mail' in sys.argv

    out = None
    if '--out' in sys.argv:
        idx = sys.argv.index('--out')
        if idx + 1 < len(sys.argv):
            out = sys.argv[idx + 1]
    if out is None:
        fecha_hoy = now_art().strftime('%Y-%m-%d')
        out = os.path.join(OUTPUT_DIR, f'turnos_{fecha_hoy}.png')

    print(f"[{now_art().strftime('%Y-%m-%d %H:%M')}] Iniciando generación de flyer...")
    try:
        api_data = fetch_api()
        slots    = get_libre_slots(api_data)
        print(f"Turnos libres hoy desde {hora_inicio_hoy()}: {len(slots)}")

        generate_flyer(slots, out)

        if not no_mail:
            send_mail(out, slots)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        # Intentar avisar por mail aunque haya fallado
        if not no_mail:
            try:
                load_env(os.path.join(BASE_DIR, '.env'))
                email_from = os.environ.get('EMAIL_FROM', '')
                email_pass = os.environ.get('EMAIL_PASSWORD', '')
                email_to   = os.environ.get('EMAIL_TO', '')
                if all([email_from, email_pass, email_to]):
                    msg = MIMEMultipart()
                    msg['From']    = email_from
                    msg['To']      = email_to
                    msg['Subject'] = 'Negro Padel — Error al generar flyer'
                    msg.attach(MIMEText(f"Error: {e}", 'plain'))
                    ctx = ssl.create_default_context()
                    with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ctx) as srv:
                        srv.login(email_from, email_pass)
                        srv.sendmail(email_from, email_to, msg.as_string())
            except Exception:
                pass
        sys.exit(1)
