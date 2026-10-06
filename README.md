# Quillfall — The Autumn Anthology

An on-chain poetry anthology for GenLayer where acceptance into the permanent
autumn collection is adjudicated by neutral AI-validator consensus.

A poet stakes 0.01 GEN and submits a poem in a declared form (limerick,
quatrain, sonnet). Independent judges (leader + validating LLMs) return
per-criterion labels — FORM_OK and SEASON_OK — and the CONTRACT derives the
verdict; the model never picks the outcome:

- **ACCEPTED** — all PASS → poem sealed into the on-chain anthology, stake returned
- **REJECTED** — any FAIL → stake burned to the anthology treasury
- **INCONCLUSIVE** — any UNCERTAIN / unparsable judge output → fail-safe, stake refunded

## Why this is a real Intelligent Contract

- The LLM does judgment a plain contract cannot: does this text read as the
  declared form? Is the imagery autumn's throughout?
- Deterministic gates clamp the model: line counts, orthographic end-rhyme
  checks and syllable-band meters are verified in pure Python inside the
  contract; a fooled or hallucinating model cannot upgrade a FAIL, and an
  off-season poem cannot PASS.
- Every LLM failure mode (exception, non-JSON, malformed shape, off-domain
  labels) maps to a well-formed INCONCLUSIVE that never moves money.
- Money moves only in the deterministic settlement layer via
  `emit_transfer(on="finalized")` after checks-effects-interactions
  bookkeeping.
- Evidence (the poem) is embedded in the transaction — public and identical
  for every validator; no egress risk in consensus.
- Anti-spam: one open submission per poet + resubmission cooldown.

## Repo layout

    contracts/quillfall.py        the Intelligent Contract
    tests/direct/                 42 gltest direct-mode tests (pytest)
    scripts/deploy_smoke_studionet.py  deploy + live consensus smoke
    artifacts/deployment_log.json      live evidence log (tx hashes, verdicts)
    frontend/                     autumn-themed dApp (GitHub Pages)

## Live deployment (Studionet)

Contract: https://explorer-studio.genlayer.com/address/0xBDaf8695120817AeE70FAe2daa9033E53a0A146A

dApp: https://faisalnugroho.github.io/quillfall/

## Tests

    ~/genlayer-env/bin/python -m pytest tests/direct/ -q -p no:cacheprovider

42/42 passing. genvm-lint: 3/3 checks + validation passed.

## Known limitations

- The rhyme/meter checks are orthographic/heuristic (shared by all
  validators, so consensus-stable) — slant rhymes and elisions may disagree
  with a human scansion; the judges' models see the declared-form standards
  in the prompt and can override with FAIL/UNCERTAIN, never with PASS.
- Studionet only; the treasury "burn" is a balance accounting on a testnet
  contract, no real value at risk.
- `gl.message_raw["datetime"]`-based cooldown uses node-assigned time (fine
  for anti-spam; not a precision clock).
- The dApp lists anthology stats and the latest verdict; full per-entry
  enumeration lives on the explorer (client-side key enumeration is not
  exposed by the SDK).
