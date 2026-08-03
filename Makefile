.PHONY: help start_dependencies stop_dependencies compile format lint dev pre-commit test test_only

help: ## Muestra este mensaje de ayuda
	@echo "Comandos disponibles en Focusly Workflows:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

start_dependencies: ## Inicia contenedores PostgreSQL y Redis en segundo plano
	docker compose up -d db redis

stop_dependencies: ## Detiene los contenedores de dependencias
	docker compose down

compile: ## Verifica la sintaxis del código y la comprobación estática de tipos (Mypy)
	uv run mypy app

format: ## Formatea y aplica auto-correcciones al código con Ruff
	uv run ruff format app
	uv run ruff check --fix app

lint: ## Revisa el estilo de código e inconsistencias de tipos sin modificar archivos
	uv run ruff check app
	uv run mypy app

dev: ## Inicia el servidor de desarrollo FastAPI con recarga en vivo
	uv run uvicorn app.main:app --reload --port 8000

pre-commit: ## Ejecuta todas las validaciones de git pre-commit
	uv run pre-commit run --all-files

test: ## Ejecuta la suite completa de pruebas unitarias
	uv run pytest

test_only: ## Ejecuta solo un archivo o patrón de prueba (ej. make test_only FILE=test_scheduler.py o make test_only K=test_name)
	@if [ -z "$(FILE)" ] && [ -z "$(K)" ]; then \
		echo "Error: Especifica FILE=<archivo> o K=<filtro>. Ej: make test_only FILE=test_scheduler.py"; \
		exit 1; \
	fi
	@if [ -n "$(FILE)" ]; then \
		uv run pytest $(FILE); \
	elif [ -n "$(K)" ]; then \
		uv run pytest -k "$(K)"; \
	fi
