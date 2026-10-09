"""The bundled model weights: their manifest, and which runtime provider runs them.

MT-024 C-2. Nothing in this package imports `onnxruntime`, `PySide6` or any
other part of `mangatl`, so the app's startup check and the build's fetch
(`packaging/fetch_models.py`) can both use it without the inference runtime.
"""
