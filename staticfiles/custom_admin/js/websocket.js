// ============================================================================
// WEBSOCKET CONNECTION MANAGER
// Handles WebSocket connections with automatic reconnection and fallback
// ============================================================================

class WebSocketManager {
    constructor(url, options = {}) {
        this.url = url;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = options.maxReconnectAttempts || 5;
        this.reconnectDelay = options.reconnectDelay || 3000;
        this.onMessage = options.onMessage || function () { };
        this.onOpen = options.onOpen || function () { };
        this.onClose = options.onClose || function () { };
        this.onError = options.onError || function () { };
        this.fallbackToPolling = options.fallbackToPolling || false;
        this.pollingInterval = options.pollingInterval || 5000;
        this.pollingTimer = null;

        this.connect();
    }

    connect() {
        try {
            // Determine WebSocket protocol
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}${this.url}`;

            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = (event) => {
                console.log('WebSocket connected:', this.url);
                this.reconnectAttempts = 0;
                this.stopPolling();
                this.onOpen(event);
            };

            this.ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                this.onMessage(data);
            };

            this.ws.onclose = (event) => {
                console.log('WebSocket closed:', this.url);
                this.onClose(event);
                this.handleReconnect();
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.onError(error);
            };

        } catch (error) {
            console.error('WebSocket connection failed:', error);
            this.handleReconnect();
        }
    }

    handleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Reconnecting... Attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts}`);

            setTimeout(() => {
                this.connect();
            }, this.reconnectDelay);
        } else {
            console.log('Max reconnect attempts reached. Falling back to polling.');
            if (this.fallbackToPolling) {
                this.startPolling();
            }
        }
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else {
            console.warn('WebSocket is not connected. Message not sent.');
        }
    }

    close() {
        if (this.ws) {
            this.ws.close();
        }
        this.stopPolling();
    }

    startPolling() {
        if (this.pollingTimer) return;

        console.log('Starting polling fallback...');
        this.pollingTimer = setInterval(() => {
            // Trigger polling callback
            if (typeof this.onPoll === 'function') {
                this.onPoll();
            }
        }, this.pollingInterval);
    }

    stopPolling() {
        if (this.pollingTimer) {
            clearInterval(this.pollingTimer);
            this.pollingTimer = null;
        }
    }
}

// ============================================================================
// DASHBOARD WEBSOCKET
// ============================================================================
function initDashboardWebSocket() {
    const dashboardWs = new WebSocketManager('/ws/admin/dashboard/', {
        onMessage: function (data) {
            if (data.type === 'dashboard_stats') {
                updateDashboardStats(data.data);
            }
        },
        onOpen: function () {
            console.log('Dashboard WebSocket connected');
            showConnectionStatus('connected');
        },
        onClose: function () {
            showConnectionStatus('disconnected');
        },
        fallbackToPolling: true,
        onPoll: function () {
            // Fetch stats via AJAX
            fetchDashboardStats();
        }
    });

    // Request stats every 10 seconds
    setInterval(() => {
        dashboardWs.send({ type: 'request_stats' });
    }, 10000);
}

function updateDashboardStats(stats) {
    // Update stat cards
    updateStatCard('active-auctions', stats.active_auctions);
    updateStatCard('bids-today', stats.bids_today);
    updateStatCard('total-bids', stats.total_bids);
    updateStatCard('revenue-today', '₹' + stats.revenue_today.toLocaleString());
    updateStatCard('total-revenue', '₹' + stats.total_revenue.toLocaleString());
    updateStatCard('online-users', stats.online_users);
    updateStatCard('pending-deliveries', stats.pending_deliveries);
    updateStatCard('pending-payments', stats.pending_payments);
}

function updateStatCard(id, value) {
    const element = document.getElementById(id);
    if (element) {
        // Animate value change
        element.style.transform = 'scale(1.1)';
        setTimeout(() => {
            element.textContent = value;
            element.style.transform = 'scale(1)';
        }, 150);
    }
}

function showConnectionStatus(status) {
    const statusElement = document.getElementById('ws-status');
    if (statusElement) {
        statusElement.className = `ws-status ${status}`;
        statusElement.textContent = status === 'connected' ? '🟢 Live' : '🔴 Offline';
    }
}

function fetchDashboardStats() {
    fetch('/custom-admin/api/stats/')
        .then(response => response.json())
        .then(data => {
            updateDashboardStats(data);
        })
        .catch(error => {
            console.error('Error fetching stats:', error);
        });
}

// ============================================================================
// BID WEBSOCKET
// ============================================================================
function initBidWebSocket() {
    const bidWs = new WebSocketManager('/ws/admin/bids/', {
        onMessage: function (data) {
            if (data.type === 'bid_update') {
                addBidToFeed(data.data);
            }
        },
        onOpen: function () {
            console.log('Bid WebSocket connected');
        }
    });
}

function addBidToFeed(bid) {
    const feedContainer = document.getElementById('bid-feed');
    if (!feedContainer) return;

    const bidElement = document.createElement('div');
    bidElement.className = 'bid-item slide-up';
    bidElement.innerHTML = `
        <div class="bid-user">${bid.user}</div>
        <div class="bid-amount">₹${bid.amount.toLocaleString()}</div>
        <div class="bid-lot">${bid.lot}</div>
        <div class="bid-time">${new Date(bid.timestamp).toLocaleTimeString()}</div>
    `;

    feedContainer.insertBefore(bidElement, feedContainer.firstChild);

    // Remove old bids (keep only last 50)
    const bids = feedContainer.querySelectorAll('.bid-item');
    if (bids.length > 50) {
        bids[bids.length - 1].remove();
    }
}

// ============================================================================
// DELIVERY WEBSOCKET
// ============================================================================
function initDeliveryWebSocket() {
    const deliveryWs = new WebSocketManager('/ws/admin/delivery/', {
        onMessage: function (data) {
            if (data.type === 'delivery_update') {
                handleDeliveryUpdate(data.data);
            }
        },
        onOpen: function () {
            console.log('Delivery WebSocket connected');
        }
    });
}

function handleDeliveryUpdate(delivery) {
    showToast(`Delivery #${delivery.lot_number} status updated to ${delivery.status}`, 'info');

    // Refresh delivery list if on delivery page
    const deliveryList = document.getElementById('delivery-list');
    if (deliveryList) {
        location.reload();
    }
}
