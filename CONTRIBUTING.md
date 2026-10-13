# Contributing

Keep changes focused on routing, bounded assignments and acceptance. Preserve the direct-work path and user authority. New runtime claims need evidence from that runtime; a successful launch ID or model statement is insufficient.

Run the package check and deterministic benchmark-runner tests:

```sh
python -B tools/check_package.py
python -B -m unittest discover -s benchmarks -p "test_*.py" -v
python -B -m unittest discover -s skills/orchestrate-execution/scripts -p "test_*.py" -v
```

The optional mode helpers use Python 3.11 or later and its standard library. Their tests exercise local receipts and reservations, with no model calls or chat sends. Keep state and private artifacts outside the distributed skill folder and public repository.

Decision probes call a model only with explicit execution flags. They may incur usage; keep raw prompts, runtime logs and private evidence outside the repository. Preserve failed runs and report what was measured. A short probe is not a production performance benchmark.

For instruction changes, include a concrete request where the change matters and its observable expected outcome. Avoid tests that assert prose wording. For metric changes, retain denominators, model/effort, measurement scope and limitations. Do not include credentials, private transcripts or account-specific setup.

