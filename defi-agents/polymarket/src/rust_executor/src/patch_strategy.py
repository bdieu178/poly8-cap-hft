import re

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "r") as f:
    content = f.read()

# 1. Update callers in main loop
content = re.sub(
    r'(let mut p_theo_up = self\.calculate_p_theo_up\([^;]+)(l2\.rotation_ts\);)',
    r'let up_spread = (l2.poly_up_asks[0].price - l2.poly_up_bids[0].price).max(0.01);\n        \1\2, up_spread);',
    content
)
content = re.sub(
    r'(let mut p_theo_down = self\.calculate_p_theo_down\([^;]+)(l2\.rotation_ts\);)',
    r'let down_spread = (l2.poly_down_asks[0].price - l2.poly_down_bids[0].price).max(0.01);\n        \1\2, down_spread);',
    content
)

# 2. Update signatures
content = content.replace(
    'fn calculate_p_theo_up(&mut self, hl_mid: f64, ofi_signal: f64, signed_flow: f64, fading_factor: f64, informed_multiplier: f64, path_delta: f64, path_curvature: f64, rotation_ts: u64) -> f64 {',
    'fn calculate_p_theo_up(&mut self, hl_mid: f64, ofi_signal: f64, signed_flow: f64, fading_factor: f64, informed_multiplier: f64, path_delta: f64, path_curvature: f64, rotation_ts: u64, pm_spread: f64) -> f64 {'
)
content = content.replace(
    'let signed_alpha = self.calculate_base_p_theo(hl_mid, ofi_signal, signed_flow, fading_factor, informed_multiplier, path_delta, path_curvature, rotation_ts);',
    'let signed_alpha = self.calculate_base_p_theo(hl_mid, ofi_signal, signed_flow, fading_factor, informed_multiplier, path_delta, path_curvature, rotation_ts, pm_spread);'
)

content = content.replace(
    'fn calculate_p_theo_down(&mut self, hl_mid: f64, ofi_signal: f64, signed_flow: f64, fading_factor: f64, informed_multiplier: f64, path_delta: f64, path_curvature: f64, rotation_ts: u64) -> f64 {',
    'fn calculate_p_theo_down(&mut self, hl_mid: f64, ofi_signal: f64, signed_flow: f64, fading_factor: f64, informed_multiplier: f64, path_delta: f64, path_curvature: f64, rotation_ts: u64, pm_spread: f64) -> f64 {'
)

content = content.replace(
    'fn calculate_base_p_theo(&mut self, hl_mid: f64, ofi_signal: f64, signed_flow: f64, fading_factor: f64, informed_multiplier: f64, path_delta: f64, path_curvature: f64, rotation_ts: u64) -> f64 {',
    'fn calculate_base_p_theo(&mut self, hl_mid: f64, ofi_signal: f64, signed_flow: f64, fading_factor: f64, informed_multiplier: f64, path_delta: f64, path_curvature: f64, rotation_ts: u64, pm_spread: f64) -> f64 {'
)

# 3. Update tests
content = re.sub(r'strategy\.calculate_p_theo_up\(([^;]+),\s*0\);', r'strategy.calculate_p_theo_up(\1, 0, 0.02);', content)
content = re.sub(r'strategy\.calculate_p_theo_down\(([^;]+),\s*0\);', r'strategy.calculate_p_theo_down(\1, 0, 0.02);', content)
content = re.sub(r'strategy\.calculate_p_theo_up\(([^;]+),\s*dummy_ts\);', r'strategy.calculate_p_theo_up(\1, dummy_ts, 0.02);', content)
content = re.sub(r'strategy\.calculate_p_theo_down\(([^;]+),\s*dummy_ts\);', r'strategy.calculate_p_theo_down(\1, dummy_ts, 0.02);', content)

# 4. Update internal logic in calculate_base_p_theo
content = content.replace(
'''        let w_ofi = 0.40;
        let w_flow = 0.35;
        let w_path = 0.15;
        let w_curv = 0.10;
        let w_h = 0.25; // Memory decay factor

        let input_signal = (ofi_signal * w_ofi) + 
                           (signed_flow * w_flow) + 
                           (path_delta * w_path) + 
                           (path_curvature * w_curv);
        
        let new_hidden_state = (input_signal + self.rnn_hidden_state * w_h).tanh();
        self.rnn_hidden_state = new_hidden_state; // Persist memory

        let sensitivity_multiplier = informed_multiplier * 0.15;''',
'''        let w_ofi = 0.40;
        let w_flow = 0.35;
        let w_path = 0.15;
        let w_curv = 0.15; // Increased for 15m Absorption Reversal
        let w_h = 0.45; // Increased for 15m Macro Bleed

        let input_signal = (ofi_signal * w_ofi) + 
                           (signed_flow * w_flow) + 
                           (path_delta * w_path) + 
                           (path_curvature * w_curv);
        
        let new_hidden_state = (input_signal + self.rnn_hidden_state * w_h).tanh();
        self.rnn_hidden_state = new_hidden_state; // Persist memory

        let max_swing = if self.asset == "ETH" { 0.10 } else { 0.15 };
        let sensitivity_multiplier = informed_multiplier * max_swing;'''
)

content = content.replace(
'''        // 4. Longshot Spread Premium Cutoff (Arxiv 2604.24366v2)
        // At extremes (p < 0.10 or p > 0.90 -> dev < -0.40 or dev > 0.40), spreads explode to 1300-1800 bps.
        if final_deviation > 0.40 {
            final_deviation -= 0.15; // Penalty applied
        } else if final_deviation < -0.40 {
            final_deviation += 0.15;
        }

        // 5. Geometric Depth Slippage Discount
        // L1 only holds ~13.6% depth. Step-wise discount for chewing L2-L10
        let order_size = self.current_size_scale; // Use current scaling
        let geometric_discount = if order_size > 1000.0 {
            0.05 // Heavy sweep
        } else if order_size > 500.0 {
            0.02 // Moderate sweep
        } else {
            0.00 // L1 only
        };''',
'''        // 4. Dynamic Longshot Spread Premium Cutoff
        // Apply dynamic L1 spread penalty instead of hard 0.15 at boundaries
        if final_deviation > 0.40 {
            final_deviation -= pm_spread; // Penalty applied
        } else if final_deviation < -0.40 {
            final_deviation += pm_spread;
        }

        // 5. Geometric Depth Slippage Discount
        // L1 only holds ~13.6% depth. Step-wise discount for chewing L2-L10
        let order_size = self.current_size_scale; // Use current scaling
        let geometric_discount = if self.asset == "BTC" {
            if order_size > 1000.0 { 0.03 } else if order_size > 500.0 { 0.02 } else { 0.00 }
        } else {
            if order_size > 1000.0 { 0.05 } else if order_size > 500.0 { 0.02 } else { 0.00 }
        };'''
)

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "w") as f:
    f.write(content)
