#!/usr/bin/env python3
import argparse
from datetime import datetime

p = argparse.ArgumentParser(description="Generate a client issue ledger entry template.")
p.add_argument("--client", required=True)
p.add_argument("--title", required=True)
p.add_argument("--severity", default="P2", choices=["P1", "P2", "P3"])
p.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d %H:%M"))
args = p.parse_args()

print(f"""## {args.date}｜{args.severity}｜{args.title}

- Client: {args.client}
- Reporter: 待填
- Symptom: 待填
- Exact error: 待填
- Affected system/channel/model: 待填
- Root cause confidence: unknown
- Immediate action: 待填
- Prevention / skill or config update: 待填
- Evidence path / log path: 待填
- Owner: 待填
- Next review date: 待填
- Status: open
""")
