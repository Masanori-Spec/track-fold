# Verification status

Local source-stage verification on 2026-10-04:

- Node 24.19.0: 104 tests passed
- Bundled HTML and actual worker script syntax, no-network CSP, embedded fixture
  worker smoke: passed
- Python 3.12.14 independent oracle: 1,183 default and 3,244 alternate-seed cases
  passed; 18 deliberately corrupted certificates rejected
- CLI stdin multibyte decoding defect found by the alternate oracle corpus, fixed
  with UTF-8 streaming decode, retested and regression-covered
- Python ZIP/CSV semantic consumers passed standard and adversarial exports; 19
  corrupted bundles were rejected. Native LibreOffice has not passed locally: its
  first conversion exited 137, followed by an executor rollback. The source was
  restored and the full Node/oracle/semantic suites rerun. Later local consumers
  explicitly used --skip-libreoffice; native conversion is a required CI gate
- Performance bounds: operation/time budget paths tested; no universal device
  responsiveness or completion-time guarantee is claimed

## Initial hosted CI and responsive correction

[Run 37203726116](https://github.com/Masanori-Spec/track-fold/actions/runs/37203726116)
verified source commit `431b4699ddb2983dbc2516afeda7744a47ce6868`:

- Node 22 and 24 jobs, including both independent oracle corpora: passed
- Sandbox-enabled Chromium: 19 of 20 scenarios passed
- Actual browser-downloaded standard and hostile ZIPs: Python semantic checks and
  LibreOffice 7.3.7.2 CSV→XLSX consumers passed, preserving every cell as text with
  zero formula cells
- Standalone HTML and A4 generation: passed; all ten rendered pages inspected,
  with no cropped table/cue text and repeated headings on the long-table continuation
- Japanese app at 390px: failed with a 589px document scroll width

The first width-containment correction did not resolve the failure in
[run 37204333888](https://github.com/Masanori-Spec/track-fold/actions/runs/37204333888).
Its layout diagnostics isolated an absolutely positioned, visually hidden header
label at x=588–589px. Because its containing block was outside the scrolling table,
the label widened the document even though the visible columns were clipped correctly.

The targeted correction positions each table header relatively, keeping its hidden
label's containing block inside the scrollport. The mobile regression checks both
accessible remove-column names, their actual containing blocks, document width and
scroll access to the last columns. Document-level overflow is never hidden.
Local Node checks still pass. The exact targeted correction's hosted rerun and
mobile screenshot inspection are pending; this is not a final release pass.

No local browser or further native LibreOffice execution was attempted after the
local environment failure. No sandbox weakening or shared browser was used.

The incomplete-worker browser scenario injects a result specifically to test UI
wording and export suppression. The real engine budget paths are tested separately;
the injected scenario is not evidence of a real engine timeout.

The source repository is published for hosted CI. No hosted app deployment, paid
service, external outreach, license selection or new credential/access grant was
performed in this build.

Independent source review additionally caught and fixed invalid UTF-16 export text, stale async import failures, same-file reselection, and CR/CRLF canonicalization. Dedicated regression tests now cover those paths; the source fixes passed the initial hosted browser checks described above.
