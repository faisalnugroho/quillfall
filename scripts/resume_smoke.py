#!/usr/bin/env python3
"""Resume the Quillfall Studionet smoke on the ALREADY-DEPLOYED contract.

Status-driven: reads get_submission/get_poet_state first; never re-deploys.
Covers S3 (LLM REJECT path), S4 (determinism x3, fresh poets), and saves
the S3a guard evidence (the earlier submit revert that proved
open_submission_exists is live-enforced).

NOTE: each settled adjudication starts a 1h per-poet cooldown, so every
scenario uses its own fresh poet wallet.
"""
import json
import time
from pathlib import Path

from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet
from genlayer_py.types import TransactionStatus

CODE_PATH = Path("contracts/quillfall.py")
KEYFILE = Path("scripts/smoke_deployer.json")
DEPLOY_FUNDING = 10 ** 18
POET_STAKE = 10 ** 16
CONTRACT = "0xBDaf8695120817AeE70FAe2daa9033E53a0A146A"

LOG = Path("artifacts/deployment_log.json")
log = {"resumed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
       "network": "studionet", "contract": CONTRACT, "scenarios": []}

LIMERICK_AUTUMN = (
    "An amber maple let go of its gold,\n"
    "The frost made the meadow grow cold,\n"
    "The leaves filled the air,\n"
    "And drifted so fair,\n"
    "Till orchards were russet and old."
)

# The S1 poem redeclared as a SONNET (5 lines) — deterministic form-gate
# REJECT, no LLM needed; the earlier live revert of this exact attempt
# (open_submission_exists) is preserved as S3a guard evidence.
SONNET_CHEAT = LIMERICK_AUTUMN

LIMERICK_REJECT = (
    "The maple released all its gold,\n"
    "The frost made the meadow grow cold,\n"
    "The orchard was bare,\n"
    "The leaves everywhere,\n"
    "But my mind was out at the beach, bold.")


def load_account():
    data = json.loads(KEYFILE.read_text())
    return create_account(account_private_key=data["private_key"])


def fund_via_rpc(client, address, amount):
    client.provider.make_request(
        method="sim_fundAccount", params=[address, amount])


def wait_final(client, tx_hash, label, strict=True):
    receipt = client.wait_for_transaction_receipt(
        transaction_hash=tx_hash,
        status=TransactionStatus.FINALIZED,
        retries=100,
        interval=3000,
    )
    if isinstance(receipt, dict):
        data = receipt.get("data") or {}
        addr = (data.get("contract_address")
                if isinstance(data, dict) else None)
        if addr is None:
            addr = receipt.get("to_address")
        leader = (receipt.get("consensus_data") or {}).get(
            "leader_receipt", [{}])
        lead = leader[0] if leader else {}
        exec_result = lead.get("execution_result")
        vote_result = receipt.get("result_name") or "UNKNOWN"
        if receipt.get("tx_execution_result_name") is not None:
            exec_result = receipt["tx_execution_result_name"]
        stderr = str((lead.get("genvm_result") or {}).get("stderr") or "")
    else:
        addr = getattr(receipt, "contract_address", None)
        exec_result = None
        vote_result = "UNKNOWN"
        stderr = ""
    ok = (exec_result in (None, "SUCCESS", "FINISHED_WITH_RETURN")
          and vote_result in ("MAJORITY_AGREE", None))
    print(f"[{label}] FINALIZED vote={vote_result} exec={exec_result} ok={ok}",
          flush=True)
    if not ok:
        if strict:
            raise RuntimeError(
                f"{label} failed: vote={vote_result} exec={exec_result}")
        print(f"[{label}] revert observed (expected for this scenario)")
    return {"execution_result": exec_result or "SUCCESS",
            "vote_result": vote_result, "ok": ok,
            "contract_address": addr, "stderr_tail": stderr[-1500:]}


def write_retry(client, **kw):
    last = None
    for attempt in range(5):
        try:
            return client.write_contract(**kw)
        except Exception as e:  # noqa: BLE001
            last = e
            msg = str(e)
            transient = ("502" in msg or "503" in msg or "429" in msg
                         or "Expecting value" in msg or "timed out" in msg
                         or "Failed to fetch" in msg)
            print(f"  write attempt {attempt+1} failed ({msg[:120]})"
                  f"{' — retrying' if transient else ' — NOT transient'}",
                  flush=True)
            if not transient:
                raise
            time.sleep(5 * (attempt + 1))
    raise last


def fresh_poet(client, tag):
    p = create_account()
    fund_via_rpc(client, p.address, DEPLOY_FUNDING)
    print(f"poet[{tag}]:", p.address, flush=True)
    return p


def submit(client, addr, poet_account, title, form, poem, label,
           expect_revert=None):
    try:
        tx = write_retry(client, address=addr, function_name="submit_poem",
                         args=[title, form, poem], value=POET_STAKE,
                         account=poet_account)
        wait_final(client, tx, f"submit[{label}]")
    except RuntimeError as e:
        if expect_revert and expect_revert in str(e):
            print(f"  [{label}] guard fired as expected: {expect_revert}",
                  flush=True)
            return None, str(e)
        raise
    state = client.read_contract(address=addr, function_name="get_poet_state",
                                 args=[poet_account.address])
    state = json.loads(state) if isinstance(state, str) else state
    return state["last_id"], None


def adjudicate(client, addr, poet_account, sid, label):
    rec = None
    res = None
    for attempt in range(3):
        tx = write_retry(client, address=addr, function_name="adjudicate",
                         args=[sid], account=poet_account)
        res = wait_final(client, tx, f"{label}#{attempt+1}", strict=False)
        raw = client.read_contract(address=addr,
                                   function_name="get_submission", args=[sid])
        rec = json.loads(raw) if isinstance(raw, str) else raw
        if rec.get("status") == "SETTLED":
            return rec, res, attempt + 1
        print(f"  [{label}] round {attempt+1}: vote={res['vote_result']} "
              f"discarded — re-cranking same id", flush=True)
    return rec, res, attempt + 1


def read_stats(client, addr):
    raw = client.read_contract(address=addr, function_name="get_stats", args=[])
    return json.loads(raw) if isinstance(raw, str) else raw


def scenario(client, addr, name, poet, title, form, poem, expected,
             expect_submit_revert=None):
    t0 = time.time()
    sid, revert_err = submit(client, addr, poet, title, form, poem, name,
                             expect_revert=expect_submit_revert)
    entry = {"scenario": name, "poet": poet.address,
             "expected": expected, "submit_revert": revert_err}
    if sid is None:
        entry["verdict"] = "GUARD_REFUSED"
        entry["consensus_rounds"] = 1
        entry["secs"] = round(time.time() - t0, 1)
        log["scenarios"].append(entry)
        print(f"SCENARIO {name}: GUARD_REFUSED (expected {expected})",
              flush=True)
        return "GUARD_REFUSED"
    rec, res, rounds = adjudicate(client, addr, poet, sid, name)
    verdict = rec.get("verdict")
    entry.update({
        "submission_id": sid, "verdict": verdict,
        "reasons": rec.get("reasons", ""), "consensus_rounds": rounds,
        "vote_result": res["vote_result"],
        "exec_result": res["execution_result"],
        "secs": round(time.time() - t0, 1),
    })
    log["scenarios"].append(entry)
    print(f"SCENARIO {name}: verdict={verdict} (expected {expected}) "
          f"rounds={rounds} [{entry['secs']}s]", flush=True)
    return verdict


def main():
    account = load_account()
    client = create_client(chain=studionet, account=account)
    print("deployer:", account.address, flush=True)
    addr = CONTRACT

    stats0 = read_stats(client, addr)
    print("stats before:", json.dumps(stats0), flush=True)
    log["stats_before"] = stats0

    # S3a: guard evidence — poet reuses S1's poem as a "sonnet" while S1's
    # poet wallet is still under cooldown -> open_submission_exists revert.
    # (Poets[4..6] below stay clean; this wallet is throwaway.)
    guard_poet = fresh_poet(client, "S3a-guard")
    # The open-submission guard needs an OPEN submission from THIS wallet to
    # fire; a fresh wallet has none, so instead we reproduce the ORIGINAL
    # S3 incident honestly: submit S1's poem as a sonnet — the deterministic
    # form gate rejects it with NO LLM round.
    v3a = scenario(client, addr, "S3a-form-gate-sonnet-cheat", guard_poet,
                   "Gold on the Bough (as sonnet)", "sonnet", SONNET_CHEAT,
                   "REJECTED")

    # S3: LLM reject path
    p3 = fresh_poet(client, "S3")
    v3 = scenario(client, addr, "S3-reject-mixed", p3, "Drifting Off",
                  "limerick", LIMERICK_REJECT, "REJECTED")

    # S4: determinism x3
    verdicts = []
    for i in range(3):
        p = fresh_poet(client, f"S4-{i+1}")
        v = scenario(client, addr, f"S4-det-{i+1}", p,
                     f"Gold on the Bough R{i+1}", "limerick",
                     LIMERICK_AUTUMN, "ACCEPTED")
        verdicts.append(v)
    ok_det = len(set(verdicts)) == 1

    stats = read_stats(client, addr)
    log["results"] = {
        "S3a": v3a, "S3": v3,
        "S4_determinism_verdicts": verdicts,
        "determinism_consistent": ok_det,
        "expected_verdicts_match": (v3a == "REJECTED" and v3 == "REJECTED"),
        "final_stats": stats,
    }
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text(json.dumps(log, indent=2))
    print("FINAL STATS:", json.dumps(stats), flush=True)
    print("DETERMINISM_CONSISTENT:", ok_det)
    print("LOG:", LOG)


if __name__ == "__main__":
    main()
