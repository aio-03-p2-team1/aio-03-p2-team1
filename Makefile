.DEFAULT_GOAL := help
.PHONY: help setup redis-up backend-dev backend-test frontend-install frontend-dev frontend-test frontend-build test build check

help: ## 사용 가능한 명령 보기
	@printf '사용법: make <명령>\n\n'
	@printf '개발 환경\n'
	@printf '  setup             백엔드 의존성 설치 (uv sync)\n'
	@printf '  redis-up          로컬 Redis 실행\n'
	@printf '  backend-dev       백엔드 개발 서버 실행\n'
	@printf '  frontend-install  프론트엔드 의존성 설치\n'
	@printf '  frontend-dev      프론트엔드 개발 서버 실행\n\n'
	@printf '검증\n'
	@printf '  backend-test      백엔드 테스트\n'
	@printf '  frontend-test     프론트엔드 테스트\n'
	@printf '  frontend-build    프론트엔드 빌드\n'
	@printf '  test              백엔드·프론트엔드 테스트\n'
	@printf '  build             프론트엔드 빌드\n'
	@printf '  check             테스트와 프론트엔드 빌드\n'

setup: ## 백엔드 의존성 설치
	uv sync

redis-up: ## 로컬 Redis 실행
	docker compose up -d redis

backend-dev: ## 백엔드 개발 서버 실행
	uv run uvicorn backend.main:app --reload --port 8000

backend-test: ## 백엔드 테스트
	uv run pytest

frontend-install: ## 프론트엔드 의존성 설치
	npm --prefix frontend ci

frontend-dev: ## 프론트엔드 개발 서버 실행
	npm --prefix frontend run dev

frontend-test: ## 프론트엔드 테스트
	npm --prefix frontend test

frontend-build: ## 프론트엔드 빌드
	npm --prefix frontend run build

test: backend-test frontend-test ## 백엔드·프론트엔드 테스트

build: frontend-build ## 프론트엔드 빌드

check: test build ## 테스트와 프론트엔드 빌드
