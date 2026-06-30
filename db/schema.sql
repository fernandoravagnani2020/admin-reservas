-- ============================================================
-- Negro Padel · Esquema de base de datos (Supabase / Postgres)
-- Reemplaza la Google Sheet del Apps Script.
-- Corré este archivo entero en: Supabase → SQL Editor → New query
-- ============================================================

-- Reservas concretas en una fecha puntual (normales y fijas materializadas).
create table if not exists reservas (
  id         bigint generated always as identity primary key,
  fecha      date    not null,           -- 2026-07-04
  hora       text    not null,           -- '14:30'
  nombre     text    not null,           -- 'EUGE'
  es_fijo    boolean not null default false,
  created_at timestamptz not null default now(),
  unique (fecha, hora)
);

create index if not exists reservas_fecha_idx on reservas (fecha);

-- Turnos fijos: plantilla recurrente por día de la semana.
-- Se proyectan automáticamente sobre cada semana al leer getTurnos.
create table if not exists turnos_fijos (
  id         bigint generated always as identity primary key,
  dia_semana text not null,              -- 'LUNES'..'DOMINGO' (mayúsculas, con tilde)
  hora       text not null,              -- '19:00'
  nombre     text not null,
  unique (dia_semana, hora)
);

-- Configuración clave/valor: precios, descuento y promociones.
-- valor es JSON, igual que lo manejaba la planilla.
create table if not exists config (
  clave text primary key,                -- 'precios' | 'descuento' | 'promociones'
  valor jsonb not null
);

-- Valores por defecto (se pueden editar luego desde el panel).
insert into config (clave, valor) values
  ('precios',      '{"semana": {}, "finDeSemana": {}}'::jsonb),
  ('descuento',    '{"activo": false, "porcentaje": 10, "minutosAntes": 90}'::jsonb),
  ('promociones',  '{}'::jsonb)
on conflict (clave) do nothing;
