// ============================================================
// Migración: Google Apps Script (viejo) → Supabase (nuevo)
// Lee la data que el Apps Script todavía expone y la carga en Postgres
// vía la API REST de Supabase (sin dependencias).
//
// Uso:
//   SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... node scripts/migrate.mjs
//
// Migra: reservas de la semana, turnos fijos y promociones.
// Los precios NO se migran (getPrecios está roto en el Apps Script);
// se cargan a mano desde el panel después.
// ============================================================

const OLD_API = 'https://script.google.com/macros/s/AKfycbyd4O4dWAUnUgGeyok35PCeGSRAbxLu4uLfh6_WQQiOYSREVlkX6Dpru7sI3Fiuusn0/exec';

const SB  = process.env.SUPABASE_URL;
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!SB || !KEY) {
  console.error('❌ Falta SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en el entorno.');
  process.exit(1);
}

async function sbUpsert(table, onConflict, rows) {
  if (!rows.length) return;
  const r = await fetch(`${SB}/rest/v1/${table}?on_conflict=${onConflict}`, {
    method: 'POST',
    headers: {
      apikey: KEY,
      Authorization: `Bearer ${KEY}`,
      'Content-Type': 'application/json',
      Prefer: 'resolution=merge-duplicates,return=minimal',
    },
    body: JSON.stringify(rows),
  });
  if (!r.ok) throw new Error(`${table}: DB ${r.status} ${await r.text()}`);
}

async function fetchOld(action, tries = 4) {
  for (let i = 1; i <= tries; i++) {
    try {
      const r = await fetch(`${OLD_API}?action=${action}`, { redirect: 'follow' });
      const text = await r.text();
      if (text.trim().startsWith('{')) {
        const json = JSON.parse(text);
        if (json.success) return json.data;
      }
      console.warn(`  ⚠ ${action}: intento ${i} no devolvió JSON válido, reintentando...`);
    } catch (e) {
      console.warn(`  ⚠ ${action}: intento ${i} falló (${e.message})`);
    }
    await new Promise((res) => setTimeout(res, 1500));
  }
  return null;
}

async function main() {
  console.log('→ Leyendo getTurnos del Apps Script viejo...');
  const turnos = await fetchOld('getTurnos');
  if (!turnos) { console.error('❌ No se pudo leer getTurnos. Abortando.'); process.exit(1); }

  // 1) Reservas de la semana ----------------------------------
  const reservas = [];
  for (const day of turnos.week || []) {
    const fijosDelDia = turnos.fixedSlotsByDay?.[day.day] || {};
    for (const [hora, nombre] of Object.entries(day.slots || {})) {
      reservas.push({ fecha: day.dateKey, hora, nombre, es_fijo: !!fijosDelDia[hora] });
    }
  }
  await sbUpsert('reservas', 'fecha,hora', reservas);
  console.log(`  ✓ ${reservas.length} reservas migradas`);

  // 2) Turnos fijos -------------------------------------------
  const fijos = [];
  for (const [dia, slots] of Object.entries(turnos.fixedSlotsByDay || {})) {
    for (const [hora, nombre] of Object.entries(slots)) {
      fijos.push({ dia_semana: dia, hora, nombre });
    }
  }
  await sbUpsert('turnos_fijos', 'dia_semana,hora', fijos);
  console.log(`  ✓ ${fijos.length} turnos fijos migrados`);

  // 3) Promociones --------------------------------------------
  console.log('→ Leyendo getPromociones...');
  const promos = await fetchOld('getPromociones');
  if (promos && Object.keys(promos).length) {
    await sbUpsert('config', 'clave', [{ clave: 'promociones', valor: promos }]);
    console.log(`  ✓ ${Object.keys(promos).length} promociones migradas`);
  } else {
    console.log('  · sin promociones para migrar');
  }

  // 4) Precios (informativo) ----------------------------------
  console.log('→ Intentando getPrecios (suele estar roto)...');
  const precios = await fetchOld('getPrecios', 2);
  if (precios?.precios) {
    const rows = [{ clave: 'precios', valor: precios.precios }];
    if (precios.descuento) rows.push({ clave: 'descuento', valor: precios.descuento });
    await sbUpsert('config', 'clave', rows);
    console.log('  ✓ precios migrados (¡bien, respondió!)');
  } else {
    console.log('  · getPrecios no respondió. Cargá los precios a mano desde el panel.');
  }

  console.log('\n✅ Migración terminada.');
}

main().catch((e) => { console.error('❌ Error:', e.message || e); process.exit(1); });
