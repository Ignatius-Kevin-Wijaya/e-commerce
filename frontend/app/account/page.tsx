'use client';

import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth-context';
import { useEffect } from 'react';
import styles from './page.module.css';

export default function AccountPage() {
    const router = useRouter();
    const { user, isAuthenticated, isLoading, logout } = useAuth();

    useEffect(() => {
        if (!isLoading && !isAuthenticated) {
            router.push('/login');
        }
    }, [isLoading, isAuthenticated, router]);

    if (isLoading || !user) {
        return (
            <div className="page">
                <div className="container">
                    <div className="loading-container">
                        <div className="spinner spinner-lg" />
                        <span>Loading profile…</span>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="page">
            <div className="container">
                <div className="page-header">
                    <h1>Account</h1>
                    <p>Manage your profile and settings.</p>
                </div>

                <div className={styles.layout}>
                    <div className={styles.card}>
                        <div className={styles.avatarLarge}>
                            {user.username.charAt(0).toUpperCase()}
                        </div>
                        <h2>{user.full_name || user.username}</h2>
                        <p className="text-muted">@{user.username}</p>
                    </div>

                    <div className={styles.details}>
                        <div className={styles.card}>
                            <h3>Profile Information</h3>
                            <div className={styles.fields}>
                                <div className={styles.field}>
                                    <span className={styles.fieldLabel}>Email</span>
                                    <span className={styles.fieldValue}>{user.email}</span>
                                </div>
                                <div className={styles.field}>
                                    <span className={styles.fieldLabel}>Username</span>
                                    <span className={styles.fieldValue}>@{user.username}</span>
                                </div>
                                <div className={styles.field}>
                                    <span className={styles.fieldLabel}>Full Name</span>
                                    <span className={styles.fieldValue}>{user.full_name || '—'}</span>
                                </div>
                                <div className={styles.field}>
                                    <span className={styles.fieldLabel}>Member Since</span>
                                    <span className={styles.fieldValue}>
                                        {new Date(user.created_at).toLocaleDateString('en-US', {
                                            year: 'numeric',
                                            month: 'long',
                                            day: 'numeric',
                                        })}
                                    </span>
                                </div>
                                <div className={styles.field}>
                                    <span className={styles.fieldLabel}>Status</span>
                                    <span className={`badge ${user.is_active ? 'badge-delivered' : 'badge-cancelled'}`}>
                                        {user.is_active ? 'Active' : 'Inactive'}
                                    </span>
                                </div>
                                {user.is_admin && (
                                    <div className={styles.field}>
                                        <span className={styles.fieldLabel}>Role</span>
                                        <span className="badge badge-confirmed">Admin</span>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className={styles.card}>
                            <h3>Account Actions</h3>
                            <div className={styles.actions}>
                                <button className="btn btn-danger" onClick={logout}>
                                    Log Out
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
