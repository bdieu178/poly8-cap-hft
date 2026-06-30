use alloy::sol;
use alloy::primitives::{Address, U256};
use alloy::providers::ProviderBuilder;
use std::str::FromStr;

sol! {
    // Standard ERC20 ABI for pUSD
    #[sol(rpc)]
    contract Erc20 {
        function balanceOf(address _owner) external view returns (uint256 balance);
        function decimals() external view returns (uint8);
    }

    // Conditional Tokens Framework ABI for outcome tokens
    #[sol(rpc)]
    contract Ctf {
        function balanceOf(address account, uint256 id) external view returns (uint256 value);
    }
}

#[derive(Debug)]
pub struct AccountBalances {
    pub pusd_balance: f64,
    pub up_balance: f64,
    pub down_balance: f64,
}

pub async fn fetch_balances(
    rpc_url: &str,
    wallet_address_str: &str,
    pusd_address_str: &str,
    ctf_address_str: &str,
    up_token_id: U256,
    down_token_id: U256,
) -> Result<AccountBalances, String> {
    let provider = ProviderBuilder::new()
        .connect_http(rpc_url.parse().unwrap());

    let wallet_address = Address::from_str(wallet_address_str).map_err(|e| e.to_string())?;
    let pusd_address = Address::from_str(pusd_address_str).map_err(|e| e.to_string())?;
    let ctf_address = Address::from_str(ctf_address_str).map_err(|e| e.to_string())?;

    let pusd_contract = Erc20::new(pusd_address, &provider);
    let ctf_contract = Ctf::new(ctf_address, &provider);

    let pusd_balance_raw = pusd_contract.balanceOf(wallet_address).call().await.map_err(|e| e.to_string())?;
    let up_balance_raw = ctf_contract.balanceOf(wallet_address, up_token_id).call().await.map_err(|e| e.to_string())?;
    let down_balance_raw = ctf_contract.balanceOf(wallet_address, down_token_id).call().await.map_err(|e| e.to_string())?;

    // Assuming 6 decimals for pUSD and outcome tokens
    let pusd_balance = pusd_balance_raw.to_string().parse::<f64>().unwrap_or(0.0) / 1_000_000.0;
    let up_balance = up_balance_raw.to_string().parse::<f64>().unwrap_or(0.0) / 1_000_000.0;
    let down_balance = down_balance_raw.to_string().parse::<f64>().unwrap_or(0.0) / 1_000_000.0;
    
    Ok(AccountBalances {
        pusd_balance,
        up_balance,
        down_balance,
    })
}
