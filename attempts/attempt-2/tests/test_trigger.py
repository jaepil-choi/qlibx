"""Pure schedule-shaped Strategy trigger contracts."""

from datetime import UTC, datetime, timedelta

from qlibx import EveryCandidate, EveryNSessions, TriggerContext


def candidates(count: int) -> tuple[datetime, ...]:
    start = datetime(2024, 1, 2, 6, 30, tzinfo=UTC)
    return tuple(start + timedelta(days=index) for index in range(count))


def evaluate(policy: EveryCandidate | EveryNSessions, count: int) -> tuple[str, ...]:
    fired_at: list[datetime] = []
    decisions: list[str] = []
    for index, candidate in enumerate(candidates(count)):
        result = policy.evaluate(
            TriggerContext(
                candidate_time=candidate,
                candidate_index=index,
                fired_at=tuple(fired_at),
            )
        )
        decisions.append(result.decision)
        if result.decision == "FIRE":
            fired_at.append(candidate)
    return tuple(decisions)


def test_every_n_sessions_is_pure_and_deterministic_without_runtime_authority() -> None:
    policy = EveryNSessions(n=3)

    first = evaluate(policy, 8)
    repeated = evaluate(policy, 8)

    assert first == repeated == ("FIRE", "SKIP", "SKIP", "FIRE", "SKIP", "SKIP", "FIRE", "SKIP")
    assert policy.requirements() == ()
    assert policy.evaluate(
        TriggerContext(candidate_time=candidates(1)[0], candidate_index=0)
    ).accesses == ()


def test_policy_parameters_change_the_frozen_trigger_identity() -> None:
    assert EveryNSessions(n=5).frozen_config_fingerprint() == (
        EveryNSessions(n=5).frozen_config_fingerprint()
    )
    assert EveryNSessions(n=5).frozen_config_fingerprint() != (
        EveryNSessions(n=10).frozen_config_fingerprint()
    )
    assert EveryCandidate().frozen_config_fingerprint() != (
        EveryNSessions(n=1).frozen_config_fingerprint()
    )
