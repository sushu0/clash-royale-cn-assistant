UV ?= uv
TARGET_VERSION ?= v0.0.0-local

.PHONY: setup install-hooks dev dev-legacy cn cn-check lint lint-check type-check test test-emulator test-all dev-validation build-msi build-dmg

# UV_PROJECT_ENVIRONMENT selects a separate verification environment when needed.
setup:
	$(UV) sync --locked --python 3.12

install-hooks:
	$(UV) run --locked --no-sync pre-commit install

dev: cn

dev-legacy:
	$(UV) run --locked --no-sync python -m pyclashbot

# Current Windows Chinese-client console. Starting the window does not start a
# battle; its Start control launches the selected strategy through the watchdog.
cn:
	$(UV) run --locked --no-sync python scripts/cn_bot_control.py

cn-check:
	$(UV) run --locked --no-sync python -m scripts.cn_windows_entry --self-check

lint:
	$(UV) run --locked --no-sync pre-commit run --all-files

# Read-only checks, suitable before deciding whether to apply formatter changes.
lint-check:
	$(UV) run --locked --no-sync ruff check .
	$(UV) run --locked --no-sync ruff format --check .

type-check:
	$(UV) run --locked --no-sync ty check

# Offline by default (pytest addopts carries -m "not emulator"); safe everywhere.
test:
	$(UV) run --locked --no-sync pytest -q

# Full live-emulator suite, ordered, stop at first failure. --integration flips the
# default marker and selects a backend; the first SUITE tests boot the emulator and
# launch Clash. Backend resolves from EMULATOR / a cached pick / interactive menu;
# ADB_SERIAL is optional and sticky.
test-emulator:
	$(UV) run --locked --no-sync pytest -x -s --integration $(if $(EMULATOR),--emulator $(EMULATOR)) $(if $(ADB_SERIAL),--adb-serial $(ADB_SERIAL))

test-all: test test-emulator

dev-validation: lint-check type-check test

build-msi:
	$(UV) run --locked --group build python scripts/setup_msi.py bdist_msi --target-version $(TARGET_VERSION)

build-dmg:
	$(UV) run --locked --group build python scripts/setup_macos.py --target-version $(TARGET_VERSION)
