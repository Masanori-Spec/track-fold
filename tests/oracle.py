#!/usr/bin/env python3
"""Independent exhaustive oracle for TrackFold; Python standard library only.

Run from any directory: python3 tests/oracle.py
The production solver is a separate JSON-in / JSON-out subprocess. This file
deliberately does not import its code, reproduce its subset DP, or prune a
partially assembled track for infeasibility: feasibility is not hereditary.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import random
import shlex
import subprocess
import sys
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
SEED = 20261004
BELLS = (1, 1, 2, 5, 15, 52, 203, 877)
TRANSITION_FIELDS = (
    "fromId", "toId", "fromRole", "toRole", "exit", "entrance",
    "gap", "required", "slack",
)


@lru_cache(maxsize=8)
def canonical_partitions(n: int) -> tuple[tuple[tuple[int, ...], ...], ...]:
    """Restricted-growth enumeration: each unlabelled partition appears once."""
    if not 0 <= n <= 7:
        raise ValueError("the exhaustive oracle supports zero through seven roles")

    def visit(i: int, blocks: list[list[int]]) -> Iterator[tuple[tuple[int, ...], ...]]:
        if i == n:
            yield tuple(tuple(block) for block in blocks)
            return
        for block in blocks:
            block.append(i)
            yield from visit(i + 1, blocks)
            block.pop()
        blocks.append([i])
        yield from visit(i + 1, blocks)
        blocks.pop()

    return tuple(visit(0, []))


def chronological_track(problem: dict[str, Any], role_ids: list[str]) -> tuple[list, list] | None:
    """Check the complete track timeline directly, then calculate its certificate."""
    members = set(role_ids)
    appearances = sorted(
        (a for a in problem["appearances"] if a["roleId"] in members),
        key=lambda a: (a["start"], a["end"], a["id"]),
    )
    overrides = {(o["from"], o["to"]): o["seconds"] for o in problem.get("overrides", [])}
    transitions = []
    for left, right in zip(appearances, appearances[1:]):
        gap = right["start"] - left["end"]
        required = (
            0 if left["roleId"] == right["roleId"]
            else overrides.get((left["roleId"], right["roleId"]), problem["defaultChangeover"])
        )
        if gap < required:
            return None
        transitions.append({
            "fromId": left["id"], "toId": right["id"],
            "fromRole": left["roleId"], "toRole": right["roleId"],
            "exit": left["end"], "entrance": right["start"],
            "gap": gap, "required": required, "slack": gap - required,
        })
    return appearances, transitions


def partition_feasible(problem: dict[str, Any], groups: list[list[str]]) -> bool:
    assigned = {role: index for index, group in enumerate(groups) for role in group}
    for together in problem.get("mustShare", []):
        if len({assigned[role] for role in together}) > 1:
            return False
    for left, right in problem.get("neverShare", []):
        if assigned[left] == assigned[right]:
            return False
    return all(chronological_track(problem, group) is not None for group in groups)


def oracle(problem: dict[str, Any]) -> int | None:
    """Enumerate *all complete* partitions; return the true minimum or None."""
    ids = [role["id"] for role in problem["roles"]]
    if not ids or len(ids) > 7:
        raise ValueError("test problems must have one through seven roles")
    optimum = None
    # No partial-block feasibility pruning, subset memoization, or partition DP.
    for partition in canonical_partitions(len(ids)):
        groups = [[ids[i] for i in block] for block in partition]
        if partition_feasible(problem, groups):
            optimum = len(groups) if optimum is None else min(optimum, len(groups))
    return optimum


@dataclass
class Case:
    name: str
    problem: dict[str, Any]
    expected: int | None
    kind: str = "fixture"


def problem_for(events: list[tuple[str, int, int]], default: int = 0, **updates: Any) -> dict:
    ids = list(dict.fromkeys(event[0] for event in events))
    problem = {
        "roles": [{"id": role, "name": f"役 {role} 🎭"} for role in ids],
        "appearances": [
            {"id": f"a{i}", "roleId": role, "start": start, "end": end, "cue": f"出番 {i} / café"}
            for i, (role, start, end) in enumerate(events)
        ],
        "defaultChangeover": default,
        "overrides": [], "mustShare": [], "neverShare": [], "targetTracks": 2,
    }
    problem.update(updates)
    return problem


def fixtures() -> list[Case]:
    cases = []

    def add(name: str, expected: int | None, problem: dict) -> None:
        cases.append(Case(name, problem, expected))

    production = [("A", 0, 60), ("A", 300, 360), ("B", 90, 150), ("C", 180, 240), ("D", 120, 210)]
    for seconds, minimum in ((60, 3), (30, 2), (31, 3)):
        add(f"four-role-directed-boundary-{seconds}", minimum, problem_for(
            production, 20, overrides=[{"from": "B", "to": "C", "seconds": seconds}],
        ))
    intermediate = [("A", 0, 10), ("C", 50, 60), ("B", 20, 30)]
    long_ac = [{"from": "A", "to": "C", "seconds": 100}]
    add("nonhereditary-AC-alone", 2, problem_for(intermediate[:2], overrides=long_ac))
    add("nonhereditary-ABC-whole-track", 1, problem_for(intermediate, overrides=long_ac))
    add("nonhereditary-forced-AC-can-include-B", 1, problem_for(
        intermediate, overrides=long_ac, mustShare=[["A", "C"]],
    ))
    add("nonhereditary-forced-AC-without-B", None, problem_for(
        intermediate[:2], overrides=long_ac, mustShare=[["A", "C"]],
    ))
    add("half-open-touching-zero", 1, problem_for([("A", 0, 10), ("B", 10, 20)]))
    add("half-open-touching-needs-one", 2, problem_for([("A", 0, 10), ("B", 10, 20)], 1))
    add("same-role-touching-ignores-default", 1, problem_for([("A", 0, 10), ("A", 10, 20)], 800))
    add("same-role-overlap-is-infeasible", None, problem_for([("A", 0, 20), ("A", 10, 30)]))
    add("one-second-overlap", 2, problem_for([("A", 0, 10), ("B", 9, 20)]))
    add("nested-overlap", 3, problem_for([("A", 0, 100), ("B", 10, 80), ("C", 20, 30)]))
    add("directed-forward-override", 2, problem_for(
        [("A", 0, 10), ("B", 30, 40)],
        overrides=[{"from": "A", "to": "B", "seconds": 21}],
    ))
    add("directed-reverse-not-applied", 1, problem_for(
        [("B", 0, 10), ("A", 30, 40)],
        overrides=[{"from": "A", "to": "B", "seconds": 21}],
    ))
    add("zero-override-replaces-default", 1, problem_for(
        [("A", 0, 10), ("B", 10, 20)], 30,
        overrides=[{"from": "A", "to": "B", "seconds": 0}],
    ))
    sequential = [("A", 0, 10), ("B", 20, 30), ("C", 40, 50)]
    add("transitive-must-share", 1, problem_for(sequential, mustShare=[["A", "B"], ["B", "C"]]))
    add("transitive-must-share-conflict", None, problem_for(
        sequential, mustShare=[["A", "B"], ["B", "C"]], neverShare=[["A", "C"]],
    ))
    add("all-never-share", 3, problem_for(
        sequential, neverShare=[["A", "B"], ["A", "C"], ["B", "C"]],
    ))
    add("must-share-transition-shortfall", None, problem_for(
        sequential[:2], 11, mustShare=[["A", "B"]],
    ))
    add("must-share-overlap", None, problem_for(
        [("A", 0, 10), ("B", 0, 10)], mustShare=[["A", "B"]],
    ))
    add("elapsed-time-upper-bound", 1, problem_for([("A", 86370, 86380), ("B", 86390, 86400)], 10))
    add("return-to-role-two-directed-edges", 1, problem_for(
        [("A", 0, 10), ("B", 20, 30), ("A", 50, 60)], 40,
        overrides=[{"from": "A", "to": "B", "seconds": 10}, {"from": "B", "to": "A", "seconds": 20}],
    ))
    add("repeated-role-same-then-different", 1, problem_for([("A", 0, 10), ("A", 15, 20), ("B", 30, 40)], 10))
    add("target-does-not-limit-optimum", 3, problem_for(
        [("A", 0, 10), ("B", 0, 10), ("C", 0, 10)], targetTracks=1,
    ))
    add("seven-sequential", 1, problem_for([(f"R{i}", i * 30, i * 30 + 10) for i in range(7)], 20))
    add("seven-simultaneous", 7, problem_for([(f"R{i}", 0, 10) for i in range(7)]))
    return cases


def random_problem(rng: random.Random, index: int) -> dict:
    n = 1 + index % 7
    ids = [f"r{i}" for i in range(n)]
    events = []
    # Mix sparse, dense, and serial-looking timelines. Within one role, normally
    # generate nonoverlapping appearances, with occasional deliberate overlap.
    for i, role in enumerate(ids):
        start = rng.randrange(0, 100) if index % 3 else i * 45
        for _ in range(rng.randint(1, 3)):
            end = start + rng.randint(1, 35)
            events.append((role, start, end))
            start = end + rng.randint(0, 100)
    if index % 29 == 0:
        role, start, end = events[0]
        events.append((role, start, end))
    pairs = [(left, right) for left in ids for right in ids if left != right]
    rng.shuffle(pairs)
    overrides = [
        {"from": a, "to": b, "seconds": rng.choice([0, 1, 5, 10, 20, 40, 90])}
        for a, b in pairs[:rng.randrange(len(pairs) + 1)]
    ]
    must_share = []
    if n >= 2 and rng.random() < 0.38:
        must_share.append(rng.sample(ids, rng.randint(2, min(n, 4))))
    if n >= 3 and rng.random() < 0.22:
        must_share.append(rng.sample(ids, 2))
    never_share = []
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < 0.12:
                never_share.append([ids[i], ids[j]])
    problem = problem_for(
        events, rng.choice([0, 0, 1, 5, 10, 20, 40]), overrides=overrides,
        mustShare=must_share, neverShare=never_share, targetTracks=rng.randint(1, n),
    )
    rng.shuffle(problem["roles"])
    rng.shuffle(problem["appearances"])
    return problem


def transformed_problems(base: dict, rng: random.Random) -> Iterator[tuple[str, dict, str]]:
    p = copy.deepcopy(base)
    for field in ("roles", "appearances", "overrides", "mustShare", "neverShare"):
        rng.shuffle(p[field])
    for group in p["mustShare"] + p["neverShare"]:
        rng.shuffle(group)
    yield "input-order", p, "equal"

    p = copy.deepcopy(base)
    renames = {r["id"]: f"renamed_{len(base['roles']) - i}" for i, r in enumerate(base["roles"])}
    for role in p["roles"]:
        role["id"], role["name"] = renames[role["id"]], "別名 / rôle 🪄"
    for i, appearance in enumerate(p["appearances"]):
        appearance.update(id=f"event_{i}", roleId=renames[appearance["roleId"]], cue="場面変換")
    for override in p["overrides"]:
        override.update({"from": renames[override["from"]], "to": renames[override["to"]]})
    for field in ("mustShare", "neverShare"):
        p[field] = [[renames[role] for role in group] for group in p[field]]
    yield "bijective-rename", p, "equal"

    p = copy.deepcopy(base)
    for appearance in p["appearances"]:
        appearance["start"] += 1000
        appearance["end"] += 1000
    yield "time-translation", p, "equal"

    p = copy.deepcopy(base)
    p["defaultChangeover"] *= 3
    for appearance in p["appearances"]:
        appearance["start"] *= 3
        appearance["end"] *= 3
    for override in p["overrides"]:
        override["seconds"] *= 3
    yield "integer-time-scaling", p, "equal"

    p = copy.deepcopy(base)
    p["defaultChangeover"] //= 2
    for override in p["overrides"]:
        override["seconds"] //= 2
    yield "relaxed-changeovers", p, "not-more"

    p = copy.deepcopy(base)
    p["defaultChangeover"] += 11
    for override in p["overrides"]:
        override["seconds"] += 11
    yield "tightened-changeovers", p, "not-less"

    p = copy.deepcopy(base)
    p["mustShare"], p["neverShare"] = [], []
    yield "removed-sharing-constraints", p, "not-more"

    if len(base["roles"]) >= 2:
        p = copy.deepcopy(base)
        pair = [r["id"] for r in rng.sample(p["roles"], 2)]
        if not any(set(old) == set(pair) for old in p["neverShare"]):
            p["neverShare"].append(pair)
        yield "added-never-share", p, "not-less"

    p = copy.deepcopy(base)
    p["targetTracks"] = 1 if base["targetTracks"] != 1 else 7
    yield "target-only", p, "equal"


def check_relation(base: int | None, changed: int | None, relation: str, name: str) -> None:
    a, b = (math.inf if x is None else x for x in (base, changed))
    valid = {"equal": b == a, "not-more": b <= a, "not-less": b >= a}[relation]
    if not valid:
        raise AssertionError(f"oracle metamorphic property failed: {name}: {base} -> {changed}, {relation}")


def build_cases(generated: int, metamorphic: int, seed: int) -> list[Case]:
    cases = fixtures()
    for case in cases:
        actual = oracle(case.problem)
        if actual != case.expected:
            raise AssertionError(f"handwritten fixture {case.name}: expected {case.expected}, oracle gave {actual}")
    rng = random.Random(seed)
    bases = []
    for i in range(generated):
        problem = random_problem(rng, i)
        case = Case(f"generated-{i:04d}", problem, oracle(problem), "generated")
        bases.append(case)
        cases.append(case)
    # Spread metamorphic testing over the corpus instead of selecting only its
    # first few role counts. Every transformed input is solved independently.
    selected = rng.sample(bases, min(metamorphic, len(bases)))
    for base in selected:
        for label, problem, relation in transformed_problems(base.problem, rng):
            name = f"{base.name}/{label}"
            expected = oracle(problem)
            check_relation(base.expected, expected, relation, name)
            cases.append(Case(name, problem, expected, "metamorphic"))
    return cases


def require(condition: bool, description: str) -> None:
    if not condition:
        raise AssertionError(description)


def validate_result(case: Case, actual: Any) -> None:
    problem, expected = case.problem, case.expected
    require(isinstance(actual, dict), "result must be a JSON object")
    expected_status = "infeasible" if expected is None else "optimal"
    require(actual.get("status") == expected_status, f"status should be {expected_status}, got {actual.get('status')!r}")
    require("minimumTracks" in actual and actual["minimumTracks"] == expected,
            f"minimumTracks should be {expected!r}, got {actual.get('minimumTracks')!r}")
    require(actual.get("targetSufficient") is (expected is not None and expected <= problem["targetTracks"]),
            "targetSufficient does not match the exact minimum and requested target")
    tracks = actual.get("tracks")
    require(isinstance(tracks, list), "tracks must be an array")
    if expected is None:
        require(tracks == [], "an infeasible result must not present a track witness")
        return
    require(type(actual["minimumTracks"]) is int, "minimumTracks must be an integer, not a boolean")
    require(len(tracks) == expected, "witness track count differs from optimum")
    all_roles, track_ids, groups, seen_appearances = [], [], [], []
    for track in tracks:
        require(isinstance(track, dict), "each track must be an object")
        role_ids = track.get("roleIds")
        require(isinstance(role_ids, list) and len(role_ids) > 0, "each track must have nonempty roleIds")
        require(all(isinstance(role, str) for role in role_ids), "roleIds must contain strings")
        all_roles.extend(role_ids)
        groups.append(role_ids)
        track_ids.append(track.get("id"))
        timeline = chronological_track(problem, role_ids)
        require(timeline is not None, "returned track violates chronological overlap/changeover constraints")
        appearances, transitions = timeline
        returned_appearances = track.get("appearances")
        require(isinstance(returned_appearances, list), "track appearances must be an array")
        require(len(returned_appearances) == len(appearances), "track appearance count is wrong")
        for actual_appearance, expected_appearance in zip(returned_appearances, appearances):
            require(isinstance(actual_appearance, dict), "track appearances must contain full appearance objects")
            for key, value in expected_appearance.items():
                require(actual_appearance.get(key) == value, f"appearance {expected_appearance['id']} has wrong {key}")
            seen_appearances.append(actual_appearance.get("id"))
        returned_transitions = track.get("transitions")
        require(isinstance(returned_transitions, list), "transitions must be an array")
        require(len(returned_transitions) == len(transitions), "one transition is required for every consecutive appearance pair")
        for returned, transition in zip(returned_transitions, transitions):
            require(isinstance(returned, dict), "each transition must be an object")
            for key in TRANSITION_FIELDS:
                require(key in returned and returned[key] == transition[key],
                        f"transition {transition['fromId']}->{transition['toId']} {key}: expected {transition[key]!r}, got {returned.get(key)!r}")
            for key in ("exit", "entrance", "gap", "required", "slack"):
                require(type(returned[key]) is int, f"transition {key} must be an integer, not a boolean")
    require(sorted(all_roles) == sorted(r["id"] for r in problem["roles"]), "roles must occur exactly once across tracks")
    require(sorted(seen_appearances) == sorted(a["id"] for a in problem["appearances"]), "appearances must occur exactly once across tracks")
    require(set(track_ids) == {f"T{i + 1}" for i in range(expected)}, "track IDs must be unique T1 through Tn")
    require(partition_feasible(problem, groups), "returned partition violates a must-share or never-share constraint")


def run_solver(command: list[str], payload: Any, timeout: int) -> Any:
    completed = subprocess.run(
        command, input=json.dumps(payload, ensure_ascii=False), text=True,
        capture_output=True, cwd=ROOT, timeout=timeout, check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"solver exited {completed.returncode}: {completed.stderr[-8000:]}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"solver stdout is not one JSON value: {completed.stdout[:2000]!r}") from error


def validate_oracle() -> None:
    for n, expected in enumerate(BELLS):
        partitions = canonical_partitions(n)
        require(len(partitions) == expected, f"Bell number mismatch for n={n}")
        require(len(set(partitions)) == expected, f"duplicate canonical partition for n={n}")
        for partition in partitions:
            require(sorted(i for block in partition for i in block) == list(range(n)), "partition does not cover its input")
            require(all(block for block in partition), "partition has an empty block")
    # Explicitly test the counterexample that makes pair-conflict pruning wrong.
    p = problem_for([("A", 0, 10), ("C", 50, 60), ("B", 20, 30)],
                    overrides=[{"from": "A", "to": "C", "seconds": 100}])
    require(chronological_track(p, ["A", "C"]) is None, "AC must be infeasible")
    require(chronological_track(p, ["A", "B", "C"]) is not None, "ABC must be feasible")
    validate_certificate_checker()


def validate_certificate_checker() -> None:
    """Sanity-check the harness itself by corrupting a known valid certificate."""
    problem = problem_for([("A", 0, 10), ("B", 20, 30), ("A", 40, 50)], 10)
    appearances, transitions = chronological_track(problem, ["A", "B"])
    case = Case("certificate-self-check", problem, 1)
    good = {
        "status": "optimal", "minimumTracks": 1, "targetSufficient": True,
        "tracks": [{"id": "T1", "roleIds": ["A", "B"], "appearances": appearances, "transitions": transitions}],
    }
    validate_result(case, good)
    corruptions = []
    for field in TRANSITION_FIELDS:
        bad = copy.deepcopy(good)
        current = bad["tracks"][0]["transitions"][0][field]
        bad["tracks"][0]["transitions"][0][field] = current + 1 if type(current) is int else "wrong"
        corruptions.append((f"wrong transition {field}", bad))
    mutations = {
        "wrong status": lambda r: r.update(status="incomplete"),
        "wrong minimum": lambda r: r.update(minimumTracks=2),
        "wrong target": lambda r: r.update(targetSufficient=False),
        "duplicate role": lambda r: r["tracks"][0]["roleIds"].append("A"),
        "missing appearance": lambda r: r["tracks"][0]["appearances"].pop(),
        "wrong cue": lambda r: r["tracks"][0]["appearances"][0].update(cue="wrong"),
        "missing transition": lambda r: r["tracks"][0]["transitions"].pop(),
        "boolean numeric": lambda r: r["tracks"][0]["transitions"][0].update(slack=False),
        "wrong track ID": lambda r: r["tracks"][0].update(id="T2"),
    }
    for label, mutate in mutations.items():
        bad = copy.deepcopy(good)
        mutate(bad)
        corruptions.append((label, bad))
    for label, bad in corruptions:
        try:
            validate_result(case, bad)
        except AssertionError:
            continue
        raise AssertionError(f"certificate checker failed to reject {label}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", default="node scripts/solve.mjs", help="JSON stdin/stdout solver command")
    parser.add_argument("--generated", type=int, default=360, help="seeded generated base cases (default: 360)")
    parser.add_argument("--metamorphic", type=int, default=90, help="base cases to transform nine ways (default: 90)")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=60, help="seconds per solver subprocess")
    parser.add_argument("--self-test", action="store_true", help="check the Python oracle/corpus without invoking Node")
    args = parser.parse_args()
    if min(args.generated, args.metamorphic) < 0 or args.batch_size < 1 or args.timeout < 1:
        parser.error("case counts must be nonnegative; batch size and timeout must be positive")
    try:
        validate_oracle()
        cases = build_cases(args.generated, args.metamorphic, args.seed)
        if not args.self_test:
            command = shlex.split(args.solver)
            require(bool(command), "solver command cannot be empty")
            # Independently exercise both supported adapter input forms.
            validate_result(cases[0], run_solver(command, cases[0].problem, args.timeout))
            for offset in range(0, len(cases), args.batch_size):
                batch = cases[offset:offset + args.batch_size]
                results = run_solver(command, [case.problem for case in batch], args.timeout)
                require(isinstance(results, list) and len(results) == len(batch), "batch result must preserve input length")
                for case, actual in zip(batch, results):
                    try:
                        validate_result(case, actual)
                    except (AssertionError, KeyError, TypeError, ValueError) as error:
                        print(json.dumps({
                            "case": case.name, "seed": args.seed, "error": str(error),
                            "input": case.problem, "expectedMinimum": case.expected, "actual": actual,
                        }, ensure_ascii=False, indent=2), file=sys.stderr)
                        return 1
        counts = {kind: sum(c.kind == kind for c in cases) for kind in ("fixture", "generated", "metamorphic")}
        counts.update({"total": len(cases), "infeasible": sum(c.expected is None for c in cases), "seed": args.seed})
        label = "Oracle self-check passed" if args.self_test else "Independent oracle passed"
        print(f"{label}: {json.dumps(counts, sort_keys=True)}")
        if not args.self_test:
            print("Verified exact minima, feasibility, target flags, complete assignments, and every transition field; object and array adapters passed.")
        return 0
    except (AssertionError, ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Oracle harness failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
