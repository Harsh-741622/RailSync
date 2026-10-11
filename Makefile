.PHONY: api test
api:
	python -m uvicorn backend.main:app --reload --port 8000

test:
	python -m pytest -q
