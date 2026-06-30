use tonic::transport::{Channel, ClientTlsConfig, Endpoint};
use tonic::{service::Interceptor, Request, Status};
use self::orderbook::{L2BookRequest, L2BookUpdate, order_book_streaming_client::OrderBookStreamingClient};

pub mod orderbook {
    tonic::include_proto!("hyperliquid");
}

#[derive(Clone)]
struct AuthInterceptor {
    token: String,
}

impl Interceptor for AuthInterceptor {
    fn call(&mut self, mut request: Request<()>) -> Result<Request<()>, Status> {
        request
            .metadata_mut()
            .insert("authorization", format!("Bearer {}", self.token).parse().unwrap());
        request
            .metadata_mut()
            .insert("x-token", self.token.parse().unwrap());
        Ok(request)
    }
}

pub async fn stream_l2_book(
    url: String,
    coin: String,
    auth_token: String,
) -> Result<tonic::Response<tonic::Streaming<L2BookUpdate>>, String> {
    let domain = url.split(':').next().unwrap_or("").to_string();

    let tls_config = ClientTlsConfig::new()
        .domain_name(domain);

    let channel = Endpoint::from_shared(format!("https://{}", url))
        .map_err(|e| e.to_string())?
        .tls_config(tls_config)
        .map_err(|e| e.to_string())?
        .connect()
        .await
        .map_err(|e| e.to_string())?;

    let interceptor = AuthInterceptor { token: auth_token };
    let mut client = OrderBookStreamingClient::with_interceptor(channel, interceptor);

    let request = tonic::Request::new(L2BookRequest {
        coin,
        n_levels: 20,
        n_sig_figs: Some(3),
        mantissa: Some(1),
    });

    let stream = client.stream_l2_book(request).await.map_err(|e| e.to_string())?;
    Ok(stream)
}
