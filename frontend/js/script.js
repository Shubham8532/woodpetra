/**
 * ============================================================
 *  SHUBHAM FASHION — Main Script
 *  Handles: CSV parsing, product rendering, search, filters,
 *           modals, cart UI, animations, navigation
 * ============================================================
 */

'use strict';

/* ─────────────────────────────────────────
   CONSTANTS
───────────────────────────────────────── */
const CSV_FILE   = '../../data/Shubham_Fashion_Current_Template.csv';
const CSV_CDN    = 'https://cdnjs.cloudflare.com/ajax/libs/PapaParse/5.4.1/papaparse.min.js';
const PLACEHOLDER_BASE = 'https://placehold.co/600x600?text=';
const ITEMS_PER_PAGE   = 12;

/* ─────────────────────────────────────────
   STATE
───────────────────────────────────────── */
const State = {
  allProducts:      [],   // raw parsed products
  filteredProducts: [],   // after search/filter
  currentPage:      1,
  cartCount:        0,
};

/* ─────────────────────────────────────────
   UTILITY HELPERS
───────────────────────────────────────── */

/** Safe JSON parse — returns null on failure */
function safeJSON(str) {
  try { return JSON.parse(str); }
  catch { return null; }
}

/** Generate star HTML from numeric rating (0-5) */
function renderStars(rating) {
  const full  = Math.floor(rating);
  const half  = rating - full >= 0.5 ? 1 : 0;
  const empty = 5 - full - half;
  return (
    '★'.repeat(full) +
    (half ? '½' : '') +
    '☆'.repeat(empty)
  );
}

/** Format price in Indian Rupees */
function formatPrice(price) {
  return Number(price).toLocaleString('en-IN');
}

/** Stock badge HTML */
function stockBadge(stock) {
  stock = Number(stock);
  if (stock === 0)   return `<span class="badge badge-danger">Out of Stock</span>`;
  if (stock <= 5)    return `<span class="badge badge-warning">Only ${stock} left</span>`;
  if (stock <= 15)   return `<span class="badge badge-accent">Low Stock</span>`;
  return `<span class="badge badge-success">In Stock</span>`;
}

/** Placeholder fallback for broken images */
function imgFallback(el, sku) {
  el.src = `${PLACEHOLDER_BASE}${encodeURIComponent(sku || 'SF')}`;
}

/** Show a toast notification */
function showToast(msg, icon = '✓') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `<span>${icon}</span> ${msg}`;
  container.appendChild(toast);

  setTimeout(() => toast.remove(), 3000);
}

/* ─────────────────────────────────────────
   CSV LOADER — PapaParse CDN
───────────────────────────────────────── */

/** Dynamically load PapaParse then parse CSV */
function loadCSV(onSuccess, onError) {
  if (window.Papa) {
    parseCSV(onSuccess, onError);
    return;
  }
  const script  = document.createElement('script');
  script.src    = CSV_CDN;
  script.onload = () => parseCSV(onSuccess, onError);
  script.onerror = () => onError('Failed to load CSV parser (PapaParse).');
  document.head.appendChild(script);
}

function parseCSV(onSuccess, onError) {
  Papa.parse(CSV_FILE, {
    download:    true,
    header:      true,
    skipEmptyLines: true,
    complete(results) {
      const products = results.data.map(parseRow).filter(Boolean);
      if (products.length === 0) {
        onError('CSV loaded but no products found.');
        return;
      }
      onSuccess(products);
    },
    error(err) {
      onError(`Unable to load products. (${err.message})`);
    }
  });
}

/**
 * Convert a CSV row into a product object.
 * Schema: name, description, price, category, image_url, website_url,
 *         product_url, stock, currency, payment_link, sku, color, size,
 *         required_fields, attributes
 * The `attributes` column contains a JSON object of variant arrays:
 *   { "color": ["Black", "White"], "size": ["S", "M", "L"] }
 * The `required_fields` column contains a JSON array of field names:
 *   ["color", "size"]
 */
function parseRow(row) {
  try {
    // Parse the attributes variant object: { color: [...], size: [...] }
    const attrs         = safeJSON(row.attributes) || {};
    // Parse the required_fields array: ["color", "size"]
    const requiredFields = safeJSON(row.required_fields) || [];

    // Top-level color/size columns are the selected/default variant values.
    // attributes.color / attributes.size are arrays of all available variants.
    const color = row.color || (Array.isArray(attrs.color) ? attrs.color[0] : '') || '';
    const size  = row.size  || (Array.isArray(attrs.size)  ? attrs.size[0]  : '') || '';

    return {
      // ── Core columns (direct from CSV) ──────────────────────────────
      name:           row.name        || 'Unnamed Product',
      description:    row.description || '',
      price:          Number(row.price) || 0,
      category:       row.category    || 'Uncategorized',
      image_url:      row.image_url   || PLACEHOLDER_BASE + encodeURIComponent(row.sku || 'SF'),
      website_url:    row.website_url || '',
      product_url:    row.product_url || '#',
      stock:          Number(row.stock) || 0,
      currency:       row.currency    || 'INR',
      payment_link:   row.payment_link || '',
      sku:            row.sku         || '',
      color:          color,
      size:           size,
      required_fields: requiredFields,

      // ── Variant arrays from attributes JSON ─────────────────────────
      available_colors: Array.isArray(attrs.color) ? attrs.color : (color ? [color] : []),
      available_sizes:  Array.isArray(attrs.size)  ? attrs.size  : (size  ? [size]  : []),

      // ── Derived / compatibility fields (graceful defaults) ───────────
      // These fields no longer exist in the new schema; keeping them
      // so existing card/modal rendering continues to work without errors.
      brand:       'Shubham Fashion',
      collection:  '',
      gender:      '',
      material:    '',
      fit:         '',
      rating:      0,
      reviews:     0,
    };
  } catch { return null; }
}

/* ─────────────────────────────────────────
   PRODUCT CARD HTML
───────────────────────────────────────── */
function buildProductCard(product, index) {
  const stockOut = Number(product.stock) === 0;
  return `
    <article class="product-card fade-in" data-index="${index}" role="article" aria-label="${product.name}">
      <div class="product-image-wrap">
        <img
          src="${product.image_url}"
          alt="${product.name}"
          loading="lazy"
          onerror="imgFallback(this,'${product.sku}')"
        />
        <div class="product-badge">${stockBadge(product.stock)}</div>
        <button class="product-wishlist" aria-label="Add to wishlist" onclick="handleWishlist(event,'${product.name}')">
          ♡
        </button>
        <div class="product-image-overlay">
          <button
            class="btn btn-ghost btn-sm"
            onclick="openModal(${index})"
            aria-label="Quick view ${product.name}"
            ${stockOut ? 'disabled' : ''}
          >
            Quick View
          </button>
          <button
            class="btn btn-primary btn-sm"
            onclick="addToCart('${product.name}')"
            aria-label="Add ${product.name} to cart"
            ${stockOut ? 'disabled' : ''}
          >
            ${stockOut ? 'Out of Stock' : 'Add to Cart'}
          </button>
        </div>
      </div>
      <div class="product-body">
        <div class="product-category">${product.category}</div>
        <h3 class="product-name">${product.name}</h3>
        <div class="product-rating">
          <span class="text-xs text-muted" style="color:var(--color-muted)">${product.color ? '● ' + product.color : ''} ${product.size ? '| ' + product.size : ''}</span>
          <span class="badge badge-accent" style="font-size:0.65rem">${product.currency || 'INR'}</span>
        </div>
        <div class="product-footer">
          <div class="product-price">
            <span class="currency">₹</span>${formatPrice(product.price)}
          </div>
          <button
            class="btn btn-outline btn-sm"
            onclick="openModal(${index})"
            aria-label="View details for ${product.name}"
          >
            Details
          </button>
        </div>
      </div>
    </article>
  `;
}

/* ─────────────────────────────────────────
   MODAL
───────────────────────────────────────── */
let modalProducts = [];  // products array accessible to modal

function openModal(index) {
  const p = modalProducts[index];
  if (!p) return;

  const overlay = document.getElementById('product-modal');
  if (!overlay) return;

  document.getElementById('modal-img').src         = p.image_url;
  document.getElementById('modal-img').alt         = p.name;
  document.getElementById('modal-img').onerror     = () => imgFallback(document.getElementById('modal-img'), p.sku);
  document.getElementById('modal-category').textContent = p.category || '';
  document.getElementById('modal-name').textContent     = p.name;
  document.getElementById('modal-price').innerHTML = `<span class="currency-sym">${p.currency === 'INR' ? '₹' : p.currency}</span>${formatPrice(p.price)}`;

  // New schema: no rating/reviews — show stock + SKU instead
  document.getElementById('modal-rating').innerHTML = `
    ${stockBadge(p.stock)}
    <span style="font-size:0.78rem;color:var(--color-muted);margin-left:8px">SKU: ${p.sku || '—'}</span>
  `;

  document.getElementById('modal-description').textContent = p.description || 'Premium quality fashion product by Shubham Fashion.';

  // Stock badge moved into rating slot above; set the dedicated stock span too
  const stockEl = document.getElementById('modal-stock');
  if (stockEl) stockEl.innerHTML = stockBadge(p.stock);

  // Available colors (from attributes array)
  const colorsEl = document.getElementById('modal-color');
  if (colorsEl) {
    if (p.available_colors && p.available_colors.length > 1) {
      colorsEl.innerHTML = p.available_colors.map(c =>
        `<span style="display:inline-block;padding:2px 10px;border-radius:20px;font-size:0.75rem;font-weight:600;margin:2px;background:${c===p.color?'var(--color-primary)':'var(--color-bg-alt)'};color:${c===p.color?'#fff':'var(--color-primary)'};border:1.5px solid var(--color-border)">${c}</span>`
      ).join('');
    } else {
      colorsEl.textContent = p.color || '—';
    }
  }

  // Available sizes (from attributes array)
  const sizesEl = document.getElementById('modal-size');
  if (sizesEl) {
    if (p.available_sizes && p.available_sizes.length > 1) {
      sizesEl.innerHTML = p.available_sizes.map(s =>
        `<span style="display:inline-block;padding:2px 10px;border-radius:20px;font-size:0.75rem;font-weight:600;margin:2px;background:${s===p.size?'var(--color-primary)':'var(--color-bg-alt)'};color:${s===p.size?'#fff':'var(--color-primary)'};border:1.5px solid var(--color-border)">${s}</span>`
      ).join('');
    } else {
      sizesEl.textContent = p.size || '—';
    }
  }

  // Fields not present in new schema — graceful fallback
  const matEl = document.getElementById('modal-material');
  if (matEl) matEl.textContent = p.material || '—';
  const fitEl = document.getElementById('modal-fit');
  if (fitEl) fitEl.textContent = p.fit || '—';
  const skuEl = document.getElementById('modal-sku');
  if (skuEl) skuEl.textContent = p.sku || '—';
  const colEl = document.getElementById('modal-collection');
  if (colEl) colEl.textContent = p.collection || '—';

  const addBtn = document.getElementById('modal-add-btn');
  if (addBtn) {
    if (p.stock === 0) {
      addBtn.textContent = 'Out of Stock';
      addBtn.disabled    = true;
    } else {
      addBtn.textContent = 'Add to Cart';
      addBtn.disabled    = false;
      addBtn.onclick     = () => { addToCart(p.name); };
    }
  }

  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  const overlay = document.getElementById('product-modal');
  if (overlay) overlay.classList.remove('open');
  document.body.style.overflow = '';
}

/* ─────────────────────────────────────────
   CART (UI only)
───────────────────────────────────────── */
function addToCart(productName) {
  State.cartCount++;
  const badge = document.querySelectorAll('.cart-count');
  badge.forEach(b => { b.textContent = State.cartCount; });
  showToast(`"${productName}" added to cart`, '🛒');
}

function handleWishlist(e, productName) {
  e.stopPropagation();
  const btn = e.currentTarget;
  const isWished = btn.textContent === '♥';
  btn.textContent = isWished ? '♡' : '♥';
  btn.style.color = isWished ? '' : '#dc2626';
  showToast(isWished ? `Removed from wishlist` : `"${productName}" saved!`, isWished ? '💔' : '♥');
}

/* ─────────────────────────────────────────
   SCROLL ANIMATIONS
───────────────────────────────────────── */
function initScrollAnimations() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

  document.querySelectorAll('.fade-in, .stagger-children').forEach(el => observer.observe(el));
}

/* ─────────────────────────────────────────
   STICKY NAVBAR
───────────────────────────────────────── */
function initNavbar() {
  const navbar = document.querySelector('.navbar');
  if (!navbar) return;

  window.addEventListener('scroll', () => {
    navbar.classList.toggle('scrolled', window.scrollY > 30);
  }, { passive: true });

  // Hamburger toggle
  const hamburger = document.querySelector('.hamburger');
  const mobileNav = document.querySelector('.mobile-nav');

  if (hamburger && mobileNav) {
    hamburger.addEventListener('click', () => {
      const open = hamburger.classList.toggle('open');
      mobileNav.classList.toggle('open', open);
      document.body.style.overflow = open ? 'hidden' : '';
    });

    // Close on mobile nav link click
    mobileNav.querySelectorAll('a').forEach(a => {
      a.addEventListener('click', () => {
        hamburger.classList.remove('open');
        mobileNav.classList.remove('open');
        document.body.style.overflow = '';
      });
    });
  }

  // Active nav link
  const currentPage = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-links a, .mobile-nav a').forEach(a => {
    const href = a.getAttribute('href');
    if (href === currentPage || (currentPage === '' && href === 'index.html')) {
      a.classList.add('active');
    }
  });
}

/* ─────────────────────────────────────────
   NAVBAR SEARCH ICON
───────────────────────────────────────── */
function initNavSearch() {
  const searchBtn = document.getElementById('nav-search-btn');
  if (!searchBtn) return;

  searchBtn.addEventListener('click', () => {
    const isProductsPage = window.location.pathname.includes('products');
    if (isProductsPage) {
      const input = document.getElementById('search-input');
      if (input) { input.focus(); return; }
    }
    window.location.href = 'products.html';
  });
}

/* ─────────────────────────────────────────
   HOME PAGE — FEATURED PRODUCTS
───────────────────────────────────────── */
function initHomePage() {
  const grid = document.getElementById('featured-products-grid');
  if (!grid) return;

  const skeletons = Array.from({ length: 8 }, () => buildSkeleton()).join('');
  grid.innerHTML = skeletons;

  loadCSV(products => {
    State.allProducts = products;
    modalProducts     = products;

    // Show top 8 by rating
    const featured = [...products]
      .sort((a, b) => b.rating - a.rating || b.reviews - a.reviews)
      .slice(0, 8);

    grid.innerHTML = featured.map((p, i) => buildProductCard(p, products.indexOf(p))).join('');
    initScrollAnimations();

  }, err => {
    grid.innerHTML = errorState(err);
  });

  // Newsletter form
  const newsletterForm = document.getElementById('newsletter-form');
  if (newsletterForm) {
    newsletterForm.addEventListener('submit', e => {
      e.preventDefault();
      showToast('Thank you for subscribing! 🎉', '✓');
      newsletterForm.reset();
    });
  }
}

/* ─────────────────────────────────────────
   PRODUCTS PAGE — Full listing, search, filter
───────────────────────────────────────── */
function initProductsPage() {
  const grid = document.getElementById('products-main-grid');
  if (!grid) return;

  grid.innerHTML = buildLoadingGrid(ITEMS_PER_PAGE);

  loadCSV(products => {
    State.allProducts     = products;
    State.filteredProducts = products;
    modalProducts          = products;

    buildCategoryFilters(products);
    renderProductsGrid();
    initFilters();
    initScrollAnimations();

  }, err => {
    grid.innerHTML = errorState(err);
  });
}

/** Build category <option> elements from data */
function buildCategoryFilters(products) {
  const sel = document.getElementById('category-filter');
  if (!sel) return;

  const cats = [...new Set(products.map(p => p.category))].sort();
  cats.forEach(cat => {
    const opt = document.createElement('option');
    opt.value       = cat;
    opt.textContent = cat;
    sel.appendChild(opt);
  });
}

/** Render current page of filteredProducts into the grid */
function renderProductsGrid() {
  const grid = document.getElementById('products-main-grid');
  if (!grid) return;

  const total  = State.filteredProducts.length;
  const start  = (State.currentPage - 1) * ITEMS_PER_PAGE;
  const end    = start + ITEMS_PER_PAGE;
  const slice  = State.filteredProducts.slice(start, end);

  updateResultsCount(total);

  if (total === 0) {
    grid.innerHTML = noResults();
  } else {
    grid.innerHTML = slice.map((p, i) => buildProductCard(p, State.allProducts.indexOf(p))).join('');
    initScrollAnimations();
  }

  renderPagination(total);
}

function updateResultsCount(total) {
  const el = document.getElementById('results-count');
  if (el) el.textContent = `${total} product${total !== 1 ? 's' : ''} found`;
}

/** Pagination */
function renderPagination(total) {
  const wrap = document.getElementById('pagination');
  if (!wrap) return;

  const pages = Math.ceil(total / ITEMS_PER_PAGE);
  if (pages <= 1) { wrap.innerHTML = ''; return; }

  let html = '';

  const prev = State.currentPage > 1;
  html += `<button class="page-btn" ${prev ? '' : 'disabled'} onclick="goToPage(${State.currentPage - 1})">‹</button>`;

  for (let i = 1; i <= pages; i++) {
    if (i === 1 || i === pages || Math.abs(i - State.currentPage) <= 2) {
      html += `<button class="page-btn ${i === State.currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    } else if (Math.abs(i - State.currentPage) === 3) {
      html += `<span style="padding:0 4px;color:var(--color-muted)">…</span>`;
    }
  }

  const next = State.currentPage < pages;
  html += `<button class="page-btn" ${next ? '' : 'disabled'} onclick="goToPage(${State.currentPage + 1})">›</button>`;

  wrap.innerHTML = html;
}

function goToPage(page) {
  State.currentPage = page;
  renderProductsGrid();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/** Search, Category, Sort filters */
function initFilters() {
  const searchInput    = document.getElementById('search-input');
  const categoryFilter = document.getElementById('category-filter');
  const sortFilter     = document.getElementById('sort-filter');

  function applyFilters() {
    const query    = (searchInput?.value || '').toLowerCase().trim();
    const category = categoryFilter?.value || '';
    const sort     = sortFilter?.value || '';

    let results = State.allProducts.filter(p => {
      // Search across name, category, description, color, material
      const matchesQuery = !query || [
        p.name, p.category, p.description, p.color, p.material, p.brand
      ].some(field => field?.toLowerCase().includes(query));

      const matchesCat = !category || p.category === category;

      return matchesQuery && matchesCat;
    });

    // Sort
    switch (sort) {
      case 'price-asc':  results.sort((a,b) => a.price - b.price); break;
      case 'price-desc': results.sort((a,b) => b.price - a.price); break;
      case 'name-asc':   results.sort((a,b) => a.name.localeCompare(b.name)); break;
      case 'name-desc':  results.sort((a,b) => b.name.localeCompare(a.name)); break;
      case 'stock-desc': results.sort((a,b) => b.stock - a.stock); break;
      case 'stock-asc':  results.sort((a,b) => a.stock - b.stock); break;
    }

    State.filteredProducts = results;
    State.currentPage      = 1;
    renderProductsGrid();
  }

  searchInput?.addEventListener('input',    applyFilters);
  categoryFilter?.addEventListener('change', applyFilters);
  sortFilter?.addEventListener('change',     applyFilters);
}

/* ─────────────────────────────────────────
   CONTACT PAGE
───────────────────────────────────────── */
function initContactPage() {
  const form = document.getElementById('contact-form');
  if (!form) return;

  form.addEventListener('submit', e => {
    e.preventDefault();
    const success = document.getElementById('form-success');
    if (success) { success.classList.add('show'); }
    form.reset();
    showToast('Message sent! We\'ll reply within 24h.', '✉️');
  });
}

/* ─────────────────────────────────────────
   CATEGORY CARDS — click to products page
───────────────────────────────────────── */
function initCategoryCards() {
  document.querySelectorAll('[data-category]').forEach(card => {
    card.addEventListener('click', () => {
      const cat = card.getAttribute('data-category');
      window.location.href = `products.html?category=${encodeURIComponent(cat)}`;
    });
  });
}

/** On products page, pre-fill filter from URL query param */
function applyURLFilters() {
  const params = new URLSearchParams(window.location.search);
  const cat    = params.get('category');
  if (cat) {
    const sel = document.getElementById('category-filter');
    if (sel) {
      // Wait for categories to be built
      const trySet = setInterval(() => {
        const opt = [...sel.options].find(o => o.value === cat);
        if (opt) {
          sel.value = cat;
          sel.dispatchEvent(new Event('change'));
          clearInterval(trySet);
        }
      }, 100);
      setTimeout(() => clearInterval(trySet), 5000);
    }
  }
}

/* ─────────────────────────────────────────
   HELPER HTML BUILDERS
───────────────────────────────────────── */
function buildSkeleton() {
  return `
    <div class="skeleton-card">
      <div class="skeleton-img"></div>
      <div class="skeleton-body">
        <div class="skeleton-line w-40"></div>
        <div class="skeleton-line w-80"></div>
        <div class="skeleton-line w-60"></div>
      </div>
    </div>`;
}

function buildLoadingGrid(count) {
  return Array.from({ length: count }, buildSkeleton).join('');
}

function errorState(msg) {
  return `
    <div class="empty-state">
      <div class="empty-icon">⚠️</div>
      <h3 class="empty-title">Unable to load products</h3>
      <p class="empty-desc">${msg}</p>
      <button class="btn btn-accent" onclick="location.reload()">Try Again</button>
    </div>`;
}

function noResults() {
  return `
    <div class="empty-state">
      <div class="empty-icon">🔍</div>
      <h3 class="empty-title">No matching products found</h3>
      <p class="empty-desc">Try adjusting your search or filters.</p>
      <button class="btn btn-outline" onclick="clearFilters()">Clear Filters</button>
    </div>`;
}

function clearFilters() {
  const search   = document.getElementById('search-input');
  const category = document.getElementById('category-filter');
  const sort     = document.getElementById('sort-filter');
  if (search)   search.value   = '';
  if (category) category.value = '';
  if (sort)     sort.value     = '';
  State.filteredProducts = State.allProducts;
  State.currentPage      = 1;
  renderProductsGrid();
}

/* ─────────────────────────────────────────
   POLICY PAGE — Sticky sidebar highlight
───────────────────────────────────────── */
function initPolicyPage() {
  const sections  = document.querySelectorAll('.policy-section[id]');
  const navLinks  = document.querySelectorAll('.policy-nav-link');
  if (!sections.length) return;

  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        navLinks.forEach(l => l.classList.remove('active'));
        const active = document.querySelector(`.policy-nav-link[href="#${entry.target.id}"]`);
        if (active) active.classList.add('active');
      }
    });
  }, { rootMargin: '-30% 0px -60% 0px' });

  sections.forEach(s => observer.observe(s));
}

/* ─────────────────────────────────────────
   GLOBAL MODAL WIRING
───────────────────────────────────────── */
function initModal() {
  const overlay = document.getElementById('product-modal');
  if (!overlay) return;

  // Close on overlay click
  overlay.addEventListener('click', e => {
    if (e.target === overlay) closeModal();
  });

  // Close button
  document.getElementById('modal-close-btn')?.addEventListener('click', closeModal);

  // ESC key
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });
}

/* ─────────────────────────────────────────
   BACK TO TOP
───────────────────────────────────────── */
function initBackToTop() {
  const btn = document.getElementById('back-to-top');
  if (!btn) return;

  window.addEventListener('scroll', () => {
    btn.style.opacity   = window.scrollY > 600 ? '1' : '0';
    btn.style.pointerEvents = window.scrollY > 600 ? 'auto' : 'none';
  }, { passive: true });

  btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
}

/* ─────────────────────────────────────────
   BOOT — run on DOMContentLoaded
───────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initNavbar();
  initNavSearch();
  initModal();
  initScrollAnimations();
  initBackToTop();
  initCategoryCards();

  // Page-specific init
  const path = window.location.pathname;

  if (path.includes('products.html') || path.includes('products')) {
    initProductsPage();
    applyURLFilters();
  } else if (path.includes('contact.html')) {
    initContactPage();
  } else if (path.includes('shipping.html') || path.includes('returns.html')) {
    initPolicyPage();
  } else {
    // index.html (home)
    initHomePage();
  }
});

/* Expose global functions needed by inline onclick handlers */
window.openModal      = openModal;
window.closeModal     = closeModal;
window.addToCart      = addToCart;
window.handleWishlist = handleWishlist;
window.imgFallback    = imgFallback;
window.goToPage       = goToPage;
window.clearFilters   = clearFilters;
