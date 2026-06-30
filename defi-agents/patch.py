import re

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "r") as f:
    content = f.read()

# 1. Update callers in main loop (around line 845)
content = re.sub(
    r'(let mut p_theo_up = self\.calculate_p_theo_up\([^;]+)(l2\.rotation_ts\);)',
    r'let up_spread = (l2.poly_up_asks[0].price - l2.poly_up_bids[0].price).max(0.01);\n        \1\2\n        let down_spread = (l2.poly_down_asks[0].price - l2.poly_down_bids[0].price).max(0.01);',
    content
)

# Actually, doing regex for callers might be brittle. Let's just do exact string replacement if possible.
