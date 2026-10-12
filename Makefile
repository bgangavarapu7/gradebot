.PHONY: up down reset test eval lint logs

# Created from the example on first use, so a fresh clone needs no manual setup.
.env:
	cp .env.example .env

up: .env  ## start the API (http://localhost:8000/docs) and Postgres with schema + seed
	docker compose up --build --detach --wait

down:
	docker compose down

reset:  ## drop the database volume so schema.sql and seed.sql are applied again
	docker compose down --volumes

test: .env  ## run the test suite against Postgres
	docker compose run --rm --build test pytest -q

eval: .env  ## run the golden-set eval; non-zero exit if the pass rate is below threshold
	docker compose run --rm --build --no-deps test python -m evals.run_eval

lint: .env
	docker compose run --rm --build --no-deps test ruff check .

logs:
	docker compose logs --follow app
