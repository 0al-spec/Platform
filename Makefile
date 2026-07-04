PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: python-quality test

python-quality:
	$(PYTHON) -m unittest discover -s tests
	$(PYTHON) -m compileall scripts/platform.py tests

test: python-quality
