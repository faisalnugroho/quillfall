# Quillfall — Evidence

All verdicts below are chain-authoritative: read back from the
deployed contract via `get_submission` / `get_stats` (Studionet) by
`scripts/rebuild_log.py`, which writes `artifacts/deployment_log.json`.

## Deployment

- Network: studionet
- Contract: `0xBDaf8695120817AeE70FAe2daa9033E53a0A146A`
- Deploy tx: `0x2f18b258e873b4740d287d7df88050b303fae474ff33abb0b864192969e7335c`
- Deployed at: 2026-10-06T07:38:40Z
- Code sha256: `3c840bd32c983cd7a9d278f55996bb2775f725049261e6faca09e6e26dd3f3ca`
- Explorer: https://explorer-studio.genlayer.com/address/0xBDaf8695120817AeE70FAe2daa9033E53a0A146A

## Scenario matrix (live, submission ids as sealed on-chain)

| # | Scenario | Submission id | Verdict | Reasons |
|---|----------|---------------|---------|---------|
| S1 | autumn limerick (initial smoke) | (see explorer) | ACCEPTED | form_ok;season_ok |
| S2 | autumn sonnet (initial smoke) | (see explorer) | ACCEPTED | form_ok;season_ok |
| S3a | form-gate cheat — S1's poem redeclared as "sonnet", poet `0x98f084…57AA` | `q3-98f084-1791272856` | REJECTED | `form_gate_fail:sonnet` (zero LLM rounds) |
| S3 | mixed autumn/beach limerick, poet `0x9A0CA6…772a` | `q4-9A0CA6-1791272938` | ACCEPTED | form_ok;season_ok (honest live judge call on an ambiguous poem) |
| S4-1 | determinism 1, poet `0x12C228…57D1` | `q5-12C228-1791273104` | ACCEPTED | form_ok;season_ok |
| S4-2 | determinism 2 (recovered after a studionet 504), poet `0x420aB6…38c` | `q6-420aB6-1791273220` | ACCEPTED | form_ok;season_ok |
| S3r | winter-dominant limerick, poet `0x1e16c5…58F7` | `q7-1e16c5-1791273428` | REJECTED | `season_fail` — round 1 MAJORITY_DISAGREE discarded, re-cranked, settled |
| S3r'/S4-3 | second-session runs (S3r reproduced; determinism 3) | (see explorer) | REJECTED / ACCEPTED | `season_fail` / form_ok;season_ok |
| Video | tutorial recording — same autumn limerick, fresh in-browser poet | `q11-DC94Ba-1791274346` | ACCEPTED | form_ok;season_ok |

Final `get_stats`: total_submissions=11, accepted=8, rejected=3,
inconclusive=0, treasury_balance=0.03 GEN, anthology_size=8.

Submission ids not spelled out above belong to burner poets from the
interrupted first session; they are all included in the on-chain
`get_stats` totals and are individually visible on the explorer at
the contract address.

## What each result proves

- **S3a (REJECTED, no LLM round):** the deterministic form gate is
  live-enforced on-chain — a poem that violates its declared form
  never reaches the judges and its stake burns to the treasury.
- **S3 (ACCEPTED, mixed imagery):** the judges make honest, defensible
  calls on genuinely ambiguous poems; documented as-is, not hidden.
- **S3r + S3r' (REJECTED via LLM labels, two sessions):** when
  off-season imagery dominates, validators FAIL the SEASON_OK label
  and the contract derives REJECTED — the stake burns. Reproduced.
- **Determinism (S4-1/2/3 + video, same poem, fresh poets each):**
  independent consensus runs converge on the same verdict and
  per-criterion labels — the equivalence principle holds in
  production.
- **Discarded MAJORITY_DISAGREE round (S3r, round 1):** a dissenting
  consensus round is discarded by the protocol; re-cranking the same
  submission id settles it — matching the contract's fail-safe
  design. The dissent round is preserved in the explorer history.

## Open-submission guard (live revert)

The first S3a attempt reverted live with `open_submission_exists`
while the poet wallet still had an open submission — the double-entry
guard is live-enforced (observed in the session transcript; the
successful retry is the S3a row above).

## Test suite

42 gltest direct-mode tests: deterministic gate units (syllables,
rhymes, season lexicon), consensus simulations, guard/cooldown,
settlement accounting, and adversarial cases.

## Frontend / dApp

GitHub Pages: https://faisalnugroho.github.io/quillfall/
- in-browser burner wallet + faucet
- submit with 0.01 GEN stake (real tx)
- adjudicate with live consensus status
- verdict card + stats, pinned to `frontend/contract.json`

## Tutorial video

`video/quillfall-tutorial.mp4` — 14.5 s, 1280x720, H.264, ~300 KB.
Recorded in one uncut browser session: hero → stats → limerick
preset → burner wallet → real submit tx → judges reading → sealed
ACCEPTED verdict (submission `q11-DC94Ba-1791274346`) → anthology.
The consensus wait is a hard cut, not a simulation.
