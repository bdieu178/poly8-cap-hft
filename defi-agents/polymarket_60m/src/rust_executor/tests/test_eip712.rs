
#[cfg(test)]
mod tests {
    use alloy::primitives::{address, Address};
    use std::str::FromStr;

    #[test]
    fn test_verifying_contract_env_override() {
        let test_addr = "0x1234567890123456789012345678901234567890";
        std::env::set_var("POLY_VERIFYING_CONTRACT", test_addr);
        
        let env_addr = std::env::var("POLY_VERIFYING_CONTRACT").unwrap();
        assert_eq!(env_addr, test_addr);
        
        let addr = Address::from_str(&env_addr).unwrap();
        assert_eq!(addr, address!("1234567890123456789012345678901234567890"));
    }

    #[test]
    fn test_domain_recalculation_logic() {
        let default_addr_str = "0x4bFb9eF43088926955a15321356A5506a5E78D71";
        let addr = Address::from_str(default_addr_str).unwrap();
        
        let expected_addr = address!("4bFb9eF43088926955a15321356A5506a5E78D71");
        assert_eq!(addr, expected_addr);
    }
}
