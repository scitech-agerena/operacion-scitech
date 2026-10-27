# Seguridad

## Capas de control
1. **Login:** oauth2-proxy con Google. Dominio `scitech.com.co` o correos externos listados en `infra/external-emails.txt`.
2. **Autorización:** la API deniega por defecto. Cada correo debe estar en `api/config/access.json` con rol y proyectos.
3. **Lista blanca de proyectos:** solo los de `api/config/projects.json` pueden consultarse; la clave se valida con expresión regular antes de armar la consulta JQL.
4. **Datos por rol:** el rol `cliente` no recibe nombres de responsables.

## Reglas
- La API no publica puertos; solo Caddy llega a ella dentro de la red de Docker. Si se expusiera, cualquiera podría falsificar el encabezado `X-Auth-Request-Email`.
- Los tokens de Jira y los secretos de Google viven solo en `infra/.env` (permiso 600), nunca en Git ni en el navegador.
- Cuentas de servicio de Jira de solo lectura, limitadas a los proyectos necesarios.
- El filtrado por cliente se hace siempre en la API.
- Caché de 10 minutos por proyecto y periodo: protege a Jira de exceso de consultas.

## Trazabilidad
- La API registra una línea JSON por solicitud (hora, correo, ruta, proyecto, estado). Sin tokens.
- Caddy guarda el registro de accesos en `/data/access.log` con rotación.
- Todo cambio de código pasa por Git (historial y revisión).

## Pendientes recomendados
- Proteger la rama `main` y exigir pull request.
- Programar copias de seguridad de `api/config/` y `infra/.env` (fuera de Git).
- Actualizar imágenes de Docker de forma periódica.
- Revisar `access.json` cada trimestre (altas, bajas y cambios de rol).
- Fijar versiones de las imágenes (`caddy`, `oauth2-proxy`) en lugar de `latest` una vez validado el piloto.
