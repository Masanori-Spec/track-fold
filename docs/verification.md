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

Browser execution is intentionally deferred to the authored Ubuntu 22.04 GitHub
Actions job because the local browser environment is blocked. No sandbox weakening
or shared browser was used. The 20 browser scenarios are authored and syntax-checked,
not locally executed. Actual browser downloads, responsive screenshots, standalone
HTML display and A4 PDF page inspection remain release gates.

The incomplete-worker browser scenario injects a result specifically to test UI
wording and export suppression. The real engine budget paths are tested separately;
the injected scenario is not evidence of a real engine timeout.

No repository publication, hosted deployment, paid service, external outreach,
license selection or new credential/access grant has been performed in this build.

Independent source review additionally caught and fixed invalid UTF-16 export text, stale async import failures, same-file reselection, and CR/CRLF canonicalization. Dedicated regression tests now cover those paths; current browser evidence remains authored only.
