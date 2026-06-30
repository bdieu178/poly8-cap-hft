use serde::Deserialize;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Deserialize, Debug)]
pub struct Market {
    #[serde(rename = "clobTokenIds")]
    pub clob_token_ids: Vec<String>,
    pub outcomes: Vec<String>,
}

fn get_current_interval_timestamp(interval_minutes: u64) -> u64 {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("Time went backwards")
        .as_secs();
    (now / (interval_minutes * 60) + 1) * (interval_minutes * 60)
}

pub async fn fetch_active_token_ids(base_url: &str, asset: &str) -> Result<(String, String), Box<dyn std::error::Error>> {
    for timeframe in ["5m", "15m"].iter() {
        let interval_minutes = if *timeframe == "5m" { 5 } else { 15 };
        let ts = get_current_interval_timestamp(interval_minutes);
        let slug = format!("{}-updown-{}-{}", asset, timeframe, ts);
        let url = format!("{}/markets?slug={}", base_url, slug);

        println!("Fetching token IDs from URL: {}", url);
        let markets: Vec<Market> = reqwest::get(&url).await?.json().await?;

        if let Some(market) = markets.get(0) {
            let clob_ids = &market.clob_token_ids;
            let outcomes = &market.outcomes;

            let mut up_id = None;
            let mut down_id = None;

            for (i, outcome) in outcomes.iter().enumerate() {
                if i < clob_ids.len() {
                    if outcome.to_lowercase() == "up" {
                        up_id = Some(clob_ids[i].clone());
                    } else if outcome.to_lowercase() == "down" {
                        down_id = Some(clob_ids[i].clone());
                    }
                }
            }

            if let (Some(up), Some(down)) = (up_id, down_id) {
                println!("Found UP token ID: {}", up);
                println!("Found DOWN token ID: {}", down);
                return Ok((up, down));
            }
        }
    }

    Err("No active markets found".into())
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_current_interval_timestamp() {
        // Test that the function returns a timestamp that is a multiple of the interval
        let interval = 15;
        let ts = get_current_interval_timestamp(interval);
        assert_eq!(ts % (interval * 60), 0, "Timestamp should be a multiple of the interval in seconds");

        // Test that the timestamp is in the future
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        assert!(ts >= now, "Timestamp should be in the future or now");
    }

    #[test]
    fn test_json_parsing() {
        let json_data = r#"
        [
            {
                "id": "0x123",
                "clobTokenIds": ["1111111111111111111111111111111111111111111111111111111111111111111", "2222222222222222222222222222222222222222222222222222222222222222222"],
                "outcomes": ["Up", "Down"]
            }
        ]
        "#;

        let markets: Vec<Market> = serde_json::from_str(json_data).unwrap();
        assert_eq!(markets.len(), 1);
        let market = &markets[0];

        assert_eq!(market.clob_token_ids.len(), 2);
        assert_eq!(market.outcomes.len(), 2);
        assert_eq!(market.clob_token_ids[0], "1111111111111111111111111111111111111111111111111111111111111111111");
        assert_eq!(market.outcomes[0], "Up");
        assert_eq!(market.clob_token_ids[1], "2222222222222222222222222222222222222222222222222222222222222222222");
        assert_eq!(market.outcomes[1], "Down");
    }
}
