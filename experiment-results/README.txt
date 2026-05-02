This directory is the active experiment workspace.

Keep here only:
- .experiment-state
- experiment.log

Historical datasets, generated reports, stray run logs, and archived reset snapshots
belong under experiment-results-archive/.

Current intent:
- Start future campaigns from a clean workspace.
- Use .experiment-state only as the active resume ledger for the current run.
- Treat experiment-results-archive/ as the historical record.
