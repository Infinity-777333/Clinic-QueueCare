/**
 * client/js/app.js
 * Global application utilities, API configuration, Socket.IO connector,
 * receipt modal handling, and mobile-safe toast notifications.
 */

// Determine backend base URL dynamically (supports mobile testing on local network)
const getApiBaseUrl = () => {
    const { protocol, hostname, port } = window.location;
    // If client is served directly by Flask backend (port 5000 or production)
    if (port === '5000' || port === '' || port === '80') {
        return `${protocol}//${hostname}${port ? ':' + port : ''}`;
    }
    // If client is served on a standalone dev server (e.g., 5173 or 8080)
    return `${protocol}//${hostname}:5000`;
};

const API_BASE = getApiBaseUrl();

// Global Socket.IO instance
let socket = null;
let socketHasConnectedBefore = false;

try {
    if (typeof io !== 'undefined') {
        socket = io(API_BASE, {
            transports: ['websocket', 'polling'],
            reconnectionAttempts: 20,
            reconnectionDelay: 1500
        });

        socket.on('connect', () => {
            console.log('[QueueCare] Connected to real-time server at', API_BASE);
            if (socketHasConnectedBefore) {
                showToast('Reconnected to live clinic queue updates.', 'success');
            }
            socketHasConnectedBefore = true;
        });

        socket.on('disconnect', () => {
            console.warn('[QueueCare] Disconnected from real-time server.');
            showToast('Unable to connect to QueueCare server. Please check clinic network connection.', 'error');
        });

        socket.on('connect_error', () => {
            // Handled gracefully without alert popups
        });
    }
} catch (err) {
    console.error('[QueueCare] Failed to initialize Socket.IO:', err);
}

/**
 * Mobile-Safe Toast Notification System
 * Reusable across Patient, Doctor, and Reception views
 */
function showToast(message, type = 'info') {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'toast-container';
        container.setAttribute('role', 'alert');
        container.setAttribute('aria-live', 'polite');
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const toastClass = type === 'error' ? 'toast-error' : type === 'success' ? 'toast-success' : type === 'warning' ? 'toast-warning' : '';
    toast.className = `toast ${toastClass}`;

    let icon = 'ℹ';
    if (type === 'success') icon = '✓';
    else if (type === 'error') icon = '✕';
    else if (type === 'warning') icon = '⚠';

    toast.innerHTML = `
        <span style="font-weight:700; font-size:1.05rem; flex-shrink:0;">${icon}</span>
        <div style="flex: 1; min-width: 0; line-height: 1.35;">${message}</div>
        <button class="toast-close" aria-label="Close notification" onclick="this.parentElement.remove()">&times;</button>
    `;

    container.appendChild(toast);

    // Auto dismiss after 4.5 seconds
    const timer = setTimeout(() => {
        if (toast.parentElement) {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(10px)';
            toast.style.transition = 'all 0.2s ease';
            setTimeout(() => { if (toast.parentElement) toast.remove(); }, 200);
        }
    }, 4500);

    toast.addEventListener('click', (e) => {
        if (e.target.closest('.toast-close')) {
            clearTimeout(timer);
        }
    });
}

/**
 * Local Storage Helper for Browser-Associated Bookings
 * Remembers all bookings created from this browser (never assumes 1 user = 1 patient).
 */
const STORAGE_KEY = 'queuecareBookings';
const SELECTED_TOKEN_KEY = 'queuecareSelectedToken';

function getStoredBookings() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
            return parsed;
        } else if (parsed && typeof parsed === 'object') {
            return [parsed];
        }
        return [];
    } catch (e) {
        console.error('Error parsing stored bookings from localStorage:', e);
        return [];
    }
}

function saveStoredBooking(booking) {
    if (!booking) return;
    const list = getStoredBookings();
    const bId = booking.id ? String(booking.id).trim() : null;

    // Filter out existing duplicate reference by ID, or by token_number on same date
    const filtered = list.filter(b => {
        if (bId && b.id) {
            return String(b.id).trim() !== bId;
        }
        if (booking.token_number && b.token_number) {
            const sameDate = (!booking.booking_date || !b.booking_date || b.booking_date === booking.booking_date);
            return !(Number(b.token_number) === Number(booking.token_number) && sameDate);
        }
        return true;
    });

    const item = {
        id: booking.id || null,
        token_number: booking.token_number,
        patient_name: booking.patient_name || 'Patient',
        patient_mobile: booking.patient_mobile || '',
        booking_date: booking.booking_date || new Date().toISOString().split('T')[0],
        booking_time: booking.booking_time || ''
    };

    // Prepend new booking so newest is first in the list
    filtered.unshift(item);
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered));
    } catch (e) {
        console.error('Error saving booking to localStorage:', e);
    }
}

function getStoredSelectedToken() {
    try {
        return localStorage.getItem(SELECTED_TOKEN_KEY) || null;
    } catch (e) {
        return null;
    }
}

function saveStoredSelectedToken(tokenId) {
    try {
        if (tokenId) {
            localStorage.setItem(SELECTED_TOKEN_KEY, String(tokenId).trim());
        } else {
            localStorage.removeItem(SELECTED_TOKEN_KEY);
        }
    } catch (e) {}
}

function clearStoredExpiredBookings(expiredIds) {
    if (!expiredIds || expiredIds.length === 0) return [];
    const expiredSet = new Set(expiredIds.map(id => String(id).trim()));
    const list = getStoredBookings();
    const updated = list.filter(b => {
        const idMatch = b.id && expiredSet.has(String(b.id).trim());
        const tokMatch = b.token_number && expiredSet.has(String(b.token_number).trim());
        return !idMatch && !tokMatch;
    });
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    } catch (e) {}
    return updated;
}

/**
 * Digital Receipt Modal Controller
 */
let currentReceiptData = null;

function openReceiptModal(booking, clinic = {}) {
    currentReceiptData = { booking, clinic };
    const modal = document.getElementById('receiptModal');
    if (!modal) return;

    const clinicName = clinic.clinic_name || 'QueueCare Clinic';
    const docName = clinic.doctor_name || 'Dr. Sarah Jenkins';
    const docSpec = clinic.doctor_specialization || 'General Physician';

    const clinicEl = document.getElementById('receiptClinicName');
    const docEl = document.getElementById('receiptDoctor');
    const tokEl = document.getElementById('receiptTokenNum');
    const nameEl = document.getElementById('receiptPatientName');
    const mobEl = document.getElementById('receiptMobile');
    const dateEl = document.getElementById('receiptDate');
    const timeEl = document.getElementById('receiptTime');
    const srcEl = document.getElementById('receiptSource');
    const statEl = document.getElementById('receiptStatus');

    if (clinicEl) clinicEl.textContent = clinicName.toUpperCase();
    if (docEl) docEl.textContent = `${docName} (${docSpec})`;
    if (tokEl) tokEl.textContent = booking.token_number || '--';
    if (nameEl) nameEl.textContent = booking.patient_name || '--';
    if (mobEl) mobEl.textContent = booking.patient_mobile || '--';
    if (dateEl) dateEl.textContent = booking.booking_date || '--';
    if (timeEl) timeEl.textContent = booking.booking_time || '--';
    if (srcEl) srcEl.textContent = booking.source || 'Patient';
    if (statEl) statEl.textContent = booking.status || 'Waiting';

    modal.classList.add('active');
    document.body.classList.add('drawer-open');
}

function closeReceiptModal() {
    const modal = document.getElementById('receiptModal');
    if (modal) {
        modal.classList.remove('active');
        document.body.classList.remove('drawer-open');
    }
}

// Global modal dismiss on backdrop or Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeReceiptModal();
    }
});

document.addEventListener('click', (e) => {
    if (e.target && e.target.classList && e.target.classList.contains('modal-backdrop')) {
        closeReceiptModal();
    }
});

function printReceipt() {
    window.print();
}

function downloadReceiptPdf() {
    // Triggers standard print dialog configured for "Save as PDF"
    window.print();
}
