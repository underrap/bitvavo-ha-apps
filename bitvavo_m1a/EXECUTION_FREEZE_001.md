# M1A_FREEZE_001 execution source lock

This branch is the immutable execution source for `M1A_FREEZE_001`.

Protocol:
- `M1A-PREREG-v1.3`
- substantive content rules identical to `M1A-PREREG-v1.2`
- executor version `1.2.0`

This marker intentionally contains no self-referential commit SHA. The exact execution
commit is the Git commit that contains this file and passes the `M1A tests` workflow.

Rules:
- do not merge later unrelated development into this branch;
- do not modify M1A implementation after this lock;
- build/deploy the M1A app from the exact passing commit on this branch;
- record that SHA externally in `execution_provenance.json`;
- do not analyze real M0 data before the provenance gate passes.
