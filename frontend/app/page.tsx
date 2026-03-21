'use client';

import { useState, useEffect } from 'react';
import { productApi, Product, Category, PaginatedProducts } from '@/lib/api';
import ProductCard from '@/components/ProductCard';
import Pagination from '@/components/Pagination';
import styles from './page.module.css';

export default function HomePage() {
  const [data, setData] = useState<PaginatedProducts | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [page, setPage] = useState(1);
  const [categoryId, setCategoryId] = useState<number | undefined>(undefined);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    productApi.getCategories().then(setCategories).catch(() => { });
  }, []);

  useEffect(() => {
    setLoading(true);
    productApi
      .list({ page, page_size: 12, category_id: categoryId, search: search || undefined })
      .then(setData)
      .catch(() => { })
      .finally(() => setLoading(false));
  }, [page, categoryId, search]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setSearch(searchInput);
    setPage(1);
  };

  return (
    <div className="page">
      <div className="container">
        <div className={styles.hero}>
          <h1>Explore Products</h1>
          <p>Discover quality items with a simple, clean shopping experience.</p>
        </div>

        <div className={styles.toolbar}>
          <form onSubmit={handleSearch} className={styles.searchForm}>
            <input
              type="text"
              className={`form-input ${styles.searchInput}`}
              placeholder="Search products…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
            <button type="submit" className="btn btn-primary btn-sm">Search</button>
          </form>

          <div className={styles.filters}>
            <button
              className={`${styles.filterBtn} ${!categoryId ? styles.filterActive : ''}`}
              onClick={() => { setCategoryId(undefined); setPage(1); }}
            >
              All
            </button>
            {categories.map((cat) => (
              <button
                key={cat.id}
                className={`${styles.filterBtn} ${categoryId === cat.id ? styles.filterActive : ''}`}
                onClick={() => { setCategoryId(cat.id); setPage(1); }}
              >
                {cat.name}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="loading-container">
            <div className="spinner spinner-lg" />
            <span>Loading products…</span>
          </div>
        ) : data && data.items.length > 0 ? (
          <>
            <div className="grid grid-4">
              {data.items.map((product) => (
                <ProductCard key={product.id} product={product} />
              ))}
            </div>
            <Pagination
              page={data.page}
              totalPages={data.total_pages}
              onPageChange={setPage}
            />
          </>
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">□</div>
            <h3>No products found</h3>
            <p>Try adjusting your search or filters.</p>
          </div>
        )}
      </div>
    </div>
  );
}
