/* ============================================
   Presentation JS — TOC, Video, Fullscreen
   ============================================ */

/* ── Slide loader ── */
var SLIDES = [
  '01-title.html',              // 0
  '02-shopping-stat.html',      // 1
  '03-shopping-time.html',      // 2
  '04-shopping-cart.html',      // 3
  '05-quote.html',              // 4
  '06-shopping-pain.html',      // 5
  '07-we-came.html',            // 6
  '08-meeting.html',            // 7
  '09-shoppinkki-reveal.html',  // 8
  '10-solution.html',           // 9
  '11-idea.html',               // 10
  '12-ux.html',                 // 11
  '13-hardware-intro.html',     // 12
  '14-robot.html',              // 13
  '15-doll.html',               // 14
  '16-doll-25000.html',         // 15
  '17-system-intro.html',       // 16
  '18-network-topology.html',   // 17
  '19-hw-architecture.html',    // 18
  '20-architecture.html',       // 19
  '21-statemachine.html',       // 20
  '22-demoenv-intro.html',      // 21
  '23-environment.html',        // 22
  '24-zones.html',              // 23
  '25-simmap.html',             // 24
  '26-features.html',           // 25
  '27-intro-login.html',        // 26
  '28-login-1.html',            // 27
  '29-login-2.html',            // 28
  '30-login-3.html',            // 29
  '31-login-4.html',            // 30
  '32-intro-tracking.html',     // 31
  '33-tracking.html',           // 32
  '34-tracking-yolo.html',      // 33
  '35-tracking-bytetracker.html', // 34
  '36-tracking-reid-intro.html',  // 35
  '37-tracking-demo.html',      // 36
  '38-tracking-pcontrol.html',  // 37
  '39-tracking-angular.html',   // 38
  '40-intro-guide.html',        // 39
  '41-guide.html',              // 40
  '42-guide-pipeline.html',     // 41
  '43-guide-llm-demo.html',       // 42
  '44-openrmf-journey.html',      // 43
  '45-openrmf-intro.html',        // 44
  '46-nav-graph-concept.html',    // 45
  '47-fleet-map.html',            // 46
  '48-openrmf-vs-custom.html',    // 47
  '49-guide-demo.html',           // 48
  '50-admin-demo.html',           // 49
  '51-intro-cart.html',           // 50
  '52-cart.html',                 // 51
  '53-intro-waiting.html',        // 52
  '54-waiting.html',              // 53
  '55-waiting-demo.html',         // 54
  '56-intro-checkout.html',       // 55
  '57-checkout.html',             // 56
  '58-checkout-demo.html',        // 57
  '59-intro-return.html',         // 58
  '60-return.html',               // 59
  '61-return-demo.html',          // 60
  '62-intro-final-demo.html',     // 61
  '63-final-demo.html',           // 62
  '64-retrospect.html',           // 63
  '65-team.html',                 // 64
  '66-thanks.html',               // 65
  '67-ref-cosine.html',           // 66
  '68-ref-hsv.html',              // 67
  '69-ref-hungarian.html',        // 68
  '70-ref-iou.html',              // 69
];

var SLIDE_TITLES = [
  '삥끼랩',                                    // 0  01-title
  '45분',                                      // 1  02-shopping-stat
  '우리가 쇼핑 시간동안 하는 일',             // 2  03-shopping-time
  '우리가 쇼핑 시간동안 하는 일',             // 3  04-shopping-cart
  '사람들은 항상 쇼핑을 합니다...',           // 4  05-quote
  '쇼핑의 3대 불편',                           // 5  06-shopping-pain
  '우리가 왔읍니다',                            // 6  07-we-came
  '쇼핑과 핑키의 만남',                        // 7  08-meeting
  '쑈삥끼',                                    // 8  09-shoppinkki-reveal
  '삥끼랩의 쑈삥끼는요,',                     // 9  10-solution
  "쑈삥끼의 아이디어 - Carrefour Scan'lib",   // 10 11-idea
  '쑈삥끼 사용자 여정',                        // 11 12-ux
  '하드웨어 정보',                             // 12 13-hardware-intro
  'Pinky Pro, Basket Edition',                 // 13 14-robot
  '사용자인형들 (무려 25000원)',               // 14 15-doll
  '25,000원으로 할 수 있는 일',               // 15 16-doll-25000
  '시스템 구성',                               // 16 17-system-intro
  'Network Topology',                          // 17 18-network-topology
  'Hardware Architecture',                     // 18 19-hw-architecture
  'Software Architecture',                     // 19 20-architecture
  'State Diagram',                             // 20 21-statemachine
  '데모 환경',                                 // 21 22-demoenv-intro
  '미니어처 마트',                             // 22 23-environment
  '구역 구성',                                 // 23 24-zones
  '시뮬레이션 맵',                             // 24 25-simmap
  '핵심기능 7가지',                            // 25 26-features
  '카트 이용 시작',                            // 26 27-intro-login
  '핵심 기능 1: 카트 이용 시작',              // 27 28-login-1
  '핵심 기능 1: 카트 이용 시작',              // 28 29-login-2
  '핵심 기능 1: 카트 이용 시작',              // 29 30-login-3
  '핵심 기능 1: 카트 이용 시작',              // 30 31-login-4
  '추종',                                      // 31 32-intro-tracking
  '핵심 기능 2: 추종',                         // 32 33-tracking
  '추종: 커스텀 YOLOv8',                       // 33 34-tracking-yolo
  '추종: ByteTracker',                         // 34 35-tracking-bytetracker
  '추종: ReID와 HSV란?',                       // 35 36-tracking-reid-intro
  '인형 인식 모델 테스트',                     // 36 37-tracking-demo
  '추종: 선속도 제어',                          // 37 38-tracking-pcontrol
  '추종: 각속도 제어',                          // 38 39-tracking-angular
  '가이드',                                    // 39 40-intro-guide
  '핵심 기능 3: 가이드',                       // 40 41-guide
  '가이드: 검색 파이프라인',                   // 41 42-guide-pipeline
  '가이드 Demo — 채팅 검색',                  // 42 43-guide-llm-demo
  '가이드: Open-RMF 도입 → 자체 구현',         // 43 44-openrmf-journey
  '가이드: Open-RMF란?',                       // 44 45-openrmf-intro
  '가이드: Nav Graph란?',                      // 45 46-nav-graph-concept
  '가이드: Fleet 웨이포인트 배치',             // 46 47-fleet-map
  '가이드: 경로 조율 방식 비교',               // 47 48-openrmf-vs-custom
  '가이드 Demo',                              // 48 49-guide-demo
  '가이드 Demo — Admin UI',                   // 49 50-admin-demo
  '장바구니',                                  // 50 51-intro-cart
  '핵심 기능 4: 장바구니',                     // 51 52-cart
  '대기',                                      // 52 53-intro-waiting
  '핵심 기능 5: 대기',                         // 53 54-waiting
  '대기 Demo',                                 // 54 55-waiting-demo
  '결제',                                      // 55 56-intro-checkout
  '핵심 기능 6: 결제',                         // 56 57-checkout
  '결제 Demo',                                 // 57 58-checkout-demo
  '복귀',                                      // 58 59-intro-return
  '핵심 기능 7: 복귀',                         // 59 60-return
  '복귀 Demo',                                 // 60 61-return-demo
  '최종 데모',                                 // 61 62-intro-final-demo
  '최종 데모 영상',                             // 62 63-final-demo
  '회고',                                      // 63 64-retrospect
  '팀원 소개',                                 // 64 65-team
  '감사합니다',                                // 65 66-thanks
  '참고자료 1: 코사인 유사도란?',              // 66 67-ref-cosine
  '참고자료 2: HSV 히스토그램 상관계수란?',    // 67 68-ref-hsv
  '참고자료 4: Hungarian Algorithm',           // 68 69-ref-hungarian
  '참고자료 5: IoU (Intersection over Union)', // 69 70-ref-iou
];

async function loadSlides() {
  var container = document.querySelector('.reveal .slides');
  // Fetch all slides in parallel (53 → 1 round-trip)
  var responses = await Promise.all(
    SLIDES.map(function(name) { return fetch('slides/' + name); })
  );
  var htmls = await Promise.all(responses.map(function(r) { return r.text(); }));
  htmls.forEach(function(html) {
    container.insertAdjacentHTML('beforeend', html);
  });
}

async function initPresentation() {
  await loadSlides();

  Reveal.initialize({
    hash: true,
    center: false,
    slideNumber: 'c/t',
    width: 1280,
    height: 720,
    margin: 0.04,
    minScale: 0.1,
    maxScale: 2.0,
    transition: 'none',
    transitionSpeed: 'fast',
    plugins: [RevealNotes, RevealHighlight],
    keyboard: {
      80: function() { toggleVideo(); },      // P
      70: function() { toggleFullscreen(); }, // F
      87: function() { toggleWebcam(); },     // W
      67: function() { toggleDraw(); },       // C — 그리기 토글
      88: function() { clearDraw(); },        // X — 지우기
    }
  });

  // Force center-align (vertically)
  function forceCenterAlign() {
    var slideHeight = 720; // from Reveal.initialize
    document.querySelectorAll('.reveal .slides section').forEach(function(s) {
      var sectionHeight = s.offsetHeight;
      var topOffset = (slideHeight - sectionHeight) / 2;
      s.style.top = topOffset + 'px';
    });
  }
  Reveal.on('ready', function() {
    // Hide loading screen
    var loadingScreen = document.getElementById('loading-screen');
    if (loadingScreen) {
      loadingScreen.style.transition = 'opacity 0.4s';
      loadingScreen.style.opacity = '0';
      setTimeout(function() { loadingScreen.remove(); }, 400);
    }
    initLoginPipelines();
    initVideoControls();
    initDraw();
    forceCenterAlign();
    // Make slide number indicator clickable
    var slideNum = document.querySelector('.reveal .slide-number');
    if (slideNum) {
      slideNum.addEventListener('click', function(e) {
        e.stopPropagation();
        toggleSlidePanel();
      });
    }
  });
  Reveal.on('slidechanged', function(event) {
    clearDraw();
    forceCenterAlign();
    // Update active state in panel if open
    var panel = document.getElementById('slide-panel');
    if (panel && !panel.classList.contains('hidden')) {
      updateSlidePanelActive();
    }
    // Auto-pause demo video when leaving demo slide
    var video = document.getElementById('demo-video');
    var container = document.getElementById('video-container');
    if (video && event.currentSlide.id !== 'demo-slide') {
      video.pause();
      if (container) container.classList.remove('playing');
    }
    // Re-play all autoplay looping videos on the current slide
    event.currentSlide.querySelectorAll('video[autoplay]').forEach(function(v) {
      v.currentTime = 0;
      v.play();
    });
  });
}

/* ── Video play/pause ── */
function toggleVideo() {
  var video = document.getElementById('demo-video');
  var container = document.getElementById('video-container');
  if (!video || (!video.src && !video.querySelector('source[src]'))) return;
  if (video.paused) {
    video.play();
    container.classList.add('playing');
  } else {
    video.pause();
    container.classList.remove('playing');
  }
}

/* ── Drawing Overlay (C: 토글, X: 지우기) ── */
var _drawActive = false;
var _drawing = false;
var _lastX = 0, _lastY = 0;

function toggleDraw() {
  _drawActive = !_drawActive;
  var canvas = document.getElementById('draw-canvas');
  canvas.style.pointerEvents = _drawActive ? 'auto' : 'none';
  document.body.style.cursor = _drawActive ? 'crosshair' : '';
}

function clearDraw() {
  var canvas = document.getElementById('draw-canvas');
  var ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function initDraw() {
  var canvas = document.getElementById('draw-canvas');
  canvas.width  = window.innerWidth;
  canvas.height = window.innerHeight;

  window.addEventListener('resize', function() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
  });

  var ctx = canvas.getContext('2d');
  ctx.strokeStyle = '#FF4444';
  ctx.lineWidth   = 4;
  ctx.lineCap     = 'round';
  ctx.lineJoin    = 'round';

  canvas.addEventListener('mousedown', function(e) {
    _drawing = true;
    _lastX = e.clientX;
    _lastY = e.clientY;
  });
  canvas.addEventListener('mousemove', function(e) {
    if (!_drawing) return;
    ctx.strokeStyle = '#FF4444';
    ctx.lineWidth   = 4;
    ctx.lineCap     = 'round';
    ctx.lineJoin    = 'round';
    ctx.beginPath();
    ctx.moveTo(_lastX, _lastY);
    ctx.lineTo(e.clientX, e.clientY);
    ctx.stroke();
    _lastX = e.clientX;
    _lastY = e.clientY;
  });
  canvas.addEventListener('mouseup',    function() { _drawing = false; });
  canvas.addEventListener('mouseleave', function() { _drawing = false; });
}

/* ── Webcam Overlay (W key) ── */
var _wcStream = null;
var _wcActive = false;
var _wcAnimFrame = null;

function toggleWebcam() {
  if (_wcActive) { _stopWebcam(); } else { _startWebcam(); }
}

async function _startWebcam() {
  var overlay = document.getElementById('webcam-overlay');
  var video   = document.getElementById('webcam-video');
  var canvas  = document.getElementById('webcam-canvas');
  var ctx     = canvas.getContext('2d');
  try {
    _wcStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: 640, height: 480 } });
    video.srcObject = _wcStream;
    await video.play();
    canvas.width  = video.videoWidth  || 640;
    canvas.height = video.videoHeight || 480;
    overlay.style.display = 'block';
    _wcActive = true;
    _startPlain(video, canvas, ctx);
  } catch(e) {
    console.warn('Webcam error:', e);
  }
}

function _startPlain(video, canvas, ctx) {
  function draw() {
    if (!_wcActive) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    _wcAnimFrame = requestAnimationFrame(draw);
  }
  draw();
}


function _stopWebcam() {
  _wcActive = false;
  if (_wcAnimFrame) { cancelAnimationFrame(_wcAnimFrame); _wcAnimFrame = null; }
  if (_wcStream) { _wcStream.getTracks().forEach(function(t) { t.stop(); }); _wcStream = null; }
  var overlay = document.getElementById('webcam-overlay');
  if (overlay) overlay.style.display = 'none';
}

/* ── Slide link (뒤로가기 지원) ── */
function goToSlide(index) {
  var cur = Reveal.getIndices().h;
  history.pushState(null, '', '#/' + cur);
  Reveal.slide(index);
}

/* ── Fullscreen ── */
function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen();
  } else {
    document.exitFullscreen();
  }
}

function updateFullscreenHint() {
  var hint = document.getElementById('fullscreen-hint');
  if (!hint) return;
  if (document.fullscreenElement) {
    hint.innerHTML = 'Press <kbd style="background:#112236;border:1px solid #1E3A5A;border-radius:4px;padding:1px 5px;font-size:0.9em;color:#7BA5C8">ESC</kbd> to minimize';
  } else {
    hint.innerHTML = 'Press <kbd style="background:#112236;border:1px solid #1E3A5A;border-radius:4px;padding:1px 5px;font-size:0.9em;color:#7BA5C8">F</kbd> for fullscreen';
  }
}
document.addEventListener('fullscreenchange', updateFullscreenHint);

/* ── Slide Panel ── */
function buildSlidePanel() {
  var list = document.getElementById('slide-panel-list');
  list.innerHTML = '';
  var sections = document.querySelectorAll('.reveal .slides > section');
  var current = Reveal.getIndices().h;

  sections.forEach(function(section, i) {
    var item = document.createElement('div');
    item.className = 'slide-thumb-item' + (i === current ? ' active' : '');
    item.dataset.index = i;

    var preview = document.createElement('div');
    preview.className = 'slide-thumb-preview';
    var inner = document.createElement('div');
    inner.className = 'slide-thumb-inner';
    inner.innerHTML = section.innerHTML;
    preview.appendChild(inner);

    var meta = document.createElement('div');
    meta.className = 'slide-thumb-meta';
    meta.innerHTML = '<span class="slide-thumb-num">' + (i + 1) + '</span>'
                   + '<span class="slide-thumb-title">' + (SLIDE_TITLES[i] || '') + '</span>';

    item.appendChild(meta);
    item.appendChild(preview);
    item.addEventListener('click', function() {
      Reveal.slide(i);
      closeSlidePanel();
    });
    list.appendChild(item);
  });
}

function updateSlidePanelActive() {
  var current = Reveal.getIndices().h;
  document.querySelectorAll('.slide-thumb-item').forEach(function(el, i) {
    el.classList.toggle('active', i === current);
  });
  // Scroll active item into view
  var activeEl = document.querySelector('.slide-thumb-item.active');
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}

function toggleSlidePanel() {
  var panel = document.getElementById('slide-panel');
  if (!panel.classList.contains('hidden')) {
    closeSlidePanel();
  } else {
    buildSlidePanel();
    panel.classList.remove('hidden');
    panel.classList.add('flex');
    document.getElementById('slide-panel-overlay').classList.remove('hidden');
    // Scroll active item into view
    setTimeout(function() {
      var activeEl = document.querySelector('.slide-thumb-item.active');
      if (activeEl) activeEl.scrollIntoView({ block: 'center' });
    }, 50);
  }
}

function closeSlidePanel() {
  var panel = document.getElementById('slide-panel');
  panel.classList.add('hidden');
  panel.classList.remove('flex');
  document.getElementById('slide-panel-overlay').classList.add('hidden');
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeSlidePanel();
});

/* ── Login Pipeline Component ── */
var LOGIN_STEPS = [
  { icon: 'qr_code_scanner', title: 'QR 스캔',        sub: '로봇 LCD' },
  { icon: 'smartphone',      title: '웹앱 접속',      sub: 'Flask + SocketIO' },
  { icon: 'smart_toy',       title: '주인 등록',      sub: '로봇 Pi 카메라' },
  { icon: 'person_pin_circle', title: 'TRACKING 시작', sub: 'IDLE → TRACKING' },
];

function renderLoginPipeline(activeIndex) {
  var html = '<div class="flex items-center justify-between w-full">';
  LOGIN_STEPS.forEach(function(step, i) {
    var isActive = i === activeIndex;
    var bg = isActive
      ? 'background:#0E2840;border:2px solid #38BDF8;box-shadow:0 0 20px rgba(56,189,248,0.25)'
      : 'background:#112236;border:1px solid #1E3A5A;opacity:0.45';
    var titleColor = isActive ? 'color:#FFFFFF' : 'color:#7BA5C8';
    var subColor = isActive ? 'color:#38BDF8' : 'color:#3A5A7A';
    var iconColor = isActive ? 'color:#38BDF8' : 'color:#3A5A7A';
    html += '<div class="rounded-xl px-2 py-2 text-center flex-1" style="' + bg + ';transition:all 0.3s">'
          + '<span class="material-icons-round text-em-xs block leading-none" style="' + iconColor + '">' + step.icon + '</span>'
          + '<div class="font-bold text-em-3xs mt-0.5" style="' + titleColor + '">' + step.title + '</div>'
          + '<div class="text-[0.35em]" style="' + subColor + '">' + step.sub + '</div>'
          + '</div>';
    if (i < LOGIN_STEPS.length - 1) {
      var arrowColor = (i === activeIndex || i + 1 === activeIndex) ? 'color:#38BDF8' : 'color:#1E3A5A';
      html += '<div class="pipeline-arrow text-em-2xl" style="' + arrowColor + '"></div>';
    }
  });
  html += '</div>';
  return html;
}

// Auto-render login pipelines after Reveal is ready
function initLoginPipelines() {
  document.querySelectorAll('[data-login-step]').forEach(function(el) {
    var step = parseInt(el.getAttribute('data-login-step'));
    el.innerHTML = renderLoginPipeline(step);
  });
}

/* ── Video Controls Component ── */
function initVideoControls() {
  document.querySelectorAll('[data-video-controls]').forEach(function(el) {
    var videoId = el.getAttribute('data-video-controls');
    var speeds = [1.0, 1.5, 2.0, 3.0];
    var scopeAttr = 'data-speed-' + videoId;
    var seekBarId = 'seek-' + videoId;
    var timeId = 'time-' + videoId;

    var btnsHtml = speeds.map(function(s, i) {
      var active = i === 0;
      var border = active ? '#38BDF8' : '#1E3A5A';
      var color  = active ? '#38BDF8' : '#E2E8F0';
      return '<button'
        + ' onclick="(function(b){document.getElementById(\'' + videoId + '\').playbackRate=' + s + ';'
        + 'document.querySelectorAll(\'[' + scopeAttr + ']\').forEach(function(x){x.style.borderColor=\'#1E3A5A\';x.style.color=\'#E2E8F0\'});'
        + 'b.style.borderColor=\'#38BDF8\';b.style.color=\'#38BDF8\'})(this)"'
        + ' ' + scopeAttr
        + ' class="rounded-xl px-3 text-em-3xs font-bold"'
        + ' style="background:#0A1929;border:1px solid ' + border + ';color:' + color + ';height:28px">'
        + s + '×'
        + '</button>';
    }).join('');

    el.innerHTML = ''
      // 시크바
      + '<div class="flex items-center gap-2 px-1 mb-1">'
      + '<span id="' + timeId + '" class="text-em-3xs font-mono shrink-0" style="color:#475569;min-width:70px">0:00 / 0:00</span>'
      + '<input id="' + seekBarId + '" type="range" min="0" max="100" value="0" step="0.1"'
      + ' style="flex:1;height:4px;accent-color:#38BDF8;cursor:pointer;background:#1E3A5A;border-radius:4px"'
      + ' oninput="(function(s){var v=document.getElementById(\'' + videoId + '\');v.currentTime=v.duration*(s.value/100);})(this)">'
      + '</div>'
      // 버튼
      + '<div class="flex items-center justify-center gap-3">'
      + '<button'
      + ' onclick="(function(btn){var v=document.getElementById(\'' + videoId + '\');var icon=btn.querySelector(\'.material-icons-round\');if(v.paused){v.play();icon.textContent=\'pause\';}else{v.pause();icon.textContent=\'play_arrow\';}})(this)"'
      + ' class="flex items-center justify-center rounded-xl px-8 text-em-3xs font-bold"'
      + ' style="background:#0A1929;border:1px solid #1E3A5A;color:#E2E8F0;min-width:120px;height:28px">'
      + '<span class="material-icons-round" style="font-size:0.9em;line-height:1">pause</span>'
      + '</button>'
      + btnsHtml
      + '</div>';

    // 시크바 업데이트
    var video = document.getElementById(videoId);
    if (video) {
      video.addEventListener('timeupdate', function() {
        var bar = document.getElementById(seekBarId);
        var timeEl = document.getElementById(timeId);
        if (bar && video.duration) {
          bar.value = (video.currentTime / video.duration) * 100;
        }
        if (timeEl && video.duration) {
          var fmt = function(t) {
            var m = Math.floor(t / 60);
            var s = Math.floor(t % 60);
            return m + ':' + (s < 10 ? '0' : '') + s;
          };
          timeEl.textContent = fmt(video.currentTime) + ' / ' + fmt(video.duration);
        }
      });
    }
  });
}

// Boot
initPresentation();
