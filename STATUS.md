# Distribution status

## Verification ledger

This distribution has no articles, revenue baseline, connected analytics, browser session or live publication authorization. Follow README for reproducible local checks. Test reports describe local behavior, not production readiness for a new account.

Verified on macOS with Python 3.11:

- 761 tests passed, including private setup, wrong-blog rejection, explicit model-call approval, staged-content privacy checks and safe failure during setup.
- Basedpyright: zero errors, warnings or notes with the optional browser dependencies available.
- Contract validation: 18 contracts and 12 runtime contracts passed.
- Offline review package: REVIEW_REQUIRED, external_write_count=0.
- Interactive setup smoke: private file permissions, dry-run defaults, STOP installation and repeated-setup refusal passed.
- Skill frontmatter and interface YAML parsed successfully with Ruby YAML. The skill-creator Python validator could not run because PyYAML was unavailable.
- Release content scan, including operator-supplied private terms: zero findings. This does not certify Git history or hosting metadata.

Live accounts, paid model generation, Chrome delivery and publication were not exercised for this release. The distribution workflow runs tests, type checking, privacy scanning, contracts and the offline demo; a hosted CI result is not yet available.
