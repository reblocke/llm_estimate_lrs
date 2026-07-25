UV_RUN_OFFLINE := uv run --offline --no-sync
PYTHON := $(UV_RUN_OFFLINE) python
ROOT_PYTHON := .venv/bin/python
CFF_CONVERT := tools/cff/.venv/bin/cffconvert
REPRODUCTION_OUTPUT := results/runs/reproduction
RELEASE_REF ?= HEAD
RELEASE_MODE ?= prepare
RELEASE_CONTRACT ?= release/contracts/v1.0.0.json

.PHONY: setup environment-check cff-env-check kernel lock-check validate-contracts validate-release-governance release-smoke smoke audit validate-data reproduce reference checksums verify-checksums test lint hygiene cff-validate manuscript-parity release-check release-check-final replicate release-archive release-assets-determinism archive-hygiene

setup:
	uv sync --frozen
	uv sync --project tools/cff --frozen

environment-check:
	@test -x "$(ROOT_PYTHON)" || (echo "Root environment is not provisioned; run make setup" && exit 2)

cff-env-check:
	@test -x "$(CFF_CONVERT)" || (echo "CFF environment is not provisioned; run make setup" && exit 2)

lock-check: environment-check
	uv lock --check --offline

validate-contracts: environment-check
	$(PYTHON) scripts/validate_contracts.py

validate-release-governance: environment-check
	$(PYTHON) scripts/validate_contracts.py --candidate-contract $(RELEASE_CONTRACT)

smoke: lock-check verify-checksums validate-contracts validate-data

release-smoke: lock-check verify-checksums validate-release-governance validate-data

audit: smoke hygiene cff-validate lint test reproduce
	git diff --check
	git diff --cached --check

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
	$(UV_RUN_OFFLINE) pytest -q

lint:
	$(UV_RUN_OFFLINE) ruff check scripts tests

hygiene:
	$(PYTHON) scripts/check_release_hygiene.py --repository . $(HYGIENE_ARGS)

cff-validate: cff-env-check
	uv run --project tools/cff --frozen --offline --no-sync cffconvert --validate -i CITATION.cff

manuscript-parity:
	@test -n "$(AUTHOR_MANUSCRIPT_DOCX)" || (echo "AUTHOR_MANUSCRIPT_DOCX is required" && exit 2)
	@test -f "$(AUTHOR_MANUSCRIPT_DOCX)" || (echo "AUTHOR_MANUSCRIPT_DOCX does not name a readable file" && exit 2)
	AUTHOR_MANUSCRIPT_DOCX="$(AUTHOR_MANUSCRIPT_DOCX)" $(UV_RUN_OFFLINE) pytest -q tests/test_manuscript_text.py

release-check: RELEASE_REF := HEAD
release-check: RELEASE_MODE := prepare
release-check: release-smoke hygiene cff-validate lint test reproduce release-archive archive-hygiene
	$(PYTHON) scripts/validate_release.py --release --mode prepare --contract $(RELEASE_CONTRACT) --ref $(RELEASE_REF)

release-check-final: RELEASE_REF := v1.0.0
release-check-final: RELEASE_MODE := final
release-check-final: release-smoke hygiene cff-validate lint test reproduce
	$(PYTHON) scripts/validate_release.py --release --mode final --contract $(RELEASE_CONTRACT) --ref $(RELEASE_REF)

replicate:
	@test -n "$(RUN_ID)" || (echo "RUN_ID is required" && exit 2)
	@test -n "$(EXPERIMENT)" || (echo "EXPERIMENT is required" && exit 2)
	@test -n "$(MODELS)" || (echo "MODELS is required" && exit 2)
	@test -n "$(MAX_CALLS)" || (echo "MAX_CALLS is required" && exit 2)
	@test "$(CONFIRM_LIVE_API)" = "YES" || (echo "Set CONFIRM_LIVE_API=YES after reviewing the call count" && exit 2)
	$(PYTHON) scripts/run_replication.py --run-id "$(RUN_ID)" --experiment "$(EXPERIMENT)" --models $(MODELS) --max-calls "$(MAX_CALLS)" --confirm-live-api YES

release-archive: validate-release-governance
	$(PYTHON) scripts/build_release_assets.py --repository . --output-dir dist --ref $(RELEASE_REF) --mode $(RELEASE_MODE) --contract $(RELEASE_CONTRACT)

release-assets-determinism: validate-release-governance
	$(PYTHON) scripts/build_release_assets.py --repository . --output-dir dist --ref $(RELEASE_REF) --mode $(RELEASE_MODE) --contract $(RELEASE_CONTRACT) --verify-determinism

archive-hygiene:
	$(PYTHON) scripts/check_release_hygiene.py --repository . \
		--archive dist/llm-estimate-lrs-v1.0.0.zip \
		--archive dist/reference-tables-v1.0.0.zip \
		--text-file dist/notebooks/data_analysis.executed.ipynb \
		--text-file dist/notebooks/supplementary_analyses.executed.ipynb \
		--text-file dist/validation-report.json \
		--text-file dist/release-attestation.json \
		--text-file dist/SHA256SUMS
