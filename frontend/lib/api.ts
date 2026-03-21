/**
 * API Client — thin fetch wrapper for the e-commerce API gateway.
 *
 * All requests go through the API Gateway (default: http://localhost:8080).
 * Auth-protected endpoints automatically attach the JWT Bearer token.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

// ── Core fetch wrapper ─────────────────────────────────

async function request<T>(
    path: string,
    options: RequestInit = {}
): Promise<T> {
    const url = `${API_BASE}${path}`;

    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers as Record<string, string> || {}),
    };

    // Attach JWT if available (client-side only)
    if (typeof window !== 'undefined') {
        const token = localStorage.getItem('access_token');
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
    }

    const res = await fetch(url, {
        ...options,
        headers,
    });

    if (res.status === 204) {
        return undefined as T;
    }

    const data = await res.json();

    if (!res.ok) {
        throw new ApiError(res.status, data.detail || 'Something went wrong');
    }

    return data as T;
}

export class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
        super(message);
        this.status = status;
        this.name = 'ApiError';
    }
}

// ── Types ──────────────────────────────────────────────

export interface User {
    id: string;
    email: string;
    username: string;
    full_name: string | null;
    is_active: boolean;
    is_admin: boolean;
    created_at: string;
}

export interface TokenResponse {
    access_token: string;
    refresh_token: string;
    token_type: string;
}

export interface Product {
    id: string;
    name: string;
    description: string | null;
    price: number;
    stock: number;
    category_id: number | null;
    category_name: string | null;
    image_url: string | null;
    created_at: string;
    updated_at: string;
}

export interface PaginatedProducts {
    items: Product[];
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
}

export interface Category {
    id: number;
    name: string;
    description: string | null;
}

export interface CartItem {
    product_id: string;
    product_name: string;
    price: number;
    quantity: number;
    image_url: string;
    subtotal: number;
}

export interface Cart {
    user_id: string;
    items: CartItem[];
    total: number;
    item_count: number;
}

export interface OrderItem {
    id: string;
    product_id: string;
    product_name: string;
    price: number;
    quantity: number;
    subtotal: number;
}

export interface Order {
    id: string;
    user_id: string;
    status: string;
    total_amount: number;
    shipping_address: string | null;
    notes: string | null;
    items: OrderItem[];
    created_at: string;
    updated_at: string;
}

export interface Payment {
    id: string;
    order_id: string;
    user_id: string;
    amount: number;
    currency: string;
    status: string;
    provider: string;
    provider_payment_id: string | null;
    idempotency_key: string;
    error_message: string | null;
    created_at: string;
    updated_at: string;
}

// ── Auth API ───────────────────────────────────────────

export const authApi = {
    register: (data: { email: string; username: string; password: string; full_name?: string }) =>
        request<User>('/auth/register', { method: 'POST', body: JSON.stringify(data) }),

    login: (data: { email: string; password: string }) =>
        request<TokenResponse>('/auth/login', { method: 'POST', body: JSON.stringify(data) }),

    refresh: (refresh_token: string) =>
        request<TokenResponse>('/auth/refresh', { method: 'POST', body: JSON.stringify({ refresh_token }) }),

    logout: (refresh_token: string) =>
        request<{ message: string }>('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token }) }),

    me: () =>
        request<User>('/auth/me'),
};

// ── Product API ────────────────────────────────────────

export const productApi = {
    list: (params?: { page?: number; page_size?: number; category_id?: number; search?: string }) => {
        const query = new URLSearchParams();
        if (params?.page) query.set('page', String(params.page));
        if (params?.page_size) query.set('page_size', String(params.page_size));
        if (params?.category_id) query.set('category_id', String(params.category_id));
        if (params?.search) query.set('search', params.search);
        const qs = query.toString();
        return request<PaginatedProducts>(`/products${qs ? `?${qs}` : ''}`);
    },

    get: (id: string) =>
        request<Product>(`/products/${id}`),

    getCategories: () =>
        request<Category[]>('/categories'),
};

// ── Cart API ───────────────────────────────────────────

export const cartApi = {
    get: () =>
        request<Cart>('/cart'),

    addItem: (data: { product_id: string; product_name: string; price: number; quantity: number; image_url: string }) =>
        request<Cart>('/cart/items', { method: 'POST', body: JSON.stringify(data) }),

    updateQuantity: (productId: string, quantity: number) =>
        request<Cart>(`/cart/items/${productId}`, { method: 'PUT', body: JSON.stringify({ quantity }) }),

    removeItem: (productId: string) =>
        request<Cart>(`/cart/items/${productId}`, { method: 'DELETE' }),

    clear: () =>
        request<void>('/cart', { method: 'DELETE' }),
};

// ── Order API ──────────────────────────────────────────

export const orderApi = {
    create: (data: { shipping_address?: string; notes?: string }) =>
        request<Order>('/orders', { method: 'POST', body: JSON.stringify(data) }),

    list: () =>
        request<Order[]>('/orders'),

    get: (id: string) =>
        request<Order>(`/orders/${id}`),
};

// ── Payment API ────────────────────────────────────────

export const paymentApi = {
    create: (data: { order_id: string; amount: number; currency?: string }) =>
        request<Payment>('/payments', { method: 'POST', body: JSON.stringify(data) }),

    get: (id: string) =>
        request<Payment>(`/payments/${id}`),

    getByOrder: (orderId: string) =>
        request<Payment>(`/payments/order/${orderId}`),
};
