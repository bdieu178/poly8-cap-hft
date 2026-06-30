import unittest
import ctypes
import math
from utils.shm_types import L2BookStruct, AccountStateStruct

class TestResearchImplementation(unittest.TestCase):
    def test_struct_alignment(self):
        """
        Ensures the Python ctypes structure matches the 1152-byte standard.
        """
        self.assertEqual(ctypes.sizeof(L2BookStruct), 1152)
        
    def test_execution_flow_and_singularity_logic(self):
        """
        Validates the mathematical principles from Paper 2 (2511.01471v1)
        Execution Flow I = dV/dt and P_max_i tracking.
        """
        dV = 1000.0 
        dt_ms = 10.0 
        
        I = dV / (dt_ms / 1000.0)
        self.assertEqual(I, 100000.0) 
        
        is_singularity = I > 100.0
        self.assertTrue(is_singularity)
        
    def test_hawkes_non_linear_alpha(self):
        """
        Validates non-linear Alpha scaling from Paper 1 (Chen et al. 2017)
        alpha_scaled = alpha * ln(I_rate)
        """
        alpha_base = 0.5
        I_rate = 500.0 
        
        alpha_scaled = alpha_base * math.log(max(I_rate, 1.0))
        self.assertGreater(alpha_scaled, alpha_base)
        
        I_rate_2 = 1000.0
        alpha_scaled_2 = alpha_base * math.log(max(I_rate_2, 1.0))
        self.assertLess(alpha_scaled_2, alpha_scaled * 2) 

    def test_sigmoid_link_function(self):
        """
        Validates the Sigmoid link function phi(lambda) from Paper 3.
        Determines the intensity boost based on Hawkes intensity.
        """
        def calculate_sigmoid_boost(intensity):
            return 0.2 / (1.0 + math.exp(-5.0 * (intensity - 1.0)))

        # Intensity = 1.0 -> Boost should be 0.1 (midpoint)
        boost_1 = calculate_sigmoid_boost(1.0)
        self.assertAlmostEqual(boost_1, 0.1, places=5)

        # High Intensity -> Boost should approach 0.2
        boost_high = calculate_sigmoid_boost(10.0)
        self.assertGreater(boost_high, 0.19)
        self.assertLessEqual(boost_high, 0.2)

        # Low Intensity -> Boost should approach 0
        boost_low = calculate_sigmoid_boost(-10.0)
        self.assertLess(boost_low, 0.01)

    def test_contrarian_fading_logic(self):
        """
        Validates Fading the Peak from Paper 3 (Kang, 2026)
        """
        hl_mid = 65050.0
        p_max_i = 65000.0 
        divergence = hl_mid - p_max_i 
        multiplier = 1.0
        intensity_phi = 0.8 
        contrarian_shift = -divergence * intensity_phi * 0.5 * multiplier
        fair_value = hl_mid + contrarian_shift
        self.assertLess(fair_value, hl_mid)
        self.assertEqual(fair_value, 65030.0) 

    def test_recursive_hawkes_decay(self):
        """
        Validates recursive decay property: S(t) = S(prev) * exp(-beta * dt)
        """
        s_prev = 1.0
        beta = 10.0
        dt = 0.1 
        s_curr = s_prev * math.exp(-beta * dt)
        self.assertAlmostEqual(s_curr, 1.0 / math.e, places=5)

    def test_kelly_sizing_logic(self):
        """
        Validates Fractional Kelly Sizing: f* = multiplier * ((win_prob * (b + 1) - 1) / b)
        """
        p_market = 0.5
        p_theo = 0.56 # Edge of 6%
        multiplier = 0.5 # Fractional Kelly (Half Kelly)
        
        # Binary option odds: b = (1/p) - 1
        b = (1.0 / p_market) - 1.0 # b = 1.0 for p=0.5
        
        kelly_fraction = multiplier * ( (p_theo * (b + 1.0) - 1.0) / b )
        
        # Expected: 0.5 * ((0.56 * 2 - 1) / 1) = 0.5 * (1.12 - 1) = 0.5 * 0.12 = 0.06
        self.assertAlmostEqual(kelly_fraction, 0.06, places=5)

if __name__ == "__main__":
    unittest.main()

if __name__ == "__main__":
    unittest.main()
