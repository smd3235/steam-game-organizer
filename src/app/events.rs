//! A small in-process pub/sub bus decoupling background work from the UI.
//!
//! Event carries a name and a payload; EventBus lets any component subscribe by name
//! and emit to every subscriber. Background jobs emit events so the scan feed, the
//! Done screen, and progress bars can react without knowing who produced them.
//!
//! 2026-11-25: Converted from `app/events.py` to Rust in the Rust conversion
//! (one file at a time, tracked on the `Rust-Conversion` branch).

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

/// A named event with an optional payload.
#[derive(Debug, Clone)]
pub struct Event {
    pub name: String,
    pub payload: serde_json::Value,
}

impl Event {
    pub fn new(name: &str, payload: serde_json::Value) -> Self {
        Event {
            name: name.to_string(),
            payload,
        }
    }

    pub fn empty(name: &str) -> Self {
        Event {
            name: name.to_string(),
            payload: serde_json::json!({}),
        }
    }
}

/// An in-process pub/sub bus.
pub struct EventBus {
    handlers: Arc<Mutex<HashMap<String, Vec<Arc<dyn Fn(&Event) + Send + Sync>>>>>,
}

impl EventBus {
    pub fn new() -> Self {
        EventBus {
            handlers: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Subscribe `handler` to events named `name`. Returns a closure that unsubscribes.
    pub fn subscribe<F>(&self, name: &str, handler: F) -> Box<dyn Fn() + Send + Sync>
    where
        F: Fn(&Event) + Send + Sync + 'static,
    {
        let name = name.to_string();
        let handler: Arc<dyn Fn(&Event) + Send + Sync> = Arc::new(handler);
        self.handlers
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .entry(name.clone())
            .or_default()
            .push(Arc::clone(&handler));
        let handlers = Arc::clone(&self.handlers);
        Box::new(move || {
            if let Some(list) = handlers.lock().unwrap_or_else(|e| e.into_inner()).get_mut(&name) {
                list.retain(|h| !Arc::ptr_eq(h, &handler));
            }
        })
    }

    pub fn unsubscribe(&self, name: &str, handler: Arc<dyn Fn(&Event) + Send + Sync>) {
        if let Some(list) = self.handlers.lock().unwrap_or_else(|e| e.into_inner()).get_mut(name) {
            list.retain(|h| !Arc::ptr_eq(h, &handler));
        }
    }

    /// Emit an event to every subscriber. Handlers are copied into a vec before
    /// calling, so a handler that unsubscribes itself mid-emission cannot corrupt
    /// the list being walked.
    pub fn emit(&self, event: &Event) {
        let handlers = {
            let map = self.handlers.lock().unwrap_or_else(|e| e.into_inner());
            map.get(&event.name)
                .map(|list| list.iter().map(Arc::clone).collect::<Vec<_>>())
                .unwrap_or_default()
        };
        for handler in handlers {
            handler(event);
        }
    }
}

impl Default for EventBus {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    #[test]
    fn test_event_bus_subscribe_and_emit() {
        let bus = EventBus::new();
        let received = Arc::new(Mutex::new(Vec::new()));
        let received_clone = Arc::clone(&received);
        let _unsub = bus.subscribe("scan", move |event| {
            received_clone.lock().unwrap().push(event.name.clone());
        });
        bus.emit(&Event::new("scan", serde_json::json!({"x": 1})));
        assert_eq!(received.lock().unwrap().as_slice(), &["scan".to_string()]);
    }

    #[test]
    fn test_event_bus_unsubscribe() {
        let bus = EventBus::new();
        let received = Arc::new(Mutex::new(Vec::new()));
        let received_clone = Arc::clone(&received);
        let _unsub = bus.subscribe("scan", move |event| {
            received_clone.lock().unwrap().push(event.name.clone());
        });
        bus.emit(&Event::new("scan", serde_json::json!({})));
        assert_eq!(received.lock().unwrap().as_slice(), &["scan".to_string()]);
        _unsub();
        bus.emit(&Event::new("scan", serde_json::json!({})));
        assert_eq!(received.lock().unwrap().len(), 1);
    }

    #[test]
    fn test_event_bus_emit_unknown_name() {
        let bus = EventBus::new();
        // Should not panic even with no subscribers
        bus.emit(&Event::new("nonexistent", serde_json::json!({})));
    }
}
