#!/usr/bin/env python3
"""Turn the settled rows of the request log into a checkable settlements record.

The reviewer's question was not "did money arrive" but "what did each payment buy,
and can a stranger check that the receipt belongs to this service". A wallet
transfer alone answers neither, so this walks the three links that do:

1. the server's own request log row: payer, resource, target, settlement tx;
2. the Base receipt for that tx: status 1, and exactly one USDC Transfer whose
   recipient is this service's `payTo` and whose amount is the quoted price;
3. the retained delivery body and its sha256, where one exists (from 2026-11-13).

Anything that does not line up is reported, not smoothed over. Self-test payments
(the operator's own spend wallet paying its own endpoint) are labelled as such and
never counted as sales.

Usage
    python3 zero/x402server/evidence_settlements.py
    python3 zero/x402server/evidence_settlements.py --out evidence/
    python3 zero/x402server/evidence_settlements.py --log <requests.jsonl> --strict

Exit code 1 under --strict if any row fails a check.
"""

import argparse
import calendar
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

RPC = os.environ.get("BASE_RPC", "https://mainnet.base.org")
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
PAY_TO_RAW = os.environ.get("X402_PAY_TO", "0x7373E88368378052EB5a449d2eBC95aD7E5f2bEF")
PAY_TO = PAY_TO_RAW.lower()
# The operator's own wallet, used for self-tests. Anything paid from here is a
# test of the endpoint, not a sale, and is labelled that way in the output.
SELF_PAYER = os.environ.get("X402_SELF_PAYER",
                            "0xab51bd381431299fe1fbdaff9fb4e793132ebdcf").lower()
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# Price in force by date. The endpoint charged 0.01 USDC (10000 atomic) until
# 2026-10-28T01:58Z and 0.05 USDC (50000 atomic) from that commit onward.
PRICE_EPOCHS = [
    (0, 10000),
    (calendar.timegm(time.strptime("2026-10-28T01:58:00Z", "%Y-%m-%dT%H:%M:%SZ")), 50000),
]
DEFAULT_LOG = Path.home() / ".local/state/cian-x402/requests.jsonl"


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        RPC, data=body,
        headers={"content-type": "application/json",
                 "user-agent": "cian-x402-evidence/1.0 (+github.com/cian-spider/cian-endpoint-audit)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload["result"]


def quote_at(ts_epoch):
    price = PRICE_EPOCHS[0][1]
    for start, atomic in PRICE_EPOCHS:
        if ts_epoch >= start:
            price = atomic
    return price


def load_paid_rows(path):
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("status") == 200 and row.get("tx"):
            rows.append(row)
    return rows


def build_row(row):
    tx = str(row["tx"])
    receipt = rpc("eth_getTransactionReceipt", [tx])
    block = rpc("eth_getBlockByNumber", [receipt["blockNumber"], False])
    transfers = [log for log in receipt["logs"]
                 if log.get("topics") and log["topics"][0] == TRANSFER]
    ours = [log for log in transfers
            if "0x" + log["topics"][2][-40:] == PAY_TO.lower()]
    ts_epoch = int(block["timestamp"], 16)
    amount = int(ours[0]["data"], 16) if len(ours) == 1 else None
    payer = "0x" + ours[0]["topics"][1][-40:] if len(ours) == 1 else None

    checks = {
        "receipt_status_ok": receipt.get("status") == "0x1",
        "exactly_one_transfer_to_pay_to": len(ours) == 1,
        "payer_matches_log": (payer or "").lower() == str(row.get("payer", "")).lower(),
        "amount_matches_price_in_force": amount == quote_at(ts_epoch),
    }
    return {
        "ts": row.get("ts"),
        "tx": tx,
        "resource": row.get("path"),
        "target": row.get("target"),
        "user_agent": row.get("ua"),
        "client_ip": row.get("ip"),
        "payer": row.get("payer"),
        "tx_from": receipt["from"],
        "tx_to": receipt["to"],
        "block": int(receipt["blockNumber"], 16),
        "block_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_epoch)),
        "asset": USDC,
        "pay_to": PAY_TO_RAW,
        "amount_atomic": amount,
        "amount_usdc": None if amount is None else f"{amount / 1_000_000:.2f}",
        "price_in_force_atomic": quote_at(ts_epoch),
        "usdc_transfers_in_tx": len(transfers),
        "self_test": str(row.get("payer", "")).lower() == SELF_PAYER,
        "delivery": (None if not row.get("delivery_sha256") else
                     {"sha256": row["delivery_sha256"],
                      "bytes": row.get("delivery_bytes"),
                      "path": row.get("delivery_path")}),
        # Retention started 2026-11-13. A row written before that is not a failed
        # check, it is a delivery body that was never kept; say which.
        "delivery_retained": bool(row.get("delivery_sha256")),
        "checks": checks,
        "checks_all_pass": all(checks.values()),
    }


def render_markdown(doc):
    lines = [
        "# Settlement record",
        "",
        f"Generated {doc['generated_at']} from `{doc['log_path']}` and Base mainnet",
        f"receipts (`{doc['rpc']}`). Every row below is one settled call to this",
        "endpoint. Rows paid from the operator's own spend wallet are self-tests and are",
        "labelled; they are not sales.",
        "",
        "| # | when (UTC) | what was bought | payer | tx | amount | self-test | body retained |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, row in enumerate(doc["rows"], 1):
        what = f"`{row['resource'] or '?'}` on `{row['target'] or '-'}`"
        lines.append(
            f"| {i} | {row['block_time_utc']} | {what} | `{row['payer']}` | "
            f"[`{row['tx'][:18]}…`](https://basescan.org/tx/{row['tx']}) | "
            f"{row['amount_usdc']} USDC | {'yes' if row['self_test'] else 'no'} | "
            f"{'yes' if row['delivery_retained'] else 'no'} |")
    lines += [
        "",
        "## What each row proves, and what it does not",
        "",
        "- The receipt proves USDC moved from that payer to this service's `payTo`, in",
        "  the exact amount the endpoint quoted at that time. It does not, on its own,",
        "  prove which resource was bought: any transfer of the right size to the same",
        "  address looks alike.",
        "- The request-log row is what attributes the payment to a resource and a target.",
        "  It is written by this server when it serves the response, and it names the",
        "  settlement tx returned by the facilitator.",
        "- For calls from 2026-11-13 onward the row also carries `delivery_sha256` and",
        "  `delivery_path`: the sha256 of the exact bytes sent, and a file under",
        "  `~/.local/state/cian-x402/deliveries/<tx>.json` holding those bytes. For",
        "  earlier calls the body was not retained; only the row above is evidence.",
        "",
        "## Reproduce a row",
        "",
        "```bash",
        "# the server's own row",
        f"grep {doc['rows'][-1]['tx'] if doc['rows'] else '<tx>'} {doc['log_path']}",
        "",
        "# the on-chain half, decoded",
        "curl -s -X POST https://mainnet.base.org -H 'content-type: application/json' \\",
        f"  --data '{{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getTransactionReceipt\",\"params\":[\"{doc['rows'][-1]['tx'] if doc['rows'] else '<tx>'}\"]}}' \\",
        "  | python3 -m json.tool",
        "```",
        "",
        "A USDC `Transfer` log with topic1 = payer, topic2 = `0x7373E88368378052EB5a449d2eBC95aD7E5f2bEF`",
        "and `data` = the atomic amount is the settlement. The EIP-3009",
        "`AuthorizationUsed` log in the same tx is the buyer's signature being spent.",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--out", default="evidence")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    log_path = Path(args.log)
    rows = [build_row(r) for r in load_paid_rows(log_path)]
    rows.sort(key=lambda r: r["block"])
    doc = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "service": {
            "name": "Cian Endpoint Audit",
            "endpoint": "https://cian-x402.netlify.app/v1/audit/<target>",
            "network": "eip155:8453",
            "asset": USDC,
            "pay_to": PAY_TO,
            "facilitator": "https://facilitator.payai.network",
        },
        "log_path": str(log_path),
        "rpc": RPC,
        "self_test_payer": SELF_PAYER,
        "rows": rows,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "settlements.json").write_text(json.dumps(doc, indent=2) + "\n")
    (out / "settlements.md").write_text(render_markdown(doc))

    failed = [r for r in rows if not r["checks_all_pass"]]
    for r in rows:
        print(f"{r['block_time_utc']} {r['amount_usdc']:>5} USDC "
              f"{'self-test' if r['self_test'] else 'sale     '} "
              f"{r['resource']} {r['tx']} "
              f"{'OK' if r['checks_all_pass'] else 'FAIL'}"
              f"{'' if r['delivery_retained'] else ' (body not retained)'}")
    retained = sum(1 for r in rows if r["delivery_retained"])
    print(f"{len(rows)} settled rows, {retained} with a retained body, "
          f"{len(failed)} failing checks")
    if args.strict and failed:
        for r in failed:
            print("FAIL", r["tx"], r["checks"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
