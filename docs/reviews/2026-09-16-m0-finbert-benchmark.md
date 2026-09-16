# M0-05 FinBERT benchmark review — 2026-09-16

**Scope:** local ML compatibility and resource benchmark. **Reviewer:** implementing agent, separate self-review. **Outcome:** passed for FP32 CPU engineering use; it does not admit a predictive news source.

## Verified evidence

- The optional ML group locks CPU-only PyTorch 2.6.0 and Transformers 4.49.0 on Python 3.12.14. CUDA is unavailable and no GPU path was attempted.
- The exact audited ProsusAI/finbert revision 5fcfed04a2ca89adf4170ec0a4715103ed7745db loaded with remote code disabled. The aggregate benchmark records SHA-256 hashes for config, tokenizer and weight files.
- The 1,000-title pass completed in 21.01 seconds at 47.60 titles/second with 816,979,968 bytes peak RSS. The 10,000-title sustained pass completed in 297.97 seconds at 33.56 titles/second with 963,940,352 bytes peak RSS. Both remain well under the 6 GiB stop threshold.
- Both runs processed their requested title count without inference error. A second inference of the deterministic 32-title prefix produced an identical aggregate checksum. The evidence excludes titles, individual probabilities, prices, outcomes and predictive metrics.

## Decision

Retain FP32 CPU, batch size eight, four compute threads and one inter-op thread as the M3 starting configuration. Do not optimize to INT8: the measured throughput is sufficient for the current engineering gate, and the blueprint requires a separate equivalence and performance decision before quantization.

The source sample contains retained Yahoo titles only. The runner accesses no supplied price, sentiment, entity, description or body field. This result establishes Windows compatibility and a conservative capacity estimate; it does not change the unresolved feed completeness, crawl-version provenance, or primary-study source admission decision.

## Review and follow-up

The review checked the fresh sentiment preflight, revision provenance, cache hashes, bounded title selection, RSS guard, deterministic repeat, error behavior and documentation. The Windows cache emitted a symlink-capability warning; caching remained functional, the local cache is ignored, and no elevated OS setting was changed. M0-05 is complete. The third completed task since the prior cross-document review triggers a combined M1/M0 review before M2-01 begins.
