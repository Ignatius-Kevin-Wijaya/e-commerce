'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { cartApi, orderApi, paymentApi, Cart } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import styles from './page.module.css';

export default function CheckoutPage() {
    const router = useRouter();
    const { isAuthenticated, isLoading: authLoading } = useAuth();
    const [cart, setCart] = useState<Cart | null>(null);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [shippingAddress, setShippingAddress] = useState('');
    const [notes, setNotes] = useState('');
    const [error, setError] = useState('');

    useEffect(() => {
        if (authLoading) return;
        if (!isAuthenticated) {
            router.push('/login');
            return;
        }
        cartApi.get()
            .then(setCart)
            .catch(() => { })
            .finally(() => setLoading(false));
    }, [isAuthenticated, authLoading, router]);

    const handlePlaceOrder = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!cart || cart.items.length === 0) return;

        setSubmitting(true);
        setError('');

        try {
            // 1. Create order from cart
            const order = await orderApi.create({
                shipping_address: shippingAddress || undefined,
                notes: notes || undefined,
            });

            // 2. Create payment for the order
            await paymentApi.create({
                order_id: order.id,
                amount: order.total_amount,
            });

            // 3. Navigate to order detail
            router.push(`/orders/${order.id}`);
        } catch (err: unknown) {
            setError((err as Error).message || 'Failed to place order');
        } finally {
            setSubmitting(false);
        }
    };

    if (loading || authLoading) {
        return (
            <div className="page">
                <div className="container">
                    <div className="loading-container">
                        <div className="spinner spinner-lg" />
                        <span>Loading checkout…</span>
                    </div>
                </div>
            </div>
        );
    }

    if (!cart || cart.items.length === 0) {
        return (
            <div className="page">
                <div className="container">
                    <div className="empty-state">
                        <div className="empty-state-icon">🛒</div>
                        <h3>Your cart is empty</h3>
                        <p>Add items to your cart before checking out.</p>
                        <button className="btn btn-primary mt-lg" onClick={() => router.push('/')}>
                            Browse Products
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="page">
            <div className="container">
                <div className="page-header">
                    <h1>Checkout</h1>
                    <p>Review your order and provide shipping details.</p>
                </div>

                {error && (
                    <div className={styles.error}>{error}</div>
                )}

                <form onSubmit={handlePlaceOrder} className={styles.layout}>
                    <div className={styles.formSection}>
                        <h3>Shipping Information</h3>
                        <div className="form-group mt-md">
                            <label className="form-label" htmlFor="address">Shipping Address</label>
                            <textarea
                                id="address"
                                className={`form-input ${styles.textarea}`}
                                placeholder="Enter your shipping address"
                                value={shippingAddress}
                                onChange={(e) => setShippingAddress(e.target.value)}
                                rows={3}
                            />
                        </div>
                        <div className="form-group mt-md">
                            <label className="form-label" htmlFor="notes">Order Notes (optional)</label>
                            <textarea
                                id="notes"
                                className={`form-input ${styles.textarea}`}
                                placeholder="Any special instructions?"
                                value={notes}
                                onChange={(e) => setNotes(e.target.value)}
                                rows={2}
                            />
                        </div>
                    </div>

                    <div className={styles.summary}>
                        <h3>Order Summary</h3>
                        <hr className="divider" />
                        <div className={styles.summaryItems}>
                            {cart.items.map((item) => (
                                <div key={item.product_id} className={styles.summaryItem}>
                                    <span className={styles.summaryItemName}>
                                        {item.product_name} × {item.quantity}
                                    </span>
                                    <span>${item.subtotal.toFixed(2)}</span>
                                </div>
                            ))}
                        </div>
                        <hr className="divider" />
                        <div className={styles.summaryRow}>
                            <span>Subtotal</span>
                            <span>${cart.total.toFixed(2)}</span>
                        </div>
                        <div className={styles.summaryRow}>
                            <span>Shipping</span>
                            <span className="text-muted">Free</span>
                        </div>
                        <hr className="divider" />
                        <div className={`${styles.summaryRow} ${styles.summaryTotal}`}>
                            <span>Total</span>
                            <span>${cart.total.toFixed(2)}</span>
                        </div>
                        <button
                            type="submit"
                            className="btn btn-primary btn-full btn-lg mt-lg"
                            disabled={submitting}
                        >
                            {submitting ? 'Placing Order…' : `Place Order — $${cart.total.toFixed(2)}`}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
