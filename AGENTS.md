# AGENTS.md

## Scope

These instructions apply to the whole repository.

## Project Overview

RHEEDCapture is a Python 3.12 desktop application for RHEED image capture. It uses
PySide6 for the UI, Basler/pypylon for camera access, motor adapters for stage
control, and TIFF/JSON files for capture output.

## Repository Layout

* `rheed_capture/domain/`: Pure domain models and calculations. Keep this layer free
  of Qt, filesystem, camera, and motor dependencies.
* `rheed_capture/application/`: Use cases and ports. Coordinate domain logic through
  interfaces rather than concrete hardware or UI classes.
* `rheed_capture/infrastructure/`: Adapters for cameras, motors, storage, and config.
  Hardware-specific behavior belongs here.
* `rheed_capture/presentation/qt/`: Qt panels, widgets, viewmodels, workers, and app
  wiring. Keep widget logic thin when a viewmodel can own state conversion.
* `rheed_capture/data_formats/`: Serializable file formats and metadata helpers.
* `tests/`: Unit and Qt tests. Add focused tests near the behavior being changed.
* `docs/`: Human-facing specifications and design notes.

## Development Commands

* Install or refresh dependencies: `uv sync`
* Run all tests: `uv run pytest -q`
* Run focused tests: `uv run pytest -q tests/path/to_test.py`
* Run lint: `uv run ruff check .`
* Run type checks: `uv run ty check`
* Build the Windows executable: `uv run poe build`

## Safe Commands

The following commands are safe to run without additional confirmation:

* `uv sync`
* `uv run pytest -q`
* `uv run pytest -q tests/path/to_test.py`
* `uv run ruff check .`
* `uv run ty check`

## Coding Guidelines

* Follow the existing architecture before adding a new abstraction.
* Keep domain and application code independent of Qt and concrete hardware adapters.
* Use application ports for behavior that touches cameras, motors, storage, or time.
* Keep Qt panels responsible for layout and signal wiring; put reusable state parsing
  and validation in viewmodels or small helper widgets.
* Prefer dataclasses and typed values for capture settings, plans, and metadata.
* Do not add fallback paths, compatibility layers, or defensive abstractions unless
  they are necessary for a concrete requirement.
* Prefer direct, explicit behavior over broad "just in case" handling.
* Do not make code overly dense.
* Separate logical blocks with blank lines when it improves readability.
* Keep comments concise and close to the code they explain.
* Prefer clear names and simple structure over explanatory comments.
* Do not add broad exception handling around hardware operations unless the caller can
  report or recover from the failure.

## Settings Policy

* Do not silently preserve compatibility for `settings.json` schema changes.
* When changing `settings.json` fields, first clarify whether to:

  * keep backward compatibility,
  * migrate old settings,
  * reset incompatible settings, or
  * intentionally break compatibility.

## Docstring and Comment Guidelines

* Use docstrings for public behavior, not history.
* Before writing a multi-line docstring, consider whether a one-line docstring is enough.
* If implementation details need explanation, consider a short inline comment instead
  of a long docstring.
* Avoid comments about historical background, rejected approaches, or internal reasoning.
* Preserve such notes only when they explain a necessary workaround, a failed approach
  that must not be repeated, or a recovery procedure that is known to work.

## Safety Notes

* Do not assume real hardware is connected.
* Do not run hardware-control code unless explicitly requested.
* Do not create, modify, move, or delete files under `data/`.
* Prefer dry-run, mock, or simulated adapters when testing hardware-facing behavior.

## Testing Guidelines

* Add or update tests for changed behavior in the closest matching test module.
* For UI changes, prefer widget or viewmodel tests that assert state and signal behavior.
* For hardware-facing code, use mocks or application ports rather than real devices.
* Run the smallest relevant test set while iterating, then run lint and type checks for
  shared behavior changes.

## Files To Avoid

* Do not commit, edit, move, or delete `.venv/`, `data/`, `dist/`, cache directories,
  or local `settings.json`.
* Do not edit generated `__pycache__` files.
* Do not modify `uv.lock` unless dependencies actually changed.
