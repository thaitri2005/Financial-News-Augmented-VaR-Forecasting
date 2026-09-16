# M2-04 protected metric contract

Metrics take decimal simple returns and lower-tail return quantiles. A breach is strictly return less than quantile; equality is not a breach. Pinball loss uses the declared alpha and original decimal units. Paired comparison intersects target-end sessions, rejects duplicate model rows and rejects mismatched realized outcomes before computing losses. Positive mean improvement favors the challenger.

Calibration reports count, rate, expected count and a 95% exact binomial interval. It uses no pseudo-count. Transition counts use the saved XNYS calendar and count only actual adjacent target sessions; a missing forecast/session breaks the transition chain. More complex coverage/independence diagnostics remain a later extension until their undefined-domain behavior has fixtures.

This contract is synthetic-first. It does not permit a final-period evaluation, outcome-based model selection, or an unpaired score comparison. The implemented private development join keys every forecast to the market label with the same forecast-origin session, then uses that label's declared target-end session as the metric key. It rejects duplicate forecast origins and absent labels. A private development join must preserve the ledger ID, metric version, common-date mask and exact target-end mapping.
