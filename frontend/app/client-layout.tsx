'use client';

import { AuthProvider } from '@/lib/auth-context';
import Header from '@/components/Header';
import Footer from '@/components/Footer';

export default function ClientLayout({ children }: { children: React.ReactNode }) {
    return (
        <AuthProvider>
            <Header />
            <main>{children}</main>
            <Footer />
        </AuthProvider>
    );
}
