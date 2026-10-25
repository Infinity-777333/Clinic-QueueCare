/**
 * client/js/reception.js
 * Front-desk reception controller:
 * Handles walk-in & phone token creation with loading states, live booking search,
 * today's patient roster with mobile card rendering (data-label),
 * and receipt viewing/reprinting.
 */

let receptionSession = null;
let currentClinicInfo = {};

document.addEventListener('DOMContentLoaded', () => {
    initReceptionAuth();
    initBookingForms();
    initSearch();
    initReceptionSocket();
    loadReceptionData();
});

async function initReceptionAuth() {
    const btnLogout = document.getElementById('btnReceptionLogout');
    if (btnLogout) {
        btnLogout.addEventListener('click', async () => {
            try {
                await fetch(`${API_BASE}/api/auth/logout`, {
                    method: 'POST',
                    credentials: 'include'
                });
            } catch (e) {}
            window.location.href = 'reception-login.html';
        });
    }
}

async function loadReceptionData() {
    try {
        const res = await fetch(`${API_BASE}/api/reception/today`, {
            credentials: 'include'
        });

        if (res.status === 401 || res.status === 403) {
            window.location.href = 'reception-login.html';
            return;
        }

        const data = await res.json();
        if (!data.success) {
            showToast(data.error || 'Failed to load reception desk data.', 'error');
            return;
        }

        receptionSession = data.user;
        currentClinicInfo = data.clinic;

        renderDeskOverview(data.queue_state, data.clinic);
        renderBookingsTable(data.tokens);
    } catch (err) {
        console.error('Error loading reception data:', err);
    }
}

function renderDeskOverview(state, clinic) {
    const totalEl = document.getElementById('recTotalTokens');
    const curEl = document.getElementById('recCurrentServing');
    const waitEl = document.getElementById('recWaitingCount');
    const statusEl = document.getElementById('recBookingStatusBadge');
    const clinicNameEl = document.getElementById('recClinicName');

    if (totalEl) totalEl.textContent = state.total_tokens ?? 0;
    if (curEl) curEl.textContent = state.current_token ? `#${state.current_token}` : '—';
    if (waitEl) waitEl.textContent = state.waiting_count ?? 0;
    if (clinicNameEl) clinicNameEl.textContent = clinic.clinic_name || 'QueueCare Clinic';

    if (statusEl) {
        const isOpen = state.booking_status === 'OPEN';
        statusEl.className = `stat-badge ${isOpen ? 'badge-open' : 'badge-closed'}`;
        statusEl.innerHTML = `<span class="status-indicator-dot"></span> Online Booking: ${state.booking_status}`;
    }
}

function renderBookingsTable(tokens) {
    const tbody = document.getElementById('receptionTableBody');
    if (!tbody) return;

    if (!tokens || tokens.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2.5rem 1rem; color:var(--text-muted);">No bookings found for today.</td></tr>`;
        return;
    }

    tbody.innerHTML = tokens.map(tok => {
        let badgeClass = 'badge-waiting';
        if (tok.status === 'Serving') badgeClass = 'badge-serving';
        if (tok.status === 'Completed') badgeClass = 'badge-completed';

        const tokJson = JSON.stringify(tok).replace(/"/g, '&quot;');
        const clinicJson = JSON.stringify(currentClinicInfo).replace(/"/g, '&quot;');

        return `
            <tr>
                <td data-label="Token"><strong>#${tok.token_number}</strong></td>
                <td data-label="Patient Name"><strong>${escapeHtml(tok.patient_name)}</strong></td>
                <td data-label="Mobile">${tok.patient_mobile}</td>
                <td data-label="Source"><span class="stat-badge badge-completed" style="font-size:0.75rem;">${tok.source}</span></td>
                <td data-label="Status"><span class="stat-badge ${badgeClass}">${tok.status}</span></td>
                <td data-label="Action">
                    <button type="button" class="btn-secondary" style="padding:0.4rem 0.85rem; font-size:0.825rem;" onclick='openReceiptModal(${tokJson}, ${clinicJson})'>
                        &#128196; Reprint Receipt
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

/**
 * Handle Walk-in and Phone booking form submissions with loading state and double-click prevention
 */
function initBookingForms() {
    const walkinForm = document.getElementById('walkinBookingForm');
    const phoneForm = document.getElementById('phoneBookingForm');

    const handleBooking = async (form, source, endpoint) => {
        const nameInput = form.querySelector('[name="patient_name"]');
        const mobileInput = form.querySelector('[name="patient_mobile"]');
        const submitBtn = form.querySelector('button[type="submit"]');

        const name = nameInput.value.trim();
        const mobile = mobileInput.value.trim();

        // Strict validation: Name 3-50 letters/spaces
        if (!/^[A-Za-z\s]{3,50}$/.test(name)) {
            showToast('Please enter a valid patient name (3 to 50 letters and spaces only).', 'error');
            nameInput.focus();
            return;
        }

        // Strict validation: Exactly 10 digits
        if (!/^\d{10}$/.test(mobile)) {
            showToast('Please enter a valid 10-digit mobile number.', 'error');
            mobileInput.focus();
            return;
        }

        if (submitBtn.disabled) return;
        submitBtn.disabled = true;
        const originalText = submitBtn.innerHTML;
        submitBtn.innerHTML = `<span>Issuing ${source} Token...</span>`;

        try {
            const res = await fetch(`${API_BASE}/api/reception/${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ patient_name: name, patient_mobile: mobile })
            });

            const data = await res.json();
            if (!data.success) {
                showToast(data.error || 'Failed to issue token.', 'error');
                return;
            }

            showToast(`✓ Token #${data.booking.token_number} issued for ${data.booking.patient_name}`, 'success');
            form.reset();

            // Open printable receipt immediately
            openReceiptModal(data.booking, data.clinic || currentClinicInfo);
            loadReceptionData();
        } catch (err) {
            showToast('Network error issuing token.', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText;
        }
    };

    if (walkinForm) {
        walkinForm.addEventListener('submit', (e) => {
            e.preventDefault();
            handleBooking(walkinForm, 'Walk-in', 'walk-in');
        });
    }

    if (phoneForm) {
        phoneForm.addEventListener('submit', (e) => {
            e.preventDefault();
            handleBooking(phoneForm, 'Phone', 'phone');
        });
    }
}

/**
 * Live Booking Search Filter
 */
function initSearch() {
    const searchInput = document.getElementById('recSearchInput');
    if (!searchInput) return;

    let debounceTimer;
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(async () => {
            const query = searchInput.value.trim();
            try {
                const res = await fetch(`${API_BASE}/api/reception/search?q=${encodeURIComponent(query)}`, {
                    credentials: 'include'
                });
                const data = await res.json();
                if (data.success) {
                    renderBookingsTable(data.results);
                }
            } catch (err) {
                console.error('Search error:', err);
            }
        }, 250);
    });
}

/**
 * Socket.IO Listeners for Reception Desk
 */
function initReceptionSocket() {
    if (!socket) return;

    socket.on('queue:update', (payload) => {
        if (payload.queue_state) {
            renderDeskOverview(payload.queue_state, payload.clinic_settings);
        }
        // If not actively searching, refresh table
        const searchInput = document.getElementById('recSearchInput');
        if (!searchInput || !searchInput.value.trim()) {
            loadReceptionData();
        }
    });

    socket.on('settings:update', (settings) => {
        currentClinicInfo = settings;
        const nameEl = document.getElementById('recClinicName');
        if (nameEl) nameEl.textContent = settings.clinic_name;
    });
}

function escapeHtml(text) {
    if (!text) return '';
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
