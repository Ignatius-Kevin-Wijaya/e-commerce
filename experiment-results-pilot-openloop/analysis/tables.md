| run | plan pos | offered req/s | attempted | goodput | dropped | err % | timeout % | p95 ms | p99 ms | p95 ok ms | SLO-viol s | onset->scale-up s | onset->new Ready s | ready@onset | max Ready | pod shares (rate) | validity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| auth B1 rep1 | 4 | 29.67 | 29.67 | 4.10 | 0 | 86.18 | 86.18 | fail | fail | 4967 | 410 | n/a | n/a | 1 | 1 | - | ok |
| auth B1 rep2 | 16 | 29.67 | 29.67 | 4.30 | 0 | 85.50 | 85.50 | fail | fail | 4970 | 410 | n/a | n/a | 1 | 1 | - | ok |
| auth B2 rep1 | 8 | 29.67 | 29.67 | 29.67 | 0 | 0.00 | 0.00 | 887 | 1927 | 887 | 20 | n/a | n/a | 5 | 5 | 0.98 1.01 1.06 0.96 0.99 | ok |
| auth B2 rep2 | 18 | 29.67 | 29.67 | 29.67 | 0 | 0.00 | 0.00 | 843 | 1857 | 843 | 10 | n/a | n/a | 5 | 5 | 1.05 0.98 0.96 1.05 0.97 | ok |
| auth H2 rep1 | 9 | 29.67 | 29.67 | 25.58 | 0 | 13.79 | 13.76 | fail | fail | 2456 | 140 | 66 | 83 | 2 | 5 | 1.02 1.02 0.74 1.00 0.92 1.02 | ok |
| auth H2 rep2 | 12 | 29.67 | 29.67 | 23.82 | 0 | 19.70 | 19.70 | fail | fail | 4429 | 170 | 51 | 69 | 3 | 5 | 0.98 1.05 1.11 1.01 0.97 1.01 0.98 | ok |
| auth H3 rep1 | 3 | 29.67 | 29.67 | 26.59 | 0 | 10.36 | 10.36 | fail | fail | 1263 | 90 | 36 | 55 | 1 | 5 | 1.00 1.00 0.98 1.02 0.99 | ok |
| auth H3 rep2 | 19 | 29.67 | 29.67 | 27.46 | 0 | 7.45 | 7.45 | fail | fail | 1356 | 60 | 21 | 38 | 1 | 5 | 1.00 1.04 0.97 1.01 0.98 | ok |
| auth K1 rep1 | 6 | 29.67 | 29.67 | 27.21 | 0 | 8.28 | 8.28 | fail | fail | 1441 | 70 | 23 | 42 | 1 | 5 | 1.01 0.99 1.02 1.01 0.98 | ok |
| auth K1 rep2 | 17 | 29.67 | 29.67 | 26.72 | 0 | 9.94 | 9.94 | fail | fail | 1763 | 90 | 39 | 57 | 1 | 5 | 0.98 1.01 0.99 1.02 0.99 | ok |
| shipping B1 rep1 | 10 | 103.87 | 103.85 | 0.91 | 0 | 99.13 | 98.59 | fail | fail | 4676 | 410 | n/a | n/a | 1 | 1 | - | ok |
| shipping B1 rep2 | 13 | 103.87 | 103.86 | 0.89 | 0 | 99.15 | 98.62 | fail | fail | 4514 | 410 | n/a | n/a | 1 | 1 | - | ok |
| shipping B2 rep1 | 7 | 103.87 | 103.85 | 103.85 | 0 | 0.00 | 0.00 | 919 | 934 | 919 | 0 | n/a | n/a | 5 | 5 | 0.98 1.00 1.06 0.99 0.97 | ok |
| shipping B2 rep2 | 14 | 103.87 | 103.86 | 103.86 | 0 | 0.00 | 0.00 | 917 | 934 | 917 | 0 | n/a | n/a | 5 | 5 | 0.97 1.00 0.98 1.03 1.01 | ok |
| shipping H2 rep1 | 5 | 103.87 | 103.86 | 78.26 | 0 | 24.65 | 24.65 | fail | fail | 921 | 170 | 64 | 82 | 1 | 5 | 1.01 0.92 1.01 1.02 1.01 | ok |
| shipping H2 rep2 | 15 | 103.87 | 103.86 | 70.62 | 0 | 32.01 | 32.01 | fail | fail | 930 | 310 | 49 | 66 | 1 | 5 | 0.91 0.92 1.07 1.06 1.02 | ok |
| shipping H3 rep1 | 2 | 103.87 | 103.86 | 0.72 | 0 | 99.30 | 98.74 | fail | fail | 4676 | 410 | n/a | n/a | 1 | 1 | - | ok |
| shipping H3 rep2 | 20 | 103.87 | 103.86 | 0.99 | 0 | 99.05 | 98.52 | fail | fail | 4713 | 410 | n/a | n/a | 1 | 1 | - | ok |
| shipping K1 rep1 | 1 | 103.87 | 103.86 | 2.09 | 0 | 97.99 | 96.97 | fail | fail | 4615 | 410 | 19 | 36 | 1 | 2 | - | ok |
| shipping K1 rep2 | 11 | 103.87 | 103.87 | 0.90 | 0 | 99.14 | 98.60 | fail | fail | 4508 | 410 | n/a | n/a | 1 | 1 | - | ok |

| service | config | reps | window p95 ms (per rep) | SLO-viol s (per rep) | err % (per rep) | onset->scale-up s | onset->new Ready s | max Ready | closed-loop spike p95 ms (5-rep mean) |
|---|---|---|---|---|---|---|---|---|---|
| auth-service | B1 | 2 | fail / fail | 410 / 410 | 86.18 / 85.50 | n/a / n/a | n/a / n/a | 1 / 1 | 4560 |
| auth-service | B2 | 2 | 887 / 843 | 20 / 10 | 0.00 / 0.00 | n/a / n/a | n/a / n/a | 5 / 5 | 1452 |
| auth-service | H2 | 2 | fail / fail | 140 / 170 | 13.79 / 19.70 | 66 / 51 | 83 / 69 | 5 / 5 | 1486 |
| auth-service | H3 | 2 | fail / fail | 90 / 60 | 10.36 / 7.45 | 36 / 21 | 55 / 38 | 5 / 5 | 1462 |
| auth-service | K1 | 2 | fail / fail | 70 / 90 | 8.28 / 9.94 | 23 / 39 | 42 / 57 | 5 / 5 | 1476 |
| shipping-rate-service | B1 | 2 | fail / fail | 410 / 410 | 99.13 / 99.15 | n/a / n/a | n/a / n/a | 1 / 1 | 3324 |
| shipping-rate-service | B2 | 2 | 919 / 917 | 0 / 0 | 0.00 / 0.00 | n/a / n/a | n/a / n/a | 5 / 5 | 917 |
| shipping-rate-service | H2 | 2 | fail / fail | 170 / 310 | 24.65 / 32.01 | 64 / 49 | 82 / 66 | 5 / 5 | 993 |
| shipping-rate-service | H3 | 2 | fail / fail | 410 / 410 | 99.30 / 99.05 | n/a / n/a | n/a / n/a | 1 / 1 | 987 |
| shipping-rate-service | K1 | 2 | fail / fail | 410 / 410 | 97.99 / 99.14 | 19 / n/a | 36 / n/a | 2 / 1 | 941 |

- **1. dropped_iterations = 0 in all runs: PASS** — 20 runs with raw data of 20; non-zero: none
- **2. B2 error < 1% and window p95 <= SLO: PASS** — auth-service rep1: err 0.00%, p95 887 vs SLO 1500; auth-service rep2: err 0.00%, p95 843 vs SLO 1500; shipping-rate-service rep1: err 0.00%, p95 919 vs SLO 1200; shipping-rate-service rep2: err 0.00%, p95 917 vs SLO 1200
- **3. B1 clearly overloaded: PASS** — auth-service B1 rep1: SLO-viol 410 s, err 86.18% (B2 max err 0.00%); auth-service B1 rep2: SLO-viol 410 s, err 85.50% (B2 max err 0.00%); shipping-rate-service B1 rep1: SLO-viol 410 s, err 99.13% (B2 max err 0.00%); shipping-rate-service B1 rep2: SLO-viol 410 s, err 99.15% (B2 max err 0.00%)
- **4. Reps agree within +/-25% (autoscaled configs): FAIL (check poll-phase explanation)** — auth-service H2: p95 fail/fail (diff 0%), SLO-viol 140/170 s (diff 19%); auth-service H3: p95 fail/fail (diff 0%), SLO-viol 90/60 s (diff 40%); auth-service K1: p95 fail/fail (diff 0%), SLO-viol 70/90 s (diff 25%); shipping-rate-service H2: p95 fail/fail (diff 0%), SLO-viol 170/310 s (diff 58%); shipping-rate-service H3: p95 fail/fail (diff 0%), SLO-viol 410/410 s (diff 0%); shipping-rate-service K1: p95 fail/fail (diff 0%), SLO-viol 410/410 s (diff 0%)
- **5. Per-pod distribution passes in all autoscaled runs: PASS** — flagged: none; runs with <2 eligible pods: shipping-rate-service_h3_spike_rep1, shipping-rate-service_h3_spike_rep2, shipping-rate-service_k1_spike_rep1, shipping-rate-service_k1_spike_rep2
