# Independent handoff consumer

`tests/consume.py` reads the actual six-file TrackFold ZIP with Python's standard library. It does not import the JavaScript solver, exporter, or their result objects. It checks the exported witness against the embedded recipe; it does not independently prove minimum track count. `tests/oracle.py` is the separate optimality check.

## Run

```sh
python3 tests/consume.py --bundle test-results/browser/handoff.zip --out test-results/consumer --require-libreoffice
```

`--bundle` is required. `--out` defaults to `artifacts/consumer`. The directory receives `consumer-report.json` and, after successful native conversion, three `native/*.xlsx` files. The report includes source ZIP/member SHA-256 hashes, per-stage results, record counts, coverage counts, LibreOffice version, exact import options, and converted workbook hashes. CI should pass the ZIP downloaded through the real browser export action, rather than substitute a newly generated fixture.

Without `--require-libreoffice`, a missing executable is reported as `available: false, status: skipped`. With it, missing LibreOffice fails. An installed executable that cannot convert a CSV always fails; it is never counted as a successful or skipped native check. Earlier semantic results remain in the JSON report. `not_run` means an earlier verification stage failed before native probing. The script never installs software or launches a browser.

For a restricted local environment, use `--skip-libreoffice` to run semantic/HTML checks without launching office software. The report explicitly records the skip even if an executable exists. It cannot be combined with `--require-libreoffice`; CI must use the required-native flag for native evidence.

## What is verified

1. **Safe archive intake.** Require exactly the documented six root-level files. Reject duplicate names, symlinks, encrypted entries, unsupported compression, excessive sizes/expansion, and unexpected members. Read bounded members in memory with ZIP CRC verification; never call `extractall`.
2. **Recipe validity.** Independently validate model version, bounded role/appearance counts, unique IDs, elapsed integer seconds, text, directed overrides, and grouping references. Reject duplicate JSON keys, non-finite JSON numbers, and unpaired Unicode surrogates. Exported role names and cues must use canonical LF line endings: the product normalizes CRLF and lone CR to LF before export, and the consumer rejects any remaining carriage return in recipe text. Valid astral Unicode and LF line breaks remain intact.
3. **CSV bytes and shape.** Decode UTF-8 with a mandatory BOM, use Python's strict CSV parser, and compare exact headers/column counts. Quoted commas, quote characters, and multiline fields remain fields, not new records.
4. **Witness completeness.** Every recipe role occurs once, with its correct name and appearance count. Anonymous IDs are contiguous `T1` through `Tn`. Every appearance occurs exactly once, on its role's single assigned track, with exact recipe times and cue text. Per-track order is recomputed from entrance, exit, and ID.
5. **Feasibility and handoffs.** Check every must-share group and never-share pair. Independently recompute each consecutive appearance pair. Gap is next entrance minus previous exit. Same-role reappearances require zero; otherwise use the matching directed override or the explicit default. Reject overlap, insufficient gap, missing/extra transitions, or wrong gap/requirement/slack. Equality is valid. Nonconsecutive pairs are not treated as direct handoffs.
6. **Text fidelity and formula escaping.** Compare every role name and cue against the recipe, including Unicode, quotes and line breaks. Expected CSV cells receive one protective apostrophe when they begin with tab/CR/LF or whitespace followed by `=`, `+`, `-`, or `@`. Ordinary leading apostrophes are not stripped. Report the number of formula-prefixed and non-ASCII source text fields; zero means that case was not exercised by this bundle.
7. **HTML and assumptions.** Parse the static HTML without executing it. Match each track section, role name, appearance/time/cue row, and transition row to independently checked data. Match default/override/grouping inputs and text-file summary. Require UTF-8 and the restrictive CSP; reject active or external elements, event attributes, resource URLs, and CSS imports. This is content validation, not a browser layout or print-render test.

Coverage counters identify same-role zero, directed override, default requirement, and equality-boundary transitions actually encountered. A pass with a zero counter does not establish coverage of that branch. Use a browser fixture containing non-ASCII names/cues, formula-prefix text, same-role repeats, directed overrides, and grouping rules for those claims.

## Native LibreOffice consumption

The consumer writes each of the three original ZIP CSV byte streams unchanged to a temporary directory. Headless LibreOffice opens each CSV using explicit import options and converts it to XLSX. An isolated profile and writable `XDG_CACHE_HOME` are used; the user's existing office profile is not changed. Every column is imported as text to prevent locale-dependent coercion. The import configuration uses comma separator `44`, double quote `34`, UTF-8 `76`, all columns set to Text `2`, quoted fields as text, and formula evaluation disabled. See the official [LibreOffice CSV filter options](https://help.libreoffice.org/latest/en-US/text/shared/guide/csv_params.html).

The script independently reads the resulting XLSX ZIP/XML. It resolves the single worksheet through workbook relationships, handles shared/inline strings, decodes OOXML escaped text, and checks every cell against the independently parsed CSV. It verifies row/column shape, exact text including Unicode and protective apostrophes, absence of formula cells, and absence of hyperlinks/external workbook links. Conversion success or an existing output file alone is insufficient. Each native run uses a fresh output directory, so an old workbook cannot satisfy the check.

These are data-import checks, not visual spreadsheet layout checks or Microsoft Excel tests. Importing with other applications or options remains unverified. CSV escaping reduces formula-import risk; it is not a guarantee for every spreadsheet program or later user transformation.

## Verification boundaries

- The recipe is the input authority for this consumer. If both recipe and exports are coherently changed, this check cannot compare them with an external original; the caller should retain the downloaded ZIP hash and test the browser's recipe round-trip separately
- Track-count labels are checked against the exported partition, not proven optimal here
- Anonymous track feasibility within the bounded elapsed-time model does not establish casting suitability, physical quick-change feasibility, or safety
- A native executable can exist but fail under a restricted environment. Read `native_libreoffice.status`; never describe semantic-only success as a native application pass
