# M3-03 causal M/C/S feature contract

The feature builder accepts only values known at an origin: at least 63 prior market returns, the latest two eligible VIX observations, the current news window, and exactly the fixed preceding news-window ranges. It emits the nine declared market features, four count/calendar controls, six sentiment features, and non-predictive feed/scoring diagnostics.

For an incomplete feed window, every C/S feature is null and `feed_complete=false`; it is not recoded as zero news. A complete empty window has `has_news=0`, null sentiment aggregates and scoring coverage one. Count z-scores use only the prior 63 windows and need 20 complete values. Sentiment shocks use only the prior 21 complete, nonempty means and need 10 values. No lookup extends backward beyond those fixed windows.

The sentiment ratio resolves a probability tie by lowest FinBERT label ID, so a positive/negative tie is not a negative label. Scores must be finite probabilities that sum to one. Retained and scored counts remain separate, and scoring coverage is diagnostic rather than a predictive feature.

This is a synthetic-input contract. Materializing rows from news requires both M3-01 live inference and M1 source admission.
