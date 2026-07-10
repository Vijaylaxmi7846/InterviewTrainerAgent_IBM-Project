"""
rag_engine.py — Retrieval-Augmented Generation Engine
Loads knowledge base documents, chunks them, builds a FAISS vector index,
and retrieves relevant context for every LLM call.
"""
from __future__ import annotations

import os
import re
import glob
import pickle
import logging
import warnings
from pathlib import Path
from typing import List, Tuple

# ── Silence noisy third-party loggers at startup ─────────────────────────────
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("filelock").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

# Tell HuggingFace to use local cache and suppress all hub warnings
os.environ.setdefault(
    "SENTENCE_TRANSFORMERS_HOME",
    os.path.join(os.path.dirname(__file__), "instance", "models"),
)
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# Suppress "unauthenticated requests" banner — it prints to stderr bypassing logging
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
os.environ.setdefault("HUGGINGFACE_HUB_VERBOSITY", "error")

def _silence_hf_warnings() -> None:
    """Patch huggingface_hub's noisy stderr warning after import."""
    try:
        import huggingface_hub.utils._http as _hf_http
        _orig = getattr(_hf_http, "_warn_once", None)
        if _orig:
            _hf_http._warn_once = lambda *a, **kw: None  # type: ignore[attr-defined]
    except Exception:
        pass

logger = logging.getLogger(__name__)

# ── Optional heavy imports (fail gracefully so app still runs without them) ──
try:
    import numpy as np
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    np = None  # type: ignore
    logger.warning("faiss-cpu/numpy not installed — RAG will use simple keyword search fallback.")

try:
    from sentence_transformers import SentenceTransformer
    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False
    logger.warning("sentence-transformers not installed — RAG will use simple keyword search fallback.")


# ─────────────────────────────────────────────────────────────────────────────
#  Text Chunker
# ─────────────────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping word-level chunks."""
    words = text.split()
    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += chunk_size - overlap
    return chunks


def _load_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _load_pdf(path: str) -> str:
    try:
        import PyPDF2
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            return " ".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        logger.error("PDF read error %s: %s", path, e)
        return ""


def _load_docx(path: str) -> str:
    try:
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        logger.error("DOCX read error %s: %s", path, e)
        return ""


def load_document(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in (".txt", ".md"):
        return _load_text_file(path)
    elif ext == ".pdf":
        return _load_pdf(path)
    elif ext == ".docx":
        return _load_docx(path)
    else:
        return _load_text_file(path)


# ─────────────────────────────────────────────────────────────────────────────
#  RAG Engine
# ─────────────────────────────────────────────────────────────────────────────

class RAGEngine:
    """
    Lightweight RAG engine:
      - Loads .txt / .pdf / .docx files from a directory.
      - Chunks text and embeds with sentence-transformers.
      - Builds a FAISS index for fast similarity search.
      - Falls back to keyword BM25-style search if libraries unavailable.
    """

    INDEX_CACHE = "instance/rag_index.pkl"

    def __init__(
        self,
        kb_dir: str = "knowledge_base",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        top_k: int = 5,
        min_score: float = 0.3,
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self.kb_dir = kb_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k
        self.min_score = min_score
        self.model_name = model_name
        self.chunks: List[str] = []
        self.index = None
        self.embedder = None
        self._ready = False

        self._build_index()

    # ── Index Building ────────────────────────────────────────────────────────

    def _build_index(self) -> None:
        """Load KB documents, chunk, embed, and build FAISS index."""
        patterns = ["*.txt", "*.md", "*.pdf", "*.docx"]
        files: List[str] = []
        for pat in patterns:
            files.extend(glob.glob(os.path.join(self.kb_dir, pat)))

        if not files:
            logger.warning("No knowledge base documents found in '%s'.", self.kb_dir)
            return

        # Load & chunk all documents
        all_chunks: List[str] = []
        for fpath in sorted(files):
            try:
                text = load_document(fpath)
                chunks = _chunk_text(text, self.chunk_size, self.chunk_overlap)
                all_chunks.extend(chunks)
                logger.info("Loaded %d chunks from %s", len(chunks), fpath)
            except Exception as e:
                logger.error("Failed to load %s: %s", fpath, e)

        self.chunks = [c for c in all_chunks if len(c.strip()) > 30]

        if FAISS_AVAILABLE and ST_AVAILABLE:
            self._build_faiss_index()
        else:
            logger.info("Using keyword-based retrieval (FAISS/ST not available).")
            self._ready = True

    def _build_faiss_index(self) -> None:
        _silence_hf_warnings()   # patch HF hub before it can print anything
        try:
            logger.info("Loading sentence transformer model '%s'...", self.model_name)
            self.embedder = SentenceTransformer(self.model_name)
            embeddings = self.embedder.encode(
                self.chunks,
                batch_size=64,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            ).astype("float32")

            dim = embeddings.shape[1]
            self.index = faiss.IndexFlatIP(dim)   # Inner product = cosine (normalized)
            self.index.add(embeddings)
            self._ready = True
            logger.info("FAISS index built: %d chunks, dim=%d", len(self.chunks), dim)

            # Persist cache
            os.makedirs("instance", exist_ok=True)
            with open(self.INDEX_CACHE, "wb") as f:
                pickle.dump({"chunks": self.chunks, "embeddings": embeddings}, f)

        except Exception as e:
            logger.error("FAISS index build failed: %s", e)
            self._ready = True   # Fallback to keyword

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def retrieve(self, query: str) -> str:
        """Return a formatted context string of top-k relevant chunks."""
        if not self.chunks:
            return ""

        if self.index is not None and self.embedder is not None:
            return self._faiss_retrieve(query)
        else:
            return self._keyword_retrieve(query)

    def _faiss_retrieve(self, query: str) -> str:
        try:
            q_emb = self.embedder.encode(
                [query],
                convert_to_numpy=True,
                normalize_embeddings=True,
            ).astype("float32")
            scores, indices = self.index.search(q_emb, self.top_k)
            results: List[str] = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0:
                    continue
                if float(score) >= self.min_score:
                    results.append(self.chunks[idx].strip())
            return "\n\n---\n\n".join(results) if results else ""
        except Exception as e:
            logger.error("FAISS retrieval error: %s", e)
            return self._keyword_retrieve(query)

    def _keyword_retrieve(self, query: str) -> str:
        """Simple TF-style keyword matching fallback."""
        query_words = set(re.findall(r"\b\w{3,}\b", query.lower()))
        scored: List[Tuple[int, str]] = []
        for chunk in self.chunks:
            chunk_words = set(re.findall(r"\b\w{3,}\b", chunk.lower()))
            score = len(query_words & chunk_words)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [c for _, c in scored[: self.top_k]]
        return "\n\n---\n\n".join(top) if top else ""

    # ── Document Upload ───────────────────────────────────────────────────────

    def add_document(self, filepath: str) -> int:
        """Add a new document to the index at runtime."""
        try:
            text = load_document(filepath)
            new_chunks = _chunk_text(text, self.chunk_size, self.chunk_overlap)
            new_chunks = [c for c in new_chunks if len(c.strip()) > 30]
            self.chunks.extend(new_chunks)

            if self.index is not None and self.embedder is not None:
                emb = self.embedder.encode(
                    new_chunks,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                ).astype("float32")
                self.index.add(emb)

            logger.info("Added %d chunks from '%s'.", len(new_chunks), filepath)
            return len(new_chunks)
        except Exception as e:
            logger.error("Failed to add document %s: %s", filepath, e)
            return 0

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)
