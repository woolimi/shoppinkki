/**
 * map.js — Canvas 기반 미니어처 마트 맵 렌더링
 *
 * shop.yaml 설정:
 *   resolution : 미터/픽셀 (예: 0.05)
 *   origin     : [x, y, theta] 맵 원점 (미터)
 *
 * 좌표 변환:
 *   px_x = (pos_x - origin_x) / resolution
 *   px_y = img_height - (pos_y - origin_y) / resolution   // Y축 반전
 *
 * 핀치 줌 지원 (모바일).
 */

"use strict";

const MapRenderer = (() => {
  // ── shop.yaml 파라미터 (서버에서 주입하거나 기본값 사용) ──
  const MAP_CONFIG = {
    resolution: window.MAP_RESOLUTION || 0.05,
    originX:    window.MAP_ORIGIN_X   || -0.1,
    originY:    window.MAP_ORIGIN_Y   || -0.1,
    imageUrl:   window.MAP_IMAGE_URL  || "/static/map/shop.png",
  };

  let canvas, ctx;
  let mapImage = null;
  let myRobotId = null;

  // 최신 로봇 위치 캐시
  let myRobot = null;          // {robot_id, pos_x, pos_y}
  let otherRobots = [];        // [{robot_id, pos_x, pos_y}, ...]

  // 핀치 줌 상태
  let scale = 1;
  let lastDist = null;

  // ── 초기화 ──────────────────────────────────────────────────

  function init(canvasId, robotId) {
    canvas = document.getElementById(canvasId);
    if (!canvas) return;
    ctx = canvas.getContext("2d");
    myRobotId = String(robotId);

    // 맵 이미지 로드
    mapImage = new Image();
    mapImage.onload = () => {
      canvas.width  = mapImage.naturalWidth;
      canvas.height = mapImage.naturalHeight;
      render();
    };
    mapImage.onerror = () => {
      // 이미지 없으면 빈 캔버스에 텍스트
      canvas.width  = 400;
      canvas.height = 300;
      ctx.fillStyle = "#1e293b";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#94a3b8";
      ctx.font = "14px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("맵 이미지를 불러올 수 없습니다.", canvas.width / 2, canvas.height / 2);
    };
    mapImage.src = MAP_CONFIG.imageUrl;

    // 핀치 줌 이벤트
    canvas.addEventListener("touchstart", onTouchStart, { passive: false });
    canvas.addEventListener("touchmove",  onTouchMove,  { passive: false });
    canvas.addEventListener("touchend",   onTouchEnd,   { passive: false });
  }

  // ── 상태 업데이트 ────────────────────────────────────────────

  /**
   * status 메시지로 로봇 위치 갱신 후 재렌더링.
   * @param {object} statusMsg — 채널 A status 페이로드
   */
  function updateFromStatus(statusMsg) {
    if (statusMsg.my_robot) {
      myRobot = statusMsg.my_robot;
    }
    if (Array.isArray(statusMsg.other_robots)) {
      otherRobots = statusMsg.other_robots;
    }
    if (canvas && mapImage && mapImage.complete) {
      render();
    }
  }

  // ── 렌더링 ──────────────────────────────────────────────────

  function render() {
    if (!canvas || !ctx) return;

    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // 핀치 줌 적용
    const cx = canvas.width  / 2;
    const cy = canvas.height / 2;
    ctx.translate(cx, cy);
    ctx.scale(scale, scale);
    ctx.translate(-cx, -cy);

    // 맵 이미지
    if (mapImage && mapImage.complete) {
      ctx.drawImage(mapImage, 0, 0);
    }

    // 다른 로봇 (회색, 40% 불투명)
    ctx.globalAlpha = 0.4;
    otherRobots.forEach((r) => {
      const [px, py] = worldToCanvas(r.pos_x, r.pos_y);
      drawRobotDot(px, py, "#94a3b8", 10, String(r.robot_id));
    });

    // 내 로봇 (파란색, 불투명)
    ctx.globalAlpha = 1.0;
    if (myRobot) {
      const [px, py] = worldToCanvas(myRobot.pos_x, myRobot.pos_y);
      drawRobotDot(px, py, "#3b82f6", 12, "#" + myRobotId);
    }

    ctx.restore();
  }

  function drawRobotDot(px, py, color, r, label) {
    // 원
    ctx.beginPath();
    ctx.arc(px, py, r, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.stroke();

    // 레이블
    if (label) {
      ctx.fillStyle = "#1e293b";
      ctx.font = `bold ${r}px sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText(label, px, py - r - 4);
    }
  }

  // ── 좌표 변환 ────────────────────────────────────────────────

  function worldToCanvas(wx, wy) {
    const px = (wx - MAP_CONFIG.originX) / MAP_CONFIG.resolution;
    const py = canvas.height - (wy - MAP_CONFIG.originY) / MAP_CONFIG.resolution;
    return [px, py];
  }

  // ── 핀치 줌 ─────────────────────────────────────────────────

  function getTouchDist(touches) {
    const dx = touches[0].clientX - touches[1].clientX;
    const dy = touches[0].clientY - touches[1].clientY;
    return Math.hypot(dx, dy);
  }

  function onTouchStart(e) {
    if (e.touches.length === 2) {
      e.preventDefault();
      lastDist = getTouchDist(e.touches);
    }
  }

  function onTouchMove(e) {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dist = getTouchDist(e.touches);
      if (lastDist) {
        const ratio = dist / lastDist;
        scale = Math.max(0.5, Math.min(5, scale * ratio));
        render();
      }
      lastDist = dist;
    }
  }

  function onTouchEnd(e) {
    if (e.touches.length < 2) lastDist = null;
  }

  // ── 공개 API ─────────────────────────────────────────────────

  return { init, updateFromStatus };
})();
