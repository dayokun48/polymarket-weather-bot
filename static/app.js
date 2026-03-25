/**
 * Weather Trading Bot — Client JavaScript
 * Bloomberg Dark UI v2.0
 */

// ── Auto-refresh dashboard setiap 60 detik ────────────────────
if (window.location.pathname === '/') {
    setInterval(() => location.reload(), 60000);
}

// ── Confirm sebelum submit form yang punya data-confirm ───────
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[data-confirm]').forEach(form => {
        form.addEventListener('submit', function (e) {
            if (!confirm(this.dataset.confirm)) e.preventDefault();
        });
    });
});

// ── Toast notification (Bloomberg style) ─────────────────────
const _toastCSS = `
.toast {
    position: fixed;
    bottom: 24px; right: 24px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-light);
    color: var(--text-primary);
    padding: 12px 18px;
    border-radius: 6px;
    font-size: 13px;
    font-family: var(--font-ui, 'DM Sans', sans-serif);
    z-index: 9999;
    opacity: 0;
    transform: translateY(8px);
    transition: all 0.2s ease;
    max-width: 320px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}
.toast.show { opacity: 1; transform: translateY(0); }
.toast.success { border-left: 3px solid #00e676; }
.toast.error   { border-left: 3px solid #ff3d57; }
.toast.info    { border-left: 3px solid #2979ff; }
.toast.warning { border-left: 3px solid #ffd600; }
`;
const _styleEl = document.createElement('style');
_styleEl.textContent = _toastCSS;
document.head.appendChild(_styleEl);

function showNotification(message, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    document.body.appendChild(el);
    requestAnimationFrame(() => {
        requestAnimationFrame(() => el.classList.add('show'));
    });
    setTimeout(() => {
        el.classList.remove('show');
        setTimeout(() => el.remove(), 300);
    }, 3000);
}

// ── Copy to clipboard ─────────────────────────────────────────
function copyToClipboard(text) {
    navigator.clipboard.writeText(text)
        .then(() => showNotification('Copied to clipboard!', 'success'))
        .catch(() => showNotification('Copy failed', 'error'));
}

// ── Format helpers ────────────────────────────────────────────
function formatMoney(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency', currency: 'USD'
    }).format(amount);
}
function formatPercent(value) {
    return (value >= 0 ? '+' : '') + value.toFixed(1) + '%';
}

// ── Highlight active nav link ─────────────────────────────────
document.querySelectorAll('.nav-link').forEach(link => {
    if (link.href === window.location.href) {
        link.classList.add('active');
    }
});

console.log('🌧️ WeatherBot v2.0 loaded');