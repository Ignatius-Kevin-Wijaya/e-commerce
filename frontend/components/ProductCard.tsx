'use client';

/* eslint-disable @next/next/no-img-element */
import Link from 'next/link';
import { Product } from '@/lib/api';
import styles from './ProductCard.module.css';

interface ProductCardProps {
    product: Product;
}

export default function ProductCard({ product }: ProductCardProps) {
    return (
        <Link href={`/products/${product.id}`} className={styles.card}>
            <div className={styles.imageWrap}>
                {product.image_url ? (
                    <img src={product.image_url} alt={product.name} className={styles.image} />
                ) : (
                    <div className={styles.placeholder}>
                        <span>■</span>
                    </div>
                )}
            </div>
            <div className={styles.info}>
                {product.category_name && (
                    <span className={styles.category}>{product.category_name}</span>
                )}
                <h3 className={styles.name}>{product.name}</h3>
                <div className={styles.bottom}>
                    <span className={styles.price}>${product.price.toFixed(2)}</span>
                    {product.stock <= 5 && product.stock > 0 && (
                        <span className={styles.lowStock}>Only {product.stock} left</span>
                    )}
                    {product.stock === 0 && (
                        <span className={styles.outOfStock}>Out of stock</span>
                    )}
                </div>
            </div>
        </Link>
    );
}
