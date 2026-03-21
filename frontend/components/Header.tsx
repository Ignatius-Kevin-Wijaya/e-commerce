'use client';

import Link from 'next/link';
import { useAuth } from '@/lib/auth-context';
import { useEffect, useState } from 'react';
import { cartApi } from '@/lib/api';
import styles from './Header.module.css';

export default function Header() {
    const { user, isAuthenticated, logout } = useAuth();
    const [cartCount, setCartCount] = useState(0);
    const [menuOpen, setMenuOpen] = useState(false);

    useEffect(() => {
        const fetchCart = async () => {
            if (isAuthenticated) {
                try {
                    const cart = await cartApi.get();
                    setCartCount(cart.item_count);
                } catch {
                    setCartCount(0);
                }
            } else {
                setCartCount(0);
            }
        };
        fetchCart();
    }, [isAuthenticated]);

    return (
        <header className={styles.header}>
            <div className={`container ${styles.inner}`}>
                <Link href="/" className={styles.logo}>
                    <span className={styles.logoIcon}>■</span>
                    <span>store</span>
                </Link>

                <nav className={styles.nav}>
                    <Link href="/" className={styles.navLink}>Products</Link>
                    {isAuthenticated && (
                        <>
                            <Link href="/cart" className={styles.navLink}>
                                Cart
                                {cartCount > 0 && <span className={styles.cartBadge}>{cartCount}</span>}
                            </Link>
                            <Link href="/orders" className={styles.navLink}>Orders</Link>
                        </>
                    )}
                </nav>

                <div className={styles.actions}>
                    {isAuthenticated ? (
                        <div className={styles.userMenu}>
                            <button
                                className={styles.userButton}
                                onClick={() => setMenuOpen(!menuOpen)}
                            >
                                <span className={styles.avatar}>
                                    {user?.username?.charAt(0).toUpperCase()}
                                </span>
                                <span className={styles.userName}>{user?.username}</span>
                            </button>
                            {menuOpen && (
                                <div className={styles.dropdown}>
                                    <Link
                                        href="/account"
                                        className={styles.dropdownItem}
                                        onClick={() => setMenuOpen(false)}
                                    >
                                        Account
                                    </Link>
                                    <Link
                                        href="/orders"
                                        className={styles.dropdownItem}
                                        onClick={() => setMenuOpen(false)}
                                    >
                                        My Orders
                                    </Link>
                                    <hr className="divider" />
                                    <button
                                        className={styles.dropdownItem}
                                        onClick={() => { logout(); setMenuOpen(false); }}
                                    >
                                        Log out
                                    </button>
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className={styles.authLinks}>
                            <Link href="/login" className="btn btn-secondary btn-sm">Log in</Link>
                            <Link href="/register" className="btn btn-primary btn-sm">Sign up</Link>
                        </div>
                    )}
                </div>
            </div>
        </header>
    );
}
