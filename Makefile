.PHONY: help setup install dev up down logs test clean format lint

help:
	@echo "DigitalOcean AI Cost Detective - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make setup              - Complete setup (install deps, create .env)"
	@echo "  make install            - Install backend and frontend dependencies"
	@echo ""
	@echo "Development:"
	@echo "  make dev                - Run backend and frontend in development mode"
	@echo "  make backend-dev        - Run only backend server (uvicorn)"
	@echo "  make frontend-dev       - Run only frontend dev server"
	@echo ""
	@echo "Docker:"
	@echo "  make up                 - Start all services with docker-compose"
	@echo "  make down               - Stop all services"
	@echo "  make logs               - View docker logs"
	@echo "  make rebuild            - Rebuild docker images"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint               - Run linting (flake8, black)"
	@echo "  make format             - Format code with black"
	@echo "  make test               - Run tests"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean              - Remove __pycache__, .pyc, logs"
	@echo "  make env                - Create .env from .env.example"

setup: env install

env:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ Created .env file"; \
	else \
		echo ".env file already exists"; \
	fi
	@if [ ! -f backend/.env ]; then \
		cp backend/.env.example backend/.env; \
		echo "✓ Created backend/.env file"; \
	else \
		echo "backend/.env file already exists"; \
	fi

install: env
	@echo "Installing backend dependencies..."
	cd backend && pip install -r requirements.txt
	@echo "✓ Backend dependencies installed"
	@echo ""
	@echo "Installing frontend dependencies..."
	cd frontend && npm install
	@echo "✓ Frontend dependencies installed"

dev:
	@echo "Starting development servers..."
	@echo "Backend: http://localhost:8000"
	@echo "Frontend: http://localhost:5173"
	@echo "API Docs: http://localhost:8000/docs"
	@echo ""
	@echo "Press Ctrl+C to stop"
	@echo ""
	@tmux new-session -d -s dev -x 200 -y 50
	@tmux send-keys -t dev "cd backend && uvicorn main:app --reload" Enter
	@tmux new-window -t dev
	@tmux send-keys -t dev "cd frontend && npm run dev" Enter
	@tmux attach -t dev

backend-dev:
	cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000

frontend-dev:
	cd frontend && npm run dev

up:
	docker-compose up -d
	@echo "✓ Services started"
	@echo "Backend: http://localhost:8000"
	@echo "Frontend: http://localhost:5173"
	@echo "Postgres: localhost:5432"

down:
	docker-compose down
	@echo "✓ Services stopped"

logs:
	docker-compose logs -f

rebuild:
	docker-compose down
	docker-compose build --no-cache
	docker-compose up -d

test:
	cd backend && pytest -v
	cd frontend && npm run test

format:
	@echo "Formatting Python code..."
	black backend --line-length 100
	@echo "✓ Python code formatted"
	@echo ""
	@echo "Formatting JavaScript code..."
	cd frontend && npm run format
	@echo "✓ JavaScript code formatted"

lint:
	@echo "Linting Python code..."
	flake8 backend --max-line-length 100 --exclude venv,__pycache__
	black backend --check --line-length 100
	@echo "✓ Python linting passed"
	@echo ""
	@echo "Linting JavaScript code..."
	cd frontend && npm run lint
	@echo "✓ JavaScript linting passed"

clean:
	@echo "Cleaning up..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".coverage" -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/htmlcov backend/.coverage 2>/dev/null || true
	rm -rf frontend/dist frontend/node_modules 2>/dev/null || true
	@echo "✓ Cleanup complete"

.DEFAULT_GOAL := help
