#!/usr/bin/env python3
"""Deploy Quillfall to Studionet + live consensus smoke test.

Scenarios (all judged by LIVE LLM consensus on studionet):
  S1 accept-limerick   : autumn limerick  -> ACCEPTED  (anthology seal)
  S2 accept-sonnet     : autumn sonnet    -> ACCEPTED  (fresh id)
  S3 reject-llm-label  : autumn limerick whose language pushes the model to
                         FAIL the form (limerick with prose-y long lines
                         AND a forced off-season final line) -> REJECTED
  S4 determinism       : S1 poem re-submitted by a 2nd fresh wallet x3 runs,
                         verdicts must agree

Built from the KNOWN-GOOD deploy_smoke_studionet template. wait_final
gates on BOTH consensus vote (MAJORITY_AGREE) and leader execution.
"""
import json
import time
from pathlib import Path

from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet
from genlayer_py.types import TransactionStatus

# ---------------- CONFIG ----------------
CODE_PATH = Path("contracts/quillfall.py")
KEYFILE = Path("scripts/smoke_deployer.json")   # gitignored
DEPLOY_FUNDING = 10 ** 18
POET_STAKE = 10 ** 16                            # 0.01 GEN
# ----------------------------------------

LOG = Path("artifacts/deployment_log.json")
log = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
       "network": "studionet", "scenarios": []}

LIMERICK_AUTUMN = (
    "An amber maple let go of its gold,\n"
    "The frost made the meadow grow cold,\n"
    "The leaves filled the air,\n"
    "And drifted so fair,\n"
    "Till orchards were russet and old."
)

SONNET_AUTUMN = (
    "The orchard bends with apples row on row,\n"
    "The cider press drips sweet beneath the tree,\n"
    "The maple sheds its amber down below,\n"
    "And geese are calling low across the lea.\n"
    "The bonfire smokes against the fading light,\n"
    "The harvest moon is climbing pale and high,\n"
    "The acorns drop when owls are out at night,\n"
    "The frost has etched its lace on every rye.\n"
    "The wheat is sheaved, the stubble fields are brown,\n"
    "The chestnuts split inside their prickled shell,\n"
    "The wind strips every bough before the town,\n"
    "The smoke of hearths is rising where we dwell.\n"
    "So autumn writes its ledger on the land,\n"
    "And seals the year with one enchanted hand."
)


def load_account():
    data = json.loads(KEYFILE.read_text())
    return create_account(account_private_key=data["private_key"])


def fund_via_rpc(client, address, amount):
    """client.fund_account is localnet-only — studionet needs a raw
    sim_fundAccount request (verified live)."""
    client.provider.make_request(
        method="sim_fundAccount", params=[address, amount])


def wait_final(client, tx_hash, label, strict=True):
    """FINALIZED wait gating on BOTH consensus vote and leader execution.

    `result_name` is the consensus VOTE, never the exec result. On a
    DISAGREE/NO_MAJORITY round the state change is DISCARDED (record stays
    PENDING) — strict=False lets the caller re-crank the SAME submission.
    """
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
        print("CONSENSUS/EXECUTION DETAIL (first 2000 chars):")
        print(json.dumps(receipt.get("consensus_data"), default=str)[:2000])
        if stderr:
            print("STDERR tail:", stderr[-1500:])
        if strict:
            raise RuntimeError(
                f"{label} failed: vote={vote_result} exec={exec_result}")
        print(f"[{label}] state change discarded — will re-crank")
    return {"execution_result": exec_result or "SUCCESS",
            "vote_result": vote_result, "ok": ok,
            "contract_address": addr, "stderr_tail": stderr[-1500:]}


def write_retry(client, **kw):
    """SDK-call retry for studionet 502/503/429 flakes (LicenseLoom
    pattern). The tx may or may not have landed on a transient failure —
    the caller's status-driven guards handle double-land cases."""
    import time as _t
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
            _t.sleep(5 * (attempt + 1))
    raise last


def submit(client, addr, poet_account, title, form, poem):
    tx = write_retry(client, address=addr, function_name="submit_poem",
                     args=[title, form, poem], value=POET_STAKE,
                     account=poet_account)
    wait_final(client, tx, f"submit[{title}]")
    state = client.read_contract(address=addr, function_name="get_poet_state",
                                 args=[poet_account.address])
    state = json.loads(state) if isinstance(state, str) else state
    return state["last_id"]


def adjudicate(client, addr, poet_account, sid, label):
    for attempt in range(3):
        tx = write_retry(client, address=addr, function_name="adjudicate",
                         args=[sid], account=poet_account)
        res = wait_final(client, tx, f"{label}#{attempt+1}", strict=False)
        rec = client.read_contract(address=addr,
                                   function_name="get_submission", args=[sid])
        rec = json.loads(rec) if isinstance(rec, str) else rec
        if rec.get("status") == "SETTLED":
            return rec, res, attempt + 1
        print(f"  [{label}] round {attempt+1}: vote={res['vote_result']} "
              f"discarded — re-cranking same id", flush=True)
    return rec, res, attempt + 1


def read_stats(client, addr):
    raw = client.read_contract(address=addr, function_name="get_stats", args=[])
    return json.loads(raw) if isinstance(raw, str) else raw


def main():
    account = load_account()
    client = create_client(chain=studionet, account=account)
    print("deployer:", account.address, flush=True)

    code = CODE_PATH.read_text()
    tx = client.deploy_contract(code=code, account=client.local_account,
                                args=[], leader_only=True)
    res = wait_final(client, tx, "deploy")
    addr = res["contract_address"]
    log["deploy"] = {"tx_hash": tx, "address": addr}
    Path("scripts/deployed_studionet.json").write_text(json.dumps(
        {"address": addr, "deploy_tx": tx,
         "deployed_at": log["started_at"]}, indent=2))
    print("CONTRACT:", addr)
    print("explorer: https://explorer-studio.genlayer.com/address/" + addr)

    # Fresh poet wallets for scenario isolation
    poet1 = create_account()
    poet2 = create_account()
    for p in (poet1, poet2):
        fund_via_rpc(client, p.address, DEPLOY_FUNDING)
    print("poet1:", poet1.address)
    print("poet2:", poet2.address)
    log["poets"] = {"poet1": poet1.address, "poet2": poet2.address}

    def scenario(name, poet, title, form, poem, expected):
        t0 = time.time()
        sid = submit(client, addr, poet, title, form, poem)
        rec, res, rounds = adjudicate(client, addr, poet, sid, name)
        verdict = rec.get("verdict")
        secs = round(time.time() - t0, 1)
        entry = {
            "scenario": name, "submission_id": sid, "expected": expected,
            "verdict": verdict, "reasons": rec.get("reasons", ""),
            "consensus_rounds": rounds, "vote_result": res["vote_result"],
            "exec_result": res["execution_result"], "secs": secs,
        }
        log["scenarios"].append(entry)
        print(f"SCENARIO {name}: verdict={verdict} (expected {expected}) "
              f"rounds={rounds} [{secs}s]", flush=True)
        return verdict

    # S1: clean autumn limerick -> ACCEPTED
    v1 = scenario("S1-accept-limerick", poet1, "Gold on the Bough",
                  "limerick", LIMERICK_AUTUMN, "ACCEPTED")

    # S2: clean autumn sonnet, second fresh wallet -> ACCEPTED
    v2 = scenario("S2-accept-sonnet", poet2, "Amber Ledger",
                  "sonnet", SONNET_AUTUMN, "ACCEPTED")

    # S3: form-valid limerick whose final line introduces summer imagery —
    # passes the deterministic gates (4 autumn words vs 1 off-season word)
    # but gives the judge a HONEST reason to FAIL SEASON_OK.
    limerick_reject = (
        "The maple released all its gold,\n"
        "The frost made the meadow grow cold,\n"
        "The orchard was bare,\n"
        "The leaves everywhere,\n"
        "But my mind was out at the beach, bold.")
    v3 = scenario("S3-reject-mixed", poet1, "Drifting Off",
                  "limerick", limerick_reject, "REJECTED")

    # S4: determinism — the S1 poem, fresh wallet, 3 fresh submissions.
    verdicts = []
    for i in range(3):
        v = scenario(f"S4-det-{i+1}", poet2, f"Gold on the Bough R{i+1}",
                     "limerick", LIMERICK_AUTUMN, "ACCEPTED")
        verdicts.append(v)
    ok_det = len(set(verdicts)) == 1

    stats = read_stats(client, addr)
    log["results"] = {
        "S1": v1, "S2": v2, "S3": v3,
        "S4_determinism_verdicts": verdicts,
        "determinism_consistent": ok_det,
        "expected_verdicts_match": (v1 == "ACCEPTED" and v2 == "ACCEPTED"
                                    and v3 == "REJECTED"),
        "final_stats": stats,
    }
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text(json.dumps(log, indent=2))
    print("FINAL STATS:", json.dumps(stats), flush=True)
    print("DETERMINISM_CONSISTENT:", ok_det)
    print("LOG:", LOG)
    print("DONE. contract:", addr)


if __name__ == "__main__":
    main()
