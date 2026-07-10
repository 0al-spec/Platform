PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: python-quality test hosted-managed-contract hosted-managed-compose-contract

python-quality:
	$(PYTHON) -m unittest discover -s tests
	$(PYTHON) -m compileall scripts/platform.py tests

test: python-quality

hosted-managed-contract:
	$(PYTHON) -m unittest \
		tests.test_hosted_managed_operation_canary \
		tests.test_hosted_managed_operation_service \
		tests.test_hosted_managed_operation_queue

hosted-managed-compose-contract:
	$(PYTHON) scripts/validate_hosted_managed_compose.py
