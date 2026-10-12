# M1A_FREEZE_002 execution source lock

This branch is the immutable execution source for `M1A_FREEZE_002`.

Protocol:
- `M1A-PREREG-v1.3`
- substantive content rules identical to `M1A-PREREG-v1.2`
- executor version `1.2.2`
- required collector version `M0 1.0.6`
- required capability `persisted_reconstructed_book_checkpoints_v2`

Integrity correction relative to FREEZE_001:
- explicit `boot_id` replaces inferred restart epochs;
- persisted checkpoint `covered_through_recv_mono_ns` is the causal replay cutoff;
- raw book events received after that watermark are replayed even if checkpoint persistence happened later;
- no target, feature, discovery/holdout split, bootstrap rule, minimum-data rule or PASS/FAIL condition changed.

Rules:
- build/deploy only from the exact passing execution commit for this freeze;
- do not modify M1A implementation after the source lock;
- create provenance before opening any real result;
- no cross-checkpoint or cross-boot target/trade-flow window is allowed.
