#!/usr/bin/env python3
"""Rebuild artifacts/deployment_log.json from chain-authoritative reads.

The resume smoke died before writing its log; all evidence lives on-chain.
Enumerates the 7 submissions via known poet wallets, reads each record,
records contract source hash, and writes the evidence log.
"""
import hashlib
import json
from pathlib import Path

from genlayer_py import create_client, create_account
from genlayer_py.chains import studionet

KEYFILE = Path("scripts/smoke_deployer.json")
CONTRACT = "0xBDaf8695120817AeE70FAe2daa9033E53a0A146A"
DEPLOY_TX = "0x2f18b258e873b4740d287d7df88050b303fae474ff33abb0b864192969e7335c"
LOG = Path("artifacts/deployment_log.json")

# Poet wallets per scenario (from session transcripts; q6 poet wallet from
# the interrupted first S3r run is unknown — its record is included via the
# chain stats and the anthology).
POETS = {
    "S3a-form-gate-sonnet-cheat": "0x98f084161b4D28D9AC655173196FF3E78e4b57AA",
    "S3-reject-mixed": "0x9A0CA6aAf73e266F38aFe93Db5B414588101772a",
    "S4-det-1": "0x12C228DEe89ED6a96788c062547b554368c957D1",
    "S3r-reject-winter-dominant": "0x1e16c5d00914E5Dc05365F110A82E5413feC58F7",
    "S4-det-2-recovered": "0x420aB6C1f4Fb953ABD47B3403e2BbFfEFCBc338c",
}

# Fetched by submission id, not poet: the tutorial-video poet was an
# in-browser burner whose full address is unrecoverable (wallet chips show
# only a 6-hex prefix; the recording browser session is gone). The id is
# plainly legible in the recorded verdict card.
DIRECT_IDS = {
    "video-tutorial-accept": "q11-DC94Ba-1791274346",
}


def main():
    data = json.loads(KEYFILE.read_text())
    acct = create_account(account_private_key=data["private_key"])
    client = create_client(chain=studionet, account=acct)

    src = Path("contracts/quillfall.py").read_bytes()
    code_sha = hashlib.sha256(src).hexdigest()

    scenarios = []
    seen_ids = set()
    for name, poet in POETS.items():
        raw = client.read_contract(address=CONTRACT,
                                   function_name="get_poet_state",
                                   args=[poet])
        st = json.loads(raw) if isinstance(raw, str) else raw
        sid = st.get("last_id")
        if not sid or sid in seen_ids:
            continue
        seen_ids.add(sid)
        sraw = client.read_contract(address=CONTRACT,
                                    function_name="get_submission", args=[sid])
        rec = json.loads(sraw) if isinstance(sraw, str) else sraw
        scenarios.append({"scenario": name, "poet": poet,
                          "submission_id": sid, "record": rec})
        print(name, sid, rec.get("verdict"), rec.get("reasons"), flush=True)

    for name, sid in DIRECT_IDS.items():
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        sraw = client.read_contract(address=CONTRACT,
                                    function_name="get_submission", args=[sid])
        rec = json.loads(sraw) if isinstance(sraw, str) else sraw
        scenarios.append({"scenario": name, "poet": None,
                          "submission_id": sid, "record": rec})
        print(name, sid, rec.get("verdict"), rec.get("reasons"), flush=True)

    stats = json.loads(client.read_contract(address=CONTRACT,
                                            function_name="get_stats", args=[]))
    log = {
        "network": "studionet",
        "contract": CONTRACT,
        "deploy_tx": DEPLOY_TX,
        "code_sha256": code_sha,
        "note": ("Reconstructed from chain-authoritative reads after the "
                 "smoke runner died before flushing its log. Verdicts are "
                 "read back from get_submission; the explorer shows every "
                 "transaction at the contract address."),
        "scenarios": scenarios,
        "final_stats": stats,
    }
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text(json.dumps(log, indent=2))
    print("wrote", LOG, "with", len(scenarios), "scenarios; stats:", stats)


if __name__ == "__main__":
    main()
