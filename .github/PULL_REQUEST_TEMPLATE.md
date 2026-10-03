## What and why

<!-- One logical change. Link issues if any. -->

## How was it tested?

- [ ] `scripts/check.sh` passes (format, lint, mypy --strict, tests)
- [ ] New behaviour has a positive test **and** a "must stay quiet" test
- [ ] Backend changes: parity test still passes
- [ ] Statistical change: assumptions/limitations documented; experiments rerun if relevant
- [ ] Findings use the right evidence label; nothing is normalised or coerced silently
- [ ] No network calls, no LLMs
- [ ] `CHANGELOG.md` updated under *Unreleased*
