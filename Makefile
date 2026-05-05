.PHONY: help dev down build test lint migrate seed deploy clean logs kind-up kind-down kind-load kind-secrets kind-monitoring kind-load-test kind-status \
       experiment experiment-dry-run experiment-resume experiment-first experiment-first-resume experiment-pilot experiment-validate experiment-status \
       experiment-product experiment-auth experiment-shipping experiment-validate-product experiment-validate-auth experiment-validate-shipping

# ──── Image Registry ───────────────────────────────────────
# Override via env: IMAGE_REGISTRY=ghcr.io/myorg make kind-load
IMAGE_REGISTRY ?= ghcr.io/$(shell git remote get-url origin 2>/dev/null | sed -E 's|.*github.com[:/]([^/]+)/.*|\1|' | tr '[:upper:]' '[:lower:]')
IMAGE_TAG      ?= latest

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ──── Local Development ────────────────────────────────────
dev: ## Start all services locally via docker-compose
	docker compose up --build -d
	@echo "\n✅ Services starting. Gateway at http://localhost:8080"
	@echo "Run 'make logs' to tail container logs."

down: ## Stop all services
	docker compose down -v

logs: ## Tail logs from all services
	docker compose logs -f

build: ## Build all Docker images
	docker compose build

restart: ## Restart all services
	docker compose restart

# ──── Testing ──────────────────────────────────────────────
test: ## Run all unit tests
	@echo "🧪 Running auth-service tests..."
	docker compose exec auth-service pytest tests/ -v || true
	@echo "🧪 Running product-service tests..."
	docker compose exec product-service pytest tests/ -v || true
	@echo "🧪 Running cart-service tests..."
	docker compose exec cart-service pytest tests/ -v || true
	@echo "🧪 Running order-service tests..."
	docker compose exec order-service pytest tests/ -v || true
	@echo "🧪 Running payment-service tests..."
	docker compose exec payment-service pytest tests/ -v || true
	@echo "🧪 Running shipping-rate-service tests..."
	docker compose exec shipping-rate-service pytest tests/ -v || true
	@echo "🧪 Running carrier-mock-service tests..."
	docker compose exec carrier-mock-service pytest tests/ -v || true

lint: ## Lint all services with ruff
	@for svc in auth-service product-service cart-service order-service payment-service shipping-rate-service carrier-mock-service; do \
		echo "🔍 Linting $$svc..."; \
		cd backend/services/$$svc && ruff check . && cd ../../..; \
	done

# ──── Database ─────────────────────────────────────────────
migrate: ## Run database migrations
	bash scripts/migrate.sh

seed: ## Seed sample data
	bash scripts/seed_data.sh

# ──── Deployment ───────────────────────────────────────────
deploy: ## Deploy to Kubernetes
	bash scripts/deploy.sh

clean: ## Full cleanup: containers, volumes, images
	bash scripts/cleanup.sh

# ──── KIND Deployment ──────────────────────────────────────
kind-up: ## Create KIND cluster and deploy full stack
	bash scripts/kind-deploy.sh

kind-secrets: ## Create/update all KIND secrets from .env.kind (idempotent)
	@echo "🔑 Applying secrets to KIND cluster..."
	@bash scripts/kind-create-secrets.sh

kind-down: ## Destroy the local KIND cluster
	kind delete cluster --name ecommerce

kind-load: ## Rebuild all images and load them into KIND
	@echo "🐳 Rebuilding and loading images into KIND..."
	@for svc in auth product cart order payment shipping-rate carrier-mock; do \
		docker build -q -t $(IMAGE_REGISTRY)/ecommerce-$$svc-service:$(IMAGE_TAG) backend/services/$$svc-service; \
		kind load docker-image $(IMAGE_REGISTRY)/ecommerce-$$svc-service:$(IMAGE_TAG) --name ecommerce; \
	done
	@docker build -q -t $(IMAGE_REGISTRY)/ecommerce-api-gateway:$(IMAGE_TAG) backend/api-gateway
	@kind load docker-image $(IMAGE_REGISTRY)/ecommerce-api-gateway:$(IMAGE_TAG) --name ecommerce
	@echo "🔄 Rollout restart deployments..."
	@kubectl rollout restart deployment -n ecommerce

kind-monitoring: ## Redeploy the monitoring stack in KIND
	@echo "📊 Applying monitoring stack..."
	kubectl apply -f infrastructure/kind/monitoring/

kind-load-test: ## Run k6 load test inside the KIND cluster
	@echo "🚦 Starting k6 load test..."
	kubectl apply -f infrastructure/kind/load-testing/k6-job.yaml
	@echo "Waiting for k6 job to complete (tailing logs)..."
	kubectl wait --for=condition=ready pod -l app=k6 -n ecommerce --timeout=30s || true
	kubectl logs -f -l app=k6 -n ecommerce

kind-status: ## Show status of all pods in ecommerce and monitoring namespaces
	@echo "\n📦 E-commerce Namespace:"
	@kubectl get pods,svc,hpa,ingress -n ecommerce
	@echo "\n📊 Monitoring Namespace:"
	@kubectl get pods,svc -n monitoring

# ──── Thesis Experiment ────────────────────────────────────
# Run experiments inside tmux to survive terminal disconnects:
#   tmux new -s experiment
#   make experiment-first-resume
#   Ctrl+B, D to detach

experiment: ## Run ALL 180 experiment runs (~45 hours)
	@echo "🧪 Starting full experiment (180 runs, ~45 hours)"
	@echo "   Tip: Run inside tmux to survive disconnects"
	@echo ""
	bash scripts/run-experiment.sh

experiment-dry-run: ## Preview the full 180-run execution plan
	bash scripts/run-experiment.sh --dry-run

experiment-resume: ## Resume experiment from last completed run
	bash scripts/run-experiment.sh --resume

experiment-first: ## Run exactly 1 repetition of all 36 configurations to test output validity
	@echo "🧪 Starting first sweep (1 Repetition across all Configs & Patterns, 36 runs)"
	bash scripts/run-experiment.sh --first

experiment-first-resume: ## Resume the 36-run first sweep across both core services
	@echo "🧪 Resuming first sweep (shipping-rate-service + auth-service, rep1 only)"
	bash scripts/run-experiment.sh --first --resume

experiment-pilot: ## Pilot run: shipping-rate-service B1 only (15 runs, ~4 hours)
	@echo "🧪 Starting pilot run (shipping-rate-service, B1 config, 15 runs)"
	bash scripts/run-experiment.sh --service shipping-rate-service --config b1

experiment-shipping: ## Run only shipping-rate-service experiments (90 runs, ~22 hours)
	bash scripts/run-experiment.sh --service shipping-rate-service

experiment-product: ## Product-service is appendix-only and not part of the active core runner
	@echo "⚠️  product-service is exploratory/appendix-only and is not part of the active core experiment runner."
	@echo "   Active core services: shipping-rate-service, auth-service"
	@echo "   Use archived product artifacts instead of launching this target."
	@exit 1

experiment-auth: ## Run only auth-service experiments (90 runs, ~22 hours)
	bash scripts/run-experiment.sh --service auth-service

experiment-validate: ## Validate all completed experiment results for anomalies
	bash scripts/validate-results.sh

experiment-validate-product: ## Validate product-service results only
	bash scripts/validate-results.sh product-service

experiment-validate-auth: ## Validate auth-service results only
	bash scripts/validate-results.sh auth-service

experiment-validate-shipping: ## Validate shipping-rate-service results only
	bash scripts/validate-results.sh shipping-rate-service

experiment-status: ## Show experiment progress
	@echo "=== Experiment Progress ==="
	@if [ -f experiment-results/.experiment-state ]; then \
		DONE=$$(grep -c "^DONE:" experiment-results/.experiment-state 2>/dev/null || echo 0); \
		echo "  Completed runs: $$DONE / 180"; \
		echo "  Remaining:      $$(( 180 - $$DONE ))"; \
		echo "  Est. time left: $$(( (180 - $$DONE) * 15 / 60 )) hours"; \
		echo ""; \
		echo "  Last completed:"; \
		tail -3 experiment-results/.experiment-state | sed 's/DONE://'; \
	else \
		echo "  No experiment state found. Run 'make experiment' to start."; \
	fi

experiment-clean: ## Delete all experiment results (⚠️ destructive!)
	@echo "⚠️  This will delete ALL experiment results!"
	@read -p "Are you sure? (y/N): " confirm; \
	if [ "$$confirm" = "y" ]; then \
		rm -rf experiment-results/; \
		echo "✅ Experiment results deleted."; \
	else \
		echo "Cancelled."; \
	fi

experiment-k6-apply: ## Apply k6 ConfigMaps and Job templates to the cluster
	kubectl apply -f infrastructure/kubernetes/load-testing/k6-job.yaml -n ecommerce
	kubectl apply -f infrastructure/kubernetes/load-testing/k6-auth-job.yaml -n ecommerce
	kubectl apply -f infrastructure/kubernetes/load-testing/k6-shipping-job.yaml -n ecommerce
	@echo "✅ k6 ConfigMaps and Job templates applied"
