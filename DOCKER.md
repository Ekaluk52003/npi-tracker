# Docker Setup

## Overview

| Environment | DB       | Web server         | Frontend      |
|-------------|----------|--------------------|---------------|
| Development | Postgres | Django runserver   | Vite dev HMR  |
| Production  | Postgres | Gunicorn + Caddy   | Pre-built bundle |

---

## Local Development

### 1. Start everything

```bash
docker compose up --build
```

This starts three services:
- **db** — PostgreSQL 16 on port `5432`
- **web** — Django dev server on port `8000`
- **vite** — Vite HMR dev server on port `5174`

Migrations run automatically on startup.

Open **http://localhost:8000**

### 2. Common commands

```bash
# Run in background
docker compose up -d

# View logs
docker compose logs -f web
docker compose logs -f vite

# Open Django shell
docker compose exec web python manage.py shell

# Create superuser
docker compose exec web python manage.py createsuperuser

# Run migrations manually
docker compose exec web python manage.py migrate

# Stop everything
docker compose down

# Stop and delete the database volume (fresh start)
docker compose down -v
```

### 3. How env vars work in dev

The file `.env.dev` is loaded by both the `web` and `db` services.  
It is already in `.gitignore` — never commit it.

---

## Production Deployment

### 1. Prepare the server

Install Docker and Docker Compose on your server, then copy the project files there.

### 2. Create the production env file

```bash
cp .env.example .env.prod
```

Edit `.env.prod` and fill in real values:

```env
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(50))">
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

DB_NAME=npi_tracker
DB_USER=postgres
DB_PASSWORD=<strong password>
DB_HOST=db
DB_PORT=5432

DOMAIN=yourdomain.com
```

### 3. Point DNS

Create an A record for `yourdomain.com` pointing to your server's IP.  
Caddy will automatically obtain a TLS certificate from Let's Encrypt.

> Ports **80** and **443** must be open in your firewall.

### 4. Build and start

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

This will:
1. Build the frontend bundle (Vite)
2. Install Python dependencies
3. Run `manage.py migrate`
4. Run `manage.py collectstatic`
5. Start Gunicorn (Django) on internal port 8000
6. Start Caddy (reverse proxy + auto-TLS) on ports 80/443

### 5. Common production commands

```bash
# View logs
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f caddy

# Create superuser
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

# Rebuild and redeploy after code changes
docker compose -f docker-compose.prod.yml up --build -d

# Stop
docker compose -f docker-compose.prod.yml down
```

---

## File reference

| File                     | Purpose                                      |
|--------------------------|----------------------------------------------|
| `Dockerfile`             | Multi-stage build (dev + prod targets)       |
| `docker-compose.yml`     | Local development stack                      |
| `docker-compose.prod.yml`| Production stack                             |
| `Caddyfile`              | Caddy reverse proxy config (auto-TLS)        |
| `entrypoint.sh`          | Runs migrations before the server starts     |
| `.env.dev`               | Dev environment variables (not committed)    |
| `.env.prod`              | Prod environment variables (not committed)   |
| `.env.example`           | Template — copy to `.env.prod` on server     |
