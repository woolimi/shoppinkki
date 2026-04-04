"""
ShopPinkki Customer Web App
Flask + Flask-SocketIO 진입점. 포트 8501.

환경 변수:
    PORT                  : 서버 포트 (기본 8501)
    ROBOT_ID              : 로봇 ID (기본 '54')
    CONTROL_SERVICE_HOST  : control_service 호스트 (기본 '127.0.0.1')
    CONTROL_SERVICE_PORT  : control_service TCP 포트 (기본 8080)
    CONTROL_SERVICE_HTTP_PORT : control_service REST 포트 (기본 8081)
    LLM_HOST              : LLM 서버 호스트 (기본 '127.0.0.1')
    LLM_PORT              : LLM 서버 포트 (기본 8000)
    SECRET_KEY            : Flask 세션 키 (기본 'shoppinkki-secret')
"""

import logging
import os
import yaml

import eventlet
eventlet.monkey_patch()  # noqa: E402 — 반드시 최상단에서 패치

import requests
from flask import Flask, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO

from control_client import ControlClient
import socket_handlers

# ── 로깅 설정 ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── 환경 변수 ──────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 8501))
ROBOT_ID = os.environ.get("ROBOT_ID", "54")
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
        "../../src/shoppinkki/shoppinkki_nav/maps/shop.yaml",
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

socketio = SocketIO(
    app,
    async_mode="eventlet",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False,
)

# ── control_client 초기화 ──────────────────────────────────────
control_client = ControlClient(
    host=CONTROL_HOST,
    port=CONTROL_PORT,
    robot_id=ROBOT_ID,
    socketio_instance=socketio,
)
control_client.connect()

# ── SocketIO 핸들러 등록 ───────────────────────────────────────
socket_handlers.register_handlers(
    socketio=socketio,
    control_client=control_client,
    llm_cfg={"host": LLM_HOST, "port": LLM_PORT},
    robot_id=ROBOT_ID,
)


# ── 헬퍼: control_service REST 호출 ───────────────────────────

def _ctrl_rest(method: str, path: str, **kwargs):
    """control_service REST API 호출 헬퍼. 실패 시 None 반환."""
    url = f"http://{CONTROL_HOST}:{CONTROL_HTTP_PORT}{path}"
    try:
        resp = requests.request(method, url, timeout=5, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("REST 호출 실패 [%s %s]: %s", method, path, e)
        return None


# ── 라우트 ────────────────────────────────────────────────────

@app.route("/")
def index():
    """
    세션 확인 후 적절한 페이지로 리다이렉트.
    - 활성 세션 있음 → /main
    - 로봇 사용 중 → /blocked
    - 없음 → /login
    """
    robot_id = request.args.get("robot_id", ROBOT_ID)
    session_id = session.get("session_id")

    # 기존 세션 유효성 확인
    if session_id:
        data = _ctrl_rest("GET", f"/session/{session_id}")
        if data and data.get("is_active"):
            return redirect(url_for("main"))
        # 만료된 세션 초기화
        session.clear()

    # 로봇 사용 중 여부 확인 — GET /robots 에서 해당 로봇 찾기
    robots = _ctrl_rest("GET", "/robots")
    if robots:
        robot = next((r for r in robots if str(r.get("robot_id")) == str(robot_id)), None)
        if robot and robot.get("active_user_id"):
            return redirect(url_for("blocked"))

    return redirect(url_for("login", robot_id=robot_id))


@app.route("/login", methods=["GET", "POST"])
def login():
    robot_id = request.args.get("robot_id", ROBOT_ID)
    error = None

    if request.method == "POST":
        robot_id = request.form.get("robot_id", ROBOT_ID)
        user_id = request.form.get("user_id", "").strip()
        password = request.form.get("password", "")

        if not user_id or not password:
            error = "아이디와 비밀번호를 입력해주세요."
        else:
            # control_service REST POST /session 으로 로그인
            data = _ctrl_rest(
                "POST",
                "/session",
                json={"robot_id": robot_id, "user_id": user_id, "password": password},
            )
            if data is None:
                error = "서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요."
            elif data.get("error") == "robot_busy":
                return redirect(url_for("blocked"))
            elif data.get("error"):
                error = "잘못된 아이디 또는 비밀번호입니다."
            else:
                session["robot_id"] = robot_id
                session["user_id"] = user_id
                session["session_id"] = data.get("session_id")
                return redirect(url_for("main"))

    return render_template("login.html", robot_id=robot_id, error=error)


@app.route("/main")
def main():
    if "session_id" not in session:
        return redirect(url_for("login"))
    return render_template(
        "main.html",
        robot_id=session.get("robot_id", ROBOT_ID),
        user_id=session.get("user_id", ""),
        map_resolution=MAP_RESOLUTION,
        map_origin_x=MAP_ORIGIN_X,
        map_origin_y=MAP_ORIGIN_Y,
    )


@app.route("/blocked")
def blocked():
    return render_template("blocked.html")


@app.route("/logout", methods=["POST"])
def logout():
    session_id = session.get("session_id")
    if session_id:
        _ctrl_rest("PATCH", f"/session/{session_id}", json={"is_active": False})
    session.clear()
    return redirect(url_for("login"))


# ── 진입점 ────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("ShopPinkki Customer Web 시작 (포트 %d, 로봇 %s)", PORT, ROBOT_ID)
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False)
