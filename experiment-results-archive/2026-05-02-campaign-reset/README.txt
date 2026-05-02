Campaign reset snapshot created on 2026-05-02.

Purpose:
- Preserve the legacy auth-service first-run dataset before a clean rerun.
- Preserve a copy of the currently valid shipping-rate-service first-run dataset.
- Preserve the pre-reset runner state and experiment log for auditability.

Contents:
- auth-service-first-run-legacy/
- shipping-rate-service-first-run-valid-snapshot/
- state_before_reset/experiment-state.pre-reset
- state_before_reset/experiment.log.pre-reset

Active workspace changes performed after snapshot:
- Moved experiment-results/auth-service into this archive bundle.
- Reset experiment-results/.experiment-state to empty.
- Reset experiment-results/experiment.log to empty.

Notes:
- Shipping results remain in experiment-results/shipping-rate-service and were also copied here so they are safe if future rep1 reruns overwrite the active tree.
- Product-service exploratory results were not moved in this reset.
