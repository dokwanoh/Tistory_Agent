---
name: tistory-onboarding
description: Set up a fresh Tistory Agent checkout through a short Korean interview and private local configuration. Use for first-run setup or onboarding, not article publication or account changes.
---

# Tistory first-run setup

Read the repository README and `docs/ONBOARDING.md`. Inspect Python availability and `.local/profile.json` existence without printing existing private values. Do not require a model, browser login or API key for the offline demo.

Ask one short question at a time, skip answers already supplied, and offer the documented defaults. Group the interview into five decisions:

1. Tistory blog URL. Ask for the public `https://<blog-id>.tistory.com` origin only, not credentials. If the user only has a custom domain, explain that this adapter needs the underlying Tistory address; do not guess it.
2. Topic scope: select from 금융/보험, 법률, 부동산, IT/소프트웨어. Do not inherit another owner's editorial identity or results.
3. Reader and tone: default 일반 독자 / 친절한 설명체. Do not ask for a legal name, private email, employer or personal history.
4. Model: inspect models available in the user's actual harness; ask for a selection or leave empty for offline-only work. Do not select an expensive model or start a paid evaluation automatically.
5. Desired weekly cadence and monthly KRW cost ceiling. Default both to zero. These are planning preferences, not schedule creation, live-publication consent or provider-enforced spending limits.

Show the compact setting summary, then write it with the repository's `Profile` and `save_profile` API or guide the user through `python -m tistory_growth_os.onboarding`. Use Python values, not a shell command interpolating untrusted answers. `save_profile` validates the URL/topics, creates private `.local/profile.json`, refuses overwrites and installs the native publisher STOP file. Keep unknown model empty; do not fill fictional credentials.

If settings already exist, ask whether the user wants to review a particular setting; do not overwrite or reset them. Setup never logs in, uploads, posts, modifies ads, creates automations, removes STOP or writes shared/global agent settings.

Finish by running `validate-contracts` and the documented offline `prepare-review` demo. Report the actual result as an inspection-only local draft, not a published article. Tell the user where private settings and draft outputs live. Explain that live delivery needs current platform-policy checks, their own login, exact-package independent review and fresh scoped approval. A blocked optional integration does not block the offline demo.
