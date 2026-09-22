.PHONY: run sync clean

run:
	uv run main.py

sync:
	uv sync

clean:
	find . -path ./venv -prune -o -path ./.venv -prune -o -type d -name "__pycache__" -exec rm -rf {} +
