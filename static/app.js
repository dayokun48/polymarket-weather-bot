// Weather Trading Bot - Client-side JavaScript

// Auto-refresh dashboard every 60 seconds
if (window.location.pathname === '/') {
    setInterval(() => {
        location.reload();
    }, 60000);
}

// Confirmation for form submissions
document.addEventListener('DOMContentLoaded', function() {
    const forms = document.querySelectorAll('form');
    
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            if (this.dataset.confirm) {
                if (!confirm(this.dataset.confirm)) {
                    e.preventDefault();
                }
            }
        });
    });
});

// Copy to clipboard
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        alert('Copied to clipboard!');
    });
}

// Format numbers
function formatMoney(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(amount);
}

function formatPercent(value) {
    return value.toFixed(1) + '%';
}

// Notification system
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.classList.add('show');
    }, 100);
    
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

console.log('Weather Trading Bot loaded successfully! 🌧️');
