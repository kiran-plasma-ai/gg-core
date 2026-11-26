"""Tests for deduplication module."""

from __future__ import annotations

from gg_core.core.dedup import Deduplicator, get_dedup


class TestDeduplicator:
    """Tests for Deduplicator class."""

    def test_check_and_add_new_content(self):
        """First check returns True for new content."""
        dedup = Deduplicator()
        assert dedup.check_and_add("session1", "hello world") is True

    def test_check_and_add_duplicate_content(self):
        """Same content returns False on second check."""
        dedup = Deduplicator()
        assert dedup.check_and_add("session1", "hello world") is True
        assert dedup.check_and_add("session1", "hello world") is False

    def test_check_and_add_different_sessions(self):
        """Same content in different sessions returns True each time."""
        dedup = Deduplicator()
        assert dedup.check_and_add("session1", "hello") is True
        assert dedup.check_and_add("session2", "hello") is True

    def test_check_and_add_different_content_same_session(self):
        """Different content in same session returns True each time."""
        dedup = Deduplicator()
        assert dedup.check_and_add("session1", "hello") is True
        assert dedup.check_and_add("session1", "world") is True
        assert dedup.check_and_add("session1", "hello") is False
        assert dedup.check_and_add("session1", "world") is False

    def test_get_new_lines_filters_duplicates(self):
        """get_new_lines only returns first occurrence of each line."""
        dedup = Deduplicator()
        lines = ["line a", "line b", "line a", "line c"]
        new = dedup.get_new_lines("session1", lines)
        assert new == ["line a", "line b", "line c"]

    def test_get_new_lines_empty_input(self):
        """get_new_lines handles empty list."""
        dedup = Deduplicator()
        assert dedup.get_new_lines("session1", []) == []

    def test_get_new_lines_all_new(self):
        """get_new_lines returns all lines when none seen before."""
        dedup = Deduplicator()
        lines = ["alpha", "beta", "gamma"]
        new = dedup.get_new_lines("session1", lines)
        assert new == ["alpha", "beta", "gamma"]

    def test_get_new_lines_all_seen(self):
        """get_new_lines returns empty when all lines already seen."""
        dedup = Deduplicator()
        dedup.check_and_add("session1", "already seen")
        new = dedup.get_new_lines("session1", ["already seen"])
        assert new == []

    def test_reset_clears_session(self):
        """reset clears all hashes for a session."""
        dedup = Deduplicator()
        dedup.check_and_add("session1", "content")
        assert dedup.check_and_add("session1", "content") is False
        dedup.reset("session1")
        assert dedup.check_and_add("session1", "content") is True

    def test_reset_unknown_session_noop(self):
        """reset on unknown session does not raise."""
        dedup = Deduplicator()
        dedup.reset("nonexistent")  # should not raise

    def test_has_session_true(self):
        """has_session returns True after content is added."""
        dedup = Deduplicator()
        dedup.check_and_add("session1", "hello")
        assert dedup.has_session("session1") is True

    def test_has_session_false(self):
        """has_session returns False for unseen session."""
        dedup = Deduplicator()
        assert dedup.has_session("session1") is False

    def test_has_session_after_reset(self):
        """has_session still returns True after reset (session key exists)."""
        dedup = Deduplicator()
        dedup.check_and_add("session1", "hello")
        dedup.reset("session1")
        assert dedup.has_session("session1") is True

    def test_sliding_window_eviction(self):
        """Oldest hashes are evicted when max_size is reached."""
        dedup = Deduplicator(max_size=2)
        import hashlib

        def h(x: str) -> str:
            return hashlib.md5(x.encode(), usedforsecurity=False).hexdigest()[:32]

        dedup.check_and_add("s1", "first")
        dedup.check_and_add("s1", "second")
        dedup.check_and_add("s1", "third")

        deque = dedup._seen["s1"]
        # With max_size=2, after 3 adds: deque = [hash("second"), hash("third")]
        assert h("second") in deque
        assert h("third") in deque
        assert h("first") not in deque

        # Once evicted, content is seen as new again
        assert dedup.check_and_add("s1", "first") is True

    def test_hash_deterministic(self):
        """Hash is deterministic across calls."""
        dedup = Deduplicator()
        h1 = dedup._hash("test content")
        h2 = dedup._hash("test content")
        assert h1 == h2
        assert len(h1) == 32  # MD5 hex digest

    def test_hash_truncated(self):
        """Hash is truncated to 32 characters."""
        dedup = Deduplicator()
        h = dedup._hash("any content")
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)


class TestGetDedup:
    """Tests for the global get_dedup singleton."""

    def test_get_dedup_returns_instance(self):
        """get_dedup returns a Deduplicator instance."""
        dedup = get_dedup()
        assert isinstance(dedup, Deduplicator)

    def test_get_dedup_singleton(self):
        """get_dedup returns the same instance every call."""
        d1 = get_dedup()
        d2 = get_dedup()
        assert d1 is d2

    def test_singleton_shared_state(self):
        """Singleton instances share state across calls."""
        d1 = get_dedup()
        d1.check_and_add("proj", "shared content")
        d2 = get_dedup()
        assert d2.check_and_add("proj", "shared content") is False
