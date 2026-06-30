import re

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "r") as f:
    content = f.read()

content = content.replace(
    'let strategy = Strategy::new(None, None, false, "btc".to_string(), "123".to_string(), "456".to_string(), 0.0, Config::default(), journal, order_tx, None);',
    'let mut strategy = Strategy::new(None, None, false, "btc".to_string(), "123".to_string(), "456".to_string(), 0.0, Config::default(), journal, order_tx, None);'
)

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "w") as f:
    f.write(content)
