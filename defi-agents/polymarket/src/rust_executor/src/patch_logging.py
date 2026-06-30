import re

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "r") as f:
    content = f.read()

target = '''        if self.ticks_seen % 100 == 0 {
            println!("{} [SIGNAL] {} | Mid: {:.2} | Strike: {:.2} | P_UP: {:.4} | P_DOWN: {:.4} | Intensity: {:.2}", 
                get_utc_ts(), self.asset, hl_mid, self.strike_price, p_theo_up, p_theo_down, self.hawkes_intensity);
        }'''

replacement = '''        if self.ticks_seen % 100 == 0 {
            println!("{} [SIGNAL] {} | P_UP: {:.4} | P_DOWN: {:.4} | RNN_Mem: {:.3} | Max_Swing: {:.2} | PM_Penalty: {:.3} | Geo_Discount: {:.3} | Intensity: {:.2}", 
                get_utc_ts(), self.asset, p_theo_up, p_theo_down, self.rnn_hidden_state, self.last_sensitivity_multiplier, self.last_dynamic_spread_penalty, self.last_geometric_discount, self.hawkes_intensity);
        }'''

content = content.replace(target, replacement)

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "w") as f:
    f.write(content)
