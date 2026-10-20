.PHONY: setup data index test lint eval eval-gate serve ui up down synth deploy destroy
setup:            ## create .venv with Python 3.12 and install everything
	uv sync --all-extras --group dev
data:             ## synthetic dataset -> curated parquet (use `make data-real` for Kaggle CSVs)
	uv run insightly data synthetic --users 5000 && uv run insightly data curate
data-real:        ## curate the real TheLook CSVs placed in data/raw/
	uv run insightly data curate
index:
	uv run insightly index
test:
	uv run pytest -q
lint:
	uv run ruff check . && uv run ruff format --check .
eval:
	uv run insightly eval run
eval-gate:
	uv run insightly eval gate
serve:
	uv run insightly serve --reload
ui:
	uv run --extra ui streamlit run ui/streamlit_app.py
up:
	docker compose up --build
down:
	docker compose down
synth:
	cd infra && uv run --group infra npx -y aws-cdk@2 synth
deploy:
	cd infra && uv run --group infra npx -y aws-cdk@2 deploy --all
destroy:
	cd infra && uv run --group infra npx -y aws-cdk@2 destroy --all
