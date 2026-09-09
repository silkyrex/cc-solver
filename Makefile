test:
	python -m pytest -q tests
example:
	# --allow-clock-drift because the fixture pins pt_time to 11:50 AM. A real run at 11:50 AM
	# does not need it, and a real run at any other hour SHOULD be refused.
	python -m ccsolver.cli take_action --inputs examples/inputs --date 2026-09-08 --allow-clock-drift
