# Settlement record

Generated 2026-11-13T02:41:34Z from `/home/deployer/.local/state/cian-x402/requests.jsonl` and Base mainnet
receipts (`https://mainnet.base.org`). Every row below is one settled call to this
endpoint. Rows paid from the operator's own spend wallet are self-tests and are
labelled; they are not sales.

| # | when (UTC) | what was bought | payer | tx | amount | self-test | body retained |
|---|---|---|---|---|---|---|---|
| 1 | 2026-10-23T16:54:39Z | `/v1/audit` on `https://example.com` | `0xab51bd381431299fe1fbdaff9fb4e793132ebdcf` | [`0x2a53912f815d9d00…`](https://basescan.org/tx/0x2a53912f815d9d00f524d2c593e94f7494c2c80156da5fd8d67f4ffc9a8fee95) | 0.01 USDC | yes | no |
| 2 | 2026-10-23T17:22:51Z | `/v1/dns-audit` on `github.com` | `0xab51bd381431299fe1fbdaff9fb4e793132ebdcf` | [`0xfa3694e9f6c7bbe7…`](https://basescan.org/tx/0xfa3694e9f6c7bbe7085400d2ee05afbe4866037a932d0834bfff0bd8944fc138) | 0.01 USDC | yes | no |
| 3 | 2026-10-23T17:23:01Z | `/v1/dns-audit` on `github.com` | `0xab51bd381431299fe1fbdaff9fb4e793132ebdcf` | [`0x2b953335cc24ca40…`](https://basescan.org/tx/0x2b953335cc24ca4088fd34a109b8e6a28f57915f97a8ed7d1b393cf2e9e55b2a) | 0.01 USDC | yes | no |
| 4 | 2026-10-24T03:18:35Z | `/v1/dns-audit` on `example.com` | `0xa1d1c0cf717402ff3651aa4873ccf96410b01978` | [`0x741b6d57c13bae07…`](https://basescan.org/tx/0x741b6d57c13bae07588b39ff7665cfc6dc5d555e8671777d1405cb35cabb96bd) | 0.01 USDC | no | no |
| 5 | 2026-10-27T00:42:11Z | `/v1/dns-audit` on `example.com` | `0x7722dfae6bbed2fd02dc07455c2f5bf14be25e4a` | [`0x465ea55ffffd51e3…`](https://basescan.org/tx/0x465ea55ffffd51e3c131bc216efbee3b580045694e4204f7f9bcf9e336e0f4d5) | 0.01 USDC | no | no |
| 6 | 2026-11-10T03:18:25Z | `/v1/audit` on `https://example.com` | `0xa1d1c0cf717402ff3651aa4873ccf96410b01978` | [`0xaf47913a384f13bf…`](https://basescan.org/tx/0xaf47913a384f13bf4a1978554d9d7a6f0db8a0ed7bf96380576db30a31802b69) | 0.05 USDC | no | no |

## What each row proves, and what it does not

- The receipt proves USDC moved from that payer to this service's `payTo`, in
  the exact amount the endpoint quoted at that time. It does not, on its own,
  prove which resource was bought: any transfer of the right size to the same
  address looks alike.
- The request-log row is what attributes the payment to a resource and a target.
  It is written by this server when it serves the response, and it names the
  settlement tx returned by the facilitator.
- For calls from 2026-11-13 onward the row also carries `delivery_sha256` and
  `delivery_path`: the sha256 of the exact bytes sent, and a file under
  `~/.local/state/cian-x402/deliveries/<tx>.json` holding those bytes. For
  earlier calls the body was not retained; only the row above is evidence.

## Reproduce a row

```bash
# the server's own row
grep 0xaf47913a384f13bf4a1978554d9d7a6f0db8a0ed7bf96380576db30a31802b69 /home/deployer/.local/state/cian-x402/requests.jsonl

# the on-chain half, decoded
curl -s -X POST https://mainnet.base.org -H 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"eth_getTransactionReceipt","params":["0xaf47913a384f13bf4a1978554d9d7a6f0db8a0ed7bf96380576db30a31802b69"]}' \
  | python3 -m json.tool
```

A USDC `Transfer` log with topic1 = payer, topic2 = `0x7373E88368378052EB5a449d2eBC95aD7E5f2bEF`
and `data` = the atomic amount is the settlement. The EIP-3009
`AuthorizationUsed` log in the same tx is the buyer's signature being spent.
