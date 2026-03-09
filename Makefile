.PHONY: help build up down logs shell db-shell migrate test clean

COMPOSE=docker-compose -f docker-compose.yml -f docker-compose.dev.yml

help:
	@echo "WorkshopPro NZ - Docker Commands (Multi-Architecture)"
	@echo "Detected: $$(uname -m)"
	@echo ""
	@echo "  make build        - Build all Docker images"
	@echo "  make up           - Start all services"
	@echo "  make down         - Stop all services"
	@echo "  make logs         - View logs (all services)"
	@echo "  make logs-app     - View API logs"
	@echo "  make shell        - Open shell in app container"
	@echo "  make db-shell     - Open PostgreSQL shell"
	@echo "  make migrate      - Run database migrations"
	@echo "  make test         - Run tests"
	@echo "  make clean        - Remove containers and volumes"
	@echo "  make restart      - Restart all services"

build:
	$(COMPOSE) build

up:
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env file"; fi
	$(COMPOSE) up -d postgres redis
	@echo "Waiting for database..."
	@sleep 5
	$(COMPOSE) run --rm app alembic upgrade head
	$(COMPOSE) up

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

logs-app:
	$(COMPOSE) logs -f app

shell:
	$(COMPOSE) exec app bash

db-shell:
	$(COMPOSE) exec postgres psql -U postgres -d workshoppro

migrate:
	$(COMPOSE) exec app alembic upgrade head

test:
	$(COMPOSE) exec app pytest

clean:
	$(COMPOSE) down -v
	docker system prune -f

restart:
	$(COMPOSE) restart
