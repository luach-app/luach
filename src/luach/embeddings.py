"""On-device sentence embeddings, for recall that survives a rewording.

What a household tells a calendar keeper is said once and asked for in other
words entirely: "I only do mornings" comes back as "is 4pm alright?", and
"Ben finishes at 3:30" as "when do I need to be at the school?". Lexical
recall matches shared word stems, so it misses every one of those. Measured on
five stored preferences with deliberately non-overlapping probes, lexical recall
found 0/5 and embeddings 5/5 at about 4ms a query, which is why luach's memory
uses them.

fastembed (ONNX runtime), not sentence-transformers: no torch in the image,
and nothing about a family's week leaves the machine, which is the whole
reason to serve the chat model locally in the first place.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from tulip.rag.embeddings.base import EmbeddingResult

from luach import config

logger = logging.getLogger(__name__)


class LocalEmbeddings:
    """A ``BaseEmbedding`` backed by a local ONNX model.

    It satisfies tulip's embedder protocol structurally and deliberately does
    not inherit ``BaseEmbedding``, which would drag torch in behind it. The
    methods are ``async`` because that is how the store calls them, not because
    anything here waits on I/O.
    """

    def __init__(self, model_name: str = "") -> None:
        cache = config.embedding_cache_dir()
        if not cache.exists():
            cache.mkdir(parents=True, exist_ok=True)
        # Two different directories, because they have two different jobs and
        # only one of them can be read-only. `cache_dir` is where the ONNX blobs
        # are — baked into the image, so nothing is fetched at boot. But
        # huggingface_hub underneath fastembed keeps scratch of its own (the Xet
        # backend's), reads its location from $HOME whatever fastembed was told,
        # and writes lock files there. Pointing that at the baked directory
        # would put a write on a read-only path, which is how recall goes down
        # quietly. It goes somewhere writable instead, and is set before
        # the import: the hub reads these at module load.
        scratch = Path(config.env("LUACH_EMBED_SCRATCH") or tempfile.gettempdir()) / "luach-hf"
        try:
            scratch.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("embeddings: %s is not writable", scratch)
        for var in ("HF_HOME", "HF_XET_CACHE", "XDG_CACHE_HOME"):
            os.environ.setdefault(var, str(scratch))

        from fastembed import TextEmbedding

        self._model_name = model_name or config.embedding_model()
        self._m = TextEmbedding(model_name=self._model_name, cache_dir=str(cache))
        self._dim = len(next(iter(self._m.embed(["dimension probe"]))))

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def capabilities(self) -> dict:
        return {"semantic_search": True}

    @property
    def config(self) -> dict:
        return {"model": self._model_name, "dimension": self._dim}

    async def embed(self, text: str) -> EmbeddingResult:
        vector = [float(x) for x in next(iter(self._m.embed([text])))]
        return EmbeddingResult(embedding=vector, text=text, model=self._model_name)

    async def embed_query(self, query: str) -> EmbeddingResult:
        return await self.embed(query)

    async def embed_documents(self, documents: list[str]) -> list[EmbeddingResult]:
        vectors = self._m.embed(documents)
        return [
            EmbeddingResult(embedding=[float(x) for x in vector], text=text, model=self._model_name)
            for text, vector in zip(documents, vectors, strict=True)
        ]

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        return await self.embed_documents(texts)
