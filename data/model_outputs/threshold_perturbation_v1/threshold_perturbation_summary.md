# Exploratory perturbation analysis of threshold-sensitive findings

We performed an exploratory perturbation analysis for threshold-dependent findings. We treat this as a sensitivity check rather than proof of reasoning, because monotonic changes in output cannot exclude memorization or distributional familiarity.

Methods: We selected 5 threshold-sensitive finding families and generated 15 prompt variants by changing only the numeric threshold within otherwise similar finding text. The primary analysis queried gpt-5 once per variant. The D-dimer family was included as a constructed reviewer exemplar because the manuscript workbook includes D-dimer findings without numeric thresholds; the other families were grounded in threshold-dependent workbook findings.

Results: 3 of 5 families were nondecreasing, flat, or strictly increasing across the tested thresholds, including 2 strictly increasing families. 2 families were nonmonotonic. 0 families met the prespecified anchored flag, defined as an endpoint fold-change <= 1.10.

Family-level results:
- DVT D-dimer: thresholds 500.0; 550.0; 1000.0 ng/mL; GPT-5 LRs 2.2; 1.6; 2.5; monotonic class nonmonotonic; endpoint fold-change 1.136; anchored flag False.
- Heart failure BNP: thresholds 50.0; 100.0; 250.0 pg/mL; GPT-5 LRs 2.6; 4; 6; monotonic class strictly_increasing; endpoint fold-change 2.308; anchored flag False.
- Temporal arteritis ESR: thresholds 50.0; 70.0; 100.0 mm/h; GPT-5 LRs 1.5; 2.4; 4; monotonic class strictly_increasing; endpoint fold-change 2.667; anchored flag False.
- Cardiac syncope hs-troponin T: thresholds 30.0; 42.0; 60.0 pg/mL; GPT-5 LRs 2.5; 2.5; 10.0; monotonic class nondecreasing_with_ties; endpoint fold-change 4.000; anchored flag False.
- Elevated ICP CT midline shift: thresholds 5; 10.0; 15.0 mm; GPT-5 LRs 12.0; 11.0; 20.0; monotonic class nonmonotonic; endpoint fold-change 1.667; anchored flag False.
