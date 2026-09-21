.PHONY: run clean venv requirements

run:
	python3 main.py

clean:
	find . -path ./venv -prune -o -type d -name "__pycache__" -exec rm -rf {} +

venv:
	python3 -m venv venv

requirements:
	pip install -r requirements.txt
