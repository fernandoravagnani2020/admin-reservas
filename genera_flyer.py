#!/usr/bin/env python3
"""
genera_flyer.py — Genera imagen de turnos disponibles y la envía por mail.

Muestra los turnos libres de HOY a partir de las 14:30.

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
from PIL import Image, ImageDraw, ImageFont

# ── Rutas ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
TEMPLATE   = os.path.join(BASE_DIR, 'public', 'Plantilla turnos.PNG')
if not os.path.exists(TEMPLATE):
    TEMPLATE = os.path.join(BASE_DIR, 'Plantilla turnos.PNG')
OUTPUT_DIR = os.path.join(BASE_DIR, 'flyers')
FONT_BLACK = os.environ.get('FONT_BLACK', '/Users/fernandoravagnani/Library/Fonts/CamptonBlack.otf')
FONT_BOLD  = os.environ.get('FONT_BOLD',  '/Users/fernandoravagnani/Library/Fonts/CamptonBold.otf')

# ── API ───────────────────────────────────────────────────────────────────────
API_URL = (
    'https://script.google.com/macros/s/'
    'AKfycbyd4O4dWAUnUgGeyok35PCeGSRAbxLu4uLfh6_WQQiOYSREVlkX6Dpru7sI3Fiuusn0/exec'
)
TIME_SLOTS  = ['09:30','11:00','12:30','14:30','16:00','17:30','19:00','20:30','22:00']
DIAS_FDS    = ['SÁBADO', 'DOMINGO']
MONTH_NAMES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']

HORA_INICIO = '14:30'   # primer turno a incluir en el flyer

# ── Área de la grilla en la plantilla (814×1446 px) ───────────────────────────
GRID = dict(x1=60, y1=220, x2=754, y2=1062)
GRID_W = GRID['x2'] - GRID['x1']
GRID_H = GRID['y2'] - GRID['y1']
PAD_X  = 50
PAD_Y  = 30

# ── Colores ───────────────────────────────────────────────────────────────────
LIME    = (195, 249, 80)
WHITE   = (255, 255, 255)
DIVIDER = (60, 88, 62)


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
    """Devuelve los turnos libres de HOY a partir de HORA_INICIO."""
    precios = api_data.get('precios')
    hoy     = now_art().date()
    slots   = []

    for day in api_data.get('week', []):
        fecha = f"{day['year']}-{day['month'].zfill(2)}-{day['date'].zfill(2)}"
        if datetime.strptime(fecha, '%Y-%m-%d').date() != hoy:
            continue
        for hora in TIME_SLOTS:
            if hora < HORA_INICIO:
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
def generate_flyer(slots: list, output_path: str) -> None:
    img  = Image.open(TEMPLATE).convert('RGBA')
    draw = ImageDraw.Draw(img)
    cx   = GRID['x1'] + GRID_W // 2

    if not slots:
        fnt = ImageFont.truetype(FONT_BOLD, 38)
        draw.text(
            (cx, GRID['y1'] + GRID_H // 2),
            'SIN TURNOS\nDISPONIBLES',
            font=fnt, fill=LIME, anchor='mm', align='center',
        )
        _save(img, output_path)
        return

    s0          = slots[0]
    mes         = MONTH_NAMES[int(s0['month']) - 1]
    fecha_label = f"{s0['dia']}  {s0['date']} DE {mes.upper()}"

    n_rows = 1 + len(slots)
    area_h = GRID_H - PAD_Y * 2

    if len(slots) <= 3:
        sz_fecha, sz_hora, sz_hs = 38, 72, 36
    elif len(slots) <= 5:
        sz_fecha, sz_hora, sz_hs = 34, 62, 30
    else:
        sz_fecha, sz_hora, sz_hs = 30, 52, 26

    row_h   = min(area_h // n_rows, 120)
    total_h = n_rows * row_h
    y       = GRID['y1'] + PAD_Y + max(0, (area_h - total_h) // 2)
    x_left  = GRID['x1'] + PAD_X
    x_right = GRID['x2'] - PAD_X

    fnt_fecha = ImageFont.truetype(FONT_BOLD,  sz_fecha)
    fnt_hora  = ImageFont.truetype(FONT_BLACK, sz_hora)
    fnt_hs    = ImageFont.truetype(FONT_BOLD,  sz_hs)

    # Header de fecha
    draw.text((cx, y + row_h // 2), fecha_label, font=fnt_fecha, fill=LIME, anchor='mm')
    y += row_h
    draw.line([(x_left, y - 6), (x_right, y - 6)], fill=DIVIDER, width=1)

    # Filas de turnos — centradas con "HS" al lado
    for slot in slots:
        cy = y + row_h // 2
        # Medir ancho total de "HH:MM HS" para centrarlo como bloque
        w_hora = fnt_hora.getlength(slot['hora'])
        w_sep  = fnt_hs.getlength(' ')
        w_hs   = fnt_hs.getlength('HS')
        total_w = w_hora + w_sep + w_hs
        x_hora = cx - total_w / 2
        x_hs   = x_hora + w_hora + w_sep
        draw.text((x_hora, cy), slot['hora'], font=fnt_hora, fill=WHITE, anchor='lm')
        draw.text((x_hs,   cy), 'HS',         font=fnt_hs,  fill=LIME,  anchor='lm')
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
        cuerpo  = f"No hay turnos disponibles para hoy {dia_str} desde las {HORA_INICIO}."
    else:
        horas   = ', '.join(s['hora'] for s in slots)
        asunto  = f"Negro Padel — {n_libres} turno(s) disponible(s) hoy ({dia_str})"
        cuerpo  = (
            f"Turnos libres para hoy {dia_str} desde las {HORA_INICIO}:\n\n"
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
        print(f"Turnos libres hoy desde {HORA_INICIO}: {len(slots)}")

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
