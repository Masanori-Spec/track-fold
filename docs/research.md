# Problem, comparison and limits

Reviewed 2026-10-04. This is evidence of an existing workflow problem and nearby
products, not customer validation or an exhaustive market/patent search.

## Primary problem evidence

A community-theatre producer asks how to determine role doubling and costume
changes; a production participant identifies costume-change coordination as the
hardest part. The discussion dates to 2013–2014 and is anecdotal, not current
market-size data. [MTI discussion](https://www.mtishows.com/help/shows/shrek-the-musical/shrek-the-musical-casting)

BackstageOS describes costume plots and tracking change location, time, garments
and assistance. That explains why the handoff needs chronological timing evidence,
and why this app cannot infer practical feasibility from a number alone.
[BackstageOS guide](https://backstageos.com/resources/guides/how-to-track-costumes-and-quick-changes/)

## Closest reviewed alternatives

- [Game Bob Cast Doubling and Scene Coverage Planner](https://www.gamebob.dev/en/utilities/categories/performing-arts/cast-doubling-scene-coverage-planner/):
  users provide actor-to-role assignments, scene calls and transition windows; the
  tool flags overlaps and short windows and explicitly disclaims optimization.
  TrackFold's bounded distinction is generating minimum anonymous role groupings
  rather than requiring repeated manual assignment-and-check cycles
- [Playerpart](https://playerpart.com/): already allocates anonymous reading parts,
  seeks balanced line counts and minimizes self-dialogue conflicts. TrackFold's
  hard onstage intervals and directed changeover requirements serve a different
  performance-planning model. Do not claim anonymous assignment as an invention

All source text is paraphrased; no scripts, site artwork, code, photos, or customer
information were copied. The sample roles and timings were authored for this tool.

## Evaluation fixture and proof

A appears [0,60) and [300,360), B [90,150), C [180,240), D [120,210).
Default changeover is 20 seconds, with B→C=60 seconds. B/C's available gap is 30;
D overlaps both B and C. Therefore B, C and D must be on three distinct tracks.
The assignment {A,B}, {C}, {D} attains three.

Change only B→C to 30. {A,B,C}, {D} attains two; its gaps are 30, 30 and 60.
D's overlap with B/C proves one impossible. At B→C=31 the minimum is three again.

This proof is specific to the fixture. In general an intermediate role can rescue
a pair by changing the consecutive transitions. For example, A [0,10), B [20,30),
C [50,60), default 0 and A→C=100: AC is infeasible but ABC is feasible. This is why
the product evaluates full sequences instead of treating all changeovers as edges.

## What remains unknown

No producer has trialled this tool. Willingness to enter accurate timings, use
anonymous tracks, review generated candidates or pay for this workflow is unknown.
Larger shows exceed the supported bound. Useful next validation would be a
consented trial with a production's anonymized timings and comparison against its
existing manual plan; no outreach or data collection has been performed.
