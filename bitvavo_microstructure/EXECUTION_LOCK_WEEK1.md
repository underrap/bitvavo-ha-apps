# F0 week-1 execution source lock

This branch is the immutable execution source for the completed seven-day
BTC/EUR ↔ BTC/USDC execution-topology analysis.

The final execution commit is the Git commit that contains this file and passes:
- `F0 execution-topology tests`;
- `F0 handoff packager tests`.

Rules:
- do not merge unrelated later development into this branch;
- do not modify `analyze_f0.py` or `prepare_f0_handoff.py` after this lock;
- do not open/analyze the real collector dataset before it has completed its seven-day duration;
- package only a manifest-consistent completed collector run;
- record the exact passing commit alongside the resulting F0 analysis.
