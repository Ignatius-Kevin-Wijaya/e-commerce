.PHONY: help dev down build test lint migrate seed deploy clean logs kind-up kind-down kind-load kind-secrets kind-monitoring kind-load-test kind-status

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

lint: ## Lint all services with ruff
	@for svc in auth-service product-service cart-service order-service payment-service; do \
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
	@for svc in auth product cart order payment; do \
		docker build -q -t ghcr.io/your-org/ecommerce-$$svc-service:latest backend/services/$$svc-service; \
		kind load docker-image ghcr.io/your-org/ecommerce-$$svc-service:latest --name ecommerce; \
	done
	@docker build -q -t ghcr.io/your-org/ecommerce-api-gateway:latest backend/api-gateway
	@kind load docker-image ghcr.io/your-org/ecommerce-api-gateway:latest --name ecommerce
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
