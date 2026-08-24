"""Config/revision-graph tests for Alembic that don't require a live database
(STORY-009). These only read alembic.ini and the versions/ directory on disk —
they never import env.py directly, since env.py's module-level code runs
actual migrations against a real connection when executed.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def test_alembic_ini_parses() -> None:
    cfg = _alembic_config()
    assert cfg.get_main_option("script_location") is not None


def test_exactly_one_head_revision_exists() -> None:
    script = ScriptDirectory.from_config(_alembic_config())
    heads = script.get_heads()
    assert len(heads) == 1


def test_baseline_revision_has_no_parent() -> None:
    """The root of the chain — not necessarily "head" anymore now that
    STORY-010 added a second migration on top of it."""
    script = ScriptDirectory.from_config(_alembic_config())
    roots = [rev for rev in script.walk_revisions() if rev.down_revision is None]
    assert len(roots) == 1
    assert "baseline" in (roots[0].doc or "").lower()


def test_head_revision_is_the_add_job_indexes_migration() -> None:
    """STORY-057 chained a new migration onto STORY-015's — the head moved
    again. (This is the fifth time this exact test has needed updating —
    STORY-009→010, STORY-010→011, STORY-011→014, STORY-014→015, now
    STORY-015→057 — a cheap, mechanical adjustment each time. Worth
    generalizing in a future Story if this keeps recurring, but not part of
    STORY-057's approved scope to refactor now.)"""
    script = ScriptDirectory.from_config(_alembic_config())
    head = script.get_revision(script.get_heads()[0])
    assert head.down_revision is not None
    assert "add job indexes" in (head.doc or "").lower()
