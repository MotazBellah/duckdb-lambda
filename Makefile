# Lambda target. Keep in sync with infra/variables.tf (lambda_runtime / lambda_architectures).
PYTHON_VERSION ?= 3.14
ARCH           ?= arm64

ifeq ($(ARCH),arm64)
PLATFORM := aarch64-manylinux_2_28
else
PLATFORM := x86_64-manylinux_2_28
endif

LAYER_DIR   := layer
BUILD_DIR   := $(LAYER_DIR)/build
DIST_DIR    := $(LAYER_DIR)/dist
LAYER_ZIP   := $(DIST_DIR)/duckdb-layer.zip

.PHONY: layer clean-layer tf-init tf-plan tf-apply tf-destroy \
	list-functions upload-data run-stores run-signals run-matched run-pipeline \
	demo-signals-oom demo-signals-fix

# Floci (local AWS emulator). Dummy credentials are fine for the emulator.
FLOCI_ENDPOINT ?= http://localhost:4566
PROJECT        ?= duckdb-demo
export AWS_ACCESS_KEY_ID     ?= test
export AWS_SECRET_ACCESS_KEY ?= test
export AWS_REGION            ?= us-east-1
AWSF := aws --endpoint-url $(FLOCI_ENDPOINT)

# Deps come straight from [dependency-groups].lambda in pyproject.toml.
layer: clean-layer
	mkdir -p $(BUILD_DIR)/python $(DIST_DIR)
	uv pip install --group lambda \
		--target $(BUILD_DIR)/python \
		--python-platform $(PLATFORM) \
		--python-version $(PYTHON_VERSION) \
		--only-binary=:all:
	find $(BUILD_DIR)/python -type d -name __pycache__ -prune -exec rm -rf {} +
	cd $(BUILD_DIR) && zip -qr ../dist/duckdb-layer.zip python
	@ls -lh $(LAYER_ZIP)

clean-layer:
	rm -rf $(BUILD_DIR) $(DIST_DIR)

tf-init:
	terraform -chdir=infra init

tf-plan:
	terraform -chdir=infra plan

tf-apply:
	terraform -chdir=infra apply

tf-destroy:
	terraform -chdir=infra destroy

# --- Pipeline (run against Floci after `make tf-apply`) ---------------------
list-functions:
	$(AWSF) lambda list-functions --query 'Functions[].FunctionName'

upload-data:
	$(AWSF) s3 cp data/stores.csv s3://$(PROJECT)-landing/stores.csv
	$(AWSF) s3 sync data/signal_data s3://$(PROJECT)-landing/signal_data/

# a) stores -> staging/stores/stores.parquet
run-stores:
	$(AWSF) lambda invoke --function-name $(PROJECT)-stores-handler \
		--cli-binary-format raw-in-base64-out \
		--payload '{"Records":[{"s3":{"bucket":{"name":"$(PROJECT)-landing"},"object":{"key":"stores.csv"}}}]}' \
		/dev/stdout

# b) signals -> staging/signals/signals.parquet
run-signals:
	$(AWSF) lambda invoke --function-name $(PROJECT)-signals-handler \
		--cli-read-timeout 900 /dev/stdout

# c) match -> curated/matched_signals/matched_signals.parquet
run-matched:
	$(AWSF) lambda invoke --function-name $(PROJECT)-matched-signals-handler \
		--cli-read-timeout 900 /dev/stdout

# Order matters: matched needs the stores and signals outputs.
run-pipeline: upload-data run-stores run-signals run-matched

# --- Demo: signals OOM and its fix (ROW_GROUP_SIZE) -------------------------
# Same small Lambda in both scenarios. Only the Parquet row group size differs.
# Needs data in landing first (`make upload-data`). Override any value, e.g.
#   make demo-signals-oom DEMO_OOM_ROW_GROUP=10000000
# Add TF_APPROVE=-auto-approve to skip terraform's confirmation prompt.
DEMO_MEMORY        ?= 1024
DEMO_DUCKDB_LIMIT  ?= 700MB
DEMO_OOM_ROW_GROUP ?= 20000000
DEMO_FIX_ROW_GROUP ?= 100000
TF_APPROVE         ?=

# 1) Huge row groups: each writer thread buffers too many rows -> Out of Memory Error
demo-signals-oom:
	terraform -chdir=infra apply $(TF_APPROVE) \
		-var signals_memory_size=$(DEMO_MEMORY) \
		-var signals_duckdb_memory_limit=$(DEMO_DUCKDB_LIMIT) \
		-var signals_row_group_size=$(DEMO_OOM_ROW_GROUP)
	$(MAKE) run-signals

# 2) Same memory, small row groups: the writer flushes often -> succeeds
demo-signals-fix:
	terraform -chdir=infra apply $(TF_APPROVE) \
		-var signals_memory_size=$(DEMO_MEMORY) \
		-var signals_duckdb_memory_limit=$(DEMO_DUCKDB_LIMIT) \
		-var signals_row_group_size=$(DEMO_FIX_ROW_GROUP)
	$(MAKE) run-signals
