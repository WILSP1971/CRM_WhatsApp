.PHONY: help setup up down logs health backup restore test-egress migrate seed clean ps shell wa-sim wa-sim-dup wa-sim-status wa-sim-challenge

# Variables
COMPOSE_FILE := docker-compose.yml
BACKEND_DIR := backend
DOCKER_COMPOSE := docker compose -f $(COMPOSE_FILE)

# Colores para output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
RED := \033[0;31m
NC := \033[0m # No Color

help:
	@echo "$(BLUE)OmniCore AI — Makefile de Operación On-Prem$(NC)"
	@echo ""
	@echo "Targets disponibles:"
	@echo "  $(GREEN)setup$(NC)              Preparar entorno (.env, validar compose)"
	@echo "  $(GREEN)up$(NC)                 Arrancar todos los servicios (docker compose up -d)"
	@echo "  $(GREEN)down$(NC)               Parar todos los servicios (sin borrar volúmenes)"
	@echo "  $(GREEN)clean$(NC)              Remover todo incluyendo volúmenes (CUIDADO)"
	@echo "  $(GREEN)logs$(NC)               Ver logs de todos los servicios (en tiempo real)"
	@echo "  $(GREEN)logs-api$(NC)           Ver logs solo de la API"
	@echo "  $(GREEN)logs-ia$(NC)            Ver logs solo de Ollama (IA)"
	@echo "  $(GREEN)health$(NC)             Verificar health de todos los servicios"
	@echo "  $(GREEN)ps$(NC)                 Listar estado de containers"
	@echo "  $(GREEN)migrate$(NC)            Ejecutar migraciones de BD (alembic upgrade head)"
	@echo "  $(GREEN)seed$(NC)               Sembrar datos ficticios (tenant demo)"
	@echo "  $(GREEN)models$(NC)             Descargar modelos Ollama (qwen2.5 + embeddings)"
	@echo "  $(GREEN)models-q4$(NC)          Descargar modelo Q4 (CPU, más pequeño)"
	@echo "  $(GREEN)backup$(NC)             Hacer backup de PostgreSQL"
	@echo "  $(GREEN)restore$(NC)            Restaurar PostgreSQL desde backup"
	@echo "  $(GREEN)test-egress$(NC)        Verificar que egress del contenedor IA está bloqueado"
	@echo "  $(GREEN)check-externos$(NC)     Ejecutar auditoría de 'cero externos' (SENSIBLE)"
	@echo "  $(GREEN)shell-api$(NC)          Abrir shell en contenedor api"
	@echo "  $(GREEN)shell-db$(NC)           Abrir shell en contenedor db (psql)"
	@echo "  $(GREEN)stats$(NC)              Ver estadísticas de recursos (CPU, RAM)"
	@echo "  $(GREEN)wa-sim$(NC)             Emitir webhook WhatsApp con firma HMAC válida"
	@echo "  $(GREEN)wa-sim-dup$(NC)         Emitir webhook duplicado (prueba idempotencia)"
	@echo "  $(GREEN)wa-sim-status$(NC)      Emitir callbacks de status (sent→delivered→read)"
	@echo "  $(GREEN)wa-sim-challenge$(NC)   Emitir GET challenge (suscripción de webhook)"
	@echo "  $(GREEN)docs$(NC)               Imprimir referencias a documentación"
	@echo ""

setup:
	@echo "$(BLUE)▶ Preparando entorno...$(NC)"
	@if [ ! -f .env ]; then \
		echo "$(YELLOW)Copiando .env.example a .env...$(NC)"; \
		cp .env.example .env; \
		echo "$(YELLOW)⚠️  IMPORTANTE: Editar .env con secretos fuertes:$(NC)"; \
		echo "  - DB_PASSWORD (≥32 caracteres)"; \
		echo "  - JWT_SECRET_KEY (≥32 caracteres)"; \
		echo ""; \
		echo "  Usar: openssl rand -hex 32"; \
	else \
		echo "$(GREEN)✓ .env ya existe$(NC)"; \
	fi
	@echo "$(BLUE)▶ Validando docker-compose.yml...$(NC)"
	@$(DOCKER_COMPOSE) config --quiet && echo "$(GREEN)✓ docker-compose.yml válido$(NC)" || (echo "$(RED)✗ Error en docker-compose.yml$(NC)"; exit 1)
	@echo "$(GREEN)✓ Entorno preparado$(NC)"

up:
	@echo "$(BLUE)▶ Arrancando servicios...$(NC)"
	@$(DOCKER_COMPOSE) up -d
	@echo "$(YELLOW)⏳ Esperando healthchecks (máximo 60s)...$(NC)"
	@for i in 1 2 3 4 5 6; do \
		if $(DOCKER_COMPOSE) ps | grep -q "healthy"; then \
			echo "$(GREEN)✓ Servicios saludables$(NC)"; \
			break; \
		fi; \
		sleep 10; \
	done
	@$(DOCKER_COMPOSE) ps

down:
	@echo "$(BLUE)▶ Parando servicios...$(NC)"
	@$(DOCKER_COMPOSE) stop --timeout 30
	@echo "$(GREEN)✓ Servicios parados (volúmenes persistidos)$(NC)"

clean:
	@echo "$(RED)⚠️  CUIDADO: Esto borrará TODOS los datos (BD, Redis, modelos)$(NC)"
	@read -p "¿Estás seguro? (escribe 'si'): " confirm; \
	if [ "$$confirm" = "si" ]; then \
		echo "$(BLUE)▶ Removiendo todo...$(NC)"; \
		$(DOCKER_COMPOSE) down -v; \
		echo "$(GREEN)✓ Limpieza completa$(NC)"; \
	else \
		echo "$(YELLOW)Cancelado$(NC)"; \
	fi

logs:
	@$(DOCKER_COMPOSE) logs -f

logs-api:
	@$(DOCKER_COMPOSE) logs -f api --tail=50

logs-ia:
	@$(DOCKER_COMPOSE) logs -f ia --tail=50

health:
	@echo "$(BLUE)▶ Verificando salud de servicios...$(NC)"
	@echo "PostgreSQL:"
	@$(DOCKER_COMPOSE) exec db pg_isready -U postgres && echo "$(GREEN)✓ OK$(NC)" || echo "$(RED)✗ ERROR$(NC)"
	@echo "Redis:"
	@$(DOCKER_COMPOSE) exec redis redis-cli ping | grep -q PONG && echo "$(GREEN)✓ OK$(NC)" || echo "$(RED)✗ ERROR$(NC)"
	@echo "Ollama:"
	@$(DOCKER_COMPOSE) exec ia curl -s http://localhost:11434/api/tags | grep -q models && echo "$(GREEN)✓ OK$(NC)" || echo "$(RED)✗ ERROR$(NC)"
	@echo "API:"
	@curl -s http://localhost:8000/healthz | grep -q '"status":"ok"' && echo "$(GREEN)✓ OK$(NC)" || echo "$(RED)✗ ERROR$(NC)"

ps:
	@$(DOCKER_COMPOSE) ps

migrate:
	@echo "$(BLUE)▶ Ejecutando migraciones (alembic upgrade head)...$(NC)"
	@$(DOCKER_COMPOSE) exec api alembic upgrade head
	@echo "$(GREEN)✓ Migraciones completadas$(NC)"

seed:
	@echo "$(BLUE)▶ Sembrando datos ficticios (tenant demo)...$(NC)"
	@$(DOCKER_COMPOSE) exec api python -m app.scripts.seed_demo_tenant
	@echo "$(GREEN)✓ Seed completado$(NC)"

models:
	@echo "$(BLUE)▶ Descargando modelos Ollama...$(NC)"
	@echo "  - qwen2.5:7b-instruct (LLM, ~5 GB, GPU: 10-15 min, CPU: 30-45 min)"
	@$(DOCKER_COMPOSE) exec ia ollama pull qwen2.5:7b-instruct
	@echo "  - nomic-embed-text (embeddings, ~274 MB)"
	@$(DOCKER_COMPOSE) exec ia ollama pull nomic-embed-text
	@echo "$(GREEN)✓ Modelos descargados$(NC)"
	@$(DOCKER_COMPOSE) exec ia curl -s http://localhost:11434/api/tags | grep -A1 '"name"'

models-q4:
	@echo "$(BLUE)▶ Descargando modelo Q4 (CPU)...$(NC)"
	@$(DOCKER_COMPOSE) exec ia ollama pull qwen2.5:7b-instruct-q4_1
	@echo "$(YELLOW)⚠️  Actualizar .env: OLLAMA_MODEL=qwen2.5:7b-instruct-q4_1$(NC)"
	@echo "$(YELLOW)Luego: make restart-ia$(NC)"

backup:
	@echo "$(BLUE)▶ Creando backup de PostgreSQL...$(NC)"
	@mkdir -p ./backups
	@$(DOCKER_COMPOSE) exec db pg_dump -U postgres -d omnicore_ai --format=plain > ./backups/backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "$(GREEN)✓ Backup creado en ./backups/$(NC)"
	@ls -lh ./backups/ | tail -5

restore:
	@echo "$(BLUE)▶ Restaurando desde backup...$(NC)"
	@echo "$(RED)CUIDADO: Esto sobrescribe los datos actuales$(NC)"
	@read -p "¿Estás seguro? (escribe 'si'): " confirm; \
	if [ "$$confirm" = "si" ]; then \
		read -p "Ingresa la ruta del backup (ej. ./backups/backup_20260918_150000.sql): " backup_file; \
		if [ -f "$$backup_file" ]; then \
			$(DOCKER_COMPOSE) stop api rag_worker sentiment_worker; \
			$(DOCKER_COMPOSE) restart db; \
			echo "$(YELLOW)⏳ Esperando a que PostgreSQL esté listo...$(NC)"; \
			sleep 10; \
			$(DOCKER_COMPOSE) exec -T db psql -U postgres < "$$backup_file"; \
			$(DOCKER_COMPOSE) up -d api rag_worker sentiment_worker; \
			echo "$(GREEN)✓ Restauración completada$(NC)"; \
		else \
			echo "$(RED)✗ Archivo no encontrado: $$backup_file$(NC)"; \
		fi; \
	else \
		echo "$(YELLOW)Cancelado$(NC)"; \
	fi

test-egress:
	@echo "$(BLUE)▶ Verificando que egress del contenedor IA está bloqueado...$(NC)"
	@$(DOCKER_COMPOSE) exec ia timeout 5 wget -T5 -qO- http://1.1.1.1 2>/dev/null \
		&& echo "$(RED)✗ FALLO: egress desbloqueado (conexión exitosa)$(NC)" \
		|| echo "$(GREEN)✓ EGRESS BLOQUEADO (timeout o error de red, como se esperaba)$(NC)"

check-externos:
	@echo "$(BLUE)▶ Ejecutando check-externos-backend.sh...$(NC)"
	@bash $(BACKEND_DIR)/check-externos-backend.sh

wa-sim:
	@echo "$(BLUE)▶ Emitiendo webhook WhatsApp (mensaje entrante)...$(NC)"
	@export WHATSAPP_APP_SECRET=$${WHATSAPP_APP_SECRET:-$$(openssl rand -hex 32)}; \
	export WEBHOOK_URL=http://localhost:8000/api/v1/whatsapp/webhook; \
	echo "$(YELLOW)app_secret: $$WHATSAPP_APP_SECRET$(NC)"; \
	python $(BACKEND_DIR)/tools/wa_webhook_simulator.py

wa-sim-dup:
	@echo "$(BLUE)▶ Emitiendo webhook duplicado (prueba idempotencia)...$(NC)"
	@export WHATSAPP_APP_SECRET=$${WHATSAPP_APP_SECRET:-$$(openssl rand -hex 32)}; \
	export WEBHOOK_URL=http://localhost:8000/api/v1/whatsapp/webhook; \
	python $(BACKEND_DIR)/tools/wa_webhook_simulator.py --duplicate

wa-sim-status:
	@echo "$(BLUE)▶ Emitiendo callbacks de status (sent→delivered→read)...$(NC)"
	@export WHATSAPP_APP_SECRET=$${WHATSAPP_APP_SECRET:-$$(openssl rand -hex 32)}; \
	export WEBHOOK_URL=http://localhost:8000/api/v1/whatsapp/webhook; \
	python $(BACKEND_DIR)/tools/wa_webhook_simulator.py --status

wa-sim-challenge:
	@echo "$(BLUE)▶ Emitiendo GET challenge (suscripción)...$(NC)"
	@export WEBHOOK_URL=http://localhost:8000/api/v1/whatsapp/webhook; \
	python $(BACKEND_DIR)/tools/wa_webhook_simulator.py --challenge

shell-api:
	@$(DOCKER_COMPOSE) exec api /bin/bash

shell-db:
	@$(DOCKER_COMPOSE) exec db psql -U postgres

stats:
	@$(DOCKER_COMPOSE) stats

docs:
	@echo "$(BLUE)Documentación Disponible:$(NC)"
	@echo ""
	@echo "  $(GREEN)OPERACION.md$(NC) — Guía de despliegue on-prem"
	@echo "    - Requisitos previos (hardware, software)"
	@echo "    - Preparación del entorno (.env, secretos)"
	@echo "    - Arranque de servicios"
	@echo "    - Descarga de modelos locales"
	@echo "    - Migraciones e inicialización"
	@echo "    - Verificación de 'cero externos'"
	@echo ""
	@echo "  $(GREEN)RUNBOOK.md$(NC) — Operación y troubleshooting"
	@echo "    - Arranque/parada ordenado"
	@echo "    - Healthchecks y diagnóstico"
	@echo "    - Backups y restauración"
	@echo "    - Rotación de secretos"
	@echo "    - Respuesta a incidentes comunes"
	@echo "    - Procedimiento de rollback"
	@echo "    - Verificación de egress bloqueado"
	@echo "    - Verificación de RLS multi-tenant"
	@echo ""
	@echo "  $(GREEN)DEPLOYMENT_CHECKLIST.md$(NC) — Pre-flight para producción"
	@echo "    - Seguridad (C3: secretos, C4: criterios verificables)"
	@echo "    - Red y firewall (egress bloqueado)"
	@echo "    - TLS/HTTPS"
	@echo "    - Base de datos (borrado lógico, backups)"
	@echo "    - Modelos locales"
	@echo "    - Observabilidad"
	@echo "    - Multi-tenant y RLS"
	@echo "    - Integración SPA"
	@echo "    - Pruebas de carga"
	@echo "    - Aprobación y deploy"
	@echo ""
	@echo "  $(GREEN)EXAMPLES_OPENAPI.md$(NC) — Ejemplos de API"
	@echo "    - Health checks"
	@echo "    - Autenticación (login)"
	@echo "    - Conversaciones"
	@echo "    - RAG con citas"
	@echo "    - Análisis de sentimiento"
	@echo "    - Derechos de datos (HABEAS DATA)"
	@echo "    - WebSocket chat en tiempo real"
	@echo ""
	@echo "  $(GREEN)README.md$(NC) — Overview del proyecto"
	@echo "    - Descripción general"
	@echo "    - Estructura del proyecto"
	@echo "    - Módulos de la SPA"
	@echo ""
	@echo "$(YELLOW)Lectura recomendada:$(NC)"
	@echo "  1. Empezar con OPERACION.md (setup inicial)"
	@echo "  2. Después RUNBOOK.md (para troubleshooting)"
	@echo "  3. DEPLOYMENT_CHECKLIST.md (antes de desplegar a PROD)"
	@echo "  4. EXAMPLES_OPENAPI.md (para integración de clientes)"

.PHONY: restart-api restart-ia
restart-api:
	@echo "$(BLUE)▶ Restarting API...$(NC)"
	@$(DOCKER_COMPOSE) restart api
	@echo "$(GREEN)✓ API restarted$(NC)"

restart-ia:
	@echo "$(BLUE)▶ Restarting Ollama...$(NC)"
	@$(DOCKER_COMPOSE) restart ia
	@echo "$(GREEN)✓ Ollama restarted$(NC)"

.DEFAULT_GOAL := help
