# v1.1.0 — Reproducibility and metadata maintenance release

## Article

**Large language models generate diagnostic likelihood ratios with low mean bias but wide dispersion**

*Scientific Reports*

[https://doi.org/10.1038/s41598-026-61766-2](https://doi.org/10.1038/s41598-026-61766-2)

Published online in *Scientific Reports* on 11 July 2026 as an unedited early-access article.

## Release relationship

`v1.0.0` remains the immutable accepted-paper snapshot published with the article. `v1.1.0` is the current maintenance release of the reproducibility package.

This release improves repository navigation, public documentation, metadata, validation, and machine-readable guidance. It does not change any accepted-paper input, output, prompt, model configuration, notebook, statistic, figure, interpretation, or conclusion.

## What changed

- The README now mirrors the publication title and gives readers a shorter path from the article to the frozen data, code, results, and reproduction commands.
- Project and citation metadata now distinguish the `v1.0.0` paper snapshot from the current `v1.1.0` maintenance release.
- Source, variable, rights, accepted-output, and release metadata have stricter offline validation and clearer documentation.
- Release tooling supports explicit, versioned successor-release contracts while preserving the historical `v1.0.0` rules.
- Machine-oriented repository guidance and contributor documentation now use the same publication and release terminology.

## Reproduce

```bash
pip install uv
uv lock --check
make setup
make reproduce
make test
```

`make setup` may download the locked dependencies. Reproduction and tests use frozen local artifacts and make no OpenAI API calls or live TheNNT requests.

## Scientific and provenance boundaries

No live model call or web-scraping request was made in preparing this release. The 39 protected accepted-paper artifacts and the frozen numerical reference results remain unchanged from `v1.0.0`.

Known provenance gaps remain recorded rather than inferred. The repository also preserves the documented evidence-direction wording discrepancy without relabeling either the submitted prose or the executable result.

The MIT License applies only to original repository software. Literature-reported values, TheNNT-derived material, provider outputs, and article text retain their distinct provenance and reuse boundaries.

## Validation boundary

Automated checks verify repository consistency; they are not independent scientific, statistical, rights, reproducibility, or high-risk certification. Any unavailable optional private-source comparison is reported as unavailable rather than passed.

## Citation

Cite the article and the exact repository release used. Use `v1.0.0` for the paper-release snapshot or `v1.1.0` for this maintained reproducibility package; `CITATION.cff` contains the full article citation and current release metadata.
