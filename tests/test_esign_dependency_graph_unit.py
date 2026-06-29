"""Unit tests for the pure backend dependency-graph mirror (task 17.4).

Covers ``validate_dependencies`` and ``add_dependency`` in
``app.modules.esignatures.dependency_graph`` — the server-side twin of the
frontend's ``dependencyGraph.ts``. These are parity checks for the Property 20
cases (self-loop / cycle / acyclic), exercising both dict-shaped and
``FieldDependency``-shaped inputs. All functions under test are pure, no I/O.

Requirements: 14.2, 14.4
"""

from __future__ import annotations

from app.modules.esignatures.dependency_graph import (
    CODE_DEPENDENCY_CYCLE,
    CODE_DEPENDENCY_SELF,
    FieldDependency,
    add_dependency,
    validate_dependencies,
)


def _dep(dependent: str, trigger: str, *, condition: str = "is_checked", effect: str = "show") -> dict:
    """Build a dict-shaped dependency edge (the wire shape)."""
    return {
        "dependent_field": dependent,
        "trigger_field": trigger,
        "condition": condition,
        "effect": effect,
    }


# ---------------------------------------------------------------------------
# validate_dependencies — acyclic accepted
# ---------------------------------------------------------------------------


def test_validate_accepts_empty_set():
    result = validate_dependencies([])
    assert result.ok is True
    assert result.code is None


def test_validate_accepts_none():
    result = validate_dependencies(None)
    assert result.ok is True
    assert result.code is None


def test_validate_accepts_acyclic_dict_set():
    # a -> b -> c, plus a -> c. No cycle.
    deps = [_dep("a", "b"), _dep("b", "c"), _dep("a", "c")]
    result = validate_dependencies(deps)
    assert result.ok is True
    assert result.code is None


def test_validate_accepts_acyclic_field_dependency_set():
    deps = [
        FieldDependency("a", "b", "is_checked", "show"),
        FieldDependency("b", "c", "equals", "require"),
    ]
    result = validate_dependencies(deps)
    assert result.ok is True


# ---------------------------------------------------------------------------
# validate_dependencies — self-loop rejected (R14.2)
# ---------------------------------------------------------------------------


def test_validate_rejects_self_loop_dict():
    deps = [_dep("a", "b"), _dep("c", "c")]
    result = validate_dependencies(deps)
    assert result.ok is False
    assert result.code == CODE_DEPENDENCY_SELF
    assert result.message
    assert "loop" in result.message.lower()


def test_validate_rejects_self_loop_field_dependency():
    deps = [FieldDependency("x", "x", "is_checked", "show")]
    result = validate_dependencies(deps)
    assert result.ok is False
    assert result.code == CODE_DEPENDENCY_SELF


# ---------------------------------------------------------------------------
# validate_dependencies — cycle rejected (R14.4)
# ---------------------------------------------------------------------------


def test_validate_rejects_two_node_cycle_dict():
    # a -> b -> a
    deps = [_dep("a", "b"), _dep("b", "a")]
    result = validate_dependencies(deps)
    assert result.ok is False
    assert result.code == CODE_DEPENDENCY_CYCLE
    assert result.message
    assert "loop" in result.message.lower()


def test_validate_rejects_longer_cycle():
    # a -> b -> c -> a
    deps = [_dep("a", "b"), _dep("b", "c"), _dep("c", "a")]
    result = validate_dependencies(deps)
    assert result.ok is False
    assert result.code == CODE_DEPENDENCY_CYCLE


# ---------------------------------------------------------------------------
# add_dependency — appends a valid edge
# ---------------------------------------------------------------------------


def test_add_appends_valid_edge_to_empty_set():
    result = add_dependency([], _dep("a", "b"))
    assert result.ok is True
    assert result.deps is not None
    assert len(result.deps) == 1
    assert result.deps[0].dependent_field == "a"
    assert result.deps[0].trigger_field == "b"


def test_add_appends_valid_edge_preserving_existing():
    existing = [_dep("a", "b")]
    result = add_dependency(existing, _dep("b", "c"))
    assert result.ok is True
    assert result.deps is not None
    assert len(result.deps) == 2
    # Original input list is not mutated.
    assert len(existing) == 1


def test_add_accepts_field_dependency_shaped_inputs():
    existing = [FieldDependency("a", "b", "is_checked", "show")]
    edge = FieldDependency("b", "c", "equals", "require")
    result = add_dependency(existing, edge)
    assert result.ok is True
    assert result.deps is not None
    assert len(result.deps) == 2


# ---------------------------------------------------------------------------
# add_dependency — rejects a self-loop without storing it (R14.2)
# ---------------------------------------------------------------------------


def test_add_rejects_self_loop_without_storing():
    result = add_dependency([_dep("a", "b")], _dep("c", "c"))
    assert result.ok is False
    assert result.code == CODE_DEPENDENCY_SELF
    # Rejected edge is never returned/stored.
    assert result.deps is None


# ---------------------------------------------------------------------------
# add_dependency — rejects a cycle-closing edge without storing it (R14.4)
# ---------------------------------------------------------------------------


def test_add_rejects_cycle_closing_edge_without_storing():
    # Existing a -> b; adding b -> a would close a cycle.
    result = add_dependency([_dep("a", "b")], _dep("b", "a"))
    assert result.ok is False
    assert result.code == CODE_DEPENDENCY_CYCLE
    assert result.deps is None


def test_add_rejects_transitive_cycle_closing_edge():
    # Existing a -> b -> c; adding c -> a would close a 3-node cycle.
    existing = [_dep("a", "b"), _dep("b", "c")]
    result = add_dependency(existing, _dep("c", "a"))
    assert result.ok is False
    assert result.code == CODE_DEPENDENCY_CYCLE
    assert result.deps is None
