# Ambiente de pruebas local

Requiere **Node 20 o superior**. No usa Docker ni Google, y solo escucha en tu computador (`127.0.0.1`).

```bash
git clone git@github.com:scitech-agerena/operacion-scitech.git
cd operacion-scitech/api
```

## Modo 1 · Jira simulado (sin credenciales)

```bash
npm run dev
```

Abrir `http://localhost:8080`. Hay tres usuarios ficticios para probar los roles; se cambian en `http://localhost:8080/_dev`:

| Usuario | Rol | Qué ve |
|---|---|---|
| `comite@demo.local` | comité | Todos los proyectos y responsables |
| `pm@demo.local` | PM | Solo `DEMO1`, con responsables |
| `cliente@demo.local` | cliente | Solo `DEMO1`, **sin** nombres de responsables |

Los datos son generados y siempre iguales; sirven para revisar diseño, filtros y permisos.

## Modo 2 · Jira real (solo lectura)

1. Crear el token de API de una cuenta de **solo lectura** en cada sitio de Jira.
2. Preparar la configuración local (ninguno de estos archivos se sube a Git):
   ```bash
   cp .env.dev.example .env.dev                           # completar URL, correo y token
   cp config/access.example.json   config/access.json     # tus correos, roles y proyectos
   cp config/projects.example.json config/projects.json   # claves reales de proyectos Jira
   ```
3. Reemplazar `EJEMPLO1`/`EJEMPLO2` por las claves reales (formato `sitio:CLAVE`, con `sitio` = `scitech` o `salud360`).
4. Ejecutar:
   ```bash
   npm run dev:real
   ```

En `/_dev` aparecen los correos de tu `access.json`, así puedes probar cómo ve cada persona su tablero.

## Pruebas automáticas

```bash
npm test
```

## Notas
- Los puertos se pueden cambiar con `WEB_PORT`, `API_PORT` y `MOCK_PORT`.
- La caché es corta en desarrollo (30–60 s); en producción es de 10 minutos.
- Este ambiente **no** prueba el login con Google ni HTTPS: eso solo se valida con el `docker compose` de `infra/`.
