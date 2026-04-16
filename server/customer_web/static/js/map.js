/**
 * map.js — 벡터 기반 미니어처 마트 맵 렌더링
 *
 * SLAM 이미지 없이 Canvas 2D로 직접 그림.
 * 구역 블록 + 로봇 마커 + 핀치 줌.
 */

"use strict";

const MapRenderer = (() => {
  /* ── 세계 좌표 경계 (미터) ─────────────────────────── */
  const W_MAX_X = 1.20, W_MIN_X = -0.10;
  const W_MAX_Y = 0.05, W_MIN_Y = -1.65;
  const W_SPAN_X = W_MAX_X - W_MIN_X;
  const W_SPAN_Y = W_MAX_Y - W_MIN_Y;

  /* 논리 좌표계 */
  const LW = 420, LH = 330;

  /* ── 구역 블록 ─────────────────────────────────────── */
  const ZONES = [
    { name: "가전\n제품", icon: "\uD83D\uDD0C", x1: 0.42, y1: 0.02, x2: 0.77, y2: -0.10, bg: "#e0f2fe", fg: "#0369a1" },
    { name: "과자",       icon: "\uD83C\uDF6A", x1: 0.77, y1: 0.02, x2: 1.05, y2: -0.10, bg: "#fef9c3", fg: "#a16207" },
    { name: "해산물",     icon: "\uD83D\uDC1F", x1: 1.05, y1: -0.10, x2: 1.17, y2: -0.50, bg: "#cffafe", fg: "#0e7490" },
    { name: "육류",       icon: "\uD83E\uDD69", x1: 1.05, y1: -0.50, x2: 1.17, y2: -1.06, bg: "#ffe4e6", fg: "#be123c" },
    { name: "채소",       icon: "\uD83E\uDD6C", x1: 1.05, y1: -1.06, x2: 1.17, y2: -1.38, bg: "#dcfce7", fg: "#15803d" },
    { name: "화장실",     icon: "\uD83D\uDEBB", x1: 0.72, y1: -1.43, x2: 0.95, y2: -1.58, bg: "#f1f5f9", fg: "#475569" },
    { name: "결제구역",   icon: "\uD83D\uDCB3", x1: 0.06, y1: -1.28, x2: 0.27, y2: -1.56, bg: "#d1fae5", fg: "#047857" },
    { name: "충전소",     icon: "\u26A1",        x1: -0.06, y1: -0.52, x2: 0.06, y2: -0.93, bg: "#fef9c3", fg: "#a16207" },
  ];

  /* ── 선반 zone (장애물 안 색상) ─────────────────────── */
  const SHELF_ZONES = [
    { x1: 0.424, y1: -0.393, x2: 0.844, y2: -0.493,
      a: { name: "빵", icon: "\uD83C\uDF5E", bg: "#fed7aa", fg: "#9a3412" },
      b: { name: "가공식품", icon: "\uD83E\uDD6B", bg: "#fce7f3", fg: "#9d174d" } },
    { x1: 0.633, y1: -1.023, x2: 0.843, y2: -1.123,
      a: { name: "음료", icon: "\uD83E\uDD64", bg: "#e0e7ff", fg: "#4338ca" },
      b: null },
  ];

  /* ── 장애물 ────────────────────────────────────────── */
  const OBSTACLES = [
    { x1: 0.064, y1: -1.22, x2: 0.264, y2: -1.25 },
  ];

  const ENTRANCE_EXIT = [
    { name: "입구", wx: -0.04, wy: -0.057, arrow: "\u25B2", color: "#16a34a" },
    { name: "출구", wx: -0.04, wy: -1.547, arrow: "\u25BC", color: "#dc2626" },
  ];

  /* ── 상태 ──────────────────────────────────────────── */
  let canvas, ctx;
  let myRobotId = null;
  let dpr = 1;
  let myRobot = null;
  let myPath = [];
  let otherRobots = [];
  let scale = 1, lastDist = null;
  let visible = false;
  let animFrameId = null;
  let pulsePhase = 0;

  const MY_COLOR    = "#2563eb";
  const OTHER_COLOR = "#94a3b8";
  const ROBOT_R     = 9;
  const ROBOT_R_SM  = 7;
  const SHELF_COLOR = "#a8896c";
  const FLOOR_COLOR = "#faf6f0";
  const WALL_COLOR  = "#78716c";

  /* ── 초기화 ────────────────────────────────────────── */
  function init(canvasId, robotId) {
    canvas = document.getElementById(canvasId);
    if (!canvas) return;
    ctx = canvas.getContext("2d");
    myRobotId = String(robotId);
    sizeBuffer();
    render();
    canvas.addEventListener("touchstart", onTouchStart, { passive: false });
    canvas.addEventListener("touchmove",  onTouchMove,  { passive: false });
    canvas.addEventListener("touchend",   onTouchEnd,   { passive: false });
  }

  function sizeBuffer() {
    dpr = Math.min(window.devicePixelRatio || 1, 3);
    var cssW = canvas.clientWidth  || 400;
    var cssH = canvas.clientHeight || Math.round(cssW * LH / LW);
    canvas.width  = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
  }

  /* ── 가시성 ────────────────────────────────────────── */
  function setVisible(v) {
    visible = v;
    if (v) { sizeBuffer(); render(); startAnim(); }
    else   { stopAnim(); }
  }

  function startAnim() {
    if (animFrameId) return;
    (function loop(ts) {
      pulsePhase = (ts % 2000) / 2000;
      render();
      if (visible) animFrameId = requestAnimationFrame(loop);
    })(performance.now());
  }

  function stopAnim() {
    if (animFrameId) { cancelAnimationFrame(animFrameId); animFrameId = null; }
  }

  /* ── 데이터 업데이트 ───────────────────────────────── */
  function updateFromStatus(statusMsg) {
    if (statusMsg.my_robot) {
      myRobot = statusMsg.my_robot;
    } else if (
      statusMsg.robot_id != null && statusMsg.pos_x != null &&
      myRobotId != null && String(statusMsg.robot_id) === myRobotId
    ) {
      myRobot = {
        robot_id: String(statusMsg.robot_id),
        pos_x: statusMsg.pos_x, pos_y: statusMsg.pos_y,
        yaw: statusMsg.yaw || 0,
      };
    }
    if (statusMsg.my_robot && Array.isArray(statusMsg.my_robot.path)) {
      myPath = statusMsg.my_robot.path;
    } else if (Array.isArray(statusMsg.path)) {
      myPath = statusMsg.path;
    }
    if (Array.isArray(statusMsg.other_robots)) otherRobots = statusMsg.other_robots;
    if (!animFrameId && canvas) render();
  }

  /* ── 렌더링 ────────────────────────────────────────── */
  function render() {
    if (!canvas || !ctx) return;
    var sx = canvas.width / LW, sy = canvas.height / LH;
    ctx.save();
    ctx.setTransform(sx, 0, 0, sy, 0, 0);
    var cx = LW / 2, cy = LH / 2;
    ctx.translate(cx, cy);
    ctx.scale(scale, scale);
    ctx.translate(-cx, -cy);

    /* 배경 */
    ctx.fillStyle = "#1c1917";
    ctx.fillRect(-10, -10, LW + 20, LH + 20);

    drawFloor();
    drawObstacles();
    drawShelfZones();
    drawZones();
    drawEntranceExit();

    drawPath();

    ctx.globalAlpha = 0.4;
    otherRobots.forEach(function(r) {
      var p = worldToCanvas(r.pos_x, r.pos_y);
      drawRobotMarker(p[0], p[1], r.yaw || 0, OTHER_COLOR, ROBOT_R_SM);
      drawRobotLabel(p[0], p[1], String(r.robot_id), ROBOT_R_SM);
    });
    ctx.globalAlpha = 1.0;

    if (myRobot) {
      var p = worldToCanvas(myRobot.pos_x, myRobot.pos_y);
      drawMyRobotMarker(p[0], p[1], myRobot.yaw || 0);
    }

    ctx.restore();
  }

  /* ── 마트 바닥 ─────────────────────────────────────── */
  function drawFloor() {
    var pad = 8;
    /* 그림자 */
    ctx.shadowColor = "rgba(0,0,0,0.4)";
    ctx.shadowBlur = 14;
    ctx.shadowOffsetX = 2; ctx.shadowOffsetY = 2;
    roundRect(pad, pad, LW - 2 * pad, LH - 2 * pad, 6);
    ctx.fillStyle = FLOOR_COLOR;
    ctx.fill();
    ctx.shadowColor = "transparent"; ctx.shadowBlur = 0;
    ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;

    /* 타일 패턴 */
    ctx.strokeStyle = "rgba(168,137,108,0.07)";
    ctx.lineWidth = 0.4;
    var step = 16;
    for (var gx = pad + step; gx < LW - pad; gx += step) {
      ctx.beginPath(); ctx.moveTo(gx, pad); ctx.lineTo(gx, LH - pad); ctx.stroke();
    }
    for (var gy = pad + step; gy < LH - pad; gy += step) {
      ctx.beginPath(); ctx.moveTo(pad, gy); ctx.lineTo(LW - pad, gy); ctx.stroke();
    }

    /* 벽 */
    roundRect(pad, pad, LW - 2 * pad, LH - 2 * pad, 6);
    ctx.strokeStyle = WALL_COLOR;
    ctx.lineWidth = 3.5;
    ctx.stroke();
  }

  /* ── 장애물 ────────────────────────────────────────── */
  function drawObstacles() {
    OBSTACLES.forEach(function(o) {
      var p1 = worldToCanvas(o.x2, o.y1), p2 = worldToCanvas(o.x1, o.y2);
      var ow = p2[0] - p1[0], oh = p2[1] - p1[1];
      ctx.fillStyle = SHELF_COLOR;
      ctx.fillRect(p1[0], p1[1], ow, Math.max(oh, 2.5));
    });
  }

  /* ── 선반 zone ─────────────────────────────────────── */
  function drawShelfZones() {
    SHELF_ZONES.forEach(function(s) {
      var p1 = worldToCanvas(s.x2, s.y1), p2 = worldToCanvas(s.x1, s.y2);
      var w = p2[0] - p1[0], h = p2[1] - p1[1];

      /* 선반 테두리 (나무색) */
      roundRect(p1[0] - 1, p1[1] - 1, w + 2, h + 2, 3);
      ctx.fillStyle = SHELF_COLOR;
      ctx.fill();

      if (s.b) {
        var hw = w / 2;
        roundRect(p1[0] + 1, p1[1] + 1, hw - 1.5, h - 2, 2);
        ctx.fillStyle = s.a.bg; ctx.fill();
        roundRect(p1[0] + hw + 0.5, p1[1] + 1, hw - 1.5, h - 2, 2);
        ctx.fillStyle = s.b.bg; ctx.fill();
        /* 라벨 바깥 */
        var fs = Math.max(6, Math.min(11, h * 0.8) / scale);
        ctx.font = "700 " + fs + 'px "Pretendard", system-ui, sans-serif';
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.fillStyle = s.a.fg;
        ctx.fillText(s.a.icon + " " + s.a.name, p1[0] + hw / 2 - 3, p1[1] - 3);
        ctx.textBaseline = "top";
        ctx.fillStyle = s.b.fg;
        ctx.fillText(s.b.icon + " " + s.b.name, p1[0] + hw + hw / 2 + 8, p2[1] + 3);
      } else {
        roundRect(p1[0] + 1, p1[1] + 1, w - 2, h - 2, 2);
        ctx.fillStyle = s.a.bg; ctx.fill();
        var fs2 = Math.max(5, Math.min(10, w * 0.7) / scale);
        ctx.font = "700 " + fs2 + 'px "Pretendard", system-ui, sans-serif';
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillStyle = s.a.fg;
        ctx.fillText(s.a.icon, p1[0] + w / 2, p1[1] + h / 2 - fs2 * 0.6);
        ctx.fillText(s.a.name, p1[0] + w / 2, p1[1] + h / 2 + fs2 * 0.5);
      }
    });
  }

  /* ── 구역 블록 ─────────────────────────────────────── */
  function drawZones() {
    ZONES.forEach(function(z) {
      var p1 = worldToCanvas(z.x2, z.y1), p2 = worldToCanvas(z.x1, z.y2);
      var w = p2[0] - p1[0], h = p2[1] - p1[1];

      ctx.shadowColor = "rgba(0,0,0,0.06)";
      ctx.shadowBlur = 3; ctx.shadowOffsetY = 1;
      roundRect(p1[0] + 1, p1[1] + 1, w - 2, h - 2, 4);
      ctx.fillStyle = z.bg; ctx.fill();
      ctx.shadowColor = "transparent"; ctx.shadowBlur = 0; ctx.shadowOffsetY = 0;
      ctx.strokeStyle = z.fg + "20"; ctx.lineWidth = 0.7; ctx.stroke();

      var lines = z.name.split("\n");
      var longest = Math.max.apply(null, lines.map(function(l) { return l.length; }));
      /* 아이콘 포함 여부에 따라 폰트 크기 조정 */
      var maxFs = Math.min(w * 0.7 / Math.max(longest, 1), h * 0.38 / lines.length);
      var fs = Math.max(5, Math.min(13, maxFs) / scale);
      ctx.font = "700 " + fs + 'px "Pretendard", system-ui, sans-serif';
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillStyle = z.fg;

      if (lines.length > 1) {
        /* 멀티라인 (가전제품): 아이콘 위, 텍스트 아래 */
        var lh = fs * 1.1;
        var totalH = lh * lines.length + fs;
        var startY = p1[1] + h / 2 - totalH / 2;
        ctx.fillText(z.icon, p1[0] + w / 2, startY + fs * 0.5);
        lines.forEach(function(ln, i) {
          ctx.fillText(ln, p1[0] + w / 2, startY + fs + lh * (i + 0.5));
        });
      } else {
        /* 한 줄: 세로 공간에 따라 아이콘 위+이름 아래 or 아이콘+이름 한줄 */
        if (h > fs * 2.5) {
          ctx.fillText(z.icon, p1[0] + w / 2, p1[1] + h / 2 - fs * 0.5);
          ctx.fillText(z.name, p1[0] + w / 2, p1[1] + h / 2 + fs * 0.6);
        } else {
          ctx.fillText(z.icon + " " + z.name, p1[0] + w / 2, p1[1] + h / 2);
        }
      }
    });
  }

  /* ── 입구/출구 ─────────────────────────────────────── */
  function drawEntranceExit() {
    ENTRANCE_EXIT.forEach(function(m) {
      var p = worldToCanvas(m.wx, m.wy);
      var fs = Math.max(5, 7 / scale);
      ctx.font = "700 " + fs + 'px "Pretendard", system-ui, sans-serif';
      var label = m.arrow + " " + m.name;
      var tw = ctx.measureText(label).width + 10;
      var th = fs + 7;
      /* 배경 pill */
      roundRect(p[0] - tw / 2, p[1] - th / 2, tw, th, th / 2);
      ctx.fillStyle = m.color + "18"; ctx.fill();
      ctx.strokeStyle = m.color + "50"; ctx.lineWidth = 0.7; ctx.stroke();
      /* 텍스트 */
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillStyle = m.color;
      ctx.fillText(label, p[0], p[1]);
    });
  }

  /* ── 로봇 마커 ─────────────────────────────────────── */
  function drawRobotMarker(px, py, yaw, color, r) {
    var angle = -yaw - Math.PI / 2;
    /* 바닥 그림자 */
    ctx.beginPath();
    ctx.ellipse(px + 1, py + 2, r * 0.9, r * 0.5, 0, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(0,0,0,0.15)"; ctx.fill();
    /* 몸체 */
    ctx.beginPath(); ctx.arc(px, py, r, 0, Math.PI * 2);
    ctx.fillStyle = color; ctx.fill();
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
    /* 방향 삼각형 */
    var tipLen = r + 4;
    var tipX = px + Math.cos(angle) * tipLen;
    var tipY = py + Math.sin(angle) * tipLen;
    var off = Math.PI * 0.72;
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(px + Math.cos(angle + off) * r * 0.7, py + Math.sin(angle + off) * r * 0.7);
    ctx.lineTo(px + Math.cos(angle - off) * r * 0.7, py + Math.sin(angle - off) * r * 0.7);
    ctx.closePath();
    ctx.fillStyle = color; ctx.fill();
    /* 카트 아이콘 */
    var ifs = Math.max(4, r * 0.9);
    ctx.font = ifs + "px sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillStyle = "#fff";
    ctx.fillText("\uD83D\uDED2", px, py);
  }

  /* ── 로봇 ID 라벨 ──────────────────────────────────── */
  function drawRobotLabel(px, py, id, r) {
    var fs = Math.max(5, 7 / scale);
    ctx.font = "700 " + fs + 'px "Pretendard", system-ui, sans-serif';
    ctx.textAlign = "center"; ctx.textBaseline = "bottom";
    /* 배경 pill */
    var tw = ctx.measureText("#" + id).width + 6;
    var th = fs + 3;
    var lx = px - tw / 2, ly = py - r - 5 - th;
    roundRect(lx, ly, tw, th, th / 2);
    ctx.fillStyle = "rgba(0,0,0,0.55)"; ctx.fill();
    /* 텍스트 */
    ctx.fillStyle = "#fff";
    ctx.textBaseline = "middle";
    ctx.fillText("#" + id, px, ly + th / 2);
  }

  /* ── 내 로봇 마커 ──────────────────────────────────── */
  function drawMyRobotMarker(px, py, yaw) {
    var pulse = Math.sin(pulsePhase * Math.PI * 2);
    /* 펄스 글로우 */
    ctx.beginPath();
    ctx.arc(px, py, ROBOT_R + 5 + 5 * pulse, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(37,99,235," + (0.10 + 0.15 * pulse).toFixed(2) + ")";
    ctx.fill();
    /* 외곽 링 */
    ctx.beginPath();
    ctx.arc(px, py, ROBOT_R + 2.5, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(37,99,235,0.45)"; ctx.lineWidth = 1.2; ctx.stroke();
    /* 본체 */
    drawRobotMarker(px, py, yaw, MY_COLOR, ROBOT_R);
    drawRobotLabel(px, py, myRobotId, ROBOT_R);
  }

  /* ── 경로 그리기 ────────────────────────────────────── */
  function drawPath() {
    if (!myPath || myPath.length < 2) return;
    ctx.save();
    ctx.setLineDash([4, 3]);
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(37,99,235,0.5)";
    ctx.beginPath();
    for (var i = 0; i < myPath.length; i++) {
      var p = worldToCanvas(myPath[i].x, myPath[i].y);
      if (i === 0) ctx.moveTo(p[0], p[1]);
      else ctx.lineTo(p[0], p[1]);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    /* 목적지 마커 (마지막 포인트) */
    var last = myPath[myPath.length - 1];
    var lp = worldToCanvas(last.x, last.y);
    ctx.beginPath();
    ctx.arc(lp[0], lp[1], 4, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(37,99,235,0.7)";
    ctx.fill();
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.restore();
  }

  /* ── 좌표 변환 ─────────────────────────────────────── */
  function worldToCanvas(wx, wy) {
    return [
      (W_MAX_Y - wy) / W_SPAN_Y * LW,
      (W_MAX_X - wx) / W_SPAN_X * LH,
    ];
  }

  /* ── 유틸 ──────────────────────────────────────────── */
  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  /* ── 핀치 줌 ───────────────────────────────────────── */
  function getTouchDist(t) {
    return Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
  }
  function onTouchStart(e) {
    if (e.touches.length === 2) { e.preventDefault(); lastDist = getTouchDist(e.touches); }
  }
  function onTouchMove(e) {
    if (e.touches.length === 2) {
      e.preventDefault();
      var d = getTouchDist(e.touches);
      if (lastDist) { scale = Math.max(0.5, Math.min(5, scale * d / lastDist)); }
      lastDist = d;
    }
  }
  function onTouchEnd(e) { if (e.touches.length < 2) lastDist = null; }

  return { init, updateFromStatus, setVisible };
})();
