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

.PHONY: layer clean-layer tf-init tf-plan tf-apply tf-destroy

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
