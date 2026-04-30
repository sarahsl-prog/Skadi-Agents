.PHONY: install scan test clean

install:
	poetry install --with dev,security

scan:
	bandit -r src/ -c .bandit.yaml
	safety check
	pip-audit --desc
	semgrep --config=p/python --config=p/security-audit src/

test:
	poetry run pytest --cov=src --cov-fail-under=80

lint:
	ruff check src/
	mypy src/
	black --check src/

fix:
	ruff --fix src/
	black src/
	isort src/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete 2>/dev/null; true
