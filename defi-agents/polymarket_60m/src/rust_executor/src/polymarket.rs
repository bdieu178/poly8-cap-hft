use polymarket_client_sdk_v2::clob::{Client as ClobClient, Config as ClobConfig};
use polymarket_client_sdk_v2::clob::types::response::{PostOrderResponse, CancelOrdersResponse};
use polymarket_client_sdk_v2::auth::state::Authenticated;
use polymarket_client_sdk_v2::auth::Normal;
use polymarket_client_sdk_v2::clob::types::{OrderType, Side, SignatureType};
use polymarket_client_sdk_v2::types::{Decimal, U256};
use alloy::signers::local::PrivateKeySigner;
use alloy::signers::Signer;
use alloy::sol;
use alloy::providers::{Provider, RootProvider};
use alloy::primitives::Address;
use alloy::network::Ethereum;
use std::str::FromStr;
use std::sync::Arc;

sol! {
    #[sol(rpc)]
    interface IERC20 {
        function balanceOf(address account) external view returns (uint256);
        function approve(address spender, uint256 amount) external returns (bool);
        function allowance(address owner, address spender) external view returns (uint256);
    }

    #[sol(rpc)]
    interface ICollateralOnramp {
        function wrap(uint256 amount) external;
        function unwrap(uint256 amount) external;
    }
}

pub struct PolymarketClient {
    pub clob_client: ClobClient<Authenticated<Normal>>,
    signer: PrivateKeySigner,
    proxy_wallet: Option<Address>,
    signature_type: SignatureType,
    provider: Arc<RootProvider<Ethereum>>,
    onramp_address: Address,
    usdc_address: Address,
    verifying_contract: Address,
}

// Helper to round price to the exchange's required tick size (0.01)
fn round_to_tick(price: f64) -> f64 {
    (price * 100.0).round() / 100.0
}

impl PolymarketClient {
    pub async fn new(
        private_key: &str, 
        api_url: &str, 
        proxy_wallet: Option<&str>, 
        chain_id: u64,
        rpc_url: &str,
        sig_type: SignatureType
    ) -> Self {
        let signer = PrivateKeySigner::from_str(private_key)
            .unwrap_or_else(|_| panic!("CRITICAL: Invalid POLY_SECRET provided to Executor"))
            .with_chain_id(Some(chain_id));

        let proxy = proxy_wallet.and_then(|p| Address::from_str(p).ok());
        
        let provider = Arc::new(RootProvider::new_http(
            reqwest::Url::parse(rpc_url).expect("Invalid RPC URL")
        ));

        // Pull Verifying Contract from Environment for Dynamic EIP-712 Domains
        let verifying_contract_str = std::env::var("POLY_VERIFYING_CONTRACT")
            .unwrap_or_else(|_| "0x4bFb9eF43088926955a15321356A5506a5E78D71".to_string());
        let verifying_contract = Address::from_str(&verifying_contract_str)
            .expect("Invalid POLY_VERIFYING_CONTRACT address");

        let config = ClobConfig::default(); 
        
        // Build the authenticated client
        let mut auth_builder = ClobClient::new(api_url, config)
            .expect("Failed to initialize CLOB client")
            .authentication_builder(&signer)
            .signature_type(sig_type);
            
        // Configure for Deposit Wallet / Proxy if needed (only if signature type is not Eoa)
        if sig_type != SignatureType::Eoa {
            if let Some(proxy_addr) = proxy {
                println!("[INIT] Configuring CLOB client with Funder: {:?}", proxy_addr);
                auth_builder = auth_builder.funder(proxy_addr);
            }
        } else {
            println!("[INIT] Skipping Funder configuration for EOA signature type.");
        }

        let clob_client = match auth_builder.authenticate().await {
            Ok(client) => client,
            Err(e) => {
                eprintln!("[CRITICAL] Failed to authenticate with CLOB API: {:?}", e);
                panic!("Failed to authenticate with CLOB API: {:?}", e);
            }
        };

        println!("[INIT] CLOB Client Authenticated. Address: {:?}, Funder: {:?}", 
            clob_client.address(), proxy);

        Self {
            clob_client,
            signer,
            proxy_wallet: proxy,
            signature_type: sig_type,
            provider,
            onramp_address: Address::from_str("0x93070a847efef7f70739046a929d47a521f5b8ee").unwrap(),
            usdc_address: Address::from_str("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174").unwrap(),
            verifying_contract,
        }
    }
    
    /// Wraps USDC into pUSD (Mandatory for Polymarket V2)
    pub async fn wrap_usdc(&self, amount_usdc: f64) -> Result<(), String> {
        let amount_raw = U256::from((amount_usdc * 1e6) as u64);
        
        let usdc_contract = IERC20::new(self.usdc_address, self.provider.clone());
        let onramp_contract = ICollateralOnramp::new(self.onramp_address, self.provider.clone());

        // 1. Check Allowance
        let allowance = usdc_contract.allowance(self.signer.address(), self.onramp_address)
            .call().await.map_err(|e| e.to_string())?;

        if allowance < amount_raw {
            println!("[ONRAMP] Approving USDC for Onramp...");
            let _ = usdc_contract.approve(self.onramp_address, U256::MAX)
                .send().await.map_err(|e| e.to_string())?;
        }

        // 2. Wrap
        println!("[ONRAMP] Wrapping {:.2} USDC to pUSD...", amount_usdc);
        let tx = onramp_contract.wrap(amount_raw)
            .send().await.map_err(|e| e.to_string())?;
        
        println!("[ONRAMP] Wrap successful. Tx: {:?}", tx.tx_hash());
        Ok(())
    }

    pub async fn submit_market_order(&self, token_id: &str, size_usd: f64, side: Side, fee_rate_bps: u64) -> Result<PostOrderResponse, String> {
        let token_id_u256 = U256::from_str(token_id).map_err(|e| e.to_string())?;
        
        // Polymarket V2 Market Orders: Maker amount (USDC) supports max 2 decimals.
        // Round down for Sell orders to prevent exceeding on-chain token balance from fractional positions.
        let rounded_size = if side == Side::Sell {
            (size_usd * 100.0).floor() / 100.0
        } else {
            (size_usd * 100.0).round() / 100.0
        };
        
        println!("[ASYNC NETWORK] Submitting signed order for token: {} (Owner={:?}, SigType={:?}, Size=${:.2})", 
            token_id, self.proxy_wallet.unwrap_or(self.signer.address()), self.signature_type, rounded_size);
        
        let amount_decimal = Decimal::from_str(&format!("{:.2}", rounded_size))
            .map_err(|e| format!("Decimal conversion error: {}", e))?;

        let amount = if side == Side::Buy {
            polymarket_client_sdk_v2::clob::types::Amount::usdc(amount_decimal)
                .map_err(|e| format!("Amount construction error: {}", e))?
        } else {
            polymarket_client_sdk_v2::clob::types::Amount::shares(amount_decimal)
                .map_err(|e| format!("Amount construction error: {}", e))?
        };

        // Transitioned from FOK to FAK (Fill-and-Kill): Take whatever is available in shallow liquidity
        let builder = self.clob_client
            .market_order()
            .token_id(token_id_u256)
            .side(side)
            .amount(amount)
            .fee_rate_bps(fee_rate_bps as u32)
            .order_type(OrderType::FAK);

        let resp_result = builder.build_sign_and_post(&self.signer).await;
            
        match resp_result {
            Ok(resp) => {
                println!("[ASYNC NETWORK] Order success: ID={} Status={}", resp.order_id, resp.status);
                Ok(resp)
            },
            Err(e) => {
                eprintln!("[ASYNC NETWORK] Order failed: {:?}", e);
                Err(e.to_string())
            }
        }
    }

    pub async fn submit_limit_order(&self, token_id: &str, size_param: f64, price: f64, side: Side, fee_rate_bps: u64, expiration_timestamp: Option<u64>, post_only: bool) -> Result<PostOrderResponse, String> {
        let token_id_u256 = U256::from_str(token_id).map_err(|e| e.to_string())?;

        // CRITICAL FIX: Ensure price and size are rounded to 2 decimal places to meet exchange tick size requirement
        let rounded_price = (price * 100.0).round() / 100.0;
        
        // For limit orders, size is in shares. 
        // If Buy, size_param is USD. If Sell, size_param is tokens (shares).
        let shares = if side == Side::Buy {
            size_param / rounded_price
        } else {
            size_param
        };
        // Round down for Sell orders to prevent exceeding on-chain token balance from fractional positions.
        let rounded_shares = if side == Side::Sell {
            (shares * 100.0).floor() / 100.0
        } else {
            (shares * 100.0).round() / 100.0
        };

        println!("{} [ASYNC NETWORK] Submitting signed LIMIT order for token: {} (Owner={:?}, SigType={:?}, Shares={:.2}, Price={:.2}, GTD={:?}, PostOnly={})", 
            crate::strategy::get_utc_ts(), token_id, self.proxy_wallet.unwrap_or(self.signer.address()), self.signature_type, rounded_shares, rounded_price, expiration_timestamp, post_only);

        let shares_decimal = Decimal::from_str(&format!("{:.2}", rounded_shares))
            .map_err(|e| format!("Decimal conversion error for size: {}", e))?;
        let price_decimal = Decimal::from_str(&format!("{:.2}", rounded_price))
            .map_err(|e| format!("Decimal conversion error for price: {}", e))?;

        let mut builder = self.clob_client
            .limit_order()
            .token_id(token_id_u256)
            .side(side)
            .size(shares_decimal)
            .price(price_decimal)
            .fee_rate_bps(fee_rate_bps as u32)
            .post_only(post_only);

        // Transitioned from GTC to GTD: Prevent orphaned orders on crash
        if let Some(ts) = expiration_timestamp {
            let expiration_dt = chrono::DateTime::from_timestamp(ts as i64, 0)
                .ok_or_else(|| "Invalid expiration timestamp".to_string())?;
            builder = builder.order_type(OrderType::GTD).expiration(expiration_dt);
        } else {
            builder = builder.order_type(OrderType::GTC);
        }

        let resp_result = builder.build_sign_and_post(&self.signer).await;
            
        match resp_result {
            Ok(resp) => {
                println!("{} [ASYNC NETWORK] Limit Order success: ID={} Status={}", crate::strategy::get_utc_ts(), resp.order_id, resp.status);
                Ok(resp)
            },
            Err(e) => {
                eprintln!("{} [ASYNC NETWORK] Limit Order failed: {:?}", crate::strategy::get_utc_ts(), e);
                Err(e.to_string())
            }
        }
    }

    pub async fn get_open_orders(&self) -> Result<Vec<polymarket_client_sdk_v2::clob::types::response::OpenOrderResponse>, String> {
        let request = polymarket_client_sdk_v2::clob::types::request::OrdersRequest::default();
        let mut all_orders = Vec::new();
        let mut cursor = None;
        loop {
            match self.clob_client.orders(&request, cursor.clone()).await {
                Ok(page) => {
                    all_orders.extend(page.data);
                    if page.next_cursor.is_empty() || page.next_cursor == "LTE=" {
                        break;
                    }
                    cursor = Some(page.next_cursor);
                }
                Err(e) => {
                    return Err(e.to_string());
                }
            }
        }
        Ok(all_orders)
    }

    pub async fn cancel_order(&self, order_id: &str) -> Result<CancelOrdersResponse, String> {
        // println!("{} [ASYNC NETWORK] Cancelling order: {}", crate::strategy::get_utc_ts(), order_id);
        self.clob_client.cancel_order(order_id).await.map_err(|e| e.to_string())
    }

    pub async fn cancel_all_orders(&self) -> Result<CancelOrdersResponse, String> {
        self.clob_client.cancel_all_orders().await.map_err(|e| e.to_string())
    }

    pub async fn get_order(&self, order_id: &str) -> Result<polymarket_client_sdk_v2::clob::types::response::OpenOrderResponse, String> {
        self.clob_client.order(order_id).await.map_err(|e| e.to_string())
    }
}
