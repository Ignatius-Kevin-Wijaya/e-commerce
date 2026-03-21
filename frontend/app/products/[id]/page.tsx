/* eslint-disable @next/next/no-img-element */
'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { productApi, cartApi, Product } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import styles from './page.module.css';

export default function ProductDetailPage() {
    const params = useParams();
    const router = useRouter();
    const { isAuthenticated } = useAuth();
    const [product, setProduct] = useState<Product | null>(null);
    const [loading, setLoading] = useState(true);
    const [quantity, setQuantity] = useState(1);
    const [adding, setAdding] = useState(false);
    const [added, setAdded] = useState(false);

    useEffect(() => {
        if (params.id) {
            productApi.get(params.id as string)
                .then(setProduct)
                .catch(() => router.push('/'))
                .finally(() => setLoading(false));
        }
    }, [params.id, router]);

    const handleAddToCart = async () => {
        if (!product) return;
        if (!isAuthenticated) {
            router.push('/login');
            return;
        }
        setAdding(true);
        try {
            await cartApi.addItem({
                product_id: product.id,
                product_name: product.name,
                price: product.price,
                quantity,
                image_url: product.image_url || '',
            });
            setAdded(true);
            setTimeout(() => setAdded(false), 2000);
        } catch {
            // handle error
        } finally {
            setAdding(false);
        }
    };

    if (loading) {
        return (
            <div className="page">
                <div className="container">
                    <div className="loading-container">
                        <div className="spinner spinner-lg" />
                        <span>Loading product…</span>
                    </div>
                </div>
            </div>
        );
    }

    if (!product) return null;

    return (
        <div className="page">
            <div className="container">
                <button className={styles.backBtn} onClick={() => router.back()}>
                    ← Back
                </button>

                <div className={styles.layout}>
                    <div className={styles.imageSection}>
                        {product.image_url ? (
                            <img src={product.image_url} alt={product.name} className={styles.image} />
                        ) : (
                            <div className={styles.placeholder}>
                                <span>■</span>
                            </div>
                        )}
                    </div>

                    <div className={styles.details}>
                        {product.category_name && (
                            <span className={styles.category}>{product.category_name}</span>
                        )}
                        <h1 className={styles.name}>{product.name}</h1>
                        <p className={styles.price}>${product.price.toFixed(2)}</p>

                        {product.description && (
                            <p className={styles.description}>{product.description}</p>
                        )}

                        <div className={styles.stock}>
                            {product.stock > 0 ? (
                                <span className="text-success">● In stock ({product.stock} available)</span>
                            ) : (
                                <span className="text-error">● Out of stock</span>
                            )}
                        </div>

                        {product.stock > 0 && (
                            <div className={styles.actions}>
                                <div className={styles.quantityControl}>
                                    <button
                                        className={styles.qtyBtn}
                                        onClick={() => setQuantity(Math.max(1, quantity - 1))}
                                    >
                                        −
                                    </button>
                                    <span className={styles.qtyValue}>{quantity}</span>
                                    <button
                                        className={styles.qtyBtn}
                                        onClick={() => setQuantity(Math.min(product.stock, quantity + 1))}
                                    >
                                        +
                                    </button>
                                </div>
                                <button
                                    className={`btn btn-primary btn-lg ${styles.addBtn}`}
                                    onClick={handleAddToCart}
                                    disabled={adding}
                                >
                                    {adding ? 'Adding…' : added ? '✓ Added to Cart' : 'Add to Cart'}
                                </button>
                            </div>
                        )}

                        <div className={styles.meta}>
                            <small>Product ID: {product.id}</small>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
