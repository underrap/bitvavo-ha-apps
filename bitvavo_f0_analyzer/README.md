# Bitvavo F0 Execution Analyzer

One-shot Home Assistant app for the completed prospective F0 dataset.

Input: `/homeassistant/bitvavo_research/bitvavo_microstructure_week1`

Output: `/homeassistant/bitvavo_research/f0_analysis_001`

The analyzer verifies completed collector state and manifest hashes, applies the frozen usable-pair gate, reports execution-topology economics, and never authenticates or places orders. It refuses to overwrite a non-empty output directory.
