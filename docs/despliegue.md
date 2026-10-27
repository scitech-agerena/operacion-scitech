# Despliegue en Contabo

## Requisitos
- VPS con Docker y Docker Compose.
- Registro DNS `tableros.scitech.com.co` apuntando a la IP del VPS (Caddy obtiene el certificado HTTPS solo).
- Puertos abiertos: 80 y 443. SSH solo por llave.

## 1. Credenciales de Google (login)
1. En Google Cloud Console crear un cliente OAuth 2.0 tipo *Aplicación web*.
2. URI de redirección autorizada: `https://tableros.scitech.com.co/oauth2/callback`.
3. Guardar `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`.

## 2. Credenciales de Jira (una por sitio)
Sitios: `scitech.atlassian.net` y `salud360.atlassian.net`.
1. Crear una cuenta de servicio (no una persona) en cada sitio, con permiso **solo de lectura** únicamente sobre los proyectos que alimentan los tableros.
2. Generar un token de API para cada cuenta.
3. Para agregar un tercer sitio basta con añadir `JIRA_<SITIO>_URL`, `_EMAIL` y `_TOKEN` al `.env`.

## 3. Configuración en el servidor
```bash
git clone git@github.com:scitech-agerena/operacion-scitech.git /opt/operacion-scitech
cd /opt/operacion-scitech
cp .env.example infra/.env                              # completar valores
cp api/config/access.example.json   api/config/access.json     # personas, roles y proyectos
cp api/config/projects.example.json api/config/projects.json   # lista blanca de proyectos Jira
cp infra/external-emails.example.txt infra/external-emails.txt # solo si hay clientes externos
chmod 600 infra/.env
```
Reemplazar las claves `EJEMPLO1`/`EJEMPLO2` por los proyectos reales.

## 4. Arranque
```bash
cd infra
docker compose up -d --build
docker compose logs -f api
```

## 5. Actualizar
```bash
cd /opt/operacion-scitech && git pull
cd infra && docker compose up -d --build
```
Los cambios en `tableros/` y `shared/` se ven al recargar; los de `api/` requieren `--build`.

## 6. Verificación rápida
- Abrir `https://tableros.scitech.com.co` sin sesión: debe redirigir al login de Google.
- Entrar con una cuenta no registrada en `access.json`: debe mostrar "Sin acceso".
- Entrar con un cliente: solo debe ver sus proyectos y no debe aparecer el nombre de los responsables.

> La configuración de `infra/` (Caddy + oauth2-proxy) no se ha probado contra un servidor real; validar en un entorno de prueba antes de publicar.
