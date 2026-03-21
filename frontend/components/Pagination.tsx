import styles from './Pagination.module.css';

interface PaginationProps {
    page: number;
    totalPages: number;
    onPageChange: (page: number) => void;
}

export default function Pagination({ page, totalPages, onPageChange }: PaginationProps) {
    if (totalPages <= 1) return null;

    const pages: (number | string)[] = [];
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= page - 1 && i <= page + 1)) {
            pages.push(i);
        } else if (pages[pages.length - 1] !== '...') {
            pages.push('...');
        }
    }

    return (
        <div className={styles.pagination}>
            <button
                className={styles.pageBtn}
                onClick={() => onPageChange(page - 1)}
                disabled={page === 1}
            >
                ←
            </button>
            {pages.map((p, i) =>
                typeof p === 'string' ? (
                    <span key={`ellipsis-${i}`} className={styles.ellipsis}>…</span>
                ) : (
                    <button
                        key={p}
                        className={`${styles.pageBtn} ${p === page ? styles.active : ''}`}
                        onClick={() => onPageChange(p)}
                    >
                        {p}
                    </button>
                )
            )}
            <button
                className={styles.pageBtn}
                onClick={() => onPageChange(page + 1)}
                disabled={page === totalPages}
            >
                →
            </button>
        </div>
    );
}
