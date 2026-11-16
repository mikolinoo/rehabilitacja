# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This is a very small, early-stage project. It currently contains only `test.py`, a PySide6 smoke test of the environment (the `OknoTestowe` window plots two synthetic sine curves with pyqtgraph). The repo has no README, no test suite, no linter/formatter config, and no build system. Don't assume any of these exist; check before relying on them.

The project's purpose (rehabilitation / movement analysis, "analiza symetrii" = symmetry analysis, of joint angles such as the elbow) is inferred from the test plot labels and comments, not from documentation.

## Commands

The project uses a local virtualenv at `.venv` (created with Python 3.12, per `.venv/pyvenv.cfg`).

```powershell
# Activate the venv (PowerShell)
.venv\Scripts\Activate.ps1

# Run the environment smoke test (prints OpenCV version, then opens the Qt window)
python test.py
```

Install dependencies from `requirements.txt`:

```powershell
pip install -r requirements.txt
```

Note: `requirements.txt` is saved as UTF-16 (with BOM), not UTF-8. Pip handles this, but tools that read it as UTF-8 will see garbage. Pinned versions: numpy 2.5.5, opencv-python 5.0.0.93, pyqtgraph 0.14.0, PySide6 6.12.0 (plus PySide6 Addons/Essentials/Pdf/WebEngineCore 6.12.x and shiboken6 6.12.0), colorama 0.4.6.

There is no test runner, lint, or build command configured. If you add one, document it here.

## Architecture

- The whole application currently lives in one file, `test.py`. It is a single `QMainWindow` subclass (`OknoTestowe`) with a `pg.PlotWidget` as its central widget, started by the `if __name__ == "__main__":` block, which creates `QApplication`, shows the window, and enters the Qt event loop via `sys.exit(app.exec())`.
- Dependencies split by role: PySide6 provides the GUI shell, pyqtgraph provides plotting, numpy provides the data arrays, and OpenCV is imported only to verify it loads (the video/image-analysis part of the app is not written yet).
- Code comments and UI strings are in Polish. Keep new user-facing strings and comments consistent with that unless the user says otherwise.

## Environment notes

- Platform is Windows; shell commands should use PowerShell-compatible syntax or the bash tool with forward slashes.
- The IDE is PyCharm (`.idea/` is committed in part; `.idea/workspace.xml` is a per-user file and is already modified in the working tree). Don't edit `.idea/` unless asked.
- `.venv/` is a local environment, not tracked by git (it ignores itself via its own `.gitignore`). Don't modify it or install packages into it without the user's go-ahead.
