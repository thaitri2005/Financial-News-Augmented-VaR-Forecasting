# M0-05 FinBERT benchmark contract

## Purpose and scope

This is a local engineering compatibility and resource test. It uses English titles from the retained Yahoo collection only to exercise tokenizer and classifier throughput. That collection remains unsuitable as the project's primary historical predictive feed because its crawl and selection provenance has not passed source admission. The benchmark reads only title text; it ignores every supplied price, sentiment, entity and outcome field.

The checkpoint is ProsusAI/finbert at immutable revision 5fcfed04a2ca89adf4170ec0a4715103ed7745db, the December 2020 first-version commit already recorded in the model-revision audit. Downloaded files stay in ignored local cache; the benchmark writes a small public evidence JSON containing hashes, versions, aggregate counts and resource measurements, never titles or per-item scores.

## Environment and run policy

Pin CPU-only PyTorch 2.6.0 and Transformers 4.49.0 in an optional ML dependency group. PyTorch's official Windows support includes Python 3.12 and its official 2.6.0 CPU wheel route is used. Transformers supplies the documented AutoTokenizer and AutoModelForSequenceClassification interfaces. The process sets one inter-op thread and at most four compute threads; model inference is FP32 CPU with no remote code.

The runner requires a fresh sentiment doctor pass, minimum five GiB available RAM. It uses deterministic file ordering, title order and no shuffle. It runs a warm-up, then 1,000 titles in batches of eight. It measures wall time, initial/final/peak process RSS, aggregate label count and a repeated prefix checksum. It may run 10,000 titles only if the 1,000-title run stays under 6 GiB process RSS and completes without inference error. A 10,000-title run is a sustained engineering test, never an outcome experiment.

## Acceptance and recovery

Pass conditions are: exact revision/config/tokenizer files resolve locally; no remote code; all selected titles have a classifier result; repeated prefix labels/probabilities are bitwise-stable under the same environment; peak RSS stays below six GiB; and the run retains provenance plus timing. The task can conclude that the local FP32 path is technically viable, not that sentiment improves VaR or that this corpus is source-admitted.

Any preflight failure, incompatible CPU wheel, file mismatch, inference exception, deterministic mismatch or RSS breach stops the sustained pass. Record the failure, leave M0-05 unresolved, and do not retry a larger batch. Later quantization is deferred until it has a separate equivalence and speed decision.
