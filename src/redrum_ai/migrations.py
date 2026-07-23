"""Backward-compatible migration import surface."""
from redrum_memory.migrations import MIGRATIONS, run_migrations

__all__ = ["MIGRATIONS", "run_migrations"]
