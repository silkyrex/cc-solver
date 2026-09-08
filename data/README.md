Live MCP snapshots for a session date. Gitignored. SHA-256 in `manifest.sha256`.

```
data/live/YYYY-MM-DD/
  quotes.json
  universe.json
  positions.json
  discovery_board.json
  run_log.json
  handoff.json
  scans.json
  bars/TICKER.json
  intraday/TICKER.json
  manifest.sha256
```

The scheduled task writes this folder from Robinhood/IBKR/Notion MCP, then:

```bash
python3 cli.py take_action --date YYYY-MM-DD --data-dir data/live/YYYY-MM-DD
```

Bytes belong in Drive folder "Consistency Capital — Data Pulls" (`1xOQAz-RCBxfArm36OFWs5fG8lwVBjigG`) with the same manifest. Code stays in Git.
