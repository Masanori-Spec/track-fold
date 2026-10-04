# Security and scope

The runtime is a dependency-free static HTML application. Inputs stay in memory;
there are no analytics, network calls, external assets or saved browser drafts.
The Content Security Policy disallows connections and remote resources. Explicit
exports are local downloads; it remains the user's decision where to share them.

Imported recipes are capped at 1 MiB and validated before replacing the current
model. The model caps roles, appearances, text lengths, time ranges and constraint
counts. Duplicate IDs and directed overrides are rejected. Unknown model versions
are rejected. Role/appearance IDs cannot contain delimiters or markup.

Rendered user text is HTML-escaped or assigned through DOM text/value APIs. The
portable report contains no script and has its own restrictive CSP. CSVs quote all
fields and prefix potentially formula-leading values with an apostrophe; the JSON
recipe preserves normalized text without the CSV apostrophe transform. This reduces spreadsheet formula interpretation
but is not a universal guarantee for every spreadsheet product or import setting.

The solver runs in a cancellable worker, with time/operation bounds and a separate
UI timeout. Input edits invalidate results immediately; stale worker responses are
ignored. No incomplete search is labelled optimal or allowed to export.

The app does not cast, evaluate or rank real people. It does not establish safety,
physical changeover feasibility, a legal call sheet or professional compliance.
Do not put real performers' sensitive information into fictional role/cue fields.

Automated browser tests require a functioning Chromium sandbox. They never use
--no-sandbox or disable Chromium's sandbox. No credentials or special account
permissions are required. The source ships without a project-license decision.

Text line endings are canonicalized at the input boundary: CRLF and lone CR become LF in names and cues. The recipe, CSVs and HTML all represent this normalized model. Other well-formed Unicode is preserved.
