# Phase 5 temporal policy v1 — registered 2026-11-13

Choose **Option B: threshold-independent features** before generating historical features
or evaluating fusion. Do not reuse September-derived Phase3 thresholds in earlier periods.
Do not extend or overwrite Phase3's 77-column test export. New columns have `p5_b_` (cheap)
or `p5_c_` (Chronos) prefixes, with identical feature definitions across all four splits.

Reuse the pinned genuine Chronos-2 revision/official adapter and its 168-hour, four-variate
context, 24-hour forecast, 0.1/0.5/0.9 quantiles, fp32 CUDA, batch16 origins, seed42 and
four CPU threads. Daily issuance is midnight UTC. Context consists only of the exact
168 observations strictly before issue; gaps/incomplete history prevent issuance, without
interpolation. Do not inspect target values to decide origin eligibility. Issue from the
first accepted snapshot's midnight to the last snapshot's midnight, requiring only valid
historical context. Save forecasts with identities and checksums before actual matching.

Cheap control is the last-24h historical mean, the strongest registered Phase3 cheap
forecast comparator. It uses the same eligible origins/history/horizon. Point forecasts
are constant over the next24h. A symmetric heuristic interval uses the empirical80th
percentile of absolute one-step historical errors of a causal last24h mean, computed
entirely inside the context (144 errors). This is a cheap uncertainty proxy, not a
calibrated or genuine pretrained quantile model. Both sources remain clearly identified.

Each feature group has **40 numeric columns**: per channel forecast mean, first-to-last
trend/hour, standard deviation, mean interval width and relative change (20); per channel
latest matured absolute residual/context MAD, completed24h mean/max and valid residual
count (16); multivariate latest residual mean/max (2); forecast age and availability (2).
MAD is1.4826 times the historical median absolute deviation, with the Phase3 causal floor.
No anomaly threshold, anomalous-count/fraction/persistence or failure annotation is used.
Forecast variation is across predicted medians, not realized future volatility.

At snapshot T use the latest issue<=T, with forecast context source<issue. Residuals may
use only target observations **strictly before T**. A forecast for T+24h cannot contribute
its unrealized residual. The completed residual window is [T−24h,T); daily issues predict
their same-day24 hourly observations. Preserve per-row source/issue/residual timestamps,
model/checkpoint identity, policy hash and feature availability. Pretraining overlap with
this public synthetic dataset remains unresolved; zero-shot means no local neural fit.

Initial history does not support January8 midnight issuance: raw telemetry starts
January1 06:00. Keep every accepted snapshot for every ablation. Use native LightGBM NaN
routing for unknown forecasts/recencies and explicit availability0/residual counts0;
age and undefined statistics stay NaN. No fitted imputation or exclusion is allowed.
Never substitute a later forecast for missing history. Do not choose columns or missingness
rules after examining test outcomes. Static metadata/UTC/immediate source availability
assumptions remain the accepted ones. Graph features keep their original separate contract.
