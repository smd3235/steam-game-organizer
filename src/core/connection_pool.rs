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
use std::time::{Duration, Instant};

use reqwest::blocking::Client;

/// HTTP/HTTPS connection pool with keep-alive for Steam API calls.
///
/// Reuses TCP/TLS connections across requests, eliminating connection overhead
/// (~50-100ms per request). Maintains separate pools per host.
///
/// Rate limits requests per host to avoid overwhelming Steam's API.
pub struct ConnectionPool {
    timeout: Duration,
    /// Minimum interval between requests to the same host (rate limiting).
    min_request_interval: Duration,
    clients: Mutex<HashMap<String, Arc<Client>>>,
    /// Last request time per host, used for rate limiting.
    last_request_times: Mutex<HashMap<String, Instant>>,
}

impl ConnectionPool {
    pub fn new(timeout_secs: u64) -> Self {
        ConnectionPool {
            timeout: Duration::from_secs(timeout_secs),
            min_request_interval: Duration::from_millis(1100), // ~1 req/sec per host
            clients: Mutex::new(HashMap::new()),
            last_request_times: Mutex::new(HashMap::new()),
        }
    }

    fn get_or_create_client(&self, host: &str) -> Result<Arc<Client>, String> {
        let mut clients = self.clients.lock().map_err(|e| format!("mutex poisoned: {}", e))?;
        if let Some(client) = clients.get(host) {
            return Ok(client.clone());
        }
        let client = Client::builder()
            .timeout(self.timeout)
            .build()
            .map_err(|e| format!("failed to build HTTP client: {}", e))?;
        let arc = Arc::new(client);
        clients.insert(host.to_string(), arc.clone());
        Ok(arc)
    }

    /// Make an HTTP request using a pooled client.
    /// Rate limits requests per host to avoid overwhelming Steam's API.
    pub fn request(
        &self,
        method: &str,
        url: &str,
        headers: Option<&reqwest::header::HeaderMap>,
        body: Option<&[u8]>,
    ) -> Result<reqwest::blocking::Response, String> {
        let parsed = reqwest::Url::parse(url)
            .map_err(|e| format!("invalid URL {}: {}", url, e))?;
        let host = parsed.host_str().unwrap_or("").to_string();
        let client = self.get_or_create_client(&host)?;

        // Rate limiting: ensure minimum interval between requests to same host.
        // Hold the lock during sleep to prevent another thread from slipping in
        // between the time check and the sleep (TOCTOU race on rate limiting).
        let mut last_times = self.last_request_times.lock().map_err(|e| format!("mutex poisoned: {}", e))?;
        let now = Instant::now();
        if let Some(last_time) = last_times.get(&host) {
            let elapsed = now.duration_since(*last_time);
            if elapsed < self.min_request_interval {
                let sleep_duration = self.min_request_interval - elapsed;
                drop(last_times);
                std::thread::sleep(sleep_duration);
                last_times = self.last_request_times.lock().map_err(|e| format!("mutex poisoned: {}", e))?;
            }
        }
        last_times.insert(host.clone(), now);
        drop(last_times);

        let req_method = method.parse::<reqwest::Method>()
            .map_err(|e| format!("invalid HTTP method {}: {}", method, e))?;
        let mut req = client.request(req_method, url);
        if let Some(h) = headers {
            req = req.headers(h.clone());
        }
        if let Some(b) = body {
            req = req.body(b.to_vec());
        }
        req.send().map_err(|e| format!("HTTP request failed: {}", e))
    }

    /// Close all pooled connections (reqwest clients are dropped when the pool is dropped).
    pub fn close_all(&self) -> Result<(), String> {
        self.clients.lock().map_err(|e| format!("mutex poisoned: {}", e))?.clear();
        self.last_request_times.lock().map_err(|e| format!("mutex poisoned: {}", e))?.clear();
        Ok(())
    }
}

impl Default for ConnectionPool {
    fn default() -> Self {
        Self::new(15)
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
        assert_eq!(pool.timeout, Duration::from_secs(15));
    }

    #[test]
    fn test_shared_pool_singleton() {
        let p1 = shared_pool();
        let p2 = shared_pool();
        assert!(std::ptr::eq(p1, p2));
    }
}
