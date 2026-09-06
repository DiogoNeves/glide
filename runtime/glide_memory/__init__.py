"""Glide's portable Markdown memory and disposable local search index."""
__version__ = "0.1.0"
from .store import Store, StoreError, ConflictError, IntegrityError
__all__ = ["Store", "StoreError", "ConflictError", "IntegrityError", "__version__"]
