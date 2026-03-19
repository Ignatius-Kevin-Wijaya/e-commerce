import http from 'k6/http';
import { check, group, sleep } from 'k6';

export const options = {
    stages: [
        { duration: '2m', target: 50 }, // Ramp up to 50 VUs
        { duration: '5m', target: 100 }, // Sustain 100 VUs
        { duration: '1m', target: 0 },  // Ramp down to 0
    ],
    thresholds: {
        http_req_duration: ['p(95)<500'], // 95% of requests must complete within 500ms
        http_req_failed: ['rate<0.01'],   // Error rate must be < 1%
    },
};

const BASE_URL = __ENV.API_BASE_URL || 'http://api-gateway.ecommerce.svc.cluster.local:8080';

export default function () {
    // 1. Health checks
    group('Health checks', () => {
        const res = http.get(`${BASE_URL}/health`);
        check(res, { 'is status 200': (r) => r.status === 200 });
    });
    sleep(1);

    // 2. Product browsing
    group('Product browsing', () => {
        const res = http.get(`${BASE_URL}/api/v1/products`);
        check(res, { 'is status 200': (r) => r.status === 200 });
    });
    sleep(1);

    // Note: Full auth/cart/order flow requires specific payloads and state.
    // In a real load test, we'd use setup() or data parametrization to create users.
}
