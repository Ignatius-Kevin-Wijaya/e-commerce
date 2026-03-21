import styles from './Footer.module.css';

export default function Footer() {
    return (
        <footer className={styles.footer}>
            <div className="container">
                <p className={styles.text}>© {new Date().getFullYear()} Store. All rights reserved.</p>
            </div>
        </footer>
    );
}
