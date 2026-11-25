//! HTTP/HTTPS connection pool with keep-alive for Steam API calls.
//!
//! Reuses TCP/TLS connections across requests, eliminating connection overhead
//! (~50-100ms per request). Maintains separate pools per host.
//!
//! Extracted from services/steam_service.py so the connection-management concern
//! lives in its own module instead of being embedded in SteamService.
//!
//! 2026-11-25: Converted from `core/connection_pool.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use reqwest::blocking::Client;

/// HTTP/HTTPS connection pool with keep-alive for Steam API calls.
///
/// Reuses TCP/TLS connections across requests, eliminating connection overhead
/// (~50-100ms per request). Maintains separate pools per host.
pub struct ConnectionPool {
    _max_connections: usize,
    timeout: Duration,
    clients: Mutex<HashMap<String, Arc<Client>>>,
}

impl ConnectionPool {
    pub fn new(max_connections: usize, timeout_secs: u64) -> Self {
        ConnectionPool {
            _max_connections: max_connections,
            timeout: Duration::from_secs(timeout_secs),
            clients: Mutex::new(HashMap::new()),
        }
    }

    fn get_or_create_client(&self, host: &str) -> Arc<Client> {
        let mut clients = self.clients.lock().unwrap();
        if let Some(client) = clients.get(host) {
            return client.clone();
        }
        let client = Client::builder().timeout(self.timeout).build().expect("client must build");
        let arc = Arc::new(client);
        clients.insert(host.to_string(), arc.clone());
        arc
    }

    /// Make an HTTP request using a pooled client.
    pub fn request(
        &self,
        method: &str,
        url: &str,
        headers: Option<&reqwest::header::HeaderMap>,
        body: Option<&[u8]>,
    ) -> reqwest::blocking::Response {
        let parsed = reqwest::Url::parse(url).expect("URL must be valid");
        let host = parsed.host_str().unwrap_or("").to_string();
        let client = self.get_or_create_client(&host);

        let mut req = client.request(method.parse().unwrap(), url);
        if let Some(h) = headers {
            req = req.headers(h.clone());
        }
        if let Some(b) = body {
            req = req.body(b.to_vec());
        }
        req.send().expect("Request must succeed")
    }

    /// Close all pooled connections (reqwest clients are dropped when the pool is dropped).
    pub fn close_all(&self) {
        self.clients.lock().unwrap().clear();
    }
}

impl Default for ConnectionPool {
    fn default() -> Self {
        Self::new(4, 15)
    }
}

/// Module-level pool shared across SteamService instances.
pub static SHARED_POOL: std::sync::OnceLock<ConnectionPool> = std::sync::OnceLock::new();

pub fn shared_pool() -> &'static ConnectionPool {
    SHARED_POOL.get_or_init(ConnectionPool::default)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_pool() {
        let pool = ConnectionPool::default();
        assert_eq!(pool._max_connections, 4);
        assert_eq!(pool.timeout, Duration::from_secs(15));
    }

    #[test]
    fn test_shared_pool_singleton() {
        let p1 = shared_pool();
        let p2 = shared_pool();
        assert!(std::ptr::eq(p1, p2));
    }
}
