# Historical prompts

The JSON files in this directory preserve the prompts used to produce the
accepted-paper outputs. They are immutable research artifacts, including the
historical spelling, punctuation, Unicode characters, and typographical errors.

- `main_estimator_v1.json` records the main estimator prompt, its eight-example
  and two-example sets, and the accepted model-to-example-set policy.
- `threshold_perturbation_v1.json` records the distinct prompt used for the
  threshold sensitivity analysis.

The prompt-file hashes are recorded in `manifests/manuscript_run_v1.json`.
A live replication must copy the prompt it uses into its run directory. Any
corrected or revised prompt requires a new version and must not replace these
files.
