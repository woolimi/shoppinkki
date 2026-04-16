"""
ShopPinkki Customer Web App
Flask + Flask-SocketIO 진입점. 포트 8501.

환경 변수:
    PORT                  : 서버 포트 (기본 8501)
    ROBOT_IDS             : 지원 로봇 ID 목록 (기본 '54,18', 쉼표 구분)
    CONTROL_SERVICE_HOST  : control_service 호스트 (기본 '127.0.0.1')
    CONTROL_SERVICE_PORT  : control_service TCP 포트 (기본 8080)
    CONTROL_SERVICE_HTTP_PORT : control_service REST 포트 (기본 8081)
    LLM_HOST              : LLM 서버 호스트 (기본 '127.0.0.1')
    LLM_PORT              : LLM 서버 포트 (기본 8000)
    SECRET_KEY            : Flask 세션 키 (기본 'shoppinkki-secret')

접속 방법:
    http://localhost:8501/?robot_id=54
    http://localhost:8501/?robot_id=18
"""

import logging
import os
import re
import yaml
from pathlib import Path

import eventlet
eventlet.monkey_patch()  # noqa: E402 — 반드시 최상단에서 패치

import requests
from flask import Flask, abort, flash, get_flashed_messages, redirect, render_template, request, send_file, session, url_for
from flask_socketio import SocketIO

from control_client import ControlClient
import socket_handlers

# ── 로깅 설정 ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_CONFIG_PATH = (
    _REPO_ROOT / "device/shoppinkki/shoppinkki_core/shoppinkki_core/config.py"
)
_WAITING_TIMEOUT_RE = re.compile(
    r"^WAITING_TIMEOUT:\s*int\s*=\s*(\d+)", re.MULTILINE
)


def _load_waiting_timeout_sec() -> int:
    """WAITING seconds: edit only ``shoppinkki_core.config.WAITING_TIMEOUT``.

    Try package import, then parse monorepo ``config.py`` if import fails.
    """
    try:
        from shoppinkki_core.config import WAITING_TIMEOUT

        return int(WAITING_TIMEOUT)
    except ImportError:
        pass
    try:
        if _CORE_CONFIG_PATH.is_file():
            text = _CORE_CONFIG_PATH.read_text(encoding="utf-8")
            m = _WAITING_TIMEOUT_RE.search(text)
            if m:
                v = int(m.group(1))
                logger.info(
                    "WAITING_TIMEOUT=%ss (parsed repo config.py; package not importable)",
                    v,
                )
                return v
    except OSError as e:
        logger.warning("config.py read failed: %s", e)
    logger.warning(
        "WAITING_TIMEOUT fallback300 (fix path or install shoppinkki_core): %s",
        _CORE_CONFIG_PATH,
    )
    return 300


_WAITING_TIMEOUT_SEC = _load_waiting_timeout_sec()

# ── 환경 변수 ──────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 8501))
KNOWN_ROBOT_IDS: list[str] = [
    r.strip() for r in os.environ.get("ROBOT_IDS", "18,54").split(",") if r.strip()
]
CONTROL_HOST = os.environ.get("CONTROL_SERVICE_HOST", "127.0.0.1")
CONTROL_PORT = int(os.environ.get("CONTROL_SERVICE_PORT", 8080))
CONTROL_HTTP_PORT = int(os.environ.get("CONTROL_SERVICE_HTTP_PORT", 8081))
LLM_HOST = os.environ.get("LLM_HOST", "127.0.0.1")
LLM_PORT = int(os.environ.get("LLM_PORT", 8000))
SECRET_KEY = os.environ.get("SECRET_KEY", "shoppinkki-secret")

# ── shop.yaml 맵 파라미터 로드 ─────────────────────────────────
_SHOP_YAML_PATH = os.environ.get(
    "SHOP_YAML_PATH",
    os.path.join(
        os.path.dirname(__file__),
        "../../device/shoppinkki/shoppinkki_nav/maps/shop.yaml",
    ),
)

MAP_RESOLUTION = 0.05
MAP_ORIGIN_X = -0.1
MAP_ORIGIN_Y = -0.1

try:
    with open(_SHOP_YAML_PATH, "r") as _f:
        _yaml = yaml.safe_load(_f)
        MAP_RESOLUTION = float(_yaml.get("resolution", MAP_RESOLUTION))
        _origin = _yaml.get("origin", [MAP_ORIGIN_X, MAP_ORIGIN_Y, 0])
        MAP_ORIGIN_X = float(_origin[0])
        MAP_ORIGIN_Y = float(_origin[1])
    logger.info(
        "shop.yaml 로드 완료: resolution=%.4f origin=(%.2f, %.2f)",
        MAP_RESOLUTION, MAP_ORIGIN_X, MAP_ORIGIN_Y,
    )
except Exception as _e:
    logger.warning("shop.yaml 로드 실패 (%s), 기본값 사용", _e)

# ── Flask 앱 ───────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = SECRET_KEY


@app.context_processor
def _inject_shop_constants():
    """템플릿/static 초기값 — WAITING_TIMEOUT 단일 소스(shoppinkki_core.config)."""
    return {"waiting_timeout_sec": int(_WAITING_TIMEOUT_SEC)}


# ── 맵 PNG 서빙 (shoppinkki_nav/maps/ 단일 원본) ──────────────
_MAP_PNG = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    '../../device/shoppinkki/shoppinkki_nav/maps/shop.png',
))


@app.get('/static/map/shop.png')
def _serve_map_png():
    if os.path.isfile(_MAP_PNG):
        return send_file(_MAP_PNG, mimetype='image/png')
    abort(404)


socketio = SocketIO(
    app,
    async_mode="eventlet",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)

# ── control_client 초기화 (로봇별 1개) ──────────────────────────
control_clients: dict[str, ControlClient] = {}
for _rid in KNOWN_ROBOT_IDS:
    _cc = ControlClient(
        host=CONTROL_HOST,
        port=CONTROL_PORT,
        robot_id=_rid,
        socketio_instance=socketio,
    )
    _cc.connect()
    control_clients[_rid] = _cc
    logger.info("ControlClient 등록: robot_id=%s", _rid)

# ── SocketIO 핸들러 등록 ───────────────────────────────────────
socket_handlers.register_handlers(
    socketio=socketio,
    control_clients=control_clients,
    llm_cfg={"host": LLM_HOST, "port": LLM_PORT},
)


# ── 헬퍼 ──────────────────────────────────────────────────────

def _ctrl_rest(method: str, path: str, **kwargs):
    """control_service REST API 호출 헬퍼.
    2xx → JSON 반환.
    4xx → JSON 반환 (에러 필드 포함, 호출부에서 처리).
    5xx / 네트워크 오류 → None 반환.
    """
    url = f"http://{CONTROL_HOST}:{CONTROL_HTTP_PORT}{path}"
    try:
        resp = requests.request(method, url, timeout=5, **kwargs)
        if resp.status_code >= 500:
            logger.warning("REST 서버 오류 [%s %s]: %s", method, path, resp.status_code)
            return None
        return resp.json()
    except Exception as e:
        logger.warning("REST 호출 실패 [%s %s]: %s", method, path, e)
        return None


def _require_robot_id(robot_id: str | None) -> str:
    """robot_id 유효성 검사. 유효하지 않으면 abort(). 유효하면 robot_id 반환."""
    if not robot_id:
        abort(400, description="robot_id 파라미터가 필요합니다.")
    if robot_id not in KNOWN_ROBOT_IDS:
        abort(404, description=f"알 수 없는 로봇 ID: {robot_id}")
    return robot_id


@app.errorhandler(400)
def handle_400(e):
    return render_template("error.html", message=str(e.description)), 400


@app.errorhandler(404)
def handle_404(e):
    return render_template("error.html", message=str(e.description)), 404


# ── robot_id 쿼리파라미터 자동 보정 ──────────────────────────────

@app.before_request
def _ensure_robot_id_param():
    """세션에 robot_id가 있는데 쿼리파라미터에 없으면 붙여서 리다이렉트."""
    if request.endpoint in ("static", None):
        return
    robot_id = session.get("robot_id", "")
    if robot_id and not request.args.get("robot_id"):
        from urllib.parse import urlencode, urlparse, parse_qs, urlunparse
        parsed = urlparse(request.url)
        qs = parse_qs(parsed.query)
        qs["robot_id"] = [robot_id]
        new_query = urlencode(qs, doseq=True)
        new_url = urlunparse(parsed._replace(query=new_query))
        return redirect(new_url)


# ── 라우트 ────────────────────────────────────────────────────

@app.route("/")
def index():
    """
    세션 확인 후 적절한 페이지로 리다이렉트.
    - robot_id 없거나 유효하지 않음 → error.html (400/404)
    - 세션 있고 robot_id 불일치 → error.html (400)
    - 세션 있고 robot_id 일치 + 활성 → /main
    - 세션 없거나 만료 → /login?robot_id=...
    - 로봇 사용 중 → /blocked
    """
    robot_id = _require_robot_id(request.args.get("robot_id", "").strip())

    session_id = session.get("session_id")

    if session_id:
        # 세션의 robot_id와 쿼리파라미터 일치 여부 확인
        session_robot_id = session.get("robot_id", "")
        if session_robot_id != robot_id:
            session.clear()
            abort(400, description=(
                f"세션 로봇(#{session_robot_id})과 "
                f"요청 로봇(#{robot_id})이 다릅니다. "
                f"올바른 URL로 접속해 주세요."
            ))

        # 세션 활성 여부 확인
        data = _ctrl_rest("GET", f"/session/{session_id}")
        if data and data.get("is_active"):
            # SM 상태에 따라 /register 또는 /main으로
            robots = _ctrl_rest("GET", "/robots")
            robot_state = (robots or {}).get(str(robot_id), {}) if robots else {}
            mode = robot_state.get("mode")
            follow_disabled = robot_state.get("follow_disabled", False)
            if mode == "IDLE" and not follow_disabled:
                return redirect(url_for("register", robot_id=robot_id))
            return redirect(url_for("main", robot_id=robot_id))
        # 만료된 세션 초기화
        session.clear()

    # 로봇 사용 중 여부 확인 — 활성 사용자가 있으면 로그인에서 판단
    robots = _ctrl_rest("GET", "/robots")
    if robots:
        robot_state = robots.get(str(robot_id))
        # IDLE은 "사용 중"이 아니므로 blocked로 보내지 않는다.
        if robot_state and robot_state.get("mode") not in ("CHARGING", "OFFLINE", "IDLE", None):
            if not robot_state.get("active_user_id"):
                return redirect(url_for("blocked", robot_id=robot_id))

    return redirect(url_for("login", robot_id=robot_id))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        robot_id = _require_robot_id(request.form.get("robot_id", "").strip())

        user_id = request.form.get("user_id", "").strip()
        password = request.form.get("password", "")

        if not user_id or not password:
            flash("아이디와 비밀번호를 입력해주세요.")
        else:
            data = _ctrl_rest(
                "POST",
                "/session",
                json={"robot_id": robot_id, "user_id": user_id, "password": password},
            )
            if data is None:
                flash("서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.")
            elif data.get("error") == "robot is charging":
                return redirect(url_for("blocked", robot_id=robot_id, reason="charging"))
            elif data.get("error") == "robot is returning":
                return redirect(url_for("blocked", robot_id=robot_id, reason="returning"))
            elif data.get("error") in ("robot already in session",):
                return redirect(url_for("blocked", robot_id=robot_id))
            elif data.get("error") == "user already has active session":
                flash("이미 다른 로봇에서 세션이 활성화되어 있습니다.")
            elif data.get("error") in ("user not found", "robot_id and user_id required"):
                flash("잘못된 아이디 또는 비밀번호입니다.")
            elif data.get("error"):
                flash(f"로그인 실패: {data.get('error')}")
            else:
                session["robot_id"] = robot_id
                session["user_id"] = user_id
                session["session_id"] = data.get("session_id")
                return redirect(url_for("register", robot_id=robot_id))

        # 실패 시 GET /login?robot_id=... 으로 리다이렉트 (PRG 패턴)
        return redirect(url_for("login", robot_id=robot_id))

    # GET
    robot_id = _require_robot_id(request.args.get("robot_id", "").strip())

    messages = get_flashed_messages()
    error = messages[0] if messages else None
    return render_template("login.html", robot_id=robot_id, error=error)


@app.route("/register")
def register():
    if "session_id" not in session:
        robot_id = request.args.get("robot_id", "").strip()
        return redirect(url_for("login", robot_id=robot_id) if robot_id else url_for("login"))
    robot_id = session.get("robot_id", "").strip()
    if not robot_id or robot_id not in KNOWN_ROBOT_IDS:
        session.clear()
        return redirect(url_for("login"))
    requested_robot_id = request.args.get("robot_id", "").strip()
    if requested_robot_id and requested_robot_id != robot_id:
        return redirect(url_for("login", robot_id=robot_id))
    # SM 상태가 IDLE이 아니면 이미 등록됨 → /main으로
    robots = _ctrl_rest("GET", "/robots")
    if robots:
        mode = robots.get(str(robot_id), {}).get("mode")
        if mode and mode != "IDLE":
            return redirect(url_for("main", robot_id=robot_id))
    return render_template("register.html", robot_id=robot_id)


@app.route("/main")
def main():
    if "session_id" not in session:
        robot_id = request.args.get("robot_id", "").strip()
        return redirect(url_for("login", robot_id=robot_id) if robot_id else url_for("login"))
    robot_id = session.get("robot_id", "").strip()
    if not robot_id or robot_id not in KNOWN_ROBOT_IDS:
        session.clear()
        return redirect(url_for("login"))
    # 쿼리파라미터의 robot_id가 세션과 다르면 접근 거부
    requested_robot_id = request.args.get("robot_id", "").strip()
    if requested_robot_id and requested_robot_id != robot_id:
        return redirect(url_for("login", robot_id=robot_id))
    # SM 상태가 IDLE이면 /register로 (아직 등록 전)
    # 단, 시뮬레이션 모드(follow_disabled)는 인형 등록 불필요
    robots = _ctrl_rest("GET", "/robots")
    if robots:
        robot_state = robots.get(str(robot_id), {})
        mode = robot_state.get("mode")
        follow_disabled = robot_state.get("follow_disabled", False)
        if mode == "IDLE" and not follow_disabled:
            return redirect(url_for("register", robot_id=robot_id))
    return render_template(
        "main.html",
        robot_id=robot_id,
        user_id=session.get("user_id", ""),
        map_resolution=MAP_RESOLUTION,
        map_origin_x=MAP_ORIGIN_X,
        map_origin_y=MAP_ORIGIN_Y,
    )


@app.route("/blocked")
def blocked():
    reason = request.args.get("reason", "")
    robot_id = request.args.get("robot_id", "")
    return render_template("blocked.html", reason=reason, robot_id=robot_id)


@app.route("/logout", methods=["POST"])
def logout():
    session_id = session.get("session_id")
    if session_id:
        _ctrl_rest("PATCH", f"/session/{session_id}", json={"is_active": False})
    robot_id = session.get("robot_id", "")
    session.clear()
    return redirect(url_for("login", robot_id=robot_id)) if robot_id else redirect(url_for("login"))


# ── 진입점 ────────────────────────────────────────────────────

if __name__ == "__main__":
    import socket as _sock
    try:
        _s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        _s.connect(('8.8.8.8', 80))
        _private_ip = _s.getsockname()[0]
        _s.close()
    except Exception:
        _private_ip = '127.0.0.1'

    logger.info("ShopPinkki Customer Web 시작 (포트 %d, 로봇: %s)", PORT, KNOWN_ROBOT_IDS)
    print(f"\n  접속 URL ({_private_ip}):")
    for rid in KNOWN_ROBOT_IDS:
        print(f"    http://{_private_ip}:{PORT}/?robot_id={rid}")
    print(f"  테스트 아이디 / 비밀번호: test01 / 1234  (또는 test02 / 1234)")
    print()
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False)
