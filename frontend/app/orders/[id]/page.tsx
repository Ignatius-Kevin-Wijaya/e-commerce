'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { orderApi, paymentApi, Order, Payment } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import styles from './page.module.css';

export default function OrderDetailPage() {
    const params = useParams();
    const router = useRouter();
    const { isAuthenticated, isLoading: authLoading } = useAuth();
    const [order, setOrder] = useState<Order | null>(null);
    const [payment, setPayment] = useState<Payment | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (authLoading) return;
        if (!isAuthenticated) {
            router.push('/login');
            return;
        }
        if (params.id) {
            Promise.all([
                orderApi.get(params.id as string),
                paymentApi.getByOrder(params.id as string).catch(() => null),
            ])
                .then(([orderData, paymentData]) => {
                    setOrder(orderData);
                    setPayment(paymentData);
                })
                .catch(() => router.push('/orders'))
                .finally(() => setLoading(false));
        }
    }, [params.id, isAuthenticated, authLoading, router]);

    if (loading || authLoading) {
        return (
            <div className="page">
                <div className="container">
                    <div className="loading-container">
                        <div className="spinner spinner-lg" />
                        <span>Loading order…</span>
                    </div>
                </div>
            </div>
        );
    }

    if (!order) return null;

    return (
        <div className="page">
            <div className="container">
                <Link href="/orders" className={styles.backBtn}>← Back to Orders</Link>

                <div className={styles.header}>
                    <div>
                        <h1>Order #{order.id.slice(0, 8)}</h1>
                        <p className={styles.date}>
                            Placed on {new Date(order.created_at).toLocaleDateString('en-US', {
                                year: 'numeric',
                                month: 'long',
                                day: 'numeric',
                                hour: '2-digit',
                                minute: '2-digit',
                            })}
                        </p>
                    </div>
                    <span className={`badge badge-${order.status}`}>{order.status}</span>
                </div>

                <div className={styles.grid}>
                    <div className={styles.section}>
                        <h3>Items</h3>
                        <div className={styles.items}>
                            {order.items.map((item) => (
                                <div key={item.id} className={styles.item}>
                                    <div className={styles.itemInfo}>
                                        <span className={styles.itemName}>{item.product_name}</span>
                                        <span className={styles.itemMeta}>
                                            ${item.price.toFixed(2)} × {item.quantity}
                                        </span>
                                    </div>
                                    <span className={styles.itemSubtotal}>${item.subtotal.toFixed(2)}</span>
                                </div>
                            ))}
                        </div>
                        <hr className="divider" />
                        <div className={styles.totalRow}>
                            <span>Total</span>
                            <span className={styles.total}>${order.total_amount.toFixed(2)}</span>
                        </div>
                    </div>

                    <div className={styles.sidebar}>
                        {order.shipping_address && (
                            <div className={styles.section}>
                                <h3>Shipping Address</h3>
                                <p className={styles.address}>{order.shipping_address}</p>
                            </div>
                        )}

                        {order.notes && (
                            <div className={styles.section}>
                                <h3>Notes</h3>
                                <p className={styles.notes}>{order.notes}</p>
                            </div>
                        )}

                        {payment && (
                            <div className={styles.section}>
                                <h3>Payment</h3>
                                <div className={styles.paymentInfo}>
                                    <div className={styles.paymentRow}>
                                        <span>Status</span>
                                        <span className={`badge badge-${payment.status}`}>{payment.status}</span>
                                    </div>
                                    <div className={styles.paymentRow}>
                                        <span>Amount</span>
                                        <span>${payment.amount.toFixed(2)} {payment.currency}</span>
                                    </div>
                                    <div className={styles.paymentRow}>
                                        <span>Provider</span>
                                        <span>{payment.provider}</span>
                                    </div>
                                </div>
                            </div>
                        )}

                        <div className={styles.section}>
                            <h3>Timeline</h3>
                            <div className={styles.timeline}>
                                <div className={styles.timelineItem}>
                                    <span className={styles.timelineDot} />
                                    <div>
                                        <span className={styles.timelineLabel}>Created</span>
                                        <span className={styles.timelineDate}>
                                            {new Date(order.created_at).toLocaleString()}
                                        </span>
                                    </div>
                                </div>
                                <div className={styles.timelineItem}>
                                    <span className={styles.timelineDot} />
                                    <div>
                                        <span className={styles.timelineLabel}>Last Updated</span>
                                        <span className={styles.timelineDate}>
                                            {new Date(order.updated_at).toLocaleString()}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
