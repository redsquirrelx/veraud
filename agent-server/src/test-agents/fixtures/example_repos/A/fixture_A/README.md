# ShopLab — Architectural boundary test repository

A minimal, runnable Python e-commerce backend for testing static architectural-boundary investigation. No external runtime dependencies or database are needed.

## Run

```powershell
$env:PYTHONPATH = "src"
python -m shoplab.app
python -m unittest discover -s tests -v
```

On macOS/Linux, use `PYTHONPATH=src python -m shoplab.app` and `PYTHONPATH=src python -m unittest discover -s tests -v`.

This repo contains both routine dependencies and unusual dependencies. They are intentional test input, **not assertions that every inter-module import is a defect**. An auditor should infer technical boundaries from code, not from this README. Compare its results to the separate evaluator key (not included here).
