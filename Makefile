# Convenience targets. Run `make help` for the list.
# (On Windows, run these commands directly or use WSL/Git Bash.)

BACKEND := cv-lab/backend
COMPOSE := cv-lab/deploy/docker-compose.yml

.PHONY: help install run compose down test image clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install backend dependencies
	cd $(BACKEND) && python -m venv .venv && \
	  ./.venv/bin/pip install --upgrade pip && \
	  ./.venv/bin/pip install -r requirements.txt

run: ## Run the backend locally (local-disk storage)
	cd $(BACKEND) && STORAGE_BACKEND=local ./.venv/bin/uvicorn app.main:app --reload --port 8000

compose: ## Start the full stack (backend + MinIO) via Docker
	docker compose -f $(COMPOSE) up --build

down: ## Stop the Docker stack
	docker compose -f $(COMPOSE) down

test: ## Run the analyzer smoke test
	cd $(BACKEND) && STORAGE_BACKEND=local DEVICE=cpu ./.venv/bin/python ../selftest.py

image: ## Build the container image
	docker build -f $(BACKEND)/Dockerfile -t cvlab-retail:0.1.0 cv-lab

clean: ## Remove caches and local runtime data
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/data $(BACKEND)/_s3cache 2>/dev/null || true
