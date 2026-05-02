Campaign reset snapshot created on 2026-05-02.

Purpose:
- Preserve the legacy auth-service first-run dataset before a clean rerun.
- Preserve a copy of the currently valid shipping-rate-service first-run dataset.
- Preserve the pre-reset runner state and experiment log for auditability.

Contents:
- auth-service-first-run-legacy/
- shipping-rate-service-first-run-valid-snapshot/
- product-service-exploratory-snapshot/
- reports/
- operational-logs/
- tmp-fragments/
- notes/
- state_before_reset/experiment-state.pre-reset
- state_before_reset/experiment.log.pre-reset

Active workspace changes performed after snapshot:
- Moved experiment-results/auth-service into this archive bundle.
- Removed experiment-results/shipping-rate-service after verifying it matched the preserved snapshot byte-for-byte.
- Moved experiment-results/product-service into this archive bundle because it is appendix-only and not part of the active core workspace.
- Moved generated report artifacts and supervisor meeting notes into this archive bundle.
- Moved watcher/live-validation/shipping-run logs into this archive bundle.
- Moved experiment-results/.tmp into this archive bundle.
- Moved the shipping investigation note into this archive bundle.
- Reset experiment-results/.experiment-state to empty.
- Reset experiment-results/experiment.log to empty.

Notes:
- This archive snapshot is now the canonical preserved copy of the original shipping-rate-service rep1 dataset.
- This archive snapshot is also the canonical preserved copy of the original product-service exploratory rep1 dataset.
- The active experiment-results/ directory should now contain only the live run ledger and live run log.
