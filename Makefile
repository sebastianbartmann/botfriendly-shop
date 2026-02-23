.PHONY: test check

URL ?= https://example.com
PYTHON ?= .venv/bin/python

test:
	$(PYTHON) -m pytest

check:
	$(PYTHON) cli.py $(URL)
