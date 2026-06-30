import re

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "r") as f:
    content = f.read()

content = content.replace(
    ");, up_spread);",
    ", up_spread);"
)
content = content.replace(
    ");, down_spread);",
    ", down_spread);"
)

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "w") as f:
    f.write(content)
