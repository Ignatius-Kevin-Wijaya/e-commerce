'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { cartApi, Cart } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import styles from './page.module.css';

export default function CartPage() {
    const router = useRouter();
    const { isAuthenticated, isLoading: authLoading } = useAuth();
    const [cart, setCart] = useState<Cart | null>(null);
    const [loading, setLoading] = useState(true);
    const [updating, setUpdating] = useState<string | null>(null);

    useEffect(() => {
        if (authLoading) return;
        if (!isAuthenticated) {
            setLoading(false);
            return;
        }
        cartApi.get()
            .then(setCart)
            .catch(() => { })
            .finally(() => setLoading(false));
    }, [isAuthenticated, authLoading]);

    const updateQuantity = async (productId: string, quantity: number) => {
        setUpdating(productId);
        try {
            const updated = await cartApi.updateQuantity(productId, quantity);
            setCart(updated);
        } catch { }
        setUpdating(null);
    };

    const removeItem = async (productId: string) => {
        setUpdating(productId);
        try {
            const updated = await cartApi.removeItem(productId);
            setCart(updated);
        } catch { }
        setUpdating(null);
    };

    const clearCart = async () => {
        await cartApi.clear();
        setCart({ user_id: '', items: [], total: 0, item_count: 0 });
    };

    if (loading || authLoading) {
        return (
            <div className="page">
                <div className="container">
                    <div className="loading-container">
                        <div className="spinner spinner-lg" />
                        <span>Loading cart…</span>
                    </div>
                </div>
            </div>
        );
    }

    if (!isAuthenticated) {
        return (
            <div className="page">
                <div className="container">
                    <div className="empty-state">
                        <div className="empty-state-icon">🛒</div>
                        <h3>Sign in to view your cart</h3>
                        <p>You need to be logged in to add items and view your cart.</p>
                        <Link href="/login" className="btn btn-primary mt-lg">Sign in</Link>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="page">
            <div className="container">
                <div className="page-header">
                    <h1>Shopping Cart</h1>
                    {cart && cart.item_count > 0 && (
                        <p>{cart.item_count} item{cart.item_count !== 1 ? 's' : ''} in your cart</p>
                    )}
                </div>

                {!cart || cart.items.length === 0 ? (
                    <div className="empty-state">
                        <div className="empty-state-icon">🛒</div>
                        <h3>Your cart is empty</h3>
                        <p>Browse our products and add items to get started.</p>
                        <Link href="/" className="btn btn-primary mt-lg">Browse Products</Link>
                    </div>
                ) : (
                    <div className={styles.layout}>
                        <div className={styles.items}>
                            {cart.items.map((item) => (
                                <div key={item.product_id} className={styles.item}>
                                    <div className={styles.itemImage}>
                                        {item.image_url ? (
                                            <img src={item.image_url} alt={item.product_name} />
                                        ) : (
                                            <div className={styles.itemPlaceholder}>■</div>
                                        )}
                                    </div>
                                    <div className={styles.itemInfo}>
                                        <Link href={`/products/${item.product_id}`} className={styles.itemName}>
                                            {item.product_name}
                                        </Link>
                                        <span className={styles.itemPrice}>${item.price.toFixed(2)}</span>
                                    </div>
                                    <div className={styles.itemActions}>
                                        <div className={styles.quantityControl}>
                                            <button
                                                className={styles.qtyBtn}
                                                onClick={() => updateQuantity(item.product_id, item.quantity - 1)}
                                                disabled={item.quantity <= 1 || updating === item.product_id}
                                            >
                                                −
                                            </button>
                                            <span className={styles.qtyValue}>{item.quantity}</span>
                                            <button
                                                className={styles.qtyBtn}
                                                onClick={() => updateQuantity(item.product_id, item.quantity + 1)}
                                                disabled={updating === item.product_id}
                                            >
                                                +
                                            </button>
                                        </div>
                                        <span className={styles.subtotal}>${item.subtotal.toFixed(2)}</span>
                                        <button
                                            className={styles.removeBtn}
                                            onClick={() => removeItem(item.product_id)}
                                            disabled={updating === item.product_id}
                                        >
                                            ✕
                                        </button>
                                    </div>
                                </div>
                            ))}
                            <button className="btn btn-secondary btn-sm mt-md" onClick={clearCart}>
                                Clear Cart
                            </button>
                        </div>

                        <div className={styles.summary}>
                            <h3>Order Summary</h3>
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
                            <Link href="/checkout" className="btn btn-primary btn-full btn-lg mt-md">
                                Proceed to Checkout
                            </Link>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
