/**
 * client/js/patient.js
 * Patient interface controller:
 * Handles View switching, Home overview, Book Token validation & Success Card,
 * My Bookings rendering (all browser bookings), Queue Progress tracking,
 * and real-time Socket.IO synchronization.
 */

let globalClinicSettings = {};
let currentSelectedToken = null;
let lastBookedTokenData = null;

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initBookingForm();
    initQueueTracker();
    initSocketListeners();
    loadClinicStatus();
    handleHashNavigation();
});

/**
 * Navigation & Hamburger Drawer Control
 */
function initNavigation() {
    const hamburgerBtn = document.getElementById('hamburgerBtn');
    const drawerOverlay = document.getElementById('drawerOverlay');
    const drawerCloseBtn = document.getElementById('drawerCloseBtn');
    const navLinks = document.querySelectorAll('.drawer-link');

    const toggleDrawer = (open) => {
        if (drawerOverlay) {
            if (open) {
                drawerOverlay.classList.add('active');
                document.body.classList.add('drawer-open');
                if (hamburgerBtn) hamburgerBtn.setAttribute('aria-expanded', 'true');
            } else {
                drawerOverlay.classList.remove('active');
                document.body.classList.remove('drawer-open');
                if (hamburgerBtn) hamburgerBtn.setAttribute('aria-expanded', 'false');
            }
        }
    };

    if (hamburgerBtn) hamburgerBtn.addEventListener('click', () => toggleDrawer(true));
    if (drawerCloseBtn) drawerCloseBtn.addEventListener('click', () => toggleDrawer(false));
    if (drawerOverlay) {
        drawerOverlay.addEventListener('click', (e) => {
            if (e.target === drawerOverlay) toggleDrawer(false);
        });
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && drawerOverlay && drawerOverlay.classList.contains('active')) {
            toggleDrawer(false);
        }
    });

    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            const targetView = link.getAttribute('data-view');
            if (targetView) {
                e.preventDefault();
                window.location.hash = targetView;
                switchView(targetView);
                toggleDrawer(false);
            }
        });
    });

    window.addEventListener('hashchange', handleHashNavigation);
}

function openDrawerWithFocus(section) {
    const drawerOverlay = document.getElementById('drawerOverlay');
    if (drawerOverlay) {
        drawerOverlay.classList.add('active');
        document.body.classList.add('drawer-open');
        if (section === 'staff') {
            const staffSec = document.getElementById('drawerStaffSection');
            if (staffSec) {
                staffSec.scrollIntoView({ behavior: 'smooth' });
            }
        }
    }
}

function handleHashNavigation() {
    const hash = window.location.hash.replace('#', '') || 'home';
    switchView(hash);
}

function switchView(viewName) {
    const views = ['home', 'book', 'my-bookings', 'queue-progress'];
    const activeView = views.includes(viewName) ? viewName : 'home';

    // Update view containers
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    const target = document.getElementById(`view-${activeView}`);
    if (target) {
        target.classList.add('active');
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // Update drawer active links
    document.querySelectorAll('.drawer-link').forEach(link => {
        if (link.getAttribute('data-view') === activeView) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });

    // View-specific data triggers
    if (activeView === 'home') loadClinicStatus();
    if (activeView === 'my-bookings') loadMyBookings();
    if (activeView === 'queue-progress') loadQueueProgressView();
}

/**
 * VIEW 1: Home View Logic
 * Displays ONLY high-level clinic overview
 */
async function loadClinicStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/clinic/status`);
        const data = await res.json();
        if (!data.success) return;

        globalClinicSettings = {
            clinic_name: data.clinic_name,
            doctor_name: data.doctor_name,
            doctor_specialization: data.doctor_specialization,
            clinic_start_time: data.clinic_start_time,
            clinic_end_time: data.clinic_end_time
        };

        // Update Hero elements
        const nameEl = document.getElementById('homeClinicName');
        const docEl = document.getElementById('homeDoctorName');
        const timingsEl = document.getElementById('homeTimings');
        const drawerTimingsEl = document.getElementById('drawerTimings');

        if (nameEl) nameEl.textContent = data.clinic_name || 'QueueCare Clinic';
        if (docEl) docEl.textContent = `${data.doctor_name || 'Dr. Sarah Jenkins'} • ${data.doctor_specialization || 'General Physician'}`;
        if (timingsEl) timingsEl.innerHTML = `<span>&#128337; Today's Consultation: ${data.clinic_start_time || '09:00 AM'} - ${data.clinic_end_time || '05:00 PM'}</span>`;
        if (drawerTimingsEl) drawerTimingsEl.textContent = `Hours: ${data.clinic_start_time || '09:00 AM'} - ${data.clinic_end_time || '05:00 PM'}`;

        // Update Key Overview Cards
        const currentTokEl = document.getElementById('homeCurrentToken');
        const totalTokEl = document.getElementById('homeTotalTokens');
        const bookingStatusEl = document.getElementById('homeBookingStatus');
        const consultStatusEl = document.getElementById('homeConsultationStatus');

        if (currentTokEl) {
            currentTokEl.textContent = data.current_token ? `#${data.current_token}` : '—';
        }
        if (totalTokEl) {
            totalTokEl.textContent = data.total_tokens ?? 0;
        }

        if (bookingStatusEl) {
            const isOpen = data.booking_status === 'OPEN';
            bookingStatusEl.className = `stat-badge ${isOpen ? 'badge-open' : 'badge-closed'}`;
            bookingStatusEl.innerHTML = `<span class="status-indicator-dot"></span> ${isOpen ? 'OPEN' : 'CLOSED'}`;
        }

        if (consultStatusEl) {
            const status = data.consultation_status || 'NOT_STARTED';
            let badgeClass = 'badge-not-started';
            let label = 'NOT STARTED';

            if (status === 'IN_PROGRESS') {
                badgeClass = 'badge-in-progress';
                label = 'IN PROGRESS';
            } else if (status === 'COMPLETED') {
                badgeClass = 'badge-completed';
                label = 'COMPLETED';
            }

            consultStatusEl.className = `stat-badge ${badgeClass}`;
            consultStatusEl.innerHTML = `<span class="status-indicator-dot ${status === 'IN_PROGRESS' ? 'pulse' : ''}"></span> ${label}`;
        }

        updateBookingAvailability(data.booking_status);
    } catch (err) {
        console.error('Error loading clinic status:', err);
    }
}

function updateBookingAvailability(bookingStatus) {
    const alertBox = document.getElementById('bookingStatusAlert');
    const submitBtn = document.getElementById('btnSubmitBooking');
    const isOpen = bookingStatus === 'OPEN';

    if (alertBox && submitBtn) {
        if (isOpen) {
            alertBox.className = 'alert-box alert-success';
            alertBox.innerHTML = `<strong>Booking Status: OPEN</strong> &bull; Tokens are currently being issued.`;
            submitBtn.disabled = false;
        } else {
            alertBox.className = 'alert-box alert-danger';
            alertBox.innerHTML = `<strong>ONLINE BOOKING CLOSED</strong> &bull; New tokens are currently unavailable.`;
            submitBtn.disabled = true;
        }
    }
}

/**
 * VIEW 2: Book Token Logic & Polished Success State Experience
 */
function initBookingForm() {
    const form = document.getElementById('tokenBookingForm');
    const successCard = document.getElementById('bookingSuccessCard');
    const btnViewReceipt = document.getElementById('btnSuccessViewReceipt');
    const btnTrackQueue = document.getElementById('btnSuccessTrackQueue');
    const btnBookAnother = document.getElementById('btnSuccessBookAnother');

    if (btnViewReceipt) {
        btnViewReceipt.addEventListener('click', () => {
            if (lastBookedTokenData) {
                openReceiptModal(lastBookedTokenData.booking, lastBookedTokenData.clinic || globalClinicSettings);
            }
        });
    }

    if (btnTrackQueue) {
        btnTrackQueue.addEventListener('click', () => {
            if (lastBookedTokenData && lastBookedTokenData.booking) {
                trackToken(lastBookedTokenData.booking.id || lastBookedTokenData.booking.token_number);
            } else {
                switchView('queue-progress');
            }
        });
    }

    if (btnBookAnother) {
        btnBookAnother.addEventListener('click', () => {
            if (successCard) successCard.style.display = 'none';
            if (form) {
                form.style.display = 'block';
                form.reset();
            }
        });
    }

    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const nameInput = document.getElementById('patientName');
        const mobileInput = document.getElementById('patientMobile');
        const submitBtn = document.getElementById('btnSubmitBooking');

        const name = nameInput.value.trim();
        const mobile = mobileInput.value.trim();

        // Strict Client Validation: Name 3-50 letters/spaces
        const nameRegex = /^[A-Za-z\s]{3,50}$/;
        if (!nameRegex.test(name)) {
            showToast('Please enter a valid patient name (3 to 50 letters and spaces only).', 'error');
            nameInput.focus();
            return;
        }

        // Strict Client Validation: Exactly 10 digits
        const mobileRegex = /^\d{10}$/;
        if (!mobileRegex.test(mobile)) {
            showToast('Please enter a valid 10-digit mobile number.', 'error');
            mobileInput.focus();
            return;
        }

        submitBtn.disabled = true;
        submitBtn.innerHTML = `<span>Booking Token...</span>`;

        try {
            const res = await fetch(`${API_BASE}/api/bookings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ patient_name: name, patient_mobile: mobile })
            });

            const data = await res.json();
            if (!data.success) {
                showToast(data.error || 'Failed to book token.', 'error');
                submitBtn.disabled = false;
                submitBtn.innerHTML = `<span>Get Clinic Token</span> &rarr;`;
                return;
            }

            // Save booking to browser storage (supports multiple bookings)
            saveStoredBooking(data.booking);
            lastBookedTokenData = {
                booking: data.booking,
                clinic: data.clinic || globalClinicSettings
            };
            currentSelectedToken = data.booking.id || data.booking.token_number;
            saveStoredSelectedToken(currentSelectedToken);

            showToast(`✓ Token #${data.booking.token_number} issued successfully!`, 'success');

            // Render Success State Experience Card
            if (form && successCard) {
                form.style.display = 'none';
                const successNameEl = document.getElementById('successPatientName');
                const successTokEl = document.getElementById('successTokenNum');
                if (successNameEl) successNameEl.textContent = data.booking.patient_name;
                if (successTokEl) successTokEl.textContent = data.booking.token_number;
                successCard.style.display = 'block';
            }

            submitBtn.disabled = false;
            submitBtn.innerHTML = `<span>Get Clinic Token</span> &rarr;`;
        } catch (err) {
            console.error('Booking submission error:', err);
            showToast('Network error while booking. Please try again.', 'error');
            submitBtn.disabled = false;
            submitBtn.innerHTML = `<span>Get Clinic Token</span> &rarr;`;
        }
    });
}

/**
 * VIEW 3: My Bookings Logic
 * Displays ALL bookings stored in the browser (stacked cards on mobile, never just bookings[0])
 */
async function loadMyBookings() {
    const container = document.getElementById('myBookingsList');
    if (!container) return;

    const stored = getStoredBookings();
    if (!stored || stored.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">&#128203;</div>
                <h3>No Bookings Yet</h3>
                <p>You haven't booked any tokens from this device today.</p>
                <a href="#book" class="btn-primary" style="display:inline-flex; width:auto; margin:0 auto;" onclick="switchView('book')">
                    Book Your First Token &rarr;
                </a>
            </div>
        `;
        return;
    }

    container.innerHTML = `<div style="text-align:center; padding: 2rem; color:var(--text-muted);">Syncing live queue statuses...</div>`;

    try {
        const idList = stored.map(b => b.id || b.token_number).join(',');
        const res = await fetch(`${API_BASE}/api/my-bookings?ids=${idList}`);
        const data = await res.json();

        const bookings = (data.success && data.bookings) ? data.bookings : [];

        // Check for expired bookings to toggle Clear Expired Tokens button
        const clearBtn = document.getElementById('btnClearExpiredTokens');
        const hasExpired = bookings.some(b => b.status === 'Expired');
        if (clearBtn) {
            clearBtn.style.display = hasExpired ? 'inline-flex' : 'none';
        }

        if (bookings.length === 0) {
            container.innerHTML = `<div class="empty-state"><h3>No active bookings found</h3></div>`;
            return;
        }

        let html = '<div class="booking-cards-list">';
        bookings.forEach(tok => {
            const rawStatus = tok.status || 'Waiting';
            let displayStatus = rawStatus;
            let badgeClass = 'badge-waiting';

            if (rawStatus === 'Serving') {
                displayStatus = 'In Progress';
                badgeClass = 'badge-serving';
            } else if (rawStatus === 'Completed') {
                displayStatus = 'Completed';
                badgeClass = 'badge-completed';
            } else if (rawStatus === 'Expired') {
                displayStatus = 'Expired Token';
                badgeClass = 'badge-closed';
            } else {
                displayStatus = 'Waiting';
                badgeClass = 'badge-waiting';
            }

            const tokJson = JSON.stringify(tok).replace(/"/g, '&quot;');
            const clinicJson = JSON.stringify(data.clinic || globalClinicSettings).replace(/"/g, '&quot;');

            const isExpired = rawStatus === 'Expired';
            const trackBtn = isExpired
                ? `<span class="stat-badge badge-closed" style="font-size:0.75rem; opacity:0.85;">Closed</span>`
                : `<button type="button" class="btn-secondary" onclick='trackToken("${tok.id || tok.token_number}")'>Track &rarr;</button>`;

            html += `
                <div class="booking-card ${isExpired ? 'booking-expired' : ''}">
                    <div class="booking-card-left">
                        <div class="token-circle" style="${isExpired ? 'opacity:0.6; filter:grayscale(0.5);' : ''}">
                            <small>Token</small>
                            ${tok.token_number}
                        </div>
                        <div class="booking-patient-info">
                            <h3>${escapeHtml(tok.patient_name)}</h3>
                            <div class="booking-meta">
                                <span>&#128222; ${tok.patient_mobile}</span>
                                <span>&bull;</span>
                                <span>${tok.booking_date ? tok.booking_date + ' ' : ''}${tok.booking_time || 'Today'}</span>
                            </div>
                        </div>
                    </div>
                    <div class="booking-card-actions">
                        <span class="stat-badge ${badgeClass}">${displayStatus}</span>
                        <button type="button" class="btn-secondary" onclick='openReceiptModal(${tokJson}, ${clinicJson})'>
                            &#128196; Receipt
                        </button>
                        ${trackBtn}
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    } catch (err) {
        console.error('Error loading my bookings:', err);
    }
}

async function clearExpiredTokens() {
    const stored = getStoredBookings();
    if (!stored || stored.length === 0) return;

    try {
        const idList = stored.map(b => b.id || b.token_number).join(',');
        const res = await fetch(`${API_BASE}/api/my-bookings?ids=${idList}`);
        const data = await res.json();
        if (data.success && data.bookings) {
            const expiredIds = data.bookings
                .filter(b => b.status === 'Expired')
                .map(b => b.id || b.token_number);

            if (expiredIds.length > 0) {
                clearStoredExpiredBookings(expiredIds);
                showToast('Expired tokens cleared from your view.', 'info');
                renderMyBookings();
                loadQueueProgressView();
            } else {
                showToast('No expired tokens to clear.', 'info');
            }
        }
    } catch (err) {
        console.error('Error clearing expired tokens:', err);
        showToast('Failed to clear expired tokens.', 'error');
    }
}

function trackToken(identifier) {
    if (!identifier) return;
    currentSelectedToken = String(identifier).trim();
    saveStoredSelectedToken(currentSelectedToken);
    window.location.hash = 'queue-progress';
    switchView('queue-progress');
}

/**
 * VIEW 4: Queue Progress Logic
 * The ONLY patient page for detailed live queue tracking
 */
function initQueueTracker() {
    const tokenSelect = document.getElementById('progressTokenSelect');
    if (tokenSelect) {
        tokenSelect.addEventListener('change', (e) => {
            const val = e.target.value;
            currentSelectedToken = val ? String(val).trim() : null;
            saveStoredSelectedToken(currentSelectedToken);
            console.log("Selected token changed:", currentSelectedToken);
            updateProgressData();
        });
    }
}

async function loadQueueProgressView() {
    const tokenSelect = document.getElementById('progressTokenSelect');
    if (!tokenSelect) return;

    const stored = getStoredBookings();
    console.log("Stored bookings:", stored);

    const storedIds = stored.map(b => b.id || b.token_number).filter(Boolean);
    console.log("Booking IDs:", storedIds);

    // If patient has NO stored booking references, show professional empty state (NO clinic-wide fallback!)
    if (storedIds.length === 0) {
        tokenSelect.innerHTML = '<option value="">No active tokens available</option>';
        tokenSelect.disabled = true;
        currentSelectedToken = null;
        saveStoredSelectedToken(null);
        updateProgressData();
        return;
    }

    try {
        const idQuery = storedIds.join(',');
        const res = await fetch(`${API_BASE}/api/queue/active-tokens?ids=${encodeURIComponent(idQuery)}`);
        const data = await res.json();
        console.log("Active token response:", data);

        if (data.success) {
            const rawUserTokens = data.user_tokens || [];
            // Show ONLY the patient's own tokens with status Waiting or Serving (In Progress)
            const userTokens = rawUserTokens.filter(t => t.status === 'Waiting' || t.status === 'Serving');

            tokenSelect.innerHTML = '';

            if (userTokens.length === 0) {
                // Patient has bookings, but none are active today (e.g. all completed or expired)
                const emptyOpt = document.createElement('option');
                emptyOpt.value = "";
                emptyOpt.textContent = "No active tokens available";
                tokenSelect.appendChild(emptyOpt);
                tokenSelect.disabled = true;
                currentSelectedToken = null;
                saveStoredSelectedToken(null);
            } else {
                tokenSelect.disabled = false;

                // Sort active tokens by token_number ASC (natural queue sequence)
                userTokens.sort((a, b) => Number(a.token_number) - Number(b.token_number));

                // Count occurrences of each patient name to disambiguate duplicates if needed
                const nameCounts = {};
                userTokens.forEach(t => {
                    const rawName = (t.patient_name || '').trim();
                    const nameKey = rawName.toLowerCase();
                    if (nameKey) {
                        nameCounts[nameKey] = (nameCounts[nameKey] || 0) + 1;
                    }
                });

                userTokens.forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t.id; // Booking ID as unique internal value
                    opt.setAttribute('data-token-number', t.token_number);

                    const rawName = (t.patient_name || '').trim();
                    const nameKey = rawName.toLowerCase();
                    let displayName;

                    if (!rawName) {
                        // Safe fallback if patient_name is unexpectedly missing
                        displayName = t.token_number ? `Token #${t.token_number}` : 'Patient';
                    } else if (nameCounts[nameKey] > 1) {
                        // Duplicate name: disambiguate with token number
                        displayName = `${rawName} — Token #${t.token_number}`;
                    } else {
                        // Unique name: clean patient name display
                        displayName = rawName;
                    }

                    opt.textContent = displayName;
                    tokenSelect.appendChild(opt);
                });

                // Check remembered selected booking ID from localStorage or variable
                const rememberedId = getStoredSelectedToken() || currentSelectedToken;
                const activeMatch = userTokens.find(t => String(t.id) === String(rememberedId) || String(t.token_number) === String(rememberedId));

                if (activeMatch) {
                    currentSelectedToken = activeMatch.id;
                } else {
                    // Default to first active token
                    currentSelectedToken = userTokens[0].id;
                }

                tokenSelect.value = currentSelectedToken;
                saveStoredSelectedToken(currentSelectedToken);
                console.log("Selected token:", currentSelectedToken);
            }
        }
    } catch (err) {
        console.error('Error loading active tokens for queue progress:', err);
    }

    updateProgressData();
}

async function updateProgressData() {
    if (!currentSelectedToken) {
        // Patient has no active token selected or available
        const yourTokEl = document.getElementById('progYourToken');
        const curServingEl = document.getElementById('progCurrentlyServing');
        const aheadEl = document.getElementById('progPatientsAhead');
        const posEl = document.getElementById('progQueuePosition');
        const statusBannerEl = document.getElementById('progStatusBanner');
        const flowContainer = document.getElementById('progLiveQueueFlow');
        const recentListEl = document.getElementById('progRecentlyCompletedList');

        if (yourTokEl) yourTokEl.textContent = '—';
        if (aheadEl) aheadEl.textContent = '—';
        if (posEl) posEl.textContent = '—';

        if (statusBannerEl) {
            statusBannerEl.className = 'alert-box alert-warning';
            statusBannerEl.innerHTML = `<strong>No Active Tokens:</strong> No active tokens available for queue tracking.`;
        }

        try {
            const res = await fetch(`${API_BASE}/api/queue`);
            const data = await res.json();
            if (data.success && data.data) {
                const qd = data.data;
                if (curServingEl) {
                    curServingEl.textContent = qd.queue_state && qd.queue_state.current_token ? qd.queue_state.current_token : '—';
                }
                if (flowContainer) {
                    let items = [];
                    if (qd.serving_patient) {
                        items.push(`
                            <div class="queue-flow-item is-serving">
                                <div class="queue-flow-token-num">${qd.serving_patient.token_number}</div>
                                <div class="queue-flow-label">Serving</div>
                            </div>
                        `);
                    }
                    if (qd.waiting_patients) {
                        qd.waiting_patients.forEach(w => {
                            items.push(`
                                <div class="queue-flow-item">
                                    <div class="queue-flow-token-num">${w.token_number}</div>
                                    <div class="queue-flow-label">Waiting</div>
                                </div>
                            `);
                        });
                    }
                    flowContainer.innerHTML = items.length > 0 ? items.join('') : '<div style="color:var(--text-muted); padding: 0.5rem 0;">No active patients in queue.</div>';
                }
                if (recentListEl && qd.recently_completed) {
                    if (qd.recently_completed.length > 0) {
                        recentListEl.innerHTML = qd.recently_completed.map(t => `
                            <div style="display:flex; justify-content:space-between; align-items:center; padding:0.5rem 0; border-bottom:1px solid #f1f5f9;">
                                <span><strong>Token #${t.token_number}</strong> (${escapeHtml(t.patient_name)})</span>
                                <span style="color:var(--text-muted); font-size:0.8rem;">${t.completed_at || 'Completed'}</span>
                            </div>
                        `).join('');
                    } else {
                        recentListEl.innerHTML = `<div style="color:var(--text-muted); font-size:0.85rem; padding: 0.5rem 0;">No consultations completed yet today.</div>`;
                    }
                }
            }
        } catch (e) {}
        return;
    }

    try {
        console.log("Fetching progress for selected token:", currentSelectedToken);
        const res = await fetch(`${API_BASE}/api/queue/progress/${currentSelectedToken}`);
        const data = await res.json();

        if (data.success && data.progress) {
            renderPatientProgress(data.progress);
        } else {
            // Token is no longer active (e.g. was completed or expired)
            currentSelectedToken = null;
            saveStoredSelectedToken(null);
            loadQueueProgressView();
        }
    } catch (err) {
        console.error('Error fetching progress:', err);
    }
}

function renderPatientProgress(progress) {
    const yourTokEl = document.getElementById('progYourToken');
    const curServingEl = document.getElementById('progCurrentlyServing');
    const aheadEl = document.getElementById('progPatientsAhead');
    const posEl = document.getElementById('progQueuePosition');
    const statusBannerEl = document.getElementById('progStatusBanner');
    const recentListEl = document.getElementById('progRecentlyCompletedList');
    const flowContainer = document.getElementById('progLiveQueueFlow');

    if (yourTokEl) yourTokEl.textContent = progress.your_token;
    if (curServingEl) curServingEl.textContent = progress.currently_serving ? progress.currently_serving : '—';
    if (aheadEl) aheadEl.textContent = progress.patients_ahead;
    if (posEl) posEl.textContent = progress.queue_position > 0 ? progress.queue_position : (progress.status === 'Serving' ? 'Serving Now' : 'Done');

    if (statusBannerEl) {
        if (progress.status === 'Serving') {
            statusBannerEl.className = 'alert-box alert-success';
            statusBannerEl.innerHTML = `<strong>🟢 It is your turn!</strong> Token #${progress.your_token} (${escapeHtml(progress.patient_name || 'Patient')}) please proceed immediately to the doctor consultation room.`;
        } else if (progress.status === 'Completed') {
            statusBannerEl.className = 'alert-box alert-warning';
            statusBannerEl.innerHTML = `<strong>Consultation Completed:</strong> Token #${progress.your_token} consultation is finished. Thank you for visiting QueueCare.`;
        } else if (progress.status === 'Expired') {
            statusBannerEl.className = 'alert-box alert-warning';
            statusBannerEl.innerHTML = `<strong>Token Expired:</strong> Token #${progress.your_token} queue session has closed or ended.`;
        } else {
            statusBannerEl.className = 'alert-box alert-warning';
            statusBannerEl.innerHTML = `<strong>Queue in Progress:</strong> Tracking Token #${progress.your_token} (${escapeHtml(progress.patient_name || 'Patient')}) &bull; You have <strong>${progress.patients_ahead}</strong> patient(s) ahead of you.`;
        }
    }

    // Render Recently Completed Tokens
    if (recentListEl) {
        if (progress.recently_completed && progress.recently_completed.length > 0) {
            recentListEl.innerHTML = progress.recently_completed.map(t => `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:0.5rem 0; border-bottom:1px solid #f1f5f9;">
                    <span><strong>Token #${t.token_number}</strong> (${escapeHtml(t.patient_name)})</span>
                    <span style="color:var(--text-muted); font-size:0.8rem;">${t.completed_at || 'Completed'}</span>
                </div>
            `).join('');
        } else {
            recentListEl.innerHTML = `<div style="color:var(--text-muted); font-size:0.85rem; padding: 0.5rem 0;">No consultations completed yet today.</div>`;
        }
    }

    // Render Live Queue flow with YOU indicator
    if (flowContainer && progress.live_queue) {
        flowContainer.innerHTML = progress.live_queue.map(item => {
            const isServing = item.status === 'Serving';
            const isYours = Number(item.token_number) === Number(progress.your_token);
            return `
                <div class="queue-flow-item ${isServing ? 'is-serving' : ''} ${isYours ? 'is-your-token' : ''}">
                    <div class="queue-flow-token-num">${item.token_number}</div>
                    <div class="queue-flow-label">${isServing ? 'Serving' : 'Waiting'}</div>
                    ${isYours ? '<div style="font-size:0.65rem; color:#b45309; font-weight:800; margin-top:2px;">YOU</div>' : ''}
                </div>
            `;
        }).join('');
    }
}

function renderQueueOverview(queueData) {
    const yourTokEl = document.getElementById('progYourToken');
    const curServingEl = document.getElementById('progCurrentlyServing');
    const aheadEl = document.getElementById('progPatientsAhead');
    const posEl = document.getElementById('progQueuePosition');
    const flowContainer = document.getElementById('progLiveQueueFlow');
    const recentListEl = document.getElementById('progRecentlyCompletedList');
    const statusBannerEl = document.getElementById('progStatusBanner');

    if (yourTokEl) yourTokEl.textContent = '—';
    if (aheadEl) aheadEl.textContent = '—';
    if (posEl) posEl.textContent = '—';
    if (curServingEl) {
        curServingEl.textContent = queueData.queue_state.current_token ? `#${queueData.queue_state.current_token}` : '—';
    }

    if (statusBannerEl) {
        statusBannerEl.className = 'alert-box alert-warning';
        statusBannerEl.innerHTML = `<strong>General Queue Monitor:</strong> Select a patient above to track their position in line.`;
    }

    if (flowContainer && queueData.waiting_patients) {
        let items = [];
        if (queueData.serving_patient) {
            items.push(`
                <div class="queue-flow-item is-serving">
                    <div class="queue-flow-token-num">${queueData.serving_patient.token_number}</div>
                    <div class="queue-flow-label">Serving</div>
                </div>
            `);
        }
        queueData.waiting_patients.forEach(w => {
            items.push(`
                <div class="queue-flow-item">
                    <div class="queue-flow-token-num">${w.token_number}</div>
                    <div class="queue-flow-label">Waiting</div>
                </div>
            `);
        });
        flowContainer.innerHTML = items.join('') || '<div style="color:var(--text-muted); padding: 0.5rem 0;">No active patients in queue.</div>';
    }

    if (recentListEl && queueData.recently_completed) {
        if (queueData.recently_completed.length > 0) {
            recentListEl.innerHTML = queueData.recently_completed.map(t => `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:0.5rem 0; border-bottom:1px solid #f1f5f9;">
                    <span><strong>Token #${t.token_number}</strong> (${escapeHtml(t.patient_name)})</span>
                    <span style="color:var(--text-muted); font-size:0.8rem;">${t.completed_at || 'Completed'}</span>
                </div>
            `).join('');
        } else {
            recentListEl.innerHTML = `<div style="color:var(--text-muted); font-size:0.85rem; padding: 0.5rem 0;">No tokens completed yet today.</div>`;
        }
    }
}

/**
 * Real-time Socket.IO Listeners
 * Auto-syncs queue progression, booking creation, and clinic settings without refreshing
 */
function initSocketListeners() {
    if (!socket) return;

    socket.on('queue:update', (payload) => {
        // Sync Home overview stats
        if (payload.queue_state) {
            const currentTokEl = document.getElementById('homeCurrentToken');
            const totalTokEl = document.getElementById('homeTotalTokens');
            const bookingStatusEl = document.getElementById('homeBookingStatus');
            const consultStatusEl = document.getElementById('homeConsultationStatus');

            if (currentTokEl) currentTokEl.textContent = payload.queue_state.current_token ? `#${payload.queue_state.current_token}` : '—';
            if (totalTokEl) totalTokEl.textContent = payload.total_issued ?? payload.queue_state.total_tokens ?? 0;

            if (bookingStatusEl) {
                const isOpen = payload.queue_state.booking_status === 'OPEN';
                bookingStatusEl.className = `stat-badge ${isOpen ? 'badge-open' : 'badge-closed'}`;
                bookingStatusEl.innerHTML = `<span class="status-indicator-dot"></span> ${isOpen ? 'OPEN' : 'CLOSED'}`;
                updateBookingAvailability(payload.queue_state.booking_status);
            }

            if (consultStatusEl) {
                const status = payload.queue_state.consultation_status || 'NOT_STARTED';
                let badgeClass = 'badge-not-started';
                let label = 'NOT STARTED';
                if (status === 'IN_PROGRESS') {
                    badgeClass = 'badge-in-progress';
                    label = 'IN PROGRESS';
                } else if (status === 'COMPLETED') {
                    badgeClass = 'badge-completed';
                    label = 'COMPLETED';
                }
                consultStatusEl.className = `stat-badge ${badgeClass}`;
                consultStatusEl.innerHTML = `<span class="status-indicator-dot ${status === 'IN_PROGRESS' ? 'pulse' : ''}"></span> ${label}`;
            }
        }

        // Live refresh whichever view is active
        const activeSection = document.querySelector('.view-section.active');
        if (activeSection && activeSection.id === 'view-queue-progress') {
            loadQueueProgressView();
        }
        if (activeSection && activeSection.id === 'view-my-bookings') {
            loadMyBookings();
        }
    });

    socket.on('settings:update', (settings) => {
        globalClinicSettings = settings;
        const nameEl = document.getElementById('homeClinicName');
        const docEl = document.getElementById('homeDoctorName');
        const timingsEl = document.getElementById('homeTimings');
        const drawerTimingsEl = document.getElementById('drawerTimings');

        if (nameEl) nameEl.textContent = settings.clinic_name;
        if (docEl) docEl.textContent = `${settings.doctor_name} • ${settings.doctor_specialization}`;
        if (timingsEl) timingsEl.innerHTML = `<span>&#128337; Today's Consultation: ${settings.clinic_start_time} - ${settings.clinic_end_time}</span>`;
        if (drawerTimingsEl) drawerTimingsEl.textContent = `Hours: ${settings.clinic_start_time} - ${settings.clinic_end_time}`;
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
