Auth h3/k1 rep1 snapshot archived on 2026-05-05 before rerunning those six runs.

Reason:
- `auth-service_h3_oscillating_rep1` had real critical issues:
  - dropped_iterations under-delivery
  - `FailedGetPodsMetric`
- `auth-service_k1_oscillating_rep1` had real critical issues:
  - dropped_iterations under-delivery
- The original auth h3/k1 result directories were moved here to preserve provenance
  before replacing the active results with clean reruns.

Preserved items:
- `auth-service/h3/*/rep1`
- `auth-service/k1/*/rep1`
- `experiment-state.before-rerun`
