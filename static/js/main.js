/**
 * HireScan — Client-side interaction script
 */

function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

document.addEventListener('DOMContentLoaded', function () {
  // ──────────────── Theme Mode (Light / Dark) Toggle ────────────────
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.setAttribute('data-bs-theme', theme);
    try {
      localStorage.setItem('hirescan_theme', theme);
    } catch (e) {}

    // Update icons
    document.querySelectorAll('.hs-theme-toggle').forEach(btn => {
      const moonIcons = btn.querySelectorAll('.theme-icon-moon');
      const sunIcons = btn.querySelectorAll('.theme-icon-sun');
      const label = btn.querySelector('.theme-toggle-label');

      if (theme === 'dark') {
        moonIcons.forEach(icon => icon.classList.add('d-none'));
        sunIcons.forEach(icon => icon.classList.remove('d-none'));
        if (label) label.textContent = 'Light Mode';
        btn.setAttribute('aria-label', 'Switch to light mode');
      } else {
        sunIcons.forEach(icon => icon.classList.add('d-none'));
        moonIcons.forEach(icon => icon.classList.remove('d-none'));
        if (label) label.textContent = 'Dark Mode';
        btn.setAttribute('aria-label', 'Switch to dark mode');
      }
    });

    // Notify listeners (e.g. Chart.js)
    window.dispatchEvent(new CustomEvent('hirescan:themechange', { detail: { theme: theme } }));
  }

  // Determine current active theme (default to 'light' unless stored)
  let initialTheme = 'light';
  try {
    initialTheme = localStorage.getItem('hirescan_theme') || document.documentElement.getAttribute('data-theme') || 'light';
  } catch (e) {
    initialTheme = document.documentElement.getAttribute('data-theme') || 'light';
  }
  applyTheme(initialTheme);

  // Attach listener to all theme toggle triggers
  document.querySelectorAll('.hs-theme-toggle').forEach(btn => {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      const activeTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      const nextTheme = activeTheme === 'dark' ? 'light' : 'dark';
      applyTheme(nextTheme);
    });
  });

  // ──────────────── Password Visibility Toggle ────────────────
  document.querySelectorAll('.password-toggle-btn').forEach(button => {
    button.addEventListener('click', function () {
      const targetId = this.getAttribute('data-target');
      const input = document.getElementById(targetId);
      if (input) {
        if (input.type === 'password') {
          input.type = 'text';
          this.innerHTML = '<i class="bi bi-eye-slash"></i>';
        } else {
          input.type = 'password';
          this.innerHTML = '<i class="bi bi-eye"></i>';
        }
      }
    });
  });

  // ──────────────── Candidate OTP Flow Handler ────────────────
  const sendOtpForm = document.getElementById('candidateSendOtpForm');
  const verifyOtpForm = document.getElementById('candidateVerifyOtpForm');
  const otpMessageAlert = document.getElementById('otpMessageAlert');
  const resendOtpBtn = document.getElementById('resendOtpBtn');
  const resendCooldownSpan = document.getElementById('resendCooldown');
  let cooldownTimer = null;

  function showAlert(msg, isError = true) {
    if (!otpMessageAlert) return;
    otpMessageAlert.classList.remove('d-none', 'alert-danger', 'alert-success');
    otpMessageAlert.classList.add(isError ? 'alert-danger' : 'alert-success');
    otpMessageAlert.innerText = msg;
  }

  function startCooldown(seconds) {
    if (resendOtpBtn) {
      resendOtpBtn.disabled = true;
    }
    let remaining = seconds;
    if (resendCooldownSpan) {
      resendCooldownSpan.innerText = ` (${remaining}s)`;
    }
    clearInterval(cooldownTimer);
    cooldownTimer = setInterval(() => {
      remaining--;
      if (remaining <= 0) {
        clearInterval(cooldownTimer);
        if (resendOtpBtn) resendOtpBtn.disabled = false;
        if (resendCooldownSpan) resendCooldownSpan.innerText = '';
      } else {
        if (resendCooldownSpan) resendCooldownSpan.innerText = ` (${remaining}s)`;
      }
    }, 1000);
  }

  if (sendOtpForm) {
    sendOtpForm.addEventListener('submit', function (e) {
      e.preventDefault();
      const emailInput = document.getElementById('candidateEmail');
      const email = emailInput ? emailInput.value.trim() : '';
      const submitBtn = sendOtpForm.querySelector('button[type="submit"]');

      if (!email) {
        showAlert('Please enter your registered email address.');
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Sending OTP...';
      }

      const csrftoken = getCookie('csrftoken') || document.querySelector('[name=csrfmiddlewaretoken]')?.value;

      fetch('/candidate/send-otp/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': csrftoken,
        },
        body: new URLSearchParams({ email: email })
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          showAlert(data.message || 'OTP sent successfully to your email.', false);
          sendOtpForm.classList.add('d-none');
          if (verifyOtpForm) {
            verifyOtpForm.classList.remove('d-none');
            const otpTargetEmail = document.getElementById('otpTargetEmail');
            if (otpTargetEmail) otpTargetEmail.innerText = email;
            const otpCodeInput = document.getElementById('otpCode');
            if (otpCodeInput) {
              otpCodeInput.value = '';
              otpCodeInput.focus();
            }
          }
          startCooldown(60);
        } else {
          showAlert(data.error || 'Failed to send OTP.', true);
        }
      })
      .catch(err => {
        showAlert('Network or server error while sending OTP.', true);
      })
      .finally(() => {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = 'Send One-Time Password';
        }
      });
    });
  }

  if (verifyOtpForm) {
    verifyOtpForm.addEventListener('submit', function (e) {
      e.preventDefault();
      const otpInput = document.getElementById('otpCode');
      const otp = otpInput ? otpInput.value.trim() : '';
      const submitBtn = verifyOtpForm.querySelector('button[type="submit"]');

      if (!otp) {
        showAlert('Please enter the 6-digit OTP code.', true);
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Verifying...';
      }

      const csrftoken = getCookie('csrftoken') || document.querySelector('[name=csrfmiddlewaretoken]')?.value;

      fetch('/candidate/verify-otp/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': csrftoken,
        },
        body: new URLSearchParams({ otp: otp })
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          showAlert('Verification successful! Redirecting...', false);
          window.location.href = data.redirect || '/test/dashboard/';
        } else {
          showAlert(data.error || 'Invalid OTP code.', true);
        }
      })
      .catch(err => {
        showAlert('Network or server error during verification.', true);
      })
      .finally(() => {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = 'Verify & Enter Assessment Portal';
        }
      });
    });
  }

  if (resendOtpBtn) {
    resendOtpBtn.addEventListener('click', function () {
      const emailInput = document.getElementById('candidateEmail');
      const email = emailInput ? emailInput.value.trim() : '';
      if (!email) return;

      resendOtpBtn.disabled = true;
      const csrftoken = getCookie('csrftoken') || document.querySelector('[name=csrfmiddlewaretoken]')?.value;

      fetch('/candidate/send-otp/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': csrftoken,
        },
        body: new URLSearchParams({ email: email })
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          showAlert(data.message || 'A new verification code has been sent to your email. Previous codes are now invalid.', false);
          startCooldown(60);
          const otpCodeInput = document.getElementById('otpCode');
          if (otpCodeInput) {
            otpCodeInput.value = '';
            otpCodeInput.focus();
          }
        } else {
          showAlert(data.error || 'Failed to resend OTP.', true);
          resendOtpBtn.disabled = false;
        }
      })
      .catch(err => {
        showAlert('Error requesting new OTP.', true);
        resendOtpBtn.disabled = false;
      });
    });
  }

  // ──────────────── Admin Sidebar Offcanvas Navigation ────────────────
  const adminSidebarEl = document.getElementById('adminSidebar');
  if (adminSidebarEl && window.bootstrap && window.bootstrap.Offcanvas) {
    const getSidebarOffcanvas = () => bootstrap.Offcanvas.getOrCreateInstance(adminSidebarEl);

    // Auto-close drawer when a navigation link is clicked on narrow screens
    adminSidebarEl.querySelectorAll('.sidebar-nav-item').forEach(link => {
      link.addEventListener('click', function () {
        if (window.innerWidth < 992) {
          const instance = getSidebarOffcanvas();
          if (instance) {
            instance.hide();
          }
        }
      });
    });

    // Ensure Escape key closes sidebar if open on narrow screens
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && window.innerWidth < 992 && adminSidebarEl.classList.contains('show')) {
        const instance = getSidebarOffcanvas();
        if (instance) {
          instance.hide();
        }
      }
    });
  }
});
