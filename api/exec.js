// ============================================================
// Negro Padel · Backend /exec  (Vercel Serverless Function)
// Replica EXACTAMENTE el contrato del viejo Google Apps Script,
// pero contra Postgres (Supabase) vía su API REST (PostgREST).
// El frontend y PadelLive solo apuntan a esta URL; nada más cambia.
// ============================================================

const SB  = process.env.SUPABASE_URL;
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

const SLOTS = ['09:30','11:00','12:30','14:30','16:00','17:30','19:00','20:30','22:00'];
// getUTCDay(): 0=Domingo .. 6=Sábado
const DIAS_BY_DOW = ['DOMINGO','LUNES','MARTES','MIÉRCOLES','JUEVES','VIERNES','SÁBADO'];
const pad = (n) => String(n).padStart(2, '0');

// ── Cliente REST mínimo contra Supabase ──
async function rest(path, { method = 'GET', body, prefer } = {}) {
  const headers = { apikey: KEY, Authorization: `Bearer ${KEY}` };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (prefer) headers['Prefer'] = prefer;
  const r = await fetch(`${SB}/rest/v1/${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await r.text();
  if (!r.ok) throw new Error(`DB ${r.status}: ${text}`);
  return text ? JSON.parse(text) : null;
}
const upsert = (table, onConflict, rows) =>
  rest(`${table}?on_conflict=${onConflict}`, {
    method: 'POST', body: rows,
    prefer: 'resolution=merge-duplicates,return=minimal',
  });

// ── Helpers de respuesta (mismo formato que el Apps Script) ──
function send(res, payload, status = 200) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.status(status).json(payload);
}
const ok  = (res, data) => send(res, { success: true, data });
const err = (res, message) => send(res, { success: false, error: String(message) });

// Lee el body aunque venga sin Content-Type (como lo manda el frontend).
async function readBody(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string' && req.body.trim()) {
    try { return JSON.parse(req.body); } catch { return {}; }
  }
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const raw = Buffer.concat(chunks).toString('utf8').trim();
  if (!raw) return {};
  try { return JSON.parse(raw); } catch { return {}; }
}

// Fecha de hoy en horario de Córdoba (Argentina).
function getArgToday() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Argentina/Cordoba',
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date()).reduce((a, p) => (a[p.type] = p.value, a), {});
  return { y: +parts.year, m: +parts.month, d: +parts.day };
}

// ── getTurnos: arma la semana de 7 días desde hoy ──
async function getTurnos(res) {
  const { y, m, d } = getArgToday();
  const base = Date.UTC(y, m - 1, d);
  const days = [];
  for (let i = 0; i < 7; i++) {
    const dt = new Date(base + i * 86400000);
    days.push({
      dia: DIAS_BY_DOW[dt.getUTCDay()],
      dateKey: `${dt.getUTCFullYear()}-${pad(dt.getUTCMonth() + 1)}-${pad(dt.getUTCDate())}`,
      date: String(dt.getUTCDate()),
      month: String(dt.getUTCMonth() + 1),
      year: String(dt.getUTCFullYear()),
    });
  }

  const desde = days[0].dateKey;
  const hasta = days[6].dateKey;

  const [reservas, fijos] = await Promise.all([
    rest(`reservas?select=fecha,hora,nombre&fecha=gte.${desde}&fecha=lte.${hasta}`),
    rest(`turnos_fijos?select=dia_semana,hora,nombre`),
  ]);

  // Fijos agrupados por día de la semana.
  const fixedSlotsByDay = {};
  for (const f of fijos || []) {
    (fixedSlotsByDay[f.dia_semana] ||= {})[f.hora] = f.nombre;
  }

  // Reservas concretas indexadas por fecha.
  const byFecha = {};
  for (const r of reservas || []) {
    (byFecha[r.fecha] ||= {})[r.hora] = r.nombre;
  }

  const week = days.map((day) => {
    const slots = { ...(byFecha[day.dateKey] || {}) };
    // Proyectar los turnos fijos del día sobre la semana (si no hay otra reserva encima).
    const fijosDelDia = fixedSlotsByDay[day.dia] || {};
    for (const [hora, nombre] of Object.entries(fijosDelDia)) {
      if (!slots[hora]) slots[hora] = nombre;
    }
    return {
      day: day.dia, date: day.date, month: day.month, year: day.year,
      dateKey: day.dateKey, slots,
    };
  });

  return ok(res, { week, fixedSlotsByDay });
}

// ── Reservas ──
async function agregarReserva(res, body) {
  const { dateKey, time, name, isFixed } = body;
  if (!dateKey || !time || !name) throw new Error('Faltan datos de la reserva');
  await upsert('reservas', 'fecha,hora',
    { fecha: dateKey, hora: time, nombre: name, es_fijo: !!isFixed });
  return ok(res, { message: 'Reserva agregada' });
}

async function eliminarReserva(res, body) {
  const { dateKey, day, time, isFixed } = body;
  if (!dateKey || !time) throw new Error('Faltan datos de la reserva');
  await rest(`reservas?fecha=eq.${dateKey}&hora=eq.${encodeURIComponent(time)}`, { method: 'DELETE' });
  // Si era fijo, también se deja de repetir hacia adelante.
  if (isFixed && day) {
    await rest(`turnos_fijos?dia_semana=eq.${encodeURIComponent(day)}&hora=eq.${encodeURIComponent(time)}`, { method: 'DELETE' });
  }
  return ok(res, { message: 'Reserva eliminada' });
}

async function toggleTurnoFijo(res, body) {
  const { day, time, name, isCurrentlyFixed } = body;
  if (!day || !time) throw new Error('Faltan datos del turno');
  if (isCurrentlyFixed) {
    await rest(`turnos_fijos?dia_semana=eq.${encodeURIComponent(day)}&hora=eq.${encodeURIComponent(time)}`, { method: 'DELETE' });
    return ok(res, { message: 'Turno fijo quitado' });
  }
  if (!name) throw new Error('Falta el nombre del turno fijo');
  await upsert('turnos_fijos', 'dia_semana,hora', { dia_semana: day, hora: time, nombre: name });
  return ok(res, { message: 'Turno marcado como fijo' });
}

// ── Precios / descuento ──
async function getPrecios(res) {
  const data = await rest(`config?select=clave,valor&clave=in.(precios,descuento)`);
  const map = Object.fromEntries((data || []).map((r) => [r.clave, r.valor]));
  return ok(res, {
    precios: map.precios || { semana: {}, finDeSemana: {} },
    descuento: map.descuento || { activo: false, porcentaje: 10, minutosAntes: 90 },
  });
}

async function guardarPrecios(res, body) {
  const { precios, descuento } = body;
  const rows = [];
  if (precios)   rows.push({ clave: 'precios', valor: precios });
  if (descuento) rows.push({ clave: 'descuento', valor: descuento });
  if (rows.length) await upsert('config', 'clave', rows);
  return ok(res, { message: 'Precios guardados' });
}

// ── Promociones ──
async function getPromociones(res) {
  const data = await rest(`config?select=valor&clave=eq.promociones`);
  return ok(res, data?.[0]?.valor || {});
}

async function guardarPromociones(res, body) {
  await upsert('config', 'clave', { clave: 'promociones', valor: body.promociones || {} });
  return ok(res, { message: 'Promociones guardadas' });
}

// ── Limpiezas ──
async function limpiarReservasNormales(res) {
  const fijos = await rest(`turnos_fijos?select=dia_semana,hora`);
  const fijoSet = new Set((fijos || []).map((f) => `${f.dia_semana}|${f.hora}`));

  const reservas = await rest(`reservas?select=id,fecha,hora`);
  const idsABorrar = (reservas || []).filter((r) => {
    const [Y, M, D] = r.fecha.split('-').map(Number);
    const dia = DIAS_BY_DOW[new Date(Date.UTC(Y, M - 1, D)).getUTCDay()];
    return !fijoSet.has(`${dia}|${r.hora}`);
  }).map((r) => r.id);

  if (idsABorrar.length) {
    await rest(`reservas?id=in.(${idsABorrar.join(',')})`, { method: 'DELETE' });
  }
  return ok(res, { message: `Eliminadas ${idsABorrar.length} reservas normales` });
}

async function limpiarTodo(res) {
  await rest(`reservas?id=gte.0`, { method: 'DELETE' });
  await rest(`turnos_fijos?id=gte.0`, { method: 'DELETE' });
  return ok(res, { message: 'Todo eliminado' });
}

// ── Router ──
module.exports = async function handler(req, res) {
  if (req.method === 'OPTIONS') return send(res, {}, 204);

  const action = (req.query && req.query.action) ||
    new URL(req.url, 'http://x').searchParams.get('action');

  try {
    switch (action) {
      // Lecturas (GET)
      case 'getTurnos':                return await getTurnos(res);
      case 'getPrecios':               return await getPrecios(res);
      case 'getPromociones':           return await getPromociones(res);
      // Escrituras (POST)
      case 'agregarReserva':           return await agregarReserva(res, await readBody(req));
      case 'eliminarReserva':          return await eliminarReserva(res, await readBody(req));
      case 'toggleTurnoFijo':          return await toggleTurnoFijo(res, await readBody(req));
      case 'guardarPrecios':           return await guardarPrecios(res, await readBody(req));
      case 'guardarPromociones':       return await guardarPromociones(res, await readBody(req));
      case 'limpiarReservasNormales':  return await limpiarReservasNormales(res);
      case 'limpiarTodo':              return await limpiarTodo(res);
      default:
        return err(res, `Acción desconocida: ${action}`);
    }
  } catch (e) {
    return err(res, e.message || e);
  }
};
