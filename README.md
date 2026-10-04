# TrackFold

**Minimum anonymous theatre role tracks, with every changeover visible.**

TrackFold takes fictional roles, entrance/exit intervals and explicit changeover
requirements, then finds a minimum-track assignment within a bounded model. It
exports the candidate and the chronological handoffs needed for a production-team
review. It does not select real performers.

The application is a single local HTML file with English/Japanese UI, editable
rows, JSON recipe import, keyboard controls, a cancellable Web Worker and a
portable handoff ZIP. No runtime dependency, account, network request, tracking,
local-storage draft or third-party font is needed.

## Try the example

Open `dist/index.html` in a current browser, or run:

```sh
npm run build
npm run serve
# http://127.0.0.1:4173/
```

1. Find the minimum for the loaded 60-second B→C example: **3 tracks**, exceeding
   the target of 2.
2. Load the 30-second variation and search: **2 tracks**. Equality is accepted.
3. Change B→C to 31 seconds: the minimum returns to **3**.
4. Review the handoffs, then download the ZIP. Opening the generated
   `run-sheet.html` needs no application or internet connection.

These are original synthetic inputs, not a licensed script or a real production.

## Why this exists

The documented problem is repeated manual experimentation with which roles can
double and whether the ensuing costume-change windows work. The nearest reviewed
checker asks users to supply actor assignments. TrackFold instead generates a
minimum anonymous grouping and exports its complete transition witness.

[Game Bob's planner](https://www.gamebob.dev/en/utilities/categories/performing-arts/cast-doubling-scene-coverage-planner/)
checks supplied assignments and explicitly says it does not optimize a production.
[Playerpart](https://playerpart.com/) already allocates anonymous Shakespeare
reading parts and balances line counts; it minimizes rather than forbids reading
self-dialogue conflicts. That is a different objective from hard onstage-presence
and entered changeover constraints. Anonymous allocation itself is not new.

See [research and scope](docs/research.md). Demand, willingness to adopt and
commercial value beyond the documented problem remain unvalidated. This is a
portfolio prototype, not a claim of a new optimization technique or a production
management suite.

## Supported model

- 1–16 roles; 1–128 appearance intervals; every role must appear
- Unique ASCII IDs (letters, digits, `_`, `-`, at most 32 characters); role names
  up to 80 and cue notes up to 500 UTF-16 code units, including well-formed Unicode
- Nonnegative integer elapsed seconds from 0 to 86,400; entrance strictly before
  exit; half-open `[entrance, exit)` intervals may touch but cannot overlap
- One fixed anonymous track per role throughout the performance
- A visible, user-entered default changeover and optional directed overrides
- Same-role consecutive appearances always require zero changeover seconds;
  self-overrides are rejected rather than silently ignored
- Changeovers apply **only between consecutive appearances on the full track**
- Must-share groups merge transitively; never-share pairs apply anywhere in a
  track; conflicting rules produce “no feasible assignment under these inputs”
- A requested maximum of 1–16 tracks, compared against the exact minimum

The solver minimizes only track count. It does not minimize walking, costume
complexity, total slack, workload imbalance or artistic disruption. Ties are
resolved deterministically using sorted role IDs and subset masks. Rename IDs and
a different equally optimal candidate may be selected.

A mathematical result does not establish physical quick-change feasibility or
safety. Do not infer that a production cannot be performed from an infeasible
input model. Adjustments to costumes, blocking, assistance or timing are outside
this model and must be reviewed by the production team.

No real-person casting, demographic/acting assessment, script/PDF parsing,
contracts, invitations, communication, real-time cueing or safety certification is
provided. Same-role costume changes are a deliberate v1 omission.

## Algorithm and completion status

1. Enumerate every nonempty role subset, subject to the group rules.
2. Sort its entire chronological appearance sequence and check overlap plus each
   consecutive directed changeover.
3. Solve an exact set partition using bitmask dynamic programming. The next subset
   must contain the lowest remaining role bit, eliminating partition permutations.
4. Reconstruct a deterministic assignment and every transition certificate.

**Do not replace step 2 with a pairwise changeover graph.** An infeasible A/C subset
can become feasible when B is inserted between A and C. The implementation never
uses an infeasible subset to prune its supersets.

Bounds: at most 65,535 candidate subsets; worst-case partition enumeration is
O(3^n), with memoization and exact one-track shortcuts. A search stops at an
8-second worker budget or 30,000,000 operation checks. Checks occur at most 4,096
operations apart. The UI also terminates an unresponsive worker after 12 seconds.
Cancel terminates the worker immediately. A budget-limited/cancelled search reports
**incomplete**, with no minimum, witness or export. “Infeasible” is emitted only
when the exact partition search finishes with no assignment.

## Handoff ZIP

- `role-tracks.csv`: anonymous track, role ID/name, appearance count
- `track-appearances.csv`: every appearance once, elapsed times and cue
- `track-transitions.csv`: every consecutive pair, including same-role pairs;
  available gap, entered requirement and slack in integer seconds
- `run-sheet.html`: script-free, printable, standalone review sheet with one track
  per section, appearance order, transitions and assumptions
- `recipe.json`: canonical normalized model, sufficient to reproduce the result
- `assumptions.txt`: scope, objective, target and review caveats

CSVs use UTF-8 BOM, quoted fields and CRLF. Formula-like cells are prefixed with an
apostrophe; `recipe.json` retains normalized text without the CSV apostrophe transform. This is a deliberate import
hardening transform, not a byte-for-byte CSV text round-trip. The output is review
paperwork, not a validated file for every production-management tool.

## Validation

Requires Node 22+ and Python 3.12+ for test tooling. The browser app itself has no
Node/Python requirement. Install the lockfile-pinned browser test dependency only
when needed:

```sh
npm ci --ignore-scripts
npm run check
python3 tests/oracle.py
python3 tests/oracle.py --seed 42 --generated 1000 --metamorphic 250
node scripts/export-example.mjs
python3 tests/consume.py --bundle test-results/local/handoff.zip --out test-results/consumer --skip-libreoffice
```

- 104 Node tests cover validation boundaries, exact examples, cancellation budgets,
  non-hereditary subsets, formula/HTML escaping, ZIP CRC and a split-UTF8 CLI case
- Independent Python oracle directly enumerates canonical set partitions and
  validates complete witnesses/transition fields. Default: 1,183 cases; alternate
  seed: 3,244. It does not call the product subset DP
- CSV consumer independently checks the actual ZIP with Python's `csv` module and,
  where available, LibreOffice CSV→XLSX plus XML cell verification
- Hosted CI uses Ubuntu 22.04, Node 22/24 and **sandbox-enabled Chromium**, including
  the real browser download, fresh-context standalone HTML, keyboard/mobile flows,
  cancellation, long Unicode text and A4 print evidence

See [oracle method](docs/oracle-method.md), [consumer method](docs/consumer-method.md),
[verification status](docs/verification.md) and [security scope](SECURITY.md).
The [initial hosted run](https://github.com/Masanori-Spec/track-fold/actions/runs/37203726116)
passed both Node/oracle jobs, 19 of 20 browser scenarios, actual-download
LibreOffice CSV imports and A4 rendering. All ten rendered A4 pages were inspected.
The remaining scenario exposed document overflow at a 390px Japanese layout. A
responsive containment fix and offscreen-column access checks are now applied; the
exact updated source still needs its hosted rerun and mobile screenshot inspection.
No browser sandbox bypass is used. These checks do not validate a real production.

## Repository status

No project license has been selected. No third-party runtime code, external
artwork, real script data or generated credentials are included. Development
component notices are in `THIRD_PARTY_NOTICES.md`. Publishing, deployment and an
open-source license decision are separate actions.

Text line endings are canonicalized at the input boundary: CRLF and lone CR become LF in names and cues. The recipe, CSVs and HTML all represent this normalized model. Other well-formed Unicode is preserved.
