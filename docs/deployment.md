# Deploy the replay, not the simulator

The public demo is plain HTML, CSS and JavaScript with six embedded synthetic runs. GitHub Pages does not execute the Python engine or a live model. No API keys, analytics, customer records, paid services or custom domain are needed.

## Build before publishing

From the repository root, after installing the package:

```sh
python -m unittest discover -s tests -v
python scripts/build_site.py --output site-output
```

The build validates all fixtures, generates fresh evidence, checks the expected teaching-baseline outcomes, and emits only `index.html`, `results.json` and `.nojekyll`. Publish **only those three files**, not the repository or private preview source. The output directory is ignored by git.

## First deployment without touching main

1. Verify the connected GitHub identity owns or can administer the intended repository. Read its current branches and Pages settings.
2. Put implementation changes in a feature branch and open a reviewable pull request. Do not merge main automatically.
3. Once public deployment is approved, publish the reviewed static artifact on a separate `gh-pages` branch. Keep the implementation branch and artifact branch separate.
4. In repository Settings > Pages, select deployment from the `gh-pages` branch root. This changes repository settings and needs admin permission. Do not change visibility, billing, domains or branch protections.
5. Read the actual URL from the successful Pages deployment or Settings > Pages. Do not infer a URL or claim success from the branch push alone.
6. Open that URL in a browser. Check all three scenarios, both strategies, play/reset/scrub and JSON export, plus mobile/desktop layout. Link the verified URL from the README in a follow-up PR.

If Pages already exists, preserve its source and content until the owner approves replacement. Never overwrite another site's deployment branch. The separate private preview keeps its existing private audience.

## Updating and rolling back

Build from an identified implementation commit after tests pass. Record that commit alongside the Pages artifact commit in the PR. Update only the reviewed static files. A branch-based update publishes publicly, even if main is unchanged. Roll back by restoring the previous known-good static artifact commit on the deployment branch, then verify the public site again. Do not delete or disable the site without approval.

## Current scope

Teaching baselines only, not measured LLM performance. The adapter is in-process, not a security boundary or production model connector. Real model execution would require a separately designed runtime, secrets handling, limits and cost approval.

Current provider documentation:
- https://docs.github.com/en/pages/getting-started-with-github-pages/about-github-pages
- https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site
