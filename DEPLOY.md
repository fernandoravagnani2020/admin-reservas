# Migración del backend a Supabase + Vercel

El backend pasó de **Google Apps Script + Google Sheet** (lento, se colgaba) a
**Vercel Serverless Function + Supabase (Postgres)**. El contrato de la API es
idéntico, así que el frontend y PadelLive solo tienen que apuntar a la URL nueva.

## Pasos (una sola vez)

### 1. Crear el proyecto en Supabase
1. Entrá a https://supabase.com → **New project** (plan gratis).
2. Elegí región **South America (São Paulo)** (la más cercana).
3. Guardá la contraseña de la base que te genere.

### 2. Crear las tablas
1. En Supabase → **SQL Editor** → **New query**.
2. Pegá todo el contenido de [`db/schema.sql`](db/schema.sql) y dale **Run**.

### 3. Conseguir las credenciales
En Supabase → **Project Settings → API**, copiá:
- **Project URL** → será `SUPABASE_URL`
- **service_role** key (la secreta, NO la `anon`) → será `SUPABASE_SERVICE_ROLE_KEY`

> ⚠️ La `service_role` key es secreta. Va solo en variables de entorno, nunca en el frontend.

### 4. Migrar los datos viejos
Desde la carpeta del proyecto, en la terminal:
```bash
npm install
SUPABASE_URL="https://xxxx.supabase.co" \
SUPABASE_SERVICE_ROLE_KEY="eyJhbGci..." \
npm run migrate
```
Esto carga las reservas, los turnos fijos y las promociones. Los **precios** los
cargás a mano desde el panel (el endpoint viejo de precios está roto).

### 5. Configurar las variables en Vercel
En el proyecto de Vercel → **Settings → Environment Variables**, agregá:

| Name | Value |
|------|-------|
| `SUPABASE_URL` | la Project URL de Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | la service_role key |

Marcalas para **Production** (y Preview si querés). Después hacé un **Redeploy**.

### 6. Frontend
Ya quedó listo: `index.html` usa `API_URL = '/exec'` (relativo, mismo dominio de
Vercel). No hay que tocar nada.

### 7. Apuntar PadelLive a la URL nueva
En la configuración de PadelLive, reemplazá la URL del Apps Script
(`https://script.google.com/.../exec`) por:
```
https://TU-PROYECTO.vercel.app/exec
```

## Probar que anda
```bash
curl "https://TU-PROYECTO.vercel.app/exec?action=getTurnos"
```
Tiene que devolver `{"success":true,"data":{"week":[...],"fixedSlotsByDay":{...}}}`
al instante (sin los 30s de cuelgue del Apps Script).

## Contrato de la API (sin cambios)
| Método | Acción | Body |
|--------|--------|------|
| GET  | `getTurnos` | — |
| GET  | `getPrecios` | — |
| GET  | `getPromociones` | — |
| POST | `agregarReserva` | `{dateKey, day, time, name, isFixed}` |
| POST | `eliminarReserva` | `{dateKey, day, time, isFixed}` |
| POST | `toggleTurnoFijo` | `{day, time, name, isCurrentlyFixed}` |
| POST | `guardarPrecios` | `{precios, descuento}` |
| POST | `guardarPromociones` | `{promociones}` |
| POST | `limpiarReservasNormales` | `{}` |
| POST | `limpiarTodo` | `{}` |

Una vez que confirmes que todo anda, podés despublicar el Apps Script viejo.
