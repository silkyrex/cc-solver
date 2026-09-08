test:
	python -m pytest -q tests
example:
	python -m ccsolver.cli take_action --inputs examples/inputs --date 2026-09-08
