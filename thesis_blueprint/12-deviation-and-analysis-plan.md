# Thesis Blueprint — Part 12: Deviation After the Gate and Pre-Registered Analysis Plan

> Part of the thesis blueprint — index and executive summary: [thesis_blueprint.md](../thesis_blueprint.md).
> Written 2026-10-07, after the open-loop campaign's rep blocks 1–2 (72 runs) and **before any rep 3–5 data
> exists**. It is committed and pushed before reps 3–5 start, so its timestamp predates that data; the commit is
> recorded in Part 08 §8.13. Nothing here changes the experiment's configuration.

---

## 12.1 The deviation

**What was pre-registered** (Part 08 §8.9, §8.13): after rep blocks 1–2, every gate criterion G1–G6 must pass;
otherwise the campaign stops, the closed-loop dataset becomes the thesis dataset and the open-loop work becomes a
robustness section.

**What happened** (2026-10-07, `analysis/gate-v2.json`): G1–G4 passed in all 72 runs; G5 failed in 1 run and G6 in 3
of 24 autoscaled cells — all CPU-based (auth gradual H1, auth oscillating H2, shipping oscillating H1). The gate
verdict is **FAIL** and stays on record.

**Decision (user, 2026-10-07):** continue with reps 3–5 and use the open-loop campaign as the thesis dataset. The
closed-loop campaign remains methodology background ("Replace", Part 08 §8.14).

**Reasons:**
1. The measurement-validity criteria passed everywhere: instrument (G1), start state (G2), observability (G3) and
   calibration (G4). The experiment measures what it is meant to measure.
2. The failures were traced to the system under test, not the setup. The HPA's CPU reading lags the load by about a
   minute and updates in steps; in auth oscillating H2 rep 1 this made the HPA scale in anti-phase to the load
   (Part 08 §8.13, finding #23). Real traffic would meet the same timing.
3. G6 treated disagreement between repetitions as a defect of the experiment. With the mechanism identified,
   repeatability becomes an outcome to measure (§12.4 A4) rather than a precondition.
4. Open-loop load is the realistic case: real users do not slow down when the server does; the closed-loop generator
   hid overload (finding #18).
5. Two repetitions cannot characterize the variability (3/12 vs 0/12 failing cells: Fisher's exact p = 0.109
   one-sided). Reps 3–5 complete the planned 5-rep design.

**What does not change:** configurations and manifests (H1 = 80%), rates, caps, SLOs, timeout, the frozen run order
(positions 73–180), runner and launcher, KPI definitions, and the archived superseded H1 runs.

**Disclosure:** BAB 3 and BAB 4 state the gate, its FAIL verdict, this decision and its reasons. This is the third
documented adjustment of the open-loop study, after G6 rule v2 (2026-10-06, before campaign data) and H1 = 80%
(2026-10-06, before any H1 result at 80%); all three are in the public git history with timestamps.

## 12.2 Data-quality rules for the full dataset (replacing the gate)

- **G1 (instrument) or G2 (start state) failure** = setup fault: the run is re-run once at the end of the campaign;
  both runs are kept and reported.
- **G3 (observability) and G5 (per-pod load) failures** are kept as outcomes, because metric loss and uneven load
  under overload are behavior of the autoscalers (findings #19, #23); they are reported per cell.
- **G4 (calibration)** is re-checked over all 5 reps per service × pattern and reported; a failing cell would be
  flagged as outside the range where autoscaling can be compared.
- **G6** is no longer a stop rule; its question is answered by analysis A4.
- No run is excluded for any other reason.

## 12.3 Outcomes (per run, over the KPI window 120–540 s of k6 time)

| ID | Outcome | Definition | Source |
|---|---|---|---|
| O1 (primary) | Seconds over SLO | Number of 10 s bins whose p95 (failed requests = infinite latency) exceeds the SLO, × 10 | Raw per-request data |
| O2 | Error % | Share of requests not answered successfully: 503 rejections, timeouts, other non-2xx/3xx | Raw per-request data |
| O3 | Goodput | Successful requests per second | Raw per-request data |
| O4 | Time to scale | Onset → first increase of the HPA's desired replicas; onset → first new pod Ready | `hpa-timeline.jsonl`, `pod-timeline.jsonl` (not Kubernetes events, which merge repeats) |
| O5 | Resource use | Ready replica-seconds and CPU core-seconds in the KPI window | `pod-timeline.jsonl`, `prom_cpu_usage.json` |

*Implementation note (added 2026-10-09, after the data and before any analysis; the definitions are unchanged):* for O4,
the time of an increase of desired replicas is the HPA status field `lastScaleTime` recorded in the first
`hpa-timeline.jsonl` snapshot that shows the increase. The snapshots are ≈6.1 s apart (a 5 s sleep plus the queries),
so the snapshot time alone would add up to one interval of watcher lag; `lastScaleTime` is exact to the second.

## 12.4 Analyses

**A1 — Description.** Per cell (service × pattern × config): median, minimum and maximum over the 5 reps for O1–O5.

**A2 — Planned contrasts** within each service × pattern, on O1 and O2:
- H2 vs H3 — metric (CPU vs request rate, each at its target);
- H3 vs K1 — engine (HPA vs KEDA);
- H1 vs H2 — default vs tuned HPA.

Test: exact two-sided permutation (Mann–Whitney) test, n = 5 vs 5, ties handled exactly. Effect size: Vargha–Delaney
A12 (Arcuri & Briand 2011). Multiplicity: Holm correction within each family of 3 contrasts (one family per service ×
pattern × outcome). With 5 vs 5 the smallest possible two-sided p is 0.0079, so a significant result needs complete or
near-complete separation (U ≤ 1, p ≤ 0.0159, for the first Holm step). **Effect sizes and medians are the primary
reporting; every test is reported, significant or not.**

*Clarification (added 2026-10-09; no change to the plan):* this test supersedes the "Wilcoxon signed-rank, 95% CI"
planned in older parts (01, 04, 09, 10): the signed-rank test assumes paired samples, while runs of two configurations
are independent. The metric contrast is H2 vs H3 because they share the scaling-behavior block; the older
decomposition table's "H3 vs H1" also changes the CPU target and the behavior.

**A3 — Normalized comparison across services and patterns** (Part 11 §11.10): for each autoscaler, the share of the
B1→B2 gap it closes on O1, using cell medians: (B1 − X) / (B1 − B2). Rankings and the direction of the metric and
engine effects are compared across cells; raw latencies are not.

**A4 — Repeatability (the question behind the deviation).**
- Per cell, the dispersion of O1 and O2 over the 5 reps: range and median absolute deviation.
- CPU-based (H1, H2) vs request-rate (H3, K1): compare the 12 vs 12 per-cell dispersions with an exact two-sided
  permutation test; report the effect size.
- Mechanism count, from the HPA timelines: an **anti-phase scale-down** is any decrease of the HPA's desired replicas
  while the scheduled load is at its peak (gradual: 420–540 s; spike: 130–540 s; oscillating: 130–210, 310–390 and
  490–540 s of k6 time). Report the count per run and per config.

*Exploratory addition — session check (user decision 2026-10-09, written before any A1–A6 analysis; not
pre-registered: prompted by a pattern noticed while auditing the blueprint, where reps 1–2 looked worse than reps 3–5
in several cells).* Reps 1–2 ran in session 1 (2026-10-06 12:33 → 10-07 13:31 UTC) and reps 3–5 in session 2
(2026-10-07 14:32 → 10-09 02:47 UTC), with an AKS stop and start in between. Every config has 2 runs in session 1 and
3 in session 2, so a session shift cannot bias the A2 contrasts, but it adds to the A4 dispersion. Reported as
exploratory, separate from A1–A6, which are unchanged:
- per cell, the session medians of O1 and O2 (reps 1–2 vs reps 3–5) and their difference; with 2 vs 3 runs no per-cell
  test is possible (smallest two-sided p = 0.2);
- across cells, the number in which session 1 is worse versus better (ties left out), with an exact two-sided sign
  test, separately for B1/B2 (a shift in the system itself) and for the autoscaled configs;
- the A4 dispersion recomputed within sessions (spread around each session's median), to show how much of a cell's
  spread lies between the sessions;
- a candidate cause: the nodes the service pods ran on in each session (`pod-timeline.jsonl` records each pod's node).

**A5 — Efficiency.** O5 against O1 per cell (resource used versus seconds over SLO), shown as a Pareto view per service ×
pattern; B1 and B2 mark the extremes.

**A6 — Mechanism illustration.** HPA timelines (metric reading, desired and current replicas) for selected runs,
including auth oscillating H2 rep 1 and rep 2.

## 12.5 Reporting rules

- All 180 runs are analysed and reported. The two superseded H1 runs (70%) are reported only as a disclosed note.
- The closed-loop campaign is background: the evidence for switching generators (finding #18), not a second result
  set.
- Any further deviation is documented the same way, before the data it affects.

## 12.6 Execution of reps 3–5 (needs the user's go-ahead)

1. Commit and push this part; record the commit in Part 08 §8.13.
2. Start AKS; delete pods left `Failed` by the stop; check that the VM's tracked files equal the pushed HEAD.
3. On the VM: `run-openloop-vm.sh experiment-results-openloop yes` (no stop-at, so it runs to position 180), which
   stops AKS at the end. About 36 h and $19 of AKS (estimate).
4. Fetch the results, verify the checksums, run the validator and the analyses above.

**Executed:** Part 12 pushed in `b7fa4d3` (2026-10-07 14:22:42 UTC); reps 3–5 ran 2026-10-07 14:32 → 2026-10-09 02:47 UTC
with no failure; AKS stopped 02:50:54. Data-quality rules (§12.2) over all 180 runs: G1, G2 and G3 pass in every run,
so no re-runs were needed; G4 passes in every service × pattern over the 5 reps; G5 flags only auth H2 oscillating
rep 1, kept as an outcome (Part 08 §8.13). Analyses A1–A6 are next; nothing in this plan was changed after the data
arrived. Added on 2026-10-09, before any analysis and marked as such: two clarifications (O4 timing; the choice of
test) and the exploratory session check under A4.
