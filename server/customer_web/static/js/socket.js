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
// 추종 비활성화 여부
let followDisabled = false;
// WAITING 카운트다운: main.html 이 `window.__SHOPPINKKI_WAITING_TIMEOUT_SEC__` 로
// shoppinkki_core.config.WAITING_TIMEOUT 과 동기. 이후 status.waiting_timeout_sec 로 덮어씀.
const WAITING_TIMEOUT_INJECT_FALLBACK_SEC = 300;
const DEFAULT_WAITING_TIMEOUT_SEC = (typeof window !== "undefined" &&
  typeof window.__SHOPPINKKI_WAITING_TIMEOUT_SEC__ === "number" &&
  window.__SHOPPINKKI_WAITING_TIMEOUT_SEC__ > 0)
  ? Math.floor(window.__SHOPPINKKI_WAITING_TIMEOUT_SEC__)
  : WAITING_TIMEOUT_INJECT_FALLBACK_SEC;
let waitingDeadlineMs = null;
let waitingTimerId = null;
let waitingTimeoutSec = DEFAULT_WAITING_TIMEOUT_SEC;
let waitingTimeoutHandled = false;
let waitingRedirectTimerId = null;
/**
 * WAITING 종료 트리거 2차(보험): UI 카운트다운 00:00 후에도 모드가 WAITING이면
 * `mode: RETURNING` 전송. 1차: 로봇 BT3 타임아웃 → BTRunner → SM 전이.
 * 지연은 BT와의 레이스 완화(보통 BT가 먼저 전이).
 */
const WAITING_RETURNING_FALLBACK_MS = 2500;
// 도착한 구역명 캐시
let arrivedZoneName = "";

// control_service TCP 연결 상태 (customer_web ↔ control_service)
window.CONTROL_CONNECTED = false;

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
  window.CONTROL_CONNECTED = !!data.connected;
});

// 내 로봇 메시지인지 확인 (다른 로봇 status/cart 무시)
function _isMyRobot(data) {
  return !data.robot_id || String(data.robot_id) === String(window.ROBOT_ID);
}

// status — 1~2Hz push
socket.on("status", (data) => {
  if (!_isMyRobot(data)) return;
  updateStatusBar(data);
  const timeoutFromStatus = Number(
    data.my_robot?.waiting_timeout_sec ?? data.waiting_timeout_sec
  );
  if (Number.isFinite(timeoutFromStatus) && timeoutFromStatus > 0) {
    waitingTimeoutSec = Math.floor(timeoutFromStatus);
  }
  // follow_disabled 값을 먼저 반영한 뒤 버튼 가시성을 계산해야
  // 상태 업데이트 타이밍에 따른 버튼 깜빡임/오판정이 줄어든다.
  updateFollowDisabledBanner(data.my_robot?.follow_disabled ?? data.follow_disabled);
  updatePanelVisibility(data.my_robot?.mode ?? data.mode);
  if (typeof MapRenderer !== "undefined") {
    MapRenderer.updateFromStatus(data);
  }
});

// cart
socket.on("cart", (data) => {
  if (!_isMyRobot(data)) return;
  updateCart(data.items || []);
});

// 인형 등록 완료
socket.on("registration_done", () => {
  showTrackingPanel();
});

// 결제 구역 진입
socket.on("checkout_zone_enter", () => {
  if (typeof syncCheckoutModalFromCart === "function") {
    syncCheckoutModalFromCart();
  }
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

// RETURNING(빈 카트) 자동 종료 등 서버 주도 세션 종료
socket.on("session_ended", (data) => {
  if (!_isMyRobot(data || {})) return;
  sessionEnd();
});

// ── 상태바 갱신 ──────────────────────────────────────────────

function updateStatusBar(data) {
  const mode = data.my_robot?.mode ?? data.mode ?? "OFFLINE";
  currentMode = mode;

  const badgeEl = document.getElementById("mode-badge");
  if (badgeEl) {
    badgeEl.className = "badge badge-" + mode;
    badgeEl.textContent = _modeLabel(mode);
  }

  const battEl = document.getElementById("battery-level");
  if (battEl) {
    const batt = data.my_robot?.battery ?? data.battery ?? "--";
    battEl.textContent = "🔋" + batt + "%";
    battEl.style.color = batt < 20 ? "#ef4444" : "";
  }
}

// ── 패널 표시/숨김 ─────────────────────────────────────────────

const SHOPPING_MODES = ["TRACKING", "TRACKING_CHECKOUT", "WAITING", "GUIDING", "SEARCHING"];

function _clearWaitingTimers() {
  if (waitingTimerId) {
    clearInterval(waitingTimerId);
    waitingTimerId = null;
  }
  if (waitingRedirectTimerId) {
    clearTimeout(waitingRedirectTimerId);
    waitingRedirectTimerId = null;
  }
}

function _hideWaitingCountdown() {
  const waitingEl = document.getElementById("waiting-countdown");
  if (waitingEl) waitingEl.style.display = "none";
}

function _armWaitingDeadline() {
  // status 샘플링 지연과 무관하게 버튼 클릭 시점 기준으로 카운트를 강제한다.
  waitingDeadlineMs = Date.now() + waitingTimeoutSec * 1000;
  waitingTimeoutHandled = false;
}

function updatePanelVisibility(mode) {
  if (!mode) return;
  const prevMode = currentMode;
  currentMode = mode;

  const panelCharging = document.getElementById("panel-charging");
  const panelIdle     = document.getElementById("panel-idle");
  const panelShopping = document.getElementById("panel-shopping");
  const panelLocked   = document.getElementById("panel-locked");
  const panelHalted   = document.getElementById("panel-halted");

  // 패널 전환
  _setActive(panelCharging, mode === "CHARGING");
  _setActive(panelIdle,     mode === "IDLE");
  _setActive(panelShopping, SHOPPING_MODES.includes(mode));
  _setActive(panelLocked,   mode === "LOCKED" || mode === "RETURNING");
  _setActive(panelHalted,   mode === "HALTED");

  // [대기하기] / [따라가기] 버튼 전환
  const btnWait   = document.getElementById("btn-wait");
  const btnFollow = document.getElementById("btn-follow");

  const isGuiding = (mode === "GUIDING" || mode === "SEARCHING");
  const isShoppingMode = SHOPPING_MODES.includes(mode);
  const isWaiting = (mode === "WAITING");
  // UX 요구사항: 쇼핑 패널에서는 [대기하기]와 [쇼핑 종료]를 항상 함께 노출.
  const showWait = isShoppingMode && !isWaiting;
  const handleResumeFromWaiting = () => {
    // WAITING 취소 직후 status 반영 지연(1~2Hz) 중 경합을 막기 위해
    // 카운트다운/redirect 타이머를 즉시 정리한다.
    _clearWaitingTimers();
    waitingDeadlineMs = null;
    waitingTimeoutHandled = false;
    _hideWaitingCountdown();

    // WAITING 중 취소 시 이전 추종 상태로 복귀
    socket.emit("resume_tracking", {});
  };

  if (btnWait) {
    btnWait.style.display = showWait ? "" : "none";
    btnWait.disabled = false;
    if (isGuiding) {
      btnWait.innerHTML = "⏸ 안내 중단";
      btnWait.onclick = () => {
        socket.emit("resume_tracking", {});
        showToast("상품 안내를 중단합니다.");
      };
    } else {
      btnWait.innerHTML = "⏸ 대기하기";
      btnWait.onclick = () => {
        _armWaitingDeadline();
        socket.emit("mode", { value: "WAITING" });
      };
    }
  }
  if (btnFollow) {
    btnFollow.style.display = (mode === "WAITING") ? "" : "none";
    btnFollow.onclick = (mode === "WAITING")
      ? handleResumeFromWaiting
      : () => socket.emit("resume_tracking", {});
  }
  _syncWaitingCountdown(prevMode, mode);
}

function showTrackingPanel() {
  updatePanelVisibility("TRACKING");
}

function updateFollowDisabledBanner(disabled) {
  followDisabled = !!disabled;
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
      const rid = window.ROBOT_ID;
      window.location.href = rid ? `/login?robot_id=${rid}` : "/login";
    });
}

// ── 상품 검색 패널 ─────────────────────────────────────────────

function openFindPanel() {
  const overlay = document.getElementById("find-overlay");
  if (overlay) overlay.classList.remove("hidden");
  _resetFindPanelState();
}

function closeFindPanel() {
  const overlay = document.getElementById("find-overlay");
  if (overlay) overlay.classList.add("hidden");
  _resetFindPanelState();
}

function submitFind() {
  const input = document.getElementById("find-input");
  const name = input ? input.value.trim() : "";
  if (!name) return;

  const resultEl = document.getElementById("find-result");
  const btnPrimary = document.getElementById("btn-find-primary");
  const btnSecondary = document.getElementById("btn-find-secondary");

  if (resultEl) {
    resultEl.innerHTML = `<span class="spinner-small"></span> AI가 답변을 준비 중입니다...`;
  }
  if (btnPrimary) btnPrimary.disabled = true;
  if (btnSecondary) btnSecondary.disabled = true;

  socket.emit("find_product", { name });
}

function showFindProductResult(data) {
  const resultEl = document.getElementById("find-result");
  const btnPrimary = document.getElementById("btn-find-primary");
  const btnSecondary = document.getElementById("btn-find-secondary");
  const mapPreview = document.getElementById("find-map-preview");

  if (btnPrimary) btnPrimary.disabled = false;
  if (btnSecondary) btnSecondary.disabled = false;

  if (data.error) {
    if (resultEl) resultEl.textContent = data.error;
    return;
  }

  if (resultEl) {
    resultEl.textContent = data.answer || `"${data.zone_name}"으로 안내합니다.`;
  }

  // 버튼 텍스트 및 기능 전환
  if (btnPrimary) {
    btnPrimary.innerHTML = "🚀 안내 시작하기";
    btnPrimary.onclick = () => startNavigationFromSearch(data.zone_id, data.zone_name);
  }
  if (btnSecondary) {
    btnSecondary.innerHTML = "🔍 더 물어보기";
    btnSecondary.onclick = () => continueSearching();
  }

  // 지도 미리보기 영역 표시 (Placeholder)
  if (mapPreview) mapPreview.classList.remove("hidden");
}

function startNavigationFromSearch(zoneId, zoneName) {
  if (!zoneId) return;
  socket.emit("navigate_to", { zone_id: zoneId });
  showToast(`"${zoneName}"으로 안내를 시작합니다.`);
  closeFindPanel();
}

function continueSearching() {
  _resetFindPanelState();
}

function _resetFindPanelState() {
  const input = document.getElementById("find-input");
  const resultEl = document.getElementById("find-result");
  const btnPrimary = document.getElementById("btn-find-primary");
  const btnSecondary = document.getElementById("btn-find-secondary");
  const mapPreview = document.getElementById("find-map-preview");

  if (input) { input.value = ""; input.focus(); }
  if (resultEl) resultEl.textContent = "";
  if (mapPreview) mapPreview.classList.add("hidden");

  if (btnPrimary) {
    btnPrimary.disabled = false;
    btnPrimary.innerHTML = "검색";
    btnPrimary.onclick = submitFind;
  }
  if (btnSecondary) {
    btnSecondary.disabled = false;
    btnSecondary.innerHTML = "닫기";
    btnSecondary.onclick = closeFindPanel;
  }
}

// ── QR 스캔 패널 ───────────────────────────────────────────────

let qrTimeoutId = null;
const QR_TIMEOUT_SEC = 30;
let _qrStream = null;      // MediaStream (시뮬레이션 모드)
let _qrAnimId = null;       // requestAnimationFrame ID
let _qrLastScanned = "";    // 중복 스캔 방지
let _qrVideoHealthTimer = null;
let _qrCloseAfterFirstScan = true; // 첫 스캔 후 자동 닫기

function openQrPanel() {
  const overlay = document.getElementById("qr-overlay");
  if (overlay) overlay.classList.remove("hidden");
  _resetQrTimeout();
  _qrLastScanned = "";

  // 웹앱 카메라로 QR 스캔
  _startQrCamera();
}

function closeQrPanel() {
  const overlay = document.getElementById("qr-overlay");
  if (overlay) overlay.classList.add("hidden");
  if (qrTimeoutId) { clearTimeout(qrTimeoutId); qrTimeoutId = null; }
  _stopQrCamera();
  // 담기 완료 → 추종 재개
  socket.emit("resume_tracking", {});
}

function _startQrCamera() {
  const wrap = document.getElementById("qr-camera-wrap");
  const video = document.getElementById("qr-video");
  if (!wrap || !video) return;
  wrap.style.display = "";

  // 일부 환경에서 {facingMode:"environment"} 제약 때문에 검은 화면/장치 선택 문제가 날 수 있어
  // 실패 시 더 완화된 제약(video:true)로 재시도한다.
  const preferred = { video: { facingMode: "environment", width: { ideal: 640 }, height: { ideal: 480 } } };
  const fallback = { video: true };

  const tryGet = (constraints) => navigator.mediaDevices.getUserMedia(constraints);

  tryGet(preferred)
    .catch((e1) => {
      console.warn("[QR] 카메라 제약(preferred) 실패, fallback 재시도:", e1);
      return tryGet(fallback);
    })
    .then((stream) => {
      _qrStream = stream;
      video.srcObject = stream;
      const playPromise = video.play();
      if (playPromise && typeof playPromise.catch === "function") {
        playPromise.catch((e) => console.warn("[QR] video.play() 실패:", e));
      }
      _startQrVideoHealthCheck(video);
      _qrScanLoop();
    })
    .catch((err) => {
      console.warn("[QR] 카메라 접근 실패:", err);
      const reason = err && (err.name || err.message) ? (err.name || err.message) : "unknown";
      showToast(`카메라를 사용할 수 없습니다 (${reason})`);
      wrap.style.display = "none";
    });
}

function _stopQrCamera() {
  if (_qrAnimId) { cancelAnimationFrame(_qrAnimId); _qrAnimId = null; }
  if (_qrVideoHealthTimer) { clearTimeout(_qrVideoHealthTimer); _qrVideoHealthTimer = null; }
  if (_qrStream) {
    _qrStream.getTracks().forEach((t) => t.stop());
    _qrStream = null;
  }
  const video = document.getElementById("qr-video");
  if (video) video.srcObject = null;
  const wrap = document.getElementById("qr-camera-wrap");
  if (wrap) wrap.style.display = "none";
  const resultEl = document.getElementById("qr-scan-result");
  if (resultEl) resultEl.style.display = "none";
}

function _startQrVideoHealthCheck(video) {
  if (_qrVideoHealthTimer) { clearTimeout(_qrVideoHealthTimer); _qrVideoHealthTimer = null; }
  // 스트림이 열렸는데도 videoWidth/Height가 0이면 대개 권한/점유/디바이스 선택 문제다.
  _qrVideoHealthTimer = setTimeout(() => {
    if (!_qrStream) return;
    if ((video.videoWidth || 0) < 2 || (video.videoHeight || 0) < 2) {
      console.warn("[QR] 비디오 프레임 없음 (videoWidth/Height=0)");
      showToast("카메라 영상이 들어오지 않습니다 (권한/다른 앱 점유/디바이스 확인)");
    }
  }, 1500);
}

function _qrScanLoop() {
  if (!_qrStream) return;
  const video = document.getElementById("qr-video");
  const canvas = document.getElementById("qr-canvas");
  if (!video || !canvas || typeof jsQR === "undefined") return;

  const ctx = canvas.getContext("2d", { willReadFrequently: true });

  function tick() {
    if (!_qrStream) return;
    if (video.readyState === video.HAVE_ENOUGH_DATA) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      ctx.drawImage(video, 0, 0);
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const code = jsQR(imageData.data, canvas.width, canvas.height, { inversionAttempts: "dontInvert" });
      if (code && code.data && code.data !== _qrLastScanned) {
        _qrLastScanned = code.data;
        _onQrDecoded(code.data);
      }
    }
    _qrAnimId = requestAnimationFrame(tick);
  }
  tick();
}

function _onQrDecoded(data) {
  // QR 데이터 전송 + 피드백 표시
  const resultEl = document.getElementById("qr-scan-result");
  try {
    const parsed = JSON.parse(data);
    const name = parsed.product_name || parsed.name || data;
    if (resultEl) {
      resultEl.textContent = "✓ " + name;
      resultEl.style.display = "";
      setTimeout(() => { resultEl.style.display = "none"; }, 1500);
    }
  } catch {
    if (resultEl) {
      resultEl.textContent = "✓ 스캔 완료";
      resultEl.style.display = "";
      setTimeout(() => { resultEl.style.display = "none"; }, 1500);
    }
  }
  socket.emit("qr_scan", { data: data });
  // 타임아웃 리셋 (활동 감지)
  _resetQrTimeout();

  // 기본 동작: 첫 스캔이 성공하면 바로 닫아 중복 인식을 막는다.
  if (_qrCloseAfterFirstScan) {
    // UI 피드백이 살짝 보이도록 짧게 지연 후 닫기
    setTimeout(() => closeQrPanel(), 350);
    return;
  }

  // (옵션) 여러 개 연속 스캔을 허용할 때만 다시 스캔 허용
  setTimeout(() => { _qrLastScanned = ""; }, 1500);
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
  let msg = "쑈삥끼 사용을 끝내시겠습니까?";
  if (hasUnpaidItems()) {
    msg += "\n\n⚠️ 미결제 항목이 있습니다. 종료 시 미결제 항목은 자동 반환처리됩니다.";
  }
  const ok = confirm(msg);
  if (!ok) return;
  socket.emit("return", {});
  // return 이벤트가 control_service까지 전달되기 전에 페이지가 이동하면 누락될 수 있어
  // 아주 짧게 지연 후 로그아웃/리다이렉트한다.
  setTimeout(() => sessionEnd(), 200);
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

function _syncWaitingCountdown(prevMode, mode) {
  const el = document.getElementById("waiting-countdown");
  if (!el) return;

  if (mode !== "WAITING") {
    _clearWaitingTimers();
    waitingTimeoutHandled = false;
    waitingDeadlineMs = null;
    _hideWaitingCountdown();
    return;
  }

  // WAITING에 처음 진입할 때만 deadline을 잡고, 기간은 waitingTimeoutSec(설정·status)이다.
  if (prevMode !== "WAITING" || waitingDeadlineMs === null) {
    waitingDeadlineMs = Date.now() + waitingTimeoutSec * 1000;
    waitingTimeoutHandled = false;
  }

  const render = () => {
    if (waitingDeadlineMs === null) return;
    const remainMs = Math.max(0, waitingDeadlineMs - Date.now());
    const remainSec = Math.floor(remainMs / 1000);
    const mm = String(Math.floor(remainSec / 60)).padStart(2, "0");
    const ss = String(remainSec % 60).padStart(2, "0");
    el.textContent = `자동 복귀까지 ${mm}:${ss}`;
    el.style.display = "";

    if (remainSec === 0 && !waitingTimeoutHandled) {
      waitingTimeoutHandled = true;
      if (waitingRedirectTimerId) {
        clearTimeout(waitingRedirectTimerId);
        waitingRedirectTimerId = null;
      }
      // BT3가 먼저 전이했으면 currentMode는 이미 변경 → WAITING일 때만 전송.
      waitingRedirectTimerId = setTimeout(() => {
        waitingRedirectTimerId = null;
        if (currentMode === "WAITING") {
          console.info(
            "[socket] WAITING: UI deadline reached; fallback mode RETURNING"
          );
          socket.emit("mode", { value: "RETURNING" });
        }
      }, WAITING_RETURNING_FALLBACK_MS);
    }
  };

  render();
  if (waitingTimerId) clearInterval(waitingTimerId);
  waitingTimerId = setInterval(render, 1000);
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
