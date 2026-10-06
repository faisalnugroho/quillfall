#!/usr/bin/env python3
"""S3-retry: prove the LLM-label REJECT path with an unambiguous
winter-dominant limerick that still passes the deterministic gates
(2 autumn words vs 2 off-season words -> gate PASS by design), giving
the judges an HONEST reason to FAIL SEASON_OK.

The first S3 attempt (mixed autumn/beach daydream) was ACCEPTED by live
consensus — documented honestly in the deployment log. This retry uses
a poem where winter imagery dominates.
"""
import json
import time
from pathlib import Path

from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet
from genlayer_py.types import TransactionStatus

KEYFILE = Path("scripts/smoke_deployer.json")
CONTRACT = "0xBDaf8695120817AeE70FAe2daa9033E53a0A146A"
LOG = Path("artifacts/deployment_log.json")
DEPLOY_FUNDING = 10 ** 18
POET_STAKE = 10 ** 16

# Winter-dominant limerick; orthographic rhymes snow/blow/know (ow),
# drifts/lifts (fts). Syllables 8/8/4/5/8 (bands A 7-11, B 4-7).
# Gate math: autumn_hits = {amber, leaf} = 2; off_hits = {snow, winter} = 2;
# off > autumn is False -> deterministic season gate PASSES; the LLM judges.
LIMERICK_WINTER = (
    "The maples stand bare in the snow,\n"
    "The north wind is starting to blow,\n"
    "One amber leaf drifts,\n"
    "The winter air lifts,\n"
    "Across ponds where the skaters know."
)


def load_account():
    data = json.loads(KEYFILE.read_text())
    return create_account(account_private_key=data["private_key"])


def fund_via_rpc(client, address, amount):
    client.provider.make_request(
        method="sim_fundAccount", params=[address, amount])


def wait_final(client, tx_hash, label, strict=True):
    receipt = client.wait_for_transaction_receipt(
        transaction_hash=tx_hash, status=TransactionStatus.FINALIZED,
        retries=100, interval=3000)
    if isinstance(receipt, dict):
        leader = (receipt.get("consensus_data") or {}).get(
            "leader_receipt", [{}])
        lead = leader[0] if leader else {}
        exec_result = lead.get("execution_result")
        vote_result = receipt.get("result_name") or "UNKNOWN"
        if receipt.get("tx_execution_result_name") is not None:
            exec_result = receipt["tx_execution_result_name"]
        stderr = str((lead.get("genvm_result") or {}).get("stderr") or "")
    else:
        exec_result, vote_result, stderr = None, "UNKNOWN", ""
    ok = (exec_result in (None, "SUCCESS", "FINISHED_WITH_RETURN")
          and vote_result in ("MAJORITY_AGREE", None))
    print(f"[{label}] FINALIZED vote={vote_result} exec={exec_result} ok={ok}",
          flush=True)
    if not ok and strict:
        raise RuntimeError(f"{label} failed: vote={vote_result} "
                           f"exec={exec_result} stderr={stderr[-800:]}")
    return {"exec_result": exec_result, "vote_result": vote_result, "ok": ok}


def write_retry(client, **kw):
    last = None
    for attempt in range(5):
        try:
            return client.write_contract(**kw)
        except Exception as e:  # noqa: BLE001
            last = e
            msg = str(e)
            if not ("502" in msg or "503" in msg or "429" in msg
                    or "Expecting value" in msg or "timed out" in msg):
                raise
            print(f"  write attempt {attempt+1}: {msg[:100]} — retry",
                  flush=True)
            time.sleep(5 * (attempt + 1))
    raise last


def main():
    account = load_account()
    client = create_client(chain=studionet, account=account)
    poet = create_account()
    fund_via_rpc(client, poet.address, DEPLOY_FUNDING)
    print("poet[S3r]:", poet.address, flush=True)
    addr = CONTRACT

    tx = write_retry(client, address=addr, function_name="submit_poem",
                     args=["The Last Leaf", "limerick", LIMERICK_WINTER],
                     value=POET_STAKE, account=poet)
    wait_final(client, tx, "submit[S3r]")
    state = client.read_contract(address=addr, function_name="get_poet_state",
                                 args=[poet.address])
    sid = json.loads(state)["last_id"]
    print("sid:", sid, flush=True)

    rec = None
    rounds = 0
    for attempt in range(3):
        tx = write_retry(client, address=addr, function_name="adjudicate",
                         args=[sid], account=poet)
        wait_final(client, tx, f"S3r#{attempt+1}", strict=False)
        raw = client.read_contract(address=addr,
                                   function_name="get_submission", args=[sid])
        rec = json.loads(raw) if isinstance(raw, str) else raw
        rounds = attempt + 1
        if rec.get("status") == "SETTLED":
            break
        print(f"  round {attempt+1} discarded — re-cranking", flush=True)

    verdict = rec.get("verdict")
    print(f"S3r verdict={verdict} reasons={rec.get('reasons')} "
          f"rounds={rounds}", flush=True)
    entry = {
        "scenario": "S3r-reject-winter-dominant", "poet": poet.address,
        "submission_id": sid, "expected": "REJECTED", "verdict": verdict,
        "reasons": rec.get("reasons", ""), "consensus_rounds": rounds,
        "note": ("First S3 attempt (mixed autumn/beach) was ACCEPTED by live "
                 "consensus — judges read it as autumn-dominant. This retry "
                 "uses a winter-dominant poem that still passes the "
                 "deterministic gates by design (2 vs 2 lexicon hits)."),
    }
    LOG.write_text(json.dumps(
        json.loads(LOG.read_text()) | {"s3r_retry": entry,
        "stats_after_s3r": json.loads(client.read_contract(
            address=addr, function_name="get_stats", args=[]))}, indent=2))
    print("log updated:", LOG)


if __name__ == "__main__":
    main()
