use alloy::signers::local::PrivateKeySigner;
use alloy::signers::Signer; // Import Signer trait
use polymarket_client_sdk_v2::clob::{Client as ClobClient, Config as ClobConfig, types::SignatureType};
use std::str::FromStr;
use alloy::primitives::Address;

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    
    let pkey = std::env::var("POLY_SECRET").expect("POLY_SECRET missing");
    let api_url = std::env::var("POLY_CLOB_API_URL").expect("POLY_CLOB_API_URL missing");
    let proxy_wallet = std::env::var("POLY_PROXY_WALLET").ok();
    let sig_type_str = std::env::var("POLY_SIGNATURE_TYPE").unwrap_or_else(|_| "0".to_string());
    
    let sig_type = match sig_type_str.as_str() {
        "1" => SignatureType::Proxy,
        "2" => SignatureType::GnosisSafe,
        "3" => SignatureType::Poly1271,
        _ => SignatureType::Eoa,
    };
    
    println!("POLY_SECRET: {}", &pkey[..10]);
    println!("POLY_CLOB_API_URL: {}", api_url);
    println!("POLY_PROXY_WALLET: {:?}", proxy_wallet);
    println!("POLY_SIGNATURE_TYPE: {:?} ({})", sig_type, sig_type_str);
    
    let signer = PrivateKeySigner::from_str(&pkey)
        .expect("Invalid key")
        .with_chain_id(Some(137));
        
    let proxy = proxy_wallet.and_then(|p| Address::from_str(&p).ok());
    
    let config = ClobConfig::default();
    let mut auth_builder = ClobClient::new(&api_url, config)
        .expect("Failed to init CLOB client")
        .authentication_builder(&signer)
        .signature_type(sig_type);
        
    if sig_type != SignatureType::Eoa {
        if let Some(proxy_addr) = proxy {
            println!("Setting funder to: {:?}", proxy_addr);
            auth_builder = auth_builder.funder(proxy_addr);
        }
    }
    
    match auth_builder.authenticate().await {
        Ok(client) => {
            println!("SUCCESS! Authenticated. Address: {:?}", client.address());
            
            use polymarket_client_sdk_v2::clob::types::AssetType;
            use polymarket_client_sdk_v2::clob::types::request::BalanceAllowanceRequest;
            
            // 1. Query Collateral Balance/Allowance
            let req_coll = BalanceAllowanceRequest::builder()
                .asset_type(AssetType::Collateral)
                .signature_type(sig_type)
                .build();
            
            println!("--- Querying Collateral Balance/Allowance (before update) ---");
            match client.balance_allowance(req_coll.clone()).await {
                Ok(resp) => {
                    println!("  Balance: {}", resp.balance);
                    println!("  Allowances: {:?}", resp.allowances);
                }
                Err(e) => {
                    println!("  Error: {:?}", e);
                }
            }
            
            // 2. Force Update
            println!("--- Triggering update_balance_allowance ---");
            match client.update_balance_allowance(req_coll.clone()).await {
                Ok(_) => {
                    println!("  Update trigger sent successfully!");
                }
                Err(e) => {
                    println!("  Error triggering update: {:?}", e);
                }
            }
            
            // 3. Query Collateral Balance/Allowance Again
            println!("--- Querying Collateral Balance/Allowance (after update) ---");
            match client.balance_allowance(req_coll).await {
                Ok(resp) => {
                    println!("  Balance: {}", resp.balance);
                    println!("  Allowances: {:?}", resp.allowances);
                }
                Err(e) => {
                    println!("  Error: {:?}", e);
                }
            }
        }
        Err(e) => {
            println!("FAILURE: {:?}", e);
        }
    }
}
