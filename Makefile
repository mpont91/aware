# ═══════════════════════════════════════════════════════════════════════════════
# AWARE Fund - Makefile
# ═══════════════════════════════════════════════════════════════════════════════
# The Vanguard of Prediction Markets
#
# Usage: make <target>
# Run 'make help' to see all available targets
# ═══════════════════════════════════════════════════════════════════════════════

.PHONY: help local up down build logs status clean ssh deploy prod-up prod-down prod-logs test

# Read configuration from .env in the repo root. Optional, so targets that
# don't need it still work on a fresh clone.
-include .env

# Default target
.DEFAULT_GOAL := help

# Production stack: the compose files live in deploy/ but are always run from
# the repo root, so .env sits where you'd expect it. Compose resolves the paths
# inside them relative to their own directory, so this is safe.
PROD_COMPOSE := --env-file .env -f deploy/docker-compose.prod.yaml

# Colors
GREEN  := $(shell tput -Txterm setaf 2)
YELLOW := $(shell tput -Txterm setaf 3)
BLUE   := $(shell tput -Txterm setaf 4)
RESET  := $(shell tput -Txterm sgr0)

# ═══════════════════════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════════════════════

help: ## Show this help
	@echo ''
	@echo '${GREEN}AWARE Fund${RESET} - The Vanguard of Prediction Markets'
	@echo ''
	@echo '${YELLOW}Quick Start:${RESET}'
	@echo '  ${BLUE}make build${RESET}       Rebuild Docker images (after code changes)'
	@echo '  ${BLUE}make local${RESET}       Start everything (services + analytics)'
	@echo '  ${BLUE}make down${RESET}        Stop everything'
	@echo ''
	@echo '${YELLOW}ML Training:${RESET}'
	@echo '  ${BLUE}make train${RESET}       Quick (10K traders, ~8 min)'
	@echo '  ${BLUE}make train-all${RESET}   All eligible traders (currently ~4K)'
	@echo ''
	@echo '${YELLOW}Deployment:${RESET}'
	@echo '  ${BLUE}make deploy${RESET}      Pull and restart on the server'
	@echo '  ${BLUE}make ssh${RESET}         Shell on the server, in the project dir'
	@echo ''
	@echo '${YELLOW}Other:${RESET}'
	@echo '  ${BLUE}make analytics${RESET}   Run analytics only'
	@echo '  ${BLUE}make logs${RESET}        View logs'
	@echo '  ${BLUE}make status${RESET}      Health check'
	@echo ''

# ═══════════════════════════════════════════════════════════════════════════════
# LOCAL DEVELOPMENT
# ═══════════════════════════════════════════════════════════════════════════════

local: docker-check ## Start everything + run analytics (one command!)
	@echo '${GREEN}Starting AWARE Fund local stack...${RESET}'
	docker compose -f docker-compose.local.yaml up -d
	@echo ''
	@echo '${YELLOW}Waiting for services to be ready...${RESET}'
	@sleep 10
	@echo '${GREEN}Running analytics pipeline...${RESET}'
	@docker exec aware-analytics python3 run_all.py 2>&1 | grep -E "(INFO|WARNING|Complete)" | tail -20 || true
	@echo ''
	@echo '${GREEN}✓ AWARE Fund ready!${RESET}'
	@echo ''
	@echo '  Web Dashboard:     http://localhost:3000'
	@echo '  Python API:        http://localhost:8000'
	@echo '  Strategy Service:  http://localhost:8081'
	@echo '  ClickHouse:        http://localhost:8123'
	@echo ''
	@echo 'Commands: ${BLUE}make train${RESET} (retrain ML) | ${BLUE}make logs${RESET} | ${BLUE}make down${RESET}'

up: local ## Alias for 'make local'

down: ## Stop all local services
	@echo '${YELLOW}Stopping all services...${RESET}'
	docker compose -f docker-compose.local.yaml down
	@echo '${GREEN}Done!${RESET}'

build: docker-check ## Rebuild and start local stack
	@echo '${GREEN}Rebuilding AWARE Fund...${RESET}'
	docker compose -f docker-compose.local.yaml build
	docker compose -f docker-compose.local.yaml up -d

logs: ## View logs (usage: make logs or make logs SERVICE=strategy)
	@if [ -z "$(SERVICE)" ]; then \
		docker compose -f docker-compose.local.yaml logs -f --tail=100; \
	else \
		docker compose -f docker-compose.local.yaml logs -f --tail=100 $(SERVICE); \
	fi

status: ## Check service health status
	@echo '${GREEN}Service Status:${RESET}'
	@echo ''
	@docker compose -f docker-compose.local.yaml ps
	@echo ''
	@echo '${GREEN}Health Checks:${RESET}'
	@curl -s http://localhost:8080/api/polymarket/health > /dev/null 2>&1 && echo '  ✓ Executor (8080)' || echo '  ✗ Executor (8080)'
	@curl -s http://localhost:8081/api/strategy/status > /dev/null 2>&1 && echo '  ✓ Strategy (8081)' || echo '  ✗ Strategy (8081)'
	@curl -s http://localhost:8000/api/health > /dev/null 2>&1 && echo '  ✓ API (8000)' || echo '  ✗ API (8000)'
	@curl -s http://localhost:3000 > /dev/null 2>&1 && echo '  ✓ Web (3000)' || echo '  ✗ Web (3000)'
	@curl -s http://localhost:8123 > /dev/null 2>&1 && echo '  ✓ ClickHouse (8123)' || echo '  ✗ ClickHouse (8123)'

clean: ## Stop all services and remove volumes
	@echo '${YELLOW}Stopping and removing all containers and volumes...${RESET}'
	docker compose -f docker-compose.local.yaml down -v
	@echo '${GREEN}Cleaned!${RESET}'

monitor: docker-check ## Start with Prometheus + Grafana monitoring
	docker compose -f docker-compose.local.yaml --profile monitoring up -d
	@echo ''
	@echo '${GREEN}Monitoring started:${RESET}'
	@echo '  Grafana:    http://localhost:3001 (admin/admin)'
	@echo '  Prometheus: http://localhost:9090'

# ═══════════════════════════════════════════════════════════════════════════════
# INFRASTRUCTURE ONLY (for running Java services from IDE)
# ═══════════════════════════════════════════════════════════════════════════════

infra: docker-check ## Start only infrastructure (ClickHouse, Kafka) for IDE dev
	@echo '${GREEN}Starting infrastructure only...${RESET}'
	docker compose -f docker-compose.analytics.yaml up -d
	@echo ''
	@echo '${GREEN}Infrastructure ready:${RESET}'
	@echo '  ClickHouse: localhost:8123'
	@echo '  Kafka:      localhost:9092'

infra-down: ## Stop infrastructure
	docker compose -f docker-compose.analytics.yaml down

# ═══════════════════════════════════════════════════════════════════════════════
# JAVA SERVICES (run from Maven, not Docker)
# ═══════════════════════════════════════════════════════════════════════════════

java-build: ## Build all Java services
	@echo '${GREEN}Building Java services...${RESET}'
	mvn clean package -DskipTests

java-test: ## Run Java tests
	mvn test

executor: ## Start executor-service (requires infra)
	cd executor-service && mvn spring-boot:run -Dspring-boot.run.profiles=develop

strategy: ## Start strategy-service (requires infra + executor)
	cd strategy-service && mvn spring-boot:run -Dspring-boot.run.profiles=develop

ingestor: ## Start ingestor-service (requires infra)
	cd ingestor-service && mvn spring-boot:run -Dspring-boot.run.profiles=develop

# ═══════════════════════════════════════════════════════════════════════════════
# PYTHON SERVICES
# ═══════════════════════════════════════════════════════════════════════════════

python-setup: ## Setup Python virtual environments
	@echo '${GREEN}Setting up Python environments...${RESET}'
	cd aware-fund/services/analytics && python -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd aware-fund/services/api && python -m venv .venv && .venv/bin/pip install -r requirements.txt

python-analytics: ## Run analytics jobs ONCE (requires infra)
	cd aware-fund/services/analytics && source .venv/bin/activate && CLICKHOUSE_HOST=localhost python run_all.py

python-analytics-continuous: ## Run ML analytics continuously (hourly updates)
	@echo '${GREEN}Starting ML analytics pipeline (continuous mode)...${RESET}'
	cd aware-fund/services/analytics && source .venv/bin/activate && CLICKHOUSE_HOST=localhost python run_all.py --continuous --interval 3600

python-api: ## Start Python API (requires infra)
	cd aware-fund/services/api && source .venv/bin/activate && CLICKHOUSE_HOST=localhost uvicorn main:app --reload --host 0.0.0.0 --port 8000

# ═══════════════════════════════════════════════════════════════════════════════
# ML PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

train: ## Retrain ML models (quick: 10K traders, ~8 min)
	@echo '${GREEN}Retraining ML models (quick mode)...${RESET}'
	@echo 'Training on 10K traders, 50 epochs (~8 min)'
	@docker exec aware-analytics python3 -m ml.training.train --max-traders 10000 --epochs 50
	@echo ''
	@echo '${GREEN}Running analytics with new model...${RESET}'
	@docker exec aware-analytics python3 run_all.py 2>&1 | grep -E "(INFO|Complete)" | tail -10
	@echo '${GREEN}✓ Training complete! Refresh UI to see changes.${RESET}'

train-all: ## Retrain on ALL eligible traders (no limit)
	@echo '${GREEN}Retraining ML models on ALL data...${RESET}'
	@echo 'Training on all eligible traders, 100 epochs'
	@docker exec aware-analytics python3 -m ml.training.train --max-traders 999999 --epochs 100
	@echo ''
	@echo '${GREEN}Running analytics with new model...${RESET}'
	@docker exec aware-analytics python3 run_all.py 2>&1 | grep -E "(INFO|Complete)" | tail -10
	@echo '${GREEN}✓ Training complete! Refresh UI to see changes.${RESET}'

analytics: ## Run analytics pipeline only (no training)
	@echo '${GREEN}Running analytics...${RESET}'
	@docker exec aware-analytics python3 run_all.py 2>&1 | grep -E "(INFO|WARNING|Complete)" | tail -20

# ═══════════════════════════════════════════════════════════════════════════════
# WEB DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

web-install: ## Install web dependencies
	cd aware-fund/services/web && npm install

web-dev: ## Start web dashboard in dev mode
	cd aware-fund/services/web && npm run dev

web-build: ## Build web dashboard for production
	cd aware-fund/services/web && npm run build

# ═══════════════════════════════════════════════════════════════════════════════
# SERVER DEPLOYMENT
# ═══════════════════════════════════════════════════════════════════════════════

require-server:
	@if [ -z "$(SERVER_USER)" ] || [ -z "$(SERVER_IP)" ] || [ -z "$(PROJECT_PATH)" ]; then \
		echo '${YELLOW}Set SERVER_USER, SERVER_IP and PROJECT_PATH in .env${RESET}'; exit 1; fi

ssh: require-server ## Open a shell on the server, in the project directory
	ssh $(SERVER_USER)@$(SERVER_IP) -t "cd $(PROJECT_PATH) && bash"

deploy: require-server ## Pull and restart on the server (one command)
	ssh $(SERVER_USER)@$(SERVER_IP) "cd $(PROJECT_PATH) && git pull && make prod-up"

# ── Run on the server itself ──────────────────────────────────────────────────
# --build because this project builds its images rather than pulling them.
prod-up: ## Build and start the production stack (run on the server)
	docker compose $(PROD_COMPOSE) up -d --build
	@# Caddy reads its config at startup and compose does not recreate it when
	@# only the mounted file changed, so a routing or rate-limit edit would sit
	@# on disk unapplied until something else forced a restart.
	@docker compose $(PROD_COMPOSE) exec -T caddy caddy reload \
		--config /etc/caddy/Caddyfile 2>/dev/null \
		&& echo "caddy config reloaded" || echo "caddy not running; skipped reload"
	docker image prune -f
	@# Every --build leaves layers behind and nothing evicts them: 16.5 GB had
	@# piled up by the time the disk filled. A week keeps rebuilds fast while
	@# bounding the cache.
	docker builder prune -f --filter until=168h

prod-down: ## Stop the production stack (run on the server)
	docker compose $(PROD_COMPOSE) down

prod-logs: ## Follow production logs (usage: make prod-logs SERVICE=api)
	docker compose $(PROD_COMPOSE) logs -f $(SERVICE)

prod-status: ## Check production service status (run on the server)
	docker compose $(PROD_COMPOSE) ps

# ═══════════════════════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

docker-check:
	@docker info > /dev/null 2>&1 || (echo '${YELLOW}Docker is not running. Please start Docker.${RESET}' && exit 1)

clickhouse-shell: ## Open ClickHouse SQL shell
	docker exec -it aware-clickhouse clickhouse-client

redpanda-shell: ## Open Redpanda/Kafka shell
	docker exec -it aware-redpanda rpk topic list

psql: ## Alias for clickhouse-shell
	$(MAKE) clickhouse-shell

# Show fund status
fund-status: ## Show all fund status
	@curl -s http://localhost:8081/api/strategy/funds/all | python3 -m json.tool

# Run PSI index rebuild
psi-rebuild: ## Rebuild all PSI indices
	cd aware-fund/services/analytics && source .venv/bin/activate && CLICKHOUSE_HOST=localhost python -c "from psi_index import *; import clickhouse_connect; c=clickhouse_connect.get_client(host='localhost',port=8123,database='polybot'); b=PSIIndexBuilder(c); [b.save_index(b.build_index(t)) for t in [IndexType.PSI_10, IndexType.PSI_25, IndexType.PSI_CRYPTO, IndexType.PSI_SPORTS, IndexType.PSI_ALPHA]]"
