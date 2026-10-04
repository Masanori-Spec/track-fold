# Independent exactness oracle

Run `python3 tests/oracle.py` from the project root. The harness uses only the
Python standard library and invokes `node scripts/solve.mjs` through JSON stdin
and stdout. It checks both a single-object request and array batches. A custom
adapter command can be supplied with `--solver 'node path/to/adapter.mjs'`.

## Independence and exhaustive coverage

The production algorithm enumerates feasible role subsets and uses an exact
partition dynamic program. The oracle does **neither**. It generates canonical
set partitions directly using restricted-growth enumeration. Each role joins
each existing block in turn, or starts the next new block. Every complete
unlabelled partition is generated exactly once. The harness verifies the Bell
counts for zero through seven roles: 1, 1, 2, 5, 15, 52, 203, 877, including
coverage, nonempty blocks, and uniqueness checks.

For each complete partition it independently checks:

1. Each must-share group has one assigned track. Overlapping groups thereby
   enforce transitivity without sharing the production grouping algorithm.
2. Each never-share pair has different assigned tracks, regardless of time.
3. Each track's complete appearance sequence, sorted by start, end, and ID,
   has no overlap. Intervals are positive and half-open, so an exit and entrance
   at the same second do not overlap.
4. Every consecutive appearance pair has enough gap for its directed override,
   or the default when no override exists. Consecutive appearances of the same
   role always require zero seconds. Self-overrides are invalid product input
   and are deliberately excluded from this valid-input corpus.

The lowest number of blocks among **all** feasible complete partitions is the
exact minimum. If none exists, the expected answer is infeasible. The oracle
does not inspect, import, call, or reuse production solver helpers or DP state.

## Why partial-track pruning would be unsound

Feasibility is not hereditary under removal of roles. For A at `[0,10)`, B at
`[20,30)`, C at `[50,60)`, default changeover zero, and A→C changeover 100, track
AC is infeasible while track ABC is feasible. B changes which transitions are
consecutive. The harness includes AC, ABC, forced AC without B, and forced AC
with B available. It never rejects a partial block on timing grounds. A
pairwise conflict-graph coloring oracle would be incorrect for this model.

## Test corpus

The default seed is `20261004`. The default run includes 27 handwritten cases,
360 generated base cases of one through seven roles, and nine metamorphic
transformations for each of 90 selected base cases (the added-never-share
transformation is skipped when there is only one role). Generation is fixed by
Python's seeded random generator, and failures print the seed, full input,
expected minimum, and actual result for reproduction.

The handwritten cases include:

- A at `[0,60)` and `[300,360)`, B at `[90,150)`, C at `[180,240)`, and D at
  `[120,210)`, default 20: B→C values 60, 30, and 31 yield minima 3, 2, and 3
- The intermediate-role counterexample above
- Touching endpoints, a one-second overlap, and nested intervals
- Same-role overlap, which is infeasible because a role cannot split tracks
- Same-role transitions, zero overrides, and directed asymmetry
- Transitive must-share groups, contradictions, and all-never-share groups
- Repeated role appearances, a return to a role, and Unicode labels/cues
- The 86400-second endpoint, seven simultaneous roles, and seven serial roles
- A target below the optimum, which must not limit exact optimization

Generated problems mix sparse, dense, and serial-looking timelines, multiple
appearances per role, directed overrides, forced grouping, separation, and
occasional same-role overlaps. The exhaustive claim applies to partitions of
each generated problem, not to every possible input in the product's domain.

Metamorphic cases verify the following relations, treating infeasibility as
infinite minimum:

- Input-order changes, bijective identifier renaming, time translation, exact
  integer time scaling, and target-only changes preserve the optimum
- Relaxing all applicable changeovers or removing sharing constraints cannot
  increase the optimum
- Tightening all applicable changeovers or adding a never-share pair cannot
  decrease the optimum

Each transformed case is itself exhaustively solved. No assertion is made that
removing a role must preserve feasibility; the counterexample forbids it.

## Witness and transition verification

Matching a minimum alone is insufficient. Every production answer must also:

- Report the exact status and minimum, with no incomplete result for this corpus
- Set `targetSufficient` from the exact optimum and target
- Assign every role exactly once across the reported number of nonempty tracks
- Assign every appearance exactly once and preserve its input fields and order
- Satisfy all sharing rules and complete-track chronological constraints
- Use unique track IDs T1 through Tn
- Return exactly one transition per consecutive appearance pair, including
  same-role pairs, with independently checked `fromId`, `toId`, `fromRole`,
  `toRole`, `exit`, `entrance`, `gap`, `required`, and `slack`
- Return no witness tracks for an infeasible result

Different valid optimal partitions are accepted. This avoids mistaking an
arbitrary tie-breaking difference for an optimization error.

The harness also tests its own certificate checker: a known valid witness must
pass, and 18 deliberately corrupted witnesses must fail. These mutations cover
every transition field, status, minimum, target flag, duplicate assignments,
missing appearances or transitions, cue preservation, booleans disguised as
numbers, and track IDs.

## Reproduction and limits

```sh
python3 tests/oracle.py
python3 tests/oracle.py --self-test
python3 tests/oracle.py --seed 42 --generated 1000 --metamorphic 250
```

`--self-test` checks the oracle, fixture expectations, and metamorphic relations
without running production code; it is not a production solver pass. The
default integration run exhaustively tests only up to seven roles. The product
supports larger inputs, which require separate boundary, performance, and UI
tests. This harness does not cover validation of malformed inputs, interruption
behavior, browser rendering, persistence, or resource bounds at 16 roles.
