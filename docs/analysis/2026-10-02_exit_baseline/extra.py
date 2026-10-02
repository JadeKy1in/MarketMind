"""Extra splits: cost by asset type, long/short, stopped-out trades' path after the stop."""
import json, numpy as np
from collections import defaultdict
R = json.load(open("entries.json"))["rows"]
L = [r for r in R if r["source_type"] != "benchmark"]
def m(v): return f"{100*np.mean(v):+.2f}%" if len(v) else "—"
print("cost by asset type (LLM all):")
g = defaultdict(list)
for r in L: g[r["asset_type"]].append(r)
for k, v in g.items():
    print(f"  {k}: n={len(v)} cost={m([x['cost'] for x in v])} R0={m([x['rules']['R0_current']['net'] for x in v])} "
          f"R1={m([x['rules']['R1_expiry_only']['net'] for x in v])} gross_R1={m([x['rules']['R1_expiry_only']['gross'] for x in v])}")
nc = [r for r in L if r["asset_type"] != "crypto" and not r["ticker"].endswith("-USD")]
print("ex-crypto n", len(nc), "R0", m([x['rules']['R0_current']['net'] for x in nc]), "R1", m([x['rules']['R1_expiry_only']['net'] for x in nc]),
      "always_long", m([x['long_gross']-x['cost'] for x in nc]), "cost", m([x['cost'] for x in nc]))
for d in ("long", "short"):
    v = [r for r in L if r["direction"] == d]
    print(d, len(v), "R0", m([x['rules']['R0_current']['net'] for x in v]), "R1", m([x['rules']['R1_expiry_only']['net'] for x in v]),
          "settled R0", m([x['rules']['R0_current']['net'] for x in v if x['status']=='settled']), sum(x['status']=='settled' for x in v))
for reason in ("stop", "falsifier", "target", "expiry"):
    v = [r for r in L if r["rules"]["R0_current"]["reason"] == reason]
    print(f"R0 exit={reason}: n={len(v)} R0={m([x['rules']['R0_current']['net'] for x in v])} same-entry expiry/MTM={m([x['rules']['R1_expiry_only']['net'] for x in v])} "
          f"share where holding beat exit={np.mean([x['rules']['R1_expiry_only']['net']>x['rules']['R0_current']['net'] for x in v]):.0%}")
print("hold<=1:", sum(r["hold_bars"] <= 1 for r in L))
st = [r for r in L if r["status"]=="settled"]
print("settled by source:", {k: (sum(r['source_type']==k for r in st)) for k in set(r['source_type'] for r in st)})
print("days held distribution R1 (bars to now):", np.percentile([ (np.datetime64(r['r1_exit_date'])-np.datetime64(r['entry_date'])).astype(int) for r in L],[0,50,100]))
