PYTHON := uv run python
REPRODUCTION_OUTPUT := results/runs/reproduction
RELEASE_REF ?= HEAD
RELEASE_MODE ?= prepare

.PHONY: setup kernel validate-data reproduce reference checksums verify-checksums test lint hygiene cff-validate manuscript-parity release-check release-check-final replicate release-archive release-assets-determinism archive-hygiene

setup:
	uv sync --frozen
	uv sync --project tools/cff --frozen

kernel:
	$(PYTHON) -m ipykernel install --sys-prefix --name llm-estimate-lrs-v1 --display-name "Python (llm-estimate-lrs v1)"

validate-data:
	$(PYTHON) scripts/validate_release.py --data-only

reproduce:
	$(PYTHON) scripts/reproduce_paper.py --offline --output $(REPRODUCTION_OUTPUT) --replace-output

reference:
	$(PYTHON) scripts/compute_reference_results.py --input data/curated/diagnostic_lrs_manuscript_v1.csv --output results/reference

checksums:
	$(PYTHON) scripts/build_checksums.py --root . --output checksums/SHA256SUMS

verify-checksums:
	$(PYTHON) scripts/verify_checksums.py checksums/SHA256SUMS

test:
	uv run pytest -q

lint:
	uv run ruff check scripts tests

hygiene:
	$(PYTHON) scripts/check_release_hygiene.py --repository . $(HYGIENE_ARGS)

cff-validate:
	uv run --project tools/cff --frozen cffconvert --validate -i CITATION.cff

manuscript-parity:
	@test -n "$(AUTHOR_MANUSCRIPT_DOCX)" || (echo "AUTHOR_MANUSCRIPT_DOCX is required" && exit 2)
	@test -f "$(AUTHOR_MANUSCRIPT_DOCX)" || (echo "AUTHOR_MANUSCRIPT_DOCX does not name a readable file" && exit 2)
	AUTHOR_MANUSCRIPT_DOCX="$(AUTHOR_MANUSCRIPT_DOCX)" uv run pytest -q tests/test_manuscript_text.py

release-check: RELEASE_REF := HEAD
release-check: RELEASE_MODE := prepare
release-check: verify-checksums validate-data hygiene cff-validate lint test reproduce release-archive archive-hygiene
	$(PYTHON) scripts/validate_release.py --release --mode prepare

release-check-final: RELEASE_REF := v1.0.0
release-check-final: RELEASE_MODE := final
release-check-final: verify-checksums validate-data hygiene cff-validate lint test reproduce
	$(PYTHON) scripts/validate_release.py --release --mode final

replicate:
	@test -n "$(RUN_ID)" || (echo "RUN_ID is required" && exit 2)
	@test -n "$(EXPERIMENT)" || (echo "EXPERIMENT is required" && exit 2)
	@test -n "$(MODELS)" || (echo "MODELS is required" && exit 2)
	@test -n "$(MAX_CALLS)" || (echo "MAX_CALLS is required" && exit 2)
	@test "$(CONFIRM_LIVE_API)" = "YES" || (echo "Set CONFIRM_LIVE_API=YES after reviewing the call count" && exit 2)
	$(PYTHON) scripts/run_replication.py --run-id "$(RUN_ID)" --experiment "$(EXPERIMENT)" --models $(MODELS) --max-calls "$(MAX_CALLS)" --confirm-live-api YES

release-archive:
	$(PYTHON) scripts/build_release_assets.py --repository . --output-dir dist --ref $(RELEASE_REF) --mode $(RELEASE_MODE)

release-assets-determinism:
	$(PYTHON) scripts/build_release_assets.py --repository . --output-dir dist --ref $(RELEASE_REF) --mode $(RELEASE_MODE) --verify-determinism

archive-hygiene:
	$(PYTHON) scripts/check_release_hygiene.py --repository . \
		--archive dist/llm-estimate-lrs-v1.0.0.zip \
		--archive dist/reference-tables-v1.0.0.zip \
		--text-file dist/notebooks/data_analysis.executed.ipynb \
		--text-file dist/notebooks/supplementary_analyses.executed.ipynb \
		--text-file dist/validation-report.json \
		--text-file dist/release-attestation.json \
		--text-file dist/SHA256SUMS
