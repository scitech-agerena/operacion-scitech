# operacion-scitech

Plataforma centralizada de tableros vivos de la operación de SCITECH: proyectos, mesas de servicio, capacidad y costos, con datos de Jira y acceso por audiencia.

Repositorio privado que centraliza la operación de SCITECH en tableros dinámicos por audiencia (comité, PMs, líderes de área y clientes). Una API intermedia consulta Jira con caché y entrega los datos; los tableros HTML los consumen. El acceso se controla con Google Workspace y el despliegue se hace en infraestructura propia (Contabo).

## Arquitectura

```
Navegador ──HTTPS──> Caddy ──> oauth2-proxy (login Google, dominio scitech.com.co)
                        │
                        ├── /            tableros HTML estáticos
                        └── /api/*  ──>  API (Node) ──> Jira (scitech.atlassian.net, salud360.atlassian.net)
                                          └─ caché en memoria + control de acceso por rol/cliente
```

## Estructura

| Carpeta | Contenido |
|---|---|
| `infra/` | docker-compose, Caddyfile y configuración de despliegue |
| `api/` | API intermedia: consulta Jira, caché, filtros por rol y cliente |
| `shared/` | Estilos y utilidades comunes a todos los tableros |
| `tableros/` | Un tablero por carpeta (`mesas-servicio` es el piloto) |
| `docs/` | Despliegue, seguridad y decisiones |

## Reglas

- Nunca se guardan tokens, claves ni datos de clientes en el repositorio (ver `.env.example`).
- El filtrado por cliente se hace siempre en la API, nunca en el navegador.
- Cambios a `main` mediante pull request.

Guía de despliegue: [`docs/despliegue.md`](docs/despliegue.md) · Seguridad: [`docs/seguridad.md`](docs/seguridad.md) · Pruebas locales: [`docs/desarrollo-local.md`](docs/desarrollo-local.md)

## Probar en local

```bash
cd api && npm run dev     # Jira simulado → http://localhost:8080
```
