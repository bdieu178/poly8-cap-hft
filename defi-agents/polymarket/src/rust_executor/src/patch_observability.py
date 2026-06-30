import re

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "r") as f:
    content = f.read()

# 1. Add fields to Strategy struct
content = content.replace(
'''    pub rnn_hidden_state: f64,
}''',
'''    pub rnn_hidden_state: f64,
    pub last_sensitivity_multiplier: f64,
    pub last_dynamic_spread_penalty: f64,
    pub last_geometric_discount: f64,
}'''
)

# 2. Add fields to Strategy::new
content = content.replace(
'''            tkg_log_tx: None,
            rnn_hidden_state: 0.0,
        };''',
'''            tkg_log_tx: None,
            rnn_hidden_state: 0.0,
            last_sensitivity_multiplier: 0.0,
            last_dynamic_spread_penalty: 0.0,
            last_geometric_discount: 0.0,
        };'''
)

# 3. Update calculate_base_p_theo to set the fields
content = content.replace(
'''        let max_swing = if self.asset == "ETH" { 0.10 } else { 0.15 };
        let sensitivity_multiplier = informed_multiplier * max_swing;
        let micro_adjustment = new_hidden_state * sensitivity_multiplier * fading_factor;''',
'''        let max_swing = if self.asset == "ETH" { 0.10 } else { 0.15 };
        let sensitivity_multiplier = informed_multiplier * max_swing;
        self.last_sensitivity_multiplier = sensitivity_multiplier;
        let micro_adjustment = new_hidden_state * sensitivity_multiplier * fading_factor;'''
)

content = content.replace(
'''        // 4. Dynamic Longshot Spread Premium Cutoff
        // Apply dynamic L1 spread penalty instead of hard 0.15 at boundaries
        if final_deviation > 0.40 {
            final_deviation -= pm_spread; // Penalty applied
        } else if final_deviation < -0.40 {
            final_deviation += pm_spread;
        }''',
'''        // 4. Dynamic Longshot Spread Premium Cutoff
        // Apply dynamic L1 spread penalty instead of hard 0.15 at boundaries
        let mut penalty_applied = 0.0;
        if final_deviation > 0.40 {
            final_deviation -= pm_spread; // Penalty applied
            penalty_applied = pm_spread;
        } else if final_deviation < -0.40 {
            final_deviation += pm_spread;
            penalty_applied = pm_spread;
        }
        self.last_dynamic_spread_penalty = penalty_applied;'''
)

content = content.replace(
'''        // 5. Geometric Depth Slippage Discount
        // L1 only holds ~13.6% depth. Step-wise discount for chewing L2-L10
        let order_size = self.current_size_scale; // Use current scaling
        let geometric_discount = if self.asset == "BTC" {
            if order_size > 1000.0 { 0.03 } else if order_size > 500.0 { 0.02 } else { 0.00 }
        } else {
            if order_size > 1000.0 { 0.05 } else if order_size > 500.0 { 0.02 } else { 0.00 }
        };''',
'''        // 5. Geometric Depth Slippage Discount
        // L1 only holds ~13.6% depth. Step-wise discount for chewing L2-L10
        let order_size = self.current_size_scale; // Use current scaling
        let geometric_discount = if self.asset == "BTC" {
            if order_size > 1000.0 { 0.03 } else if order_size > 500.0 { 0.02 } else { 0.00 }
        } else {
            if order_size > 1000.0 { 0.05 } else if order_size > 500.0 { 0.02 } else { 0.00 }
        };
        self.last_geometric_discount = geometric_discount;'''
)

# 4. Update telemetry JSON
content = content.replace(
'''                    "l4_intensity": self.hawkes_intensity,
                    "rnn_hidden_state": self.rnn_hidden_state,
                    "q_up": self.internal_up_position,
                    "q_down": self.internal_down_position,''',
'''                    "l4_intensity": self.hawkes_intensity,
                    "rnn_hidden_state": self.rnn_hidden_state,
                    "sensitivity_multiplier": self.last_sensitivity_multiplier,
                    "dynamic_spread_penalty": self.last_dynamic_spread_penalty,
                    "geometric_discount": self.last_geometric_discount,
                    "q_up": self.internal_up_position,
                    "q_down": self.internal_down_position,'''
)

with open("/home/bdieu178/user/defi-agents/polymarket/src/rust_executor/src/strategy.rs", "w") as f:
    f.write(content)
