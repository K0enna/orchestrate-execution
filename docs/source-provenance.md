# Source provenance for v0.3.0

The table identifies the distributed Python bytes. Eight helpers remain byte-for-byte copies of their maintained source files. `routing_decisions.py` and `test_routing_decisions.py` are same-author distribution derivatives with a narrow acceptance-evidence repair: `accepted: true` coordinator steps require exactly one matching eliminated stage with evidence. Their original accepted-base hashes were `bdc1ab795bcc34c1c6bfb6b5e78e91ac7bf4715d8567fa45b2edc1fbd4e355be` and `6590aaac08241a4837aa260f6d1f1b4e582efd9cd446bdc8813f9360227365c4`, respectively; the table records the current distributed bytes. The original source locations remain local and are not part of the public package. The MIT notice is retained at [`LICENSE`](../LICENSE) and in the installable skill folder.

| Packaged path | SHA-256 |
| --- | --- |
| `skills/orchestrate-execution/scripts/routing_decisions.py` | `43a16c960c7566803978b3373cb40202b408a739a76d61124960d6c94e5f8ece` |
| `skills/orchestrate-execution/scripts/decision_adviser.py` | `517039f0b126a5666a71b3dbc6341086014cab01688e4c8807125faa3870bd35` |
| `skills/orchestrate-execution/scripts/compact_evidence.py` | `d6d7d3915e0f560c65c4d2f4c8f415df13fca6a92c386e2e4d028975c673d390` |
| `skills/orchestrate-execution/scripts/test_routing_decisions.py` | `f0671b28896c19d4fd4a0f977386776cf67c0ccdbdf4bb33925c5625dc03d2a3` |
| `skills/orchestrate-execution/scripts/test_decision_adviser.py` | `56121fd7c5b95c5274ba3da65e2eb8dc892e10fae0eedc68c3bb4bf92f0cba85` |
| `skills/orchestrate-execution/scripts/test_compact_evidence.py` | `6c0769be44b6a95eb9f2d9d4ee69c85ca08b1aa156034dc4fd1fd34f9e1af478` |
| `skills/orchestrate-execution/scripts/detached_receipt.py` | `e0d011d84000a8dc55095ff476dd31238212f9076778c2968cb2032a40bb87ec` |
| `skills/orchestrate-execution/scripts/test_detached_receipt.py` | `75dfabd97633af81e6fd6bb013fe37598ed024ddabebebda7d8c6ebc630b891a` |
| `skills/orchestrate-execution/scripts/workbench_claim.py` | `e95c9d588f185693d57e462db536043b32a121e0bae7dcecc23a00b6fef86eb9` |
| `skills/orchestrate-execution/scripts/test_workbench_claim.py` | `94dbb8eb78766a875480e564d21cb36469ac479e8d4f4337759b7dcd7cd8b2f0` |

The two existing workbench files retain their previously distributed bytes. The receipt helper and its test are refreshed to the current source hashes above. The new router, adviser, evidence projector and tests are unchanged from their source bytes. No third-party Python dependency is added.
