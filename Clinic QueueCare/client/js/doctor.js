/**
 * client/js/doctor.js
 * Doctor portal administration controller:
 * Handles authentication verification, mobile-friendly navigation drawer,
 * live queue control (Next, Complete, Undo) with loading & double-click protection,
 * booking status toggles, consultation status selection, today's patient roster with
 * mobile card transformation (data-label), audit history, and dynamic clinic settings.
 */

let doctorSession = null;
let currentDashboardData = null;

document.addEventListener('DOMContentLoaded', () => {
    initDoctorTabs();
    initDoctorDrawer();
    initDoctorControls();
    initSettingsForm();
    initDoctorSocket();
    loadDoctorDashboard();
});

/**
 * Tab Navigation (Controls, Today's Patients, History, Settings)
 * Supports both desktop tabs and mobile drawer links
 */
function activateTab(targetId) {
    // Desktop tabs
    document.querySelectorAll('.doctor-tab-btn').forEach(t => {
        if (t.getAttribute('data-tab') === targetId) t.classList.add('active');
        else t.classList.remove('active');
    });

    // Mobile drawer tabs
    document.querySelectorAll('.doc-drawer-tab').forEach(t => {
        if (t.getAttribute('data-tab') === targetId) t.classList.add('active');
        else t.classList.remove('active');
    });

    // Tab panes
    document.querySelectorAll('.doctor-tab-pane').forEach(p => p.classList.remove('active'));
    const targetPane = document.getElementById(targetId);
    if (targetPane) targetPane.classList.add('active');

    if (targetId === 'tab-history') {
        const dInput = document.getElementById('historyDateInput');
        loadDoctorHistory(dInput ? dInput.value : '');
    }
    if (targetId === 'tab-settings') loadDoctorSettings();
    if (targetId === 'tab-today') loadDoctorDashboard();
}

function initDoctorTabs() {
    const tabs = document.querySelectorAll('.doctor-tab-btn');
    tabs.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab');
            activateTab(targetId);
        });
    });
}

function initDoctorDrawer() {
    const hamburger = document.getElementById('docHamburgerBtn');
    const overlay = document.getElementById('docDrawerOverlay');
    const closeBtn = document.getElementById('docDrawerCloseBtn');
    const drawerTabs = document.querySelectorAll('.doc-drawer-tab');

    const toggle = (open) => {
        if (overlay) {
            if (open) {
                overlay.classList.add('active');
                document.body.classList.add('drawer-open');
            } else {
                overlay.classList.remove('active');
                document.body.classList.remove('drawer-open');
            }
        }
    };

    if (hamburger) hamburger.addEventListener('click', () => toggle(true));
    if (closeBtn) closeBtn.addEventListener('click', () => toggle(false));
    if (overlay) {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) toggle(false);
        });
    }

    drawerTabs.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab');
            activateTab(targetId);
            toggle(false);
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && overlay && overlay.classList.contains('active')) {
            toggle(false);
        }
    });
}

/**
 * Loads full dashboard data and checks authorization
 */
async function loadDoctorDashboard() {
    try {
        const res = await fetch(`${API_BASE}/api/doctor/dashboard`, {
            credentials: 'include'
        });

        if (res.status === 401 || res.status === 403) {
            window.location.href = 'doctor-login.html';
            return;
        }

        const data = await res.json();
        if (!data.success) {
            showToast(data.error || 'Failed to load doctor dashboard.', 'error');
            return;
        }

        doctorSession = data.user;
        currentDashboardData = data.dashboard;

        updateDoctorHeader(data.dashboard.clinic_settings);
        renderQueueMetrics(data.dashboard);
        renderCurrentPatient(data.dashboard.serving_patient);
        renderTodayPatients(data.today_patients);
        updateControlButtons(data.dashboard);
    } catch (err) {
        console.error('Error loading doctor dashboard:', err);
    }
}

/**
 * Updates Doctor Header Profile & Clinic Details Dynamically
 */
function updateDoctorHeader(settings) {
    const docNameEl = document.getElementById('docProfileName');
    const docSpecEl = document.getElementById('docProfileSpec');
    const clinicNameEl = document.getElementById('docClinicName');
    const welcomeTitleEl = document.getElementById('docWelcomeTitle');

    const name = settings.doctor_name || 'Dr. Sarah Jenkins';
    const spec = settings.doctor_specialization || 'General Physician';
    const clinic = settings.clinic_name || 'QueueCare Clinic';

    if (docNameEl) docNameEl.textContent = name;
    if (docSpecEl) docSpecEl.textContent = spec;
    if (clinicNameEl) clinicNameEl.textContent = clinic;
    if (welcomeTitleEl) welcomeTitleEl.textContent = `Welcome, ${name}`;
}

/**
 * Renders Queue Metrics (Counters, Booking Status, Consultation Status)
 */
function renderQueueMetrics(dash) {
    const state = dash.queue_state;

    const curTokEl = document.getElementById('docCurrentToken');
    const totalEl = document.getElementById('docTotalTokens');
    const waitingEl = document.getElementById('docWaitingCount');
    const completedEl = document.getElementById('docCompletedCount');

    if (curTokEl) curTokEl.textContent = state.current_token ? `#${state.current_token}` : '—';
    if (totalEl) totalEl.textContent = dash.total_issued ?? state.total_tokens ?? 0;
    if (waitingEl) waitingEl.textContent = dash.waiting_count ?? state.waiting_count ?? 0;
    if (completedEl) completedEl.textContent = dash.completed_count ?? state.completed_count ?? 0;

    // Booking Status Toggle Button
    const bookingBtn = document.getElementById('btnToggleBooking');
    if (bookingBtn) {
        const isOpen = state.booking_status === 'OPEN';
        bookingBtn.className = `btn-secondary ${isOpen ? 'badge-open' : 'badge-closed'}`;
        bookingBtn.innerHTML = `<span class="status-indicator-dot"></span> Booking: <strong>${isOpen ? 'OPEN' : 'CLOSED'}</strong>`;
    }

    // Consultation Status Display Badge (Automatically managed)
    const consultBadge = document.getElementById('docConsultationStatusBadge');
    if (consultBadge) {
        const cStatus = (state.consultation_status || 'NOT_STARTED').toUpperCase();
        if (cStatus === 'IN_PROGRESS') {
            consultBadge.className = 'stat-badge badge-in-progress';
            consultBadge.innerHTML = '<span class="status-indicator-dot pulse"></span> IN PROGRESS';
        } else if (cStatus === 'COMPLETED') {
            consultBadge.className = 'stat-badge badge-completed';
            consultBadge.innerHTML = '<span class="status-indicator-dot"></span> COMPLETED';
        } else {
            consultBadge.className = 'stat-badge badge-not-started';
            consultBadge.innerHTML = '<span class="status-indicator-dot"></span> NOT STARTED';
        }
    }
}

/**
 * Renders Current Serving Patient Card
 */
function renderCurrentPatient(patient) {
    const container = document.getElementById('currentPatientContainer');
    if (!container) return;

    if (!patient) {
        container.innerHTML = `
            <div style="text-align: center; padding: 2rem 1rem; color: var(--text-muted);">
                <div style="font-size: 2.25rem; margin-bottom: 0.5rem; color: var(--primary);">&#129658;</div>
                <h3 style="font-size: 1.2rem; font-weight: 700; color: var(--text-main);">No Patient Currently in Consultation</h3>
                <p style="font-size: 0.875rem; margin-top: 0.25rem;">Click <strong>Call Next Patient</strong> to invite the next waiting token into the room.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 1rem;">
            <div style="display: flex; align-items: center; gap: 1rem; min-width: 0;">
                <div class="token-circle" style="width: 64px; height: 64px; font-size: 1.5rem; background-color: var(--primary); color: #fff; box-shadow: 0 4px 10px rgba(13, 148, 136, 0.28);">
                    <small style="color: rgba(255,255,255,0.9);">Token</small>
                    ${patient.token_number}
                </div>
                <div style="min-width: 0;">
                    <div style="font-size: 0.75rem; text-transform: uppercase; font-weight: 700; color: var(--primary); letter-spacing: 0.05em;">Currently In Consultation</div>
                    <h2 style="font-size: 1.35rem; font-weight: 800; color: var(--text-main); margin-top: 0.15rem; overflow-wrap: anywhere;">${escapeHtml(patient.patient_name)}</h2>
                    <div style="display: flex; flex-wrap: wrap; gap: 0.5rem; font-size: 0.85rem; color: var(--text-muted); margin-top: 0.25rem;">
                        <span>&#128222; ${patient.patient_mobile}</span>
                        <span>&bull;</span>
                        <span>Source: <strong>${patient.source || 'Online'}</strong></span>
                        <span>&bull;</span>
                        <span>Started: <strong>${patient.started_at || 'Just now'}</strong></span>
                    </div>
                </div>
            </div>
            <div>
                <span class="stat-badge badge-serving" style="font-size: 0.9rem; padding: 0.5rem 1rem;">
                    <span class="status-indicator-dot pulse"></span> IN PROGRESS
                </span>
            </div>
        </div>
    `;
}

/**
 * Queue Action Controls (Call Next, Complete, Undo) with loading & double-click protection
 */
function initDoctorControls() {
    const btnNext = document.getElementById('btnCallNext');
    const btnComplete = document.getElementById('btnCompleteCurrent');
    const btnUndo = document.getElementById('btnUndoAction');
    const btnReset = document.getElementById('btnResetQueue');
    const resetModal = document.getElementById('resetConfirmModal');
    const btnCancelReset = document.getElementById('btnCancelReset');
    const btnConfirmReset = document.getElementById('btnConfirmReset');
    const btnToggleBooking = document.getElementById('btnToggleBooking');
    const btnLogout = document.getElementById('btnDoctorLogout');

    // History filter elements
    const btnFilterHistory = document.getElementById('btnFilterHistory');
    const btnResetHistoryFilter = document.getElementById('btnResetHistoryFilter');
    const historyDateInput = document.getElementById('historyDateInput');

    if (btnNext) {
        btnNext.addEventListener('click', async () => {
            if (btnNext.disabled) return;
            btnNext.disabled = true;
            const originalHtml = btnNext.innerHTML;
            btnNext.innerHTML = '<span>Calling next...</span>';

            try {
                const res = await fetch(`${API_BASE}/api/doctor/next`, {
                    method: 'POST',
                    credentials: 'include'
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message, 'success');
                } else {
                    showToast(data.error || 'Failed to call next patient.', 'error');
                }
            } catch (err) {
                showToast('Network error calling next patient.', 'error');
            } finally {
                btnNext.innerHTML = originalHtml;
                // Controlled by updateControlButtons via Socket.IO
            }
        });
    }

    if (btnComplete) {
        btnComplete.addEventListener('click', async () => {
            if (btnComplete.disabled) return;
            btnComplete.disabled = true;
            const originalHtml = btnComplete.innerHTML;
            btnComplete.innerHTML = '<span>Completing...</span>';

            try {
                const res = await fetch(`${API_BASE}/api/doctor/complete`, {
                    method: 'POST',
                    credentials: 'include'
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message, 'success');
                } else {
                    showToast(data.error || 'Failed to complete patient.', 'error');
                }
            } catch (err) {
                showToast('Network error completing patient.', 'error');
            } finally {
                btnComplete.innerHTML = originalHtml;
            }
        });
    }

    if (btnUndo) {
        btnUndo.addEventListener('click', async () => {
            if (btnUndo.disabled) return;
            btnUndo.disabled = true;
            const originalHtml = btnUndo.innerHTML;
            btnUndo.innerHTML = '<span>Reverting...</span>';

            try {
                const res = await fetch(`${API_BASE}/api/doctor/undo`, {
                    method: 'POST',
                    credentials: 'include'
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message, 'success');
                } else {
                    showToast(data.error || 'Undo unavailable.', 'error');
                }
            } catch (err) {
                showToast('Network error executing undo.', 'error');
            } finally {
                btnUndo.innerHTML = originalHtml;
            }
        });
    }

    // Reset Daily Queue button & modal handling
    if (btnReset && resetModal) {
        btnReset.addEventListener('click', () => {
            if (btnReset.disabled) return;
            resetModal.classList.add('active');
        });

        if (btnCancelReset) {
            btnCancelReset.addEventListener('click', () => {
                resetModal.classList.remove('active');
            });
        }

        resetModal.addEventListener('click', (e) => {
            if (e.target === resetModal) resetModal.classList.remove('active');
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && resetModal.classList.contains('active')) {
                resetModal.classList.remove('active');
            }
        });

        if (btnConfirmReset) {
            btnConfirmReset.addEventListener('click', async () => {
                if (btnConfirmReset.disabled) return;
                btnConfirmReset.disabled = true;
                const originalText = btnConfirmReset.textContent;
                btnConfirmReset.textContent = 'Resetting...';

                try {
                    const res = await fetch(`${API_BASE}/api/doctor/queue/reset`, {
                        method: 'POST',
                        credentials: 'include'
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast(data.message, 'success');
                        resetModal.classList.remove('active');
                        loadDoctorDashboard();
                    } else {
                        showToast(data.error || 'Failed to reset queue.', 'error');
                    }
                } catch (err) {
                    showToast('Network error resetting queue.', 'error');
                } finally {
                    btnConfirmReset.disabled = false;
                    btnConfirmReset.textContent = originalText;
                }
            });
        }
    }

    // Queue History filter controls (Date only)
    if (btnFilterHistory) {
        btnFilterHistory.addEventListener('click', () => {
            const dateVal = historyDateInput ? historyDateInput.value : '';
            loadDoctorHistory(dateVal);
        });
    }

    if (btnResetHistoryFilter) {
        btnResetHistoryFilter.addEventListener('click', () => {
            if (historyDateInput) historyDateInput.value = '';
            loadDoctorHistory('');
        });
    }

    if (btnToggleBooking) {
        btnToggleBooking.addEventListener('click', async () => {
            if (!currentDashboardData) return;
            const currentStatus = currentDashboardData.queue_state.booking_status;
            const endpoint = currentStatus === 'OPEN' ? 'close' : 'open';

            try {
                const res = await fetch(`${API_BASE}/api/doctor/bookings/${endpoint}`, {
                    method: 'POST',
                    credentials: 'include'
                });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message, 'success');
                }
            } catch (e) {
                showToast('Failed to update booking status.', 'error');
            }
        });
    }

    if (btnLogout) {
        btnLogout.addEventListener('click', async () => {
            try {
                await fetch(`${API_BASE}/api/auth/logout`, {
                    method: 'POST',
                    credentials: 'include'
                });
            } catch (e) {}
            window.location.href = 'doctor-login.html';
        });
    }
}

function updateControlButtons(dash) {
    const btnComplete = document.getElementById('btnCompleteCurrent');
    const btnUndo = document.getElementById('btnUndoAction');
    const btnNext = document.getElementById('btnCallNext');
    const btnReset = document.getElementById('btnResetQueue');
    const hintReset = document.getElementById('resetButtonHint');

    if (btnComplete) {
        btnComplete.disabled = !dash.serving_patient;
    }
    if (btnUndo) {
        btnUndo.disabled = !dash.undo_available;
    }
    if (btnNext) {
        btnNext.disabled = !dash.waiting_patients || dash.waiting_patients.length === 0;
    }

    // Dynamic reset button safety validation & status message
    if (btnReset && hintReset) {
        const waitingCount = dash.waiting_count ?? dash.queue_state?.waiting_count ?? 0;
        const hasServing = Boolean(dash.serving_patient);
        const totalIssued = dash.total_issued ?? dash.queue_state?.total_tokens ?? 0;
        const completedCount = dash.completed_count ?? dash.queue_state?.completed_count ?? 0;

        if (waitingCount > 0 || hasServing) {
            btnReset.disabled = true;
            hintReset.textContent = "Complete all current patients before resetting the queue.";
            hintReset.style.color = "var(--status-waiting)";
        } else if (totalIssued === 0 && completedCount === 0) {
            btnReset.disabled = true;
            hintReset.textContent = "Reset is available only after all booked patients have been completed.";
            hintReset.style.color = "var(--text-muted)";
        } else {
            // All booked patients in this session are Completed
            btnReset.disabled = false;
            hintReset.textContent = "All patients completed. Queue can be reset.";
            hintReset.style.color = "var(--accent-emerald-dark)";
        }
    }
}

/**
 * Renders Today's Patients Table with Session column & data-label for Mobile Cards
 */
function renderTodayPatients(patients) {
    const tbody = document.getElementById('todayPatientsTbody');
    if (!tbody) return;

    if (!patients || patients.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:2rem; color:var(--text-muted);">No patients registered today.</td></tr>`;
        return;
    }

    tbody.innerHTML = patients.map(p => {
        let badgeClass = 'badge-waiting';
        if (p.status === 'Serving') badgeClass = 'badge-serving';
        if (p.status === 'Completed') badgeClass = 'badge-completed';

        return `
            <tr>
                <td data-label="Token"><strong>#${p.token_number}</strong></td>
                <td data-label="Session"><span class="stat-badge badge-completed" style="font-size:0.75rem;">Session ${p.queue_session || 1}</span></td>
                <td data-label="Patient Name"><strong>${escapeHtml(p.patient_name)}</strong></td>
                <td data-label="Mobile">${p.patient_mobile}</td>
                <td data-label="Status"><span class="stat-badge ${badgeClass}">${p.status}</span></td>
                <td data-label="Source"><span class="stat-badge badge-completed" style="font-size:0.75rem;">${p.source}</span></td>
                <td data-label="Booking Time">${p.booking_time}</td>
            </tr>
        `;
    }).join('');
}

/**
 * Loads Queue Action Audit History with date filter and data-label for Mobile Cards
 */
async function loadDoctorHistory(dateFilter = '') {
    const tbody = document.getElementById('historyTbody');
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:1.5rem; color:var(--text-muted);">Loading audit history...</td></tr>`;

    try {
        const params = new URLSearchParams();
        if (dateFilter && dateFilter.trim()) params.append('date', dateFilter.trim());

        const queryString = params.toString() ? `?${params.toString()}` : '';
        const res = await fetch(`${API_BASE}/api/doctor/history${queryString}`, { credentials: 'include' });
        const data = await res.json();

        if (!data.success || !data.history || data.history.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:2rem; color:var(--text-muted);">No queue history actions recorded for this filter.</td></tr>`;
            return;
        }

        tbody.innerHTML = data.history.map(h => {
            let badgeClass = 'badge-completed';
            if (h.action === 'Serving') badgeClass = 'badge-serving';
            else if (h.action === 'Reset') badgeClass = 'badge-closed';
            else if (h.action === 'Undo') badgeClass = 'badge-waiting';

            return `
                <tr>
                    <td data-label="Visit Date"><strong>${h.queue_date || '—'}</strong></td>
                    <td data-label="Token"><strong>#${h.token_number}</strong></td>
                    <td data-label="Patient Name"><strong>${escapeHtml(h.patient_name)}</strong></td>
                    <td data-label="Mobile">${h.patient_mobile}</td>
                    <td data-label="Source"><span class="stat-badge badge-completed" style="font-size:0.75rem;">${h.source}</span></td>
                    <td data-label="Started At">${h.started_at || '—'}</td>
                    <td data-label="Completed At">${h.completed_at || '—'}</td>
                    <td data-label="Action / Status"><span class="stat-badge ${badgeClass}">${h.action}</span></td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Error loading history:', err);
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:2rem; color:var(--status-closed);">Failed to load queue history.</td></tr>`;
    }
}

/**
 * Loads and Submits Clinic Settings
 */
async function loadDoctorSettings() {
    try {
        const res = await fetch(`${API_BASE}/api/doctor/settings`, { credentials: 'include' });
        const data = await res.json();
        if (!data.success) return;

        const s = data.settings;
        document.getElementById('setClinicName').value = s.clinic_name || '';
        document.getElementById('setDoctorName').value = s.doctor_name || '';
        document.getElementById('setDoctorSpec').value = s.doctor_specialization || '';
        document.getElementById('setStartTime').value = s.clinic_start_time || '09:00';
        document.getElementById('setEndTime').value = s.clinic_end_time || '17:00';
        document.getElementById('setDailyLimit').value = s.daily_token_limit || 100;
    } catch (err) {
        console.error('Error loading settings:', err);
    }
}

function initSettingsForm() {
    const form = document.getElementById('clinicSettingsForm');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btnSave = document.getElementById('btnSaveSettings');
        btnSave.disabled = true;
        btnSave.textContent = 'Saving Settings...';

        const payload = {
            clinic_name: document.getElementById('setClinicName').value.trim(),
            doctor_name: document.getElementById('setDoctorName').value.trim(),
            doctor_specialization: document.getElementById('setDoctorSpec').value.trim(),
            clinic_start_time: document.getElementById('setStartTime').value,
            clinic_end_time: document.getElementById('setEndTime').value,
            daily_token_limit: parseInt(document.getElementById('setDailyLimit').value, 10)
        };

        try {
            const res = await fetch(`${API_BASE}/api/doctor/settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            if (data.success) {
                showToast('Clinic settings updated and broadcasted!', 'success');
                updateDoctorHeader(data.settings);
            } else {
                showToast(data.error || 'Failed to update settings.', 'error');
            }
        } catch (err) {
            showToast('Network error saving settings.', 'error');
        } finally {
            btnSave.disabled = false;
            btnSave.textContent = 'Save & Broadcast Clinic Settings';
        }
    });
}

/**
 * Socket.IO Real-Time Synchronization for Doctor Dashboard
 */
function initDoctorSocket() {
    if (!socket) return;

    socket.on('queue:update', (payload) => {
        currentDashboardData = payload;
        renderQueueMetrics(payload);
        renderCurrentPatient(payload.serving_patient);
        updateControlButtons(payload);

        // If today's patients tab is open, reload roster
        const activeTab = document.querySelector('.doctor-tab-btn.active, .doc-drawer-tab.active');
        if (activeTab && activeTab.getAttribute('data-tab') === 'tab-today') {
            loadDoctorDashboard();
        }
    });

    socket.on('settings:update', (settings) => {
        updateDoctorHeader(settings);
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
