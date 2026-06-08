.PHONY: up up-ghcr down logs health scan install

up:
	docker compose up -d --build

up-ghcr:
	docker compose -f docker-compose.ghcr.yml up -d

down:
	docker compose down

logs:
	docker compose logs -f gigastt

health:
	./scripts/healthcheck.sh

scan:
	./scripts/recognition-worker.sh

install:
	./scripts/install-server.sh
