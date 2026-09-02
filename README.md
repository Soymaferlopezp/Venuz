# Venuz

> Análisis fundamental trazable y controles deterministas para **Alpaca Paper Trading**.

Venuz es una aplicación web para evaluar acciones estadounidenses de calidad, explicar cada conclusión con evidencia y, en fases posteriores, gestionar exclusivamente órdenes simuladas. El modelo de IA nunca decide elegibilidad, riesgo ni ejecución.

> **PAPER TRADING — NO REAL MONEY.** No es asesoría financiera ni un sistema de producción.

## Estado implementado

La fase de fundación incluye:

- `apps/web`: experiencia inicial en Next.js 16 con estado de `GET /health`, cold start de Render y fallo seguro.
- `apps/api`: FastAPI + Pydantic v2 con configuración tipada y bloqueo estricto de cualquier modo o endpoint que no sea Alpaca Paper.
- `supabase`: migración versionada, grants explícitos, RLS por propietario, idempotencia e historial de auditoría append-only.
- `.github/workflows/ci.yml`: formato, lint, tipos, pruebas, builds, pgTAP efímero y detección de secretos.
- `.github/workflows/supabase-hosted-migrations.yml`: despliegue manual y protegido de migraciones al proyecto alojado.

No hay llamadas a proveedores, lógica financiera, órdenes ni despliegues en esta fase.

## Arquitectura

```text
Browser
  -> Next.js (presentación; solo variables NEXT_PUBLIC_*)
      -> FastAPI (configuración privada y futuros controles deterministas)
          -> Supabase Postgres/Auth (RLS, estado y auditoría)
          -> Alpaca Paper / SEC / Alpha Vantage / IA (fases posteriores)
```

Responsabilidades:

- La web no contiene secretos ni calcula reglas financieras.
- El API valida su configuración al importar el entrypoint y no arranca fuera de Paper.
- Supabase niega acceso anónimo. Los catálogos son de lectura autenticada y los datos operativos se filtran por `auth.uid()`.
- Las escrituras operativas quedan reservadas al backend con la clave secreta de Supabase.

Consulta [Arquitectura](docs/ARCHITECTURE.md), [Estrategia](docs/TRADING_STRATEGY.md), [Producto](docs/PRODUCT_SPEC.md) y [Seguridad](docs/SECURITY_AND_SECRETS.md).

## Requisitos

- Windows Command Prompt (`cmd.exe`).
- Node.js 22 o superior.
- Python 3.12.x.
- Supabase CLI 2.116.0 mediante `npx` para gestionar el proyecto alojado.
- Git.

La fundación fue creada con Python 3.12.10, Node 24.20.0, npm 11.19.0 y Supabase CLI 2.116.0.

## Variables de entorno

La plantilla raíz [`.env.example`](.env.example) enumera nombres y valores seguros. Nunca copies esa plantilla completa al frontend porque contiene nombres de variables privadas.

- `apps/api/.env`: configuración privada del servidor. Debe permanecer ignorada.
- `apps/web/.env.local`: solo `NEXT_PUBLIC_APP_NAME`, `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SUPABASE_URL` y `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`. Debe permanecer ignorada.
- `apps/web/.env.example`: plantilla pública opcional para el frontend.

El API solo acepta:

```text
TRADING_MODE=paper
ALPACA_PAPER=true
ALPACA_TRADING_BASE_URL=https://paper-api.alpaca.markets
AUTO_EXECUTION_ENABLED=false
```

Los secretos se representan como `**********` y `/health` nunca devuelve estado de credenciales, cuentas ni proveedores.

## Desarrollo local en Windows Command Prompt

Desde la raíz del repositorio:

### API

```bat
cd apps\api
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abre `http://localhost:8000/health`. El proceso se detiene antes de servir tráfico si la configuración no es Paper.

### Web

En otra ventana de Command Prompt:

```bat
cd apps\web
npm ci
npm run dev
```

Abre `http://localhost:3000`.

### Supabase alojado

La base de datos de desarrollo, integración y demostración es el proyecto alojado. No se instala ni ejecuta Supabase localmente. Vincula el proyecto remoto y revisa cada migración desde Command Prompt:

```bat
npx --yes supabase@2.116.0 login
npx --yes supabase@2.116.0 link --project-ref PROJECT_REF
npx --yes supabase@2.116.0 migration list
npx --yes supabase@2.116.0 db push --dry-run
```

Solo después de revisar el dry-run y recibir aprobación explícita:

```bat
npx --yes supabase@2.116.0 db push
npx --yes supabase@2.116.0 migration list
npx --yes supabase@2.116.0 db lint --linked --level error
```

`supabase db reset --linked` está terminantemente prohibido. `supabase start` y `supabase db reset --local` no forman parte del flujo de la máquina personal. Tampoco se automatizan `migration repair` ni `db pull`.

Las tres suites pgTAP se ejecutan únicamente en GitHub Actions contra una instancia efímera creada dentro del runner. Ese job no recibe credenciales del proyecto alojado y siempre detiene el stack.

No se incluye un usuario o contraseña demo en Git. Crea el operador mediante Supabase Auth y deja que el backend aprovisione `profiles` y `app_roles` en una fase autenticada.

## Verificación

### Backend

```bat
cd apps\api
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy app tests
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m build --wheel
.venv\Scripts\python.exe -m pip check
```

### Frontend

```bat
cd apps\web
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

### Seguridad e ignore rules

```bat
git check-ignore -v apps\api\.env apps\web\.env.local
git status --short
```

Estos comandos comprueban reglas, no muestran contenido privado. La detección completa con Gitleaks corre en CI.

### Despliegue manual de migraciones alojadas

El workflow `Supabase hosted migrations` solo se inicia con `workflow_dispatch`, usa el environment protegido `supabase-development` y ejecuta preview por defecto. Tras revisar ese resultado, un segundo despacho con `apply_migrations=true` constituye la confirmación manual. Los secretos se configuran únicamente en GitHub:

- `SUPABASE_ACCESS_TOKEN`
- `SUPABASE_DB_PASSWORD`
- `SUPABASE_PROJECT_ID`

El workflow enlaza el proyecto, lista las migraciones, ejecuta el dry-run, aplica el push, vuelve a listar y termina con lint remoto. La protección del environment debe exigir revisor antes de permitir el job.

## Esquema inicial

La migración crea perfiles/roles, compañías/sectores, presupuestos de proveedor, jobs, hechos financieros, valoraciones, screenings/criterios, oportunidades/aprobaciones, posiciones, órdenes/eventos, evidencia y auditoría. Usa `numeric` para importes, `timestamptz` para tiempo, UUID, checks, foreign keys e índices para RLS y recorridos principales.

## Limitaciones actuales

- No hay conexión real a Alpaca, SEC, Alpha Vantage, Gemini u OpenRouter.
- No se ejecutan órdenes, ni siquiera paper, durante la fundación.
- pgTAP no se ejecuta en la computadora personal; su puerta definitiva es el stack efímero del runner de GitHub Actions.
- Render Free puede dormir; la web lo comunica y mantiene todas las acciones deshabilitadas.
- La estrategia no garantiza resultados futuros.

## Siguiente fase

La siguiente fase debe implementar autenticación Supabase completa y repositorios del API, verificar RLS en CI y contra el proyecto alojado de forma sanitizada, y luego construir clientes con fixtures para Alpaca Market Data y SEC antes de cualquier camino de órdenes.
