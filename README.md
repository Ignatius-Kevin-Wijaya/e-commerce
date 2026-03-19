# 🛒 E-Commerce Microservices on Kubernetes

A production-style e-commerce platform built as microservices, containerized with Docker, and orchestrated with Kubernetes — designed for learning.

## Architecture

```
Client → API Gateway (8080)
              ├── Auth Service    (8001) → PostgreSQL (auth-db)
              ├── Product Service (8002) → PostgreSQL (product-db)
              ├── Cart Service    (8003) → Redis
              ├── Order Service   (8004) → PostgreSQL (order-db)
              └── Payment Service (8005) → PostgreSQL (order-db)
```

## Quick Start

```bash
# 1. Copy env file
cp .env.example .env

# 2. Start everything
make dev

# 3. Test it
curl http://localhost:8080/health

# 4. View logs
make logs
```

## Services

| Service | Port | Database | Description |
|---------|------|----------|-------------|
| API Gateway | 8080 | — | Routing, auth check, rate limiting |
| Auth | 8001 | PostgreSQL | Registration, login, JWT tokens |
| Product | 8002 | PostgreSQL | Product catalog, categories |
| Cart | 8003 | Redis | Shopping cart (session-based) |
| Order | 8004 | PostgreSQL | Order lifecycle management |
| Payment | 8005 | PostgreSQL | Payment processing (simulated Stripe) |

## Make Commands

```bash
make help      # Show all commands
make dev       # Start services (docker-compose)
make down      # Stop services
make test      # Run all unit tests
make lint      # Lint all services
make migrate   # Run DB migrations
make seed      # Seed sample data
make deploy    # Deploy to Kubernetes
make clean     # Full cleanup
```

## Tech Stack

- **Language**: Python 3.11 + FastAPI
- **Databases**: PostgreSQL, Redis
- **Auth**: JWT (python-jose) + bcrypt
- **Containers**: Docker + Docker Compose
- **Orchestration**: Kubernetes (Deployments, Services, HPA, Ingress)
- **IaC**: Terraform (AWS EKS)
- **Monitoring**: Prometheus + Grafana + Loki
- **CI/CD**: GitHub Actions

## Project Structure

```
├── services/           # Microservices (auth, product, cart, order, payment)
├── api-gateway/        # Reverse proxy + middleware
├── infrastructure/     # Kubernetes manifests + Terraform
├── monitoring/         # Prometheus, Grafana, Loki configs
├── scripts/            # Build, deploy, migrate, seed helpers
└── .github/workflows/  # CI/CD pipelines
```

## Learning Path

1. **Week 1** — Docker, FastAPI, JWT authentication
2. **Week 2** — CRUD APIs, Redis caching, pagination
3. **Week 3** — Service-to-service communication, payments
4. **Week 4** — API Gateway pattern
5. **Week 5** — Kubernetes fundamentals
6. **Week 6** — Infrastructure as Code + Observability
