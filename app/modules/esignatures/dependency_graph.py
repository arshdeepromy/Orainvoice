"""Pure backend mirror of the field-dependency graph (R14, conditional fields).

This module is the **server-side** twin of the frontend's pure
``dependencyGraph.ts`` (task 17.1). It re-checks the conditional-field
dependency rules **before** any Documenso call so a crafted payload can never
bypass the client check — exactly the same defence-in-depth posture as
:mod:`app.modules.esignatures.field_validation`. Like that module, everything
here is a **pure function**: no DB, no network, no other I/O and no global
state, which keeps the rules directly unit/property-testable in-memory
(task 17.4).

The dependency model
--------------------
A :class:`FieldDependency` is ``{ dependent_field, trigger_field, condition,
effect }`` (the design's R14 dependency model, snake-cased for the wire):

* ``dependent_field`` — the field governed by the rule.
* ``trigger_field`` — **another** field in the same Field_Set whose value the
  rule observes. A self-trigger (``trigger_field == dependent_field``) is
  rejected (R14.2).
* ``condition`` — one of the supported :data:`SUPPORTED_CONDITIONS`
  (``is_checked`` / ``is_not_checked`` / ``equals`` / ``not_equals`` /
  ``is_filled`` / ``is_empty``) (R14.3).
* ``effect`` — ``show`` or ``require`` on the dependent field (R14.1).

The rules enforced (byte-for-byte the same rule set as ``dependencyGraph.ts``)
-----------------------------------------------------------------------------
Over the directed graph whose edges run ``dependent_field -> trigger_field``:

* **R14.2** — a self-loop (an edge whose trigger is its own dependent) is
  rejected with ``dependency_self`` and never stored.
* **R14.4** — an edge (or a submitted set) that forms a cycle is rejected with
  ``dependency_cycle`` and never stored; an acyclic set is accepted.

Both rejection codes surface the design's single humanized message ("That
dependency would create a loop. A field can't ultimately depend on itself.") so
the service can fold the result straight into the ``{ message, code }`` shape
(see ``errors.py``). The codes are defined here as constants so this pure
module carries its own codes without importing the error tables (mirroring
``field_validation.py``).

Requirements: 14.1, 14.2, 14.4
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Supported conditions (R14.3) and effects (R14.1)
# ---------------------------------------------------------------------------
#: The six supported dependency conditions. Mirrors ``dependencyGraph.ts``'s
#: ``DependencyCondition`` ``kind`` set exactly.
SUPPORTED_CONDITIONS: frozenset[str] = frozenset(
    {"is_checked", "is_not_checked", "equals", "not_equals", "is_filled", "is_empty"}
)

#: The two supported dependency effects on the dependent field.
SUPPORTED_EFFECTS: frozenset[str] = frozenset({"show", "require"})

# ---------------------------------------------------------------------------
# Machine-readable codes (design "Error Handling" table, both HTTP 422). The
# central ``ESIGN_ERROR_MESSAGES`` / ``ESIGN_ERROR_STATUS`` tables register the
# canonical message/status; defined here as constants so this pure module is
# self-contained (same pattern as ``field_validation.py``).
# ---------------------------------------------------------------------------
CODE_DEPENDENCY_SELF = "dependency_self"
CODE_DEPENDENCY_CYCLE = "dependency_cycle"

#: The single humanized, leak-free message shared by both rejection codes
#: (design Error Handling table: "Dependency closes a cycle / self-trigger").
_LOOP_MESSAGE = (
    "That dependency would create a loop. A field can't ultimately depend on itself."
)


@dataclass(frozen=True)
class FieldDependency:
    """One field dependency edge, as re-validated on the server.

    Mirrors the design's R14 dependency model and the frontend
    ``FieldDependency`` value. ``dependent_field`` / ``trigger_field`` are
    opaque field identifiers (the client's stable per-field keys); this module
    only compares them for equality and reachability, never interprets them.
    The validator also accepts plain mappings or any object exposing these as
    attributes (so a Pydantic schema or a raw dict both work).
    """

    dependent_field: str
    trigger_field: str
    condition: str
    effect: str


@dataclass(frozen=True)
class DependencyResult:
    """Outcome of :func:`validate_dependencies` / :func:`add_dependency`.

    ``ok`` is ``True`` only when the set/edge satisfies every rule. When ``ok``
    is ``False`` the result names the **first** offending condition so the
    caller can reject the whole send atomically (no Documenso call, no rows
    persisted) and surface ``message`` directly. ``message`` is always a
    non-empty, human-readable sentence that never leaks raw DB/exception text.
    On the ``ok`` path of :func:`add_dependency`, ``deps`` carries the new
    dependency list (the input list plus the accepted edge).
    """

    ok: bool
    code: str | None = None
    message: str | None = None
    #: The accepted dependency list, on the ``ok`` path of ``add_dependency``.
    deps: tuple[FieldDependency, ...] | None = None


def _get(item: Any, field: str) -> Any:
    """Read ``field`` from a dependency-like item (mapping or attribute object).

    Defensive: returns ``None`` when absent. Pure, never raises.
    """
    if isinstance(item, Mapping):
        return item.get(field)
    return getattr(item, field, None)


def _coerce(item: Any) -> FieldDependency:
    """Coerce a dependency-like item into a :class:`FieldDependency`.

    Accepts an existing :class:`FieldDependency`, a mapping, or any object
    exposing the schema's ``dependent_client_id`` / ``trigger_client_id``
    (``DependencyIn``, R14) — or the legacy ``dependent_field`` /
    ``trigger_field`` aliases — plus ``condition`` / ``effect``. Missing values
    become empty strings so equality/reachability stay total and never raise.
    Pure.
    """
    if isinstance(item, FieldDependency):
        return item
    # Prefer the schema field names (DependencyIn); fall back to the legacy
    # ``*_field`` aliases so existing FieldDependency-shaped inputs still work.
    dependent = _get(item, "dependent_client_id")
    if not isinstance(dependent, str):
        dependent = _get(item, "dependent_field")
    trigger = _get(item, "trigger_client_id")
    if not isinstance(trigger, str):
        trigger = _get(item, "trigger_field")
    condition = _get(item, "condition")
    effect = _get(item, "effect")
    return FieldDependency(
        dependent_field=dependent if isinstance(dependent, str) else "",
        trigger_field=trigger if isinstance(trigger, str) else "",
        condition=condition if isinstance(condition, str) else "",
        effect=effect if isinstance(effect, str) else "",
    )


def _adjacency(deps: Sequence[FieldDependency]) -> dict[str, set[str]]:
    """Build the directed adjacency map (``dependent_field -> {trigger_field}``).

    Self-loops are intentionally **not** filtered here so cycle detection can
    treat a self-loop as the trivial 1-node cycle if a caller reaches it that
    way; :func:`validate_dependencies` checks self-loops first regardless.
    """
    graph: dict[str, set[str]] = {}
    for dep in deps:
        graph.setdefault(dep.dependent_field, set()).add(dep.trigger_field)
    return graph


def _reaches(graph: Mapping[str, set[str]], start: str, target: str) -> bool:
    """Return ``True`` when ``target`` is reachable from ``start`` in ``graph``.

    Plain iterative DFS over the ``dependent -> trigger`` edges. Used to decide
    whether adding ``dependent -> trigger`` would close a cycle: it does iff
    ``trigger`` can already reach ``dependent``. Pure, terminates (visited set).
    """
    stack = [start]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return False


def _has_cycle(deps: Sequence[FieldDependency]) -> bool:
    """Return ``True`` when the dependency edges contain any directed cycle.

    Standard DFS three-colour cycle detection over ``dependent -> trigger``
    edges (a self-loop counts as a cycle). Pure, total.
    """
    graph = _adjacency(deps)
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {}

    # Iterative DFS to stay safe on deep graphs.
    for root in list(graph.keys()):
        if colour.get(root, WHITE) != WHITE:
            continue
        stack: list[tuple[str, bool]] = [(root, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                colour[node] = BLACK
                continue
            if colour.get(node, WHITE) == GREY:
                # Already on the current path — revisited via another branch.
                continue
            colour[node] = GREY
            stack.append((node, True))
            for nxt in graph.get(node, ()):
                state = colour.get(nxt, WHITE)
                if state == GREY:
                    return True  # back-edge → cycle
                if state == WHITE:
                    stack.append((nxt, False))
    return False


def validate_dependencies(
    dependencies: Sequence[Any] | None,
) -> DependencyResult:
    """Re-validate a submitted set of field dependencies server-side (pure).

    ``dependencies`` is the ``dependencies[]`` carried on the send (each item a
    :class:`FieldDependency`, a mapping, or an object exposing the same
    attributes). The set is accepted only when it is free of self-loops (R14.2)
    and acyclic (R14.4).

    Returns a :class:`DependencyResult`. ``ok`` is ``True`` only when **every**
    rule holds. On the first failure it returns ``ok=False`` with the humanized,
    leak-free loop message and the matching code (``dependency_self`` for a
    self-loop, ``dependency_cycle`` for a cycle).

    Pure function — no I/O, never raises.
    """
    deps = [_coerce(item) for item in (dependencies or ())]

    # R14.2 — reject any self-loop first (it is also the trivial 1-node cycle,
    # but a dedicated code/message is clearer for the sender).
    for dep in deps:
        if dep.dependent_field == dep.trigger_field:
            return DependencyResult(
                ok=False, code=CODE_DEPENDENCY_SELF, message=_LOOP_MESSAGE
            )

    # R14.4 — reject any cycle over the dependent -> trigger edges.
    if _has_cycle(deps):
        return DependencyResult(
            ok=False, code=CODE_DEPENDENCY_CYCLE, message=_LOOP_MESSAGE
        )

    return DependencyResult(ok=True)


def add_dependency(
    dependencies: Sequence[Any] | None,
    edge: Any,
) -> DependencyResult:
    """Add one dependency ``edge`` to an existing set, re-checking the rules.

    Mirror of the frontend ``addDependency(deps, edge)``: returns the new
    dependency list on success, or rejects the edge — without adding it — when
    it is a self-loop (R14.2, ``dependency_self``) or would close a cycle over
    the existing ``dependent -> trigger`` edges (R14.4, ``dependency_cycle``).

    The existing ``dependencies`` are assumed already-valid (acyclic); only the
    incremental effect of ``edge`` is checked, exactly like the client. A
    rejected edge is never included in the returned ``deps``.

    Pure function — no I/O, never raises.
    """
    existing = [_coerce(item) for item in (dependencies or ())]
    new_edge = _coerce(edge)

    # R14.2 — a self-loop is rejected and never stored.
    if new_edge.dependent_field == new_edge.trigger_field:
        return DependencyResult(
            ok=False, code=CODE_DEPENDENCY_SELF, message=_LOOP_MESSAGE
        )

    # R14.4 — adding dependent -> trigger closes a cycle iff trigger can already
    # reach dependent over the existing edges.
    graph = _adjacency(existing)
    if _reaches(graph, new_edge.trigger_field, new_edge.dependent_field):
        return DependencyResult(
            ok=False, code=CODE_DEPENDENCY_CYCLE, message=_LOOP_MESSAGE
        )

    return DependencyResult(ok=True, deps=tuple([*existing, new_edge]))
