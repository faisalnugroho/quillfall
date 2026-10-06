# Quillfall — Submission Draft (for the Builder Portal)

The owner pastes/attaches these fields manually. Nothing here claims
steward acceptance; every claim is evidence-backed.

## Category
Builder → Projects (Intelligent Contract)

## Title
Quillfall — The Autumn Anthology

## One-liner
An on-chain poetry anthology for autumn: poets stake GEN on a poem,
independent AI validators judge its form and season imagery, and the
contract — not the model — derives the verdict from per-criterion
labels. ACCEPTED seals the verse into the anthology; REJECTED burns
the stake to the treasury.

## Full description
Quillfall is a GenLayer Intelligent Contract that runs a poetry
adjudication for the autumn season. A poet submits a title, a form
(limerick / quatrain / sonnet) and the poem text with a 0.01 GEN
stake. The contract first applies fully deterministic gates on-chain:
syllable counts per form, orthographic rhyme schemes, word-count and
season-lexicon balance. Only if the deterministic gates pass do the
LLM validators judge the two human criteria — SEASON_OK (is the
imagery genuinely autumn?) and POETIC_OK (does it read as intentional
poetry, not spam?).

Why GenLayer is necessary: judging literary form and imagery is
exactly the non-deterministic work a normal smart contract cannot do,
while custody of stakes and sealing of the anthology must remain
deterministic and trustless. Quillfall draws the line cleanly — the
LLM never moves funds and never writes the verdict. Each validator
returns only two boolean labels per criterion; the contract's
Equivalence Principle compares the labels, and a pure on-chain
function derives ACCEPTED / REJECTED / INCONCLUSIVE from them.

Every failure path is a designed, tested state: a poem that fails the
deterministic gates is REJECTED without spending an LLM round; mixed
or unparsable validator labels collapse to INCONCLUSIVE with a
fail-safe stake refund; a REJECTED stake is burned to the anthology
treasury; each settled adjudication starts a per-poet cooldown, and
the open-submission guard prevents double-entry.

Deliverables: 42-test gltest suite (deterministic gates, consensus
simulations, security/adversarial cases), live Studionet deployment
with a multi-scenario smoke (positive, deterministic form-gate cheat
REJECTED live with no LLM round, LLM-label REJECTED live via a
winter-dominant limerick, 3x determinism on the same poem via fresh
poets, consensus-round discard recovered), GitHub Pages dApp with
real burner wallets, faucet, live tx states and verdict rendering,
and a chain-authoritative evidence log.

## Links
- Repo: https://github.com/faisalnugroho/quillfall
- Live explorer (contract):
  https://explorer-studio.genlayer.com/address/0xBDaf8695120817AeE70FAe2daa9033E53a0A146A
- dApp: https://faisalnugroho.github.io/quillfall/
- Video tutorial (<=30s): attached
- Evidence: docs/EVIDENCE.md + docs/deployment_log.json in the repo

## Key evidence (Studionet, chain-authoritative)
- Deploy (MAJORITY_AGREE): contract
  `0xBDaf8695120817AeE70FAe2daa9033E53a0A146A`, deploy tx
  `0x2f18b258e873b4740d287d7df88050b303fae474ff33abb0b864192969e7335c`,
  code sha256 `3c840bd32c983cd7a9d278f55996bb2775f725049261e6faca09e6e26dd3f3ca`
- S1 limerick ACCEPTED, S2 sonnet ACCEPTED (initial smoke)
- S3a form-gate cheat — S1's poem redeclared as a "sonnet": REJECTED
  live, `form_gate_fail:sonnet`, zero LLM rounds (deterministic gate)
- S3-mixed limerick (autumn + beach daydream): ACCEPTED by live
  consensus — an honest judge decision, documented as-is
- S3r winter-dominant limerick (passes deterministic gates by design,
  2-vs-2 lexicon hits): REJECTED live, `season_fail`, after one
  MAJORITY_DISAGREE round was discarded and the adjudication
  re-cranked — proving both the LLM-label REJECT path and the
  consensus-round discard behavior in one tx sequence
- S4 determinism: the same autumn limerick submitted by 3 fresh poets
  (S4-1/2/3) — all ACCEPTED with identical per-criterion labels
- S3r' (second session, same winter poem): REJECTED again — the
  REJECT path reproduced across sessions
- Final stats (get_stats): total=11, accepted=8, rejected=3,
  inconclusive=0, treasury=0.03 GEN (3 burned stakes), anthology=8

## Honest scope notes
- Literary judgment is subjective; the contract proves *process*
  integrity (who judged, what labels, what was derived), not taste.
- The deterministic gates are orthographic/lexical heuristics tuned
  for English; they are a cheap pre-filter, not a grammar authority.
- Studionet deployment — Bradbury/mainnet is future work the owner
  may choose.
- The consensus model is the network's configured validator set; all
  verdicts quoted above were read back from the deployed contract.
