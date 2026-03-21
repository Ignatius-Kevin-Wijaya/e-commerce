'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { orderApi, Order } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import styles from './page.module.css';

function StatusBadge({ status }: { status: string }) {
    return <span className={`badge badge-${status}`}>{status}</span>;
}

export default function OrdersPage() {
    const router = useRouter();
    const { isAuthenticated, isLoading: authLoading } = useAuth();
    const [orders, setOrders] = useState<Order[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (authLoading) return;
        if (!isAuthenticated) {
            router.push('/login');
            return;
        }
        orderApi.list()
            .then(setOrders)
            .catch(() => { })
            .finally(() => setLoading(false));
    }, [isAuthenticated, authLoading, router]);

    if (loading || authLoading) {
        return (
            <div className="page">
                <div className="container">
                    <div className="loading-container">
                        <div className="spinner spinner-lg" />
                        <span>Loading orders…</span>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="page">
            <div className="container">
                <div className="page-header">
                    <h1>My Orders</h1>
                    <p>Track and manage your orders.</p>
                </div>

                {orders.length === 0 ? (
                    <div className="empty-state">
                        <div className="empty-state-icon">📦</div>
                        <h3>No orders yet</h3>
                        <p>When you place an order, it will appear here.</p>
                        <Link href="/" className="btn btn-primary mt-lg">Start Shopping</Link>
                    </div>
                ) : (
                    <div className={styles.orders}>
                        {orders.map((order) => (
                            <Link key={order.id} href={`/orders/${order.id}`} className={styles.orderCard}>
                                <div className={styles.orderHeader}>
                                    <div>
                                        <span className={styles.orderId}>Order #{order.id.slice(0, 8)}</span>
                                        <span className={styles.orderDate}>
                                            {new Date(order.created_at).toLocaleDateString('en-US', {
                                                year: 'numeric',
                                                month: 'long',
                                                day: 'numeric',
                                            })}
                                        </span>
                                    </div>
                                    <StatusBadge status={order.status} />
                                </div>
                                <div className={styles.orderBody}>
                                    <span className={styles.orderItems}>
                                        {order.items.length} item{order.items.length !== 1 ? 's' : ''}
                                    </span>
                                    <span className={styles.orderTotal}>${order.total_amount.toFixed(2)}</span>
                                </div>
                            </Link>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
