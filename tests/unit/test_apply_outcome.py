"""Commit acknowledgement and safe unknown outcomes."""

from seed.insertion import commit_outcome


def test_commit_is_attempted_only_once_without_exposing_transport_error() -> None:
    calls = 0

    def lost() -> None:
        nonlocal calls
        calls += 1
        raise OSError("private driver payload")

    outcome = commit_outcome(lost)
    assert outcome is not None and outcome.status == 6
    assert outcome.insertion.outcome == "unknown" and outcome.insertion.counts is None
    assert outcome.issue is not None and outcome.issue.code == "COMMIT_OUTCOME_UNKNOWN"
    assert "private driver payload" not in outcome.issue.message
    assert calls == 1


def test_successful_commit_returns_without_error() -> None:
    assert commit_outcome(lambda: None) is None
