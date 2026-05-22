K1 fairness rerun snapshot created on 2026-05-22.

Why this snapshot exists:
- The original K1 experiment manifests did not define generated-HPA behavior, so
  K1 was not actually matched to H3/H2 on scale-up and scale-down policy.
- A live AKS verification on 2026-05-22 confirmed the gap and validated the
  manifest fix that adds `advanced.horizontalPodAutoscalerConfig.behavior`.

What is preserved here:
- `core-k1-snapshot/auth-service-k1/`
- `core-k1-snapshot/shipping-rate-service-k1/`
- `state_before_reset/experiment-state.pre-k1-reset`

How the active workspace was prepared:
- The old auth/shipping K1 result trees were moved out of `experiment-results/`
  so a clean rerun can write new `rep1..rep5` outputs in the standard paths.
- Only the `DONE:` entries for auth/shipping K1 runs were removed from the live
  `experiment-results/.experiment-state` ledger.

Scope note:
- Shipping and auth K1 are being prepared for rerun because the fairness bug
  affected both core services.
- Product-service remains exploratory / appendix-only.
