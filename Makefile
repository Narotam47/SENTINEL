.PHONY: help up down restart logs ps setup-python profile migrate ingest transform train erd status test clean

# Default target
help:
	@echo ""
	@echo "SENTINEL — Manufacturing Process Monitoring & Yield Analytics"
	@echo "================================================================"
	@echo "  make up           Start PostgreSQL + Grafana (Docker)"
	@echo "  make down         Stop and remove containers"
	@echo "  make restart      Restart all containers"
	@echo "  make logs         Tail all container logs"
	@echo "  make ps           Show running containers"
	@echo ""
	@echo "  make setup-python Create venv and install Python dependencies"
	@echo "  make profile      Profile raw SECOM files (shape, missing, imbalance)"
	@echo "  make migrate      Apply pending DB migrations to running container"
	@echo "  make ingest       Full ingest: profile → migrate → load into PostgreSQL"
	@echo "  make transform    Run feature engineering pipeline"
	@echo "  make train        Train yield prediction model"
	@echo "  make erd          Generate ERD diagram → docs/erd.png"
	@echo ""
	@echo "  make status       Full system health check"
	@echo "  make test         Run pytest suite"
	@echo "  make clean        Remove containers, volumes, and venv"
	@echo ""

# ── Docker ────────────────────────────────────────────────────────────────────

up:
	docker compose up -d
	@echo ""
	@echo "  PostgreSQL : localhost:5432  (user: sentinel / pass: sentinel_pass)"
	@echo "  Grafana    : http://localhost:3000  (admin / sentinel_grafana)"
	@echo ""

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f

ps:
	docker compose ps

# ── Python ────────────────────────────────────────────────────────────────────

setup-python:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt
	@echo "Activate with: source .venv/bin/activate"

# ── Pipeline ──────────────────────────────────────────────────────────────────

profile:
	.venv/bin/python pipeline/ingest/profile_secom.py

migrate:
	@echo "Applying migration 002 …"
	docker exec -i sentinel_postgres psql -U sentinel -d sentinel_db \
		< db/migrations/002_audit_columns.sql
	@echo "Migration 002 applied."

ingest: profile migrate
	.venv/bin/python pipeline/ingest/load_secom.py

transform:
	.venv/bin/python pipeline/transform/clean_features.py

train:
	.venv/bin/python pipeline/model/train.py

erd:
	mkdir -p docs
	.venv/bin/python scripts/generate_erd.py

# ── Checks ────────────────────────────────────────────────────────────────────

status:
	@echo "=== Docker containers ==="
	@docker compose ps
	@echo ""
	@echo "=== PostgreSQL ping ==="
	@docker exec sentinel_postgres pg_isready -U sentinel -d sentinel_db || echo "Postgres not ready"
	@echo ""
	@echo "=== DB row counts ==="
	@docker exec sentinel_postgres psql -U sentinel -d sentinel_db -c \
		"SELECT relname AS table, n_live_tup AS rows FROM pg_stat_user_tables ORDER BY relname;" \
		2>/dev/null || echo "Could not query DB"
	@echo ""
	@echo "=== Grafana ping ==="
	@curl -s -o /dev/null -w "Grafana HTTP %{http_code}\n" http://localhost:3000/api/health || echo "Grafana not reachable"

test:
	.venv/bin/python -m pytest tests/ -v --tb=short

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:
	docker compose down -v
	rm -rf .venv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned containers, volumes, and venv."
