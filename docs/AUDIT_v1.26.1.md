# Stage 4 External Evidence — v1.26.1 Repair Audit

## Scope

This repair addresses the Windows acceptance output supplied for the Stage 4
External Evidence candidate. It does not change the imported-evidence schemas,
deterministic recommendation logic, LLM authority boundary, scenario-matrix
contracts, or production-write policy.

## Defects corrected

1. `src/lpr_cpe_demo/ui/theme_dark.py` contained an unterminated Python string
   where the External Evidence anchor was inserted. The module now compiles and
   renders five explicit cross-links.
2. Stage 4 files had line-length, import-order, unused-import, dictionary-access,
   and redundant-cast Ruff findings. The affected code and tests were normalized.
3. Ruff now classifies both `lpr_cpe_demo` and `scripts` as first-party imports,
   removing an ambiguous import-section result in the release-gate test.
4. The legacy dashboard regression expected four links after Stage 4 added a
   fifth; the assertion now verifies the External Evidence link and a count of five.
5. All analytical panels now share one medium-grey surface contract: `#4B5057`,
   a 14-pixel radius, one border tone, consistent padding and AA-checked text.
6. OpenAI structured-output tests now install an in-process module stub, so the
   provider boundary is exercised without a network call or optional wheel.

## Verification performed in the packaging runtime

- Python compilation of `src`, `scripts`, and `tests`.
- Governed scenario matrix with all nine explicit contracts passing.
- Focused External Evidence and adjacent regression suite: 283 tests passing.
- Manifest verification after regeneration.
- Git object and whitespace checks after commit and clean-clone validation.

The packaging runtime uses Python 3.13 and does not contain the pinned Ruff 0.13.3
binary. The exact Windows Python 3.14.2 Ruff command remains a required acceptance
gate and is not represented as executed here.
