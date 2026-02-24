.PHONY: test check build run stop logs web batch

URL ?= https://example.com
PYTHON ?= .venv/bin/python

build:
	docker compose build

run:
	docker compose up -d

stop:
	docker compose down

logs:
	docker compose logs -f

web:
	uvicorn web_app.main:app --host 0.0.0.0 --port 8084 --reload

test:
	$(PYTHON) -m pytest

check:
	$(PYTHON) cli.py $(URL)

batch:
	$(PYTHON) scripts/batch_scan.py
