/**
 * socket.js — 채널 A SocketIO 이벤트 처리
 *
 * 수신 이벤트:
 *   status             → updateStatusBar(), updatePanelVisibility(), 맵 갱신
 *   cart               → updateCart()
 *   registration_done  → showTrackingPanel()
 *   checkout_zone_enter → showCheckoutModal()
 *   payment_done       → closeCheckoutModal()
 *   arrived            → showArrivedModal(zone_name)
 *   enter_locked       → showLockedPanel()
 *   enter_halted       → showHaltedPanel()
 *   staff_resolved     → sessionEnd() → redirect /login
 *   nav_failed         → showToast("안내에 실패했습니다")
 *   checkout_blocked   → showToast("결제 후 통과 가능합니다")
 *   find_product_result → showFindProductResult(data)
 *   control_connected  → 연결 상태 표시
 */

"use strict";

/* global io, updateCart, hasUnpaidItems, deleteItem, MapRenderer */

const socket = io();

// 현재 로봇 모드 캐시
let currentMode = "IDLE";
// 도착한 구역명 캐시
let arrivedZoneName = "";

// ── 수신 이벤트 핸들러 ─────────────────────────────────────────

socket.on("connect", () => {
  console.info("[socket] 서버 연결됨");
});

socket.on("disconnect", () => {
  console.warn("[socket] 서버 연결 끊김");
});

socket.on("control_connected", (data) => {
  const bar = document.getElementById("ctrl-status");
  if (!bar) return;
  bar.textContent = data.connected ? "" : "⚠ 서버 연결 중...";
});

// status — 1~2Hz push
socket.on("status", (data) => {
  updateStatusBar(data);
  updatePanelVisibility(data.my_robot?.mode);
  if (typeof MapRenderer !== "undefined") {
    MapRenderer.updateFromStatus(data);
  }
});

// cart
socket.on("cart", (data) => {
  updateCart(data.items || []);
});

// 인형 등록 완료
socket.on("registration_done", () => {
  showTrackingPanel();
});

// 결제 구역 진입
socket.on("checkout_zone_enter", () => {
  showCheckoutModal();
});

// 결제 완료
socket.on("payment_done", () => {
  closeCheckoutModal();
  showToast("결제가 완료되었습니다 ✓");
});

// 미결제 출구 차단
socket.on("checkout_blocked", () => {
  showToast("결제 후 통과 가능합니다");
});

// 상품 검색 결과
socket.on("find_product_result", (data) => {
  showFindProductResult(data);
});

// 도착
socket.on("arrived", (data) => {
  showArrivedModal(data.zone_name || "목적지");
});

// 안내 실패
socket.on("nav_failed", () => {
  showToast("안내에 실패했습니다");
  closeFindPanel();
});

// LOCKED
socket.on("enter_locked", () => {
  showLockedPanel();
});

// HALTED
socket.on("enter_halted", () => {
  showHaltedPanel();
});

// 직원 처리 완료 → 세션 종료
socket.on("staff_resolved", () => {
  sessionEnd();
});

// ── 상태바 갱신 ──────────────────────────────────────────────

function updateStatusBar(data) {
  const robot = data.my_robot || {};
  const mode = robot.mode || "OFFLINE";
  currentMode = mode;

  const badgeEl = document.getElementById("mode-badge");
  if (badgeEl) {
    badgeEl.className = "badge badge-" + mode;
    badgeEl.textContent = _modeLabel(mode);
  }

  const battEl = document.getElementById("battery-level");
  if (battEl) {
    const batt = robot.battery ?? "--";
    battEl.textContent = "🔋" + batt + "%";
    battEl.style.color = batt < 20 ? "#ef4444" : "";
  }
}

// ── 패널 표시/숨김 ─────────────────────────────────────────────

const SHOPPING_MODES = ["TRACKING", "TRACKING_CHECKOUT", "WAITING", "GUIDING", "SEARCHING"];

function updatePanelVisibility(mode) {
  if (!mode) return;
  currentMode = mode;

  const panelIdle     = document.getElementById("panel-idle");
  const panelShopping = document.getElementById("panel-shopping");
  const panelLocked   = document.getElementById("panel-locked");
  const panelHalted   = document.getElementById("panel-halted");

  // 패널 전환
  _setActive(panelIdle,     mode === "IDLE");
  _setActive(panelShopping, SHOPPING_MODES.includes(mode));
  _setActive(panelLocked,   mode === "LOCKED" || mode === "RETURNING");
  _setActive(panelHalted,   mode === "HALTED");

  // [대기하기] / [따라가기] 버튼 전환
  const btnWait   = document.getElementById("btn-wait");
  const btnFollow = document.getElementById("btn-follow");
  if (btnWait)   btnWait.style.display   = (mode === "TRACKING" || mode === "TRACKING_CHECKOUT") ? "" : "none";
  if (btnFollow) btnFollow.style.display = (mode === "WAITING") ? "" : "none";
}

function showTrackingPanel() {
  updatePanelVisibility("TRACKING");
}

// ── 결제 팝업 ──────────────────────────────────────────────────

function showCheckoutModal() {
  const modal = document.getElementById("checkout-modal");
  if (modal) modal.classList.remove("hidden");
}

function closeCheckoutModal() {
  const modal = document.getElementById("checkout-modal");
  if (modal) modal.classList.add("hidden");
}

// ── 도착 팝업 ──────────────────────────────────────────────────

function showArrivedModal(zoneName) {
  arrivedZoneName = zoneName;
  const modal = document.getElementById("arrived-modal");
  const nameEl = document.getElementById("arrived-zone-name");
  if (nameEl) nameEl.textContent = zoneName;
  if (modal) modal.classList.remove("hidden");
}

function closeArrivedModal() {
  const modal = document.getElementById("arrived-modal");
  if (modal) modal.classList.add("hidden");
  // [확인] 클릭 → resume_tracking
  socket.emit("resume_tracking", {});
}

// ── LOCKED / HALTED 패널 ───────────────────────────────────────

function showLockedPanel() {
  updatePanelVisibility("LOCKED");
}

function showHaltedPanel() {
  updatePanelVisibility("HALTED");
}

// ── 세션 종료 ──────────────────────────────────────────────────

function sessionEnd() {
  // 로그아웃 POST 후 리다이렉트
  fetch("/logout", { method: "POST" })
    .finally(() => {
      window.location.href = "/login";
    });
}

// ── 상품 검색 패널 ─────────────────────────────────────────────

function openFindPanel() {
  const overlay = document.getElementById("find-overlay");
  if (overlay) overlay.classList.remove("hidden");
  const input = document.getElementById("find-input");
  if (input) { input.value = ""; input.focus(); }
  const resultEl = document.getElementById("find-result");
  if (resultEl) resultEl.textContent = "";
}

function closeFindPanel() {
  const overlay = document.getElementById("find-overlay");
  if (overlay) overlay.classList.add("hidden");
}

function submitFind() {
  const input = document.getElementById("find-input");
  const name = input ? input.value.trim() : "";
  if (!name) return;
  socket.emit("find_product", { name });
}

function showFindProductResult(data) {
  const resultEl = document.getElementById("find-result");
  if (data.error) {
    if (resultEl) resultEl.textContent = data.error;
    return;
  }
  if (resultEl) {
    resultEl.textContent = `"${data.zone_name}"으로 안내합니다.`;
  }
  // 패널 닫기
  setTimeout(closeFindPanel, 1200);
}

// ── QR 스캔 패널 ───────────────────────────────────────────────

let qrTimeoutId = null;
const QR_TIMEOUT_SEC = 30;

function openQrPanel() {
  const overlay = document.getElementById("qr-overlay");
  if (overlay) overlay.classList.remove("hidden");
  _resetQrTimeout();
}

function closeQrPanel() {
  const overlay = document.getElementById("qr-overlay");
  if (overlay) overlay.classList.add("hidden");
  if (qrTimeoutId) { clearTimeout(qrTimeoutId); qrTimeoutId = null; }
  // 담기 완료 → 추종 재개
  socket.emit("resume_tracking", {});
}

function _resetQrTimeout() {
  if (qrTimeoutId) clearTimeout(qrTimeoutId);
  _animateQrBar();
  qrTimeoutId = setTimeout(() => closeQrPanel(), QR_TIMEOUT_SEC * 1000);
}

function _animateQrBar() {
  const bar = document.getElementById("qr-progress");
  if (!bar) return;
  bar.style.transition = "none";
  bar.style.width = "100%";
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      bar.style.transition = `width ${QR_TIMEOUT_SEC}s linear`;
      bar.style.width = "0%";
    });
  });
}

// ── 맵 오버레이 ────────────────────────────────────────────────

function openMapOverlay() {
  const overlay = document.getElementById("map-overlay");
  if (overlay) overlay.classList.remove("hidden");
}

function closeMapOverlay() {
  const overlay = document.getElementById("map-overlay");
  if (overlay) overlay.classList.add("hidden");
}

// ── 쇼핑 종료 ──────────────────────────────────────────────────

function requestReturn() {
  if (hasUnpaidItems()) {
    const ok = confirm("미결제 물건이 있습니다. 종료하면 카트가 잠길 수 있습니다.\n계속하시겠습니까?");
    if (!ok) return;
  }
  socket.emit("return", {});
}

// ── STT (Web Speech API) ───────────────────────────────────────

let recognition = null;

function toggleMic() {
  const btn = document.getElementById("btn-mic");

  if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
    showToast("이 브라우저는 음성 인식을 지원하지 않습니다.");
    return;
  }

  if (recognition) {
    recognition.stop();
    recognition = null;
    if (btn) btn.classList.remove("recording");
    return;
  }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.lang = "ko-KR";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  if (btn) btn.classList.add("recording");

  recognition.onresult = (e) => {
    const text = e.results[0][0].transcript;
    const input = document.getElementById("find-input");
    if (input) input.value = text;
    submitFind();
  };

  recognition.onerror = () => {
    showToast("음성 인식에 실패했습니다.");
  };

  recognition.onend = () => {
    if (btn) btn.classList.remove("recording");
    recognition = null;
  };

  recognition.start();
}

// ── 토스트 알림 ─────────────────────────────────────────────────

function showToast(message) {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.remove();
  }, 3000);
}

// ── 유틸 ────────────────────────────────────────────────────────

function _setActive(el, active) {
  if (!el) return;
  if (active) {
    el.classList.add("active");
  } else {
    el.classList.remove("active");
  }
}

function _modeLabel(mode) {
  const labels = {
    IDLE:               "등록 대기",
    TRACKING:           "추종 중",
    TRACKING_CHECKOUT:  "추종 중 (결제완료)",
    GUIDING:            "안내 중",
    SEARCHING:          "탐색 중",
    WAITING:            "대기 중",
    LOCKED:             "잠금",
    RETURNING:          "귀환 중",
    CHARGING:           "충전 중",
    HALTED:             "배터리 부족",
    OFFLINE:            "오프라인",
  };
  return labels[mode] || mode;
}
