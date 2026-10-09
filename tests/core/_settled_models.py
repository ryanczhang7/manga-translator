"""MT-024 C-1's settled manifest, transcribed from the story - never derived.

The five SHA-256 values and byte counts are MT-002's `## Decided`, `[MEASURED]`
(2026-09-12); the four revisions are the PO's 2026-10-08 reading of the Hugging
Face API. They are spelled out here, character for character, so the real
`packaging/models.json` is judged against the story and not against itself.

This module imports nothing from `mangatl`: it is an oracle, and an oracle that
imported the layout constants it is compared with would agree with them by
construction. `test_fetch_models.py` is what ties the `path` column to
`mangatl.compose` and `mangatl.ocr.session`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
MANIFEST: Final = REPO_ROOT / "packaging" / "models.json"
FETCH_SCRIPT: Final = REPO_ROOT / "packaging" / "fetch_models.py"

#: C-1's JSON block, entry by entry, in its order. Every field.
SETTLED_ENTRIES: Final[tuple[dict[str, object], ...]] = (
    {
        "name": "comic-text-detector",
        "role": "detect",
        "repo": "mayocream/comic-text-detector-onnx",
        "revision": "a5d67ec772adef819ef5b0e7aa701fcf4c8bf74a",
        "file": "comic-text-detector.onnx",
        "path": "comic-text-detector.onnx",
        "sha256": "1a86ace74961413cbd650002e7bb4dcec4980ffa21b2f19b86933372071d718f",
        "bytes": 94669756,
        "licence": (
            "GPL-3.0 (upstream dmMaze/comic-text-detector; the HF repo's metadata"
            " says apache-2.0 - architecture.md D13)"
        ),
    },
    {
        "name": "manga-ocr-encoder",
        "role": "ocr",
        "repo": "onnx-community/manga-ocr-base-ONNX",
        "revision": "f9023406bb2f6b17df67bc4a327c56ecd20611f0",
        "file": "onnx/encoder_model.onnx",
        "path": "manga-ocr/encoder_model.onnx",
        "sha256": "df35f64c2400ea860c70a2d06f2a1f99892374a78c89fcf35308076557a3863f",
        "bytes": 343377067,
        "licence": "Apache-2.0",
    },
    {
        "name": "manga-ocr-decoder",
        "role": "ocr",
        "repo": "onnx-community/manga-ocr-base-ONNX",
        "revision": "f9023406bb2f6b17df67bc4a327c56ecd20611f0",
        "file": "onnx/decoder_model.onnx",
        "path": "manga-ocr/decoder_model.onnx",
        "sha256": "31ca14d6dee6b3966144e128d0481d5a91f5083cbced81fe7a9571713fa50cd4",
        "bytes": 117445718,
        "licence": "Apache-2.0",
    },
    {
        "name": "manga-ocr-vocab",
        "role": "ocr",
        "repo": "kha-white/manga-ocr-base",
        "revision": "aa6573bd10b0d446cbf622e29c3e084914df9741",
        "file": "vocab.txt",
        "path": "manga-ocr/vocab.txt",
        "sha256": "344fbb6b8bf18c57839e924e2c9365434697e0227fac00b88bb4899b78aa594d",
        "bytes": 24072,
        "licence": "Apache-2.0",
    },
    {
        "name": "lama",
        "role": "clean",
        "repo": "Carve/LaMa-ONNX",
        "revision": "c3c0c9e468934d62e79c329e35d82dd09ff8c444",
        "file": "lama_fp32.onnx",
        "path": "lama_fp32.onnx",
        "sha256": "1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6",
        "bytes": 208044816,
        "licence": (
            "Apache-2.0 (repository metadata; the big-lama checkpoint's provenance"
            " is unverified - MT-002 E7, D13)"
        ),
    },
)

#: C-2's `ModelEntry` fields, in declaration order.
ENTRY_FIELDS: Final = (
    "name",
    "role",
    "repo",
    "revision",
    "file",
    "path",
    "sha256",
    "bytes",
    "licence",
)
