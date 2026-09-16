# M3-01 frozen encoder and score-cache contract

This increment is engineering-only and operates on synthetic `ScoreRequest` records. It does not admit a news source or create predictive features.

The loader accepts only the local directory named with FinBERT revision `5fcfed04a2ca89adf4170ec0a4715103ed7745db`, disables remote code and downloads, hashes the model and tokenizer files, and verifies class IDs `{0: positive, 1: negative, 2: neutral}`. CPU FP32 uses the existing batch size 8 and maximum sequence length 128. The fingerprint includes model weight hash, combined tokenizer-file hash, maximum length, preprocessing version, backend and precision.

The cache key combines the exact UTF-8 text SHA-256 with that fingerprint. Every JSON entry contains both identities and probabilities/token metadata, is staged and fsynced before atomic replacement, and rejects a different value under an existing key. A failed scorer batch leaves no partial entries for that batch; earlier completed batches remain usable. Misses are sorted by length then content hash for deterministic batching, while returned records retain caller order and IDs.

Inference requires the blueprint's live sentiment resource gate (at least 5 GiB available RAM). File fingerprint checks and synthetic cache tests do not bypass that gate.
