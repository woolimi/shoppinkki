#!/usr/bin/env sh
# _ros_env.sh — ROS 2 환경 자동 감지 헬퍼
#
# 지원 환경:
#   macOS  + conda (RoboStack)
#   Ubuntu + apt   (/opt/ros/jazzy)
#   Ubuntu + conda (RoboStack)
#
# 사용법 (다른 스크립트에서):
#   source "$(dirname "$0")/_ros_env.sh"    # bash/zsh 모두 동작
#
# 이후 사용 가능한 변수:
#   TMUX_SRC   — tmux send-keys 용 원라인 (항상 zsh 호환 파일 사용)
#   CONDA_BIN  — conda env bin 경로 (없으면 "")

_SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
_ROS_WS="$(dirname "$_SCRIPTS_DIR")"

# ── 1. conda env 탐색 ─────────────────────────────────────────────────────────
CONDA_BIN=""
CMAKE_EXTRA_PATH=""
_CONDA_ENV_DIR=""

# 현재 활성 conda env 먼저 확인
if [ -n "$CONDA_PREFIX" ] && [ -d "$CONDA_PREFIX/bin" ]; then
    _CONDA_ENV_DIR="$CONDA_PREFIX"
fi

# 없으면 공통 설치 경로 스캔
if [ -z "$_CONDA_ENV_DIR" ]; then
    for _base in \
        "$HOME/miniconda3" "$HOME/miniforge3" "$HOME/mambaforge" \
        "$HOME/anaconda3"  "/opt/conda" "/usr/local/conda" \
        "/opt/homebrew/Caskroom/miniconda/base"
    do
        for _name in jazzy ros2 ros; do
            _p="$_base/envs/$_name"
            if [ -d "$_p/bin" ] && { [ -f "$_p/setup.zsh" ] || [ -f "$_p/setup.bash" ]; }; then
                _CONDA_ENV_DIR="$_p"
                break 2
            fi
        done
    done
fi

if [ -n "$_CONDA_ENV_DIR" ]; then
    CONDA_BIN="$_CONDA_ENV_DIR/bin"
    export PATH="$CONDA_BIN:$PATH"

    # macOS: cmake 가 Homebrew 에 있을 수 있음
    if [ "$(uname)" = "Darwin" ]; then
        for _d in /opt/homebrew/bin /usr/local/bin; do
            if [ -x "$_d/cmake" ]; then
                CMAKE_EXTRA_PATH="$_d"
                export PATH="$CMAKE_EXTRA_PATH:$PATH"
                break
            fi
        done
    fi
fi

# ── 2. setup 파일 선택 ────────────────────────────────────────────────────────
# ROS_SETUP_FILE  : 현재 스크립트(bash/zsh) 에서 source 할 파일
# TMUX_SETUP_FILE : tmux 창(항상 zsh) 에서 source 할 파일 → .zsh 우선
ROS_SETUP_FILE=""
TMUX_SETUP_FILE=""

# 현재 쉘이 bash 이면 .bash 우선, 아니면 .zsh 우선
if [ -n "$BASH_VERSION" ]; then
    for _f in \
        "$_ROS_WS/install/setup.bash" \
        "$_CONDA_ENV_DIR/setup.bash" \
        "/opt/ros/jazzy/setup.bash" \
        "$_ROS_WS/install/setup.zsh" \
        "$_CONDA_ENV_DIR/setup.zsh" \
        "/opt/ros/jazzy/setup.zsh"
    do
        [ -n "$_f" ] && [ -f "$_f" ] && { ROS_SETUP_FILE="$_f"; break; }
    done
else
    for _f in \
        "$_ROS_WS/install/setup.zsh" \
        "$_ROS_WS/install/setup.bash" \
        "$_CONDA_ENV_DIR/setup.zsh" \
        "$_CONDA_ENV_DIR/setup.bash" \
        "/opt/ros/jazzy/setup.zsh" \
        "/opt/ros/jazzy/setup.bash"
    do
        [ -n "$_f" ] && [ -f "$_f" ] && { ROS_SETUP_FILE="$_f"; break; }
    done
fi

# tmux 창용은 항상 .zsh 우선 (macOS tmux 기본 쉘 = zsh)
for _f in \
    "$_ROS_WS/install/setup.zsh" \
    "$_CONDA_ENV_DIR/setup.zsh" \
    "/opt/ros/jazzy/setup.zsh" \
    "$_ROS_WS/install/setup.bash" \
    "$_CONDA_ENV_DIR/setup.bash" \
    "/opt/ros/jazzy/setup.bash"
do
    [ -n "$_f" ] && [ -f "$_f" ] && { TMUX_SETUP_FILE="$_f"; break; }
done

# 현재 스크립트 환경 설정
if [ -z "$ROS_SETUP_FILE" ]; then
    echo "[_ros_env] ⚠️  ROS 2 환경을 찾을 수 없습니다." >&2
    echo "           conda(RoboStack) 또는 apt 로 ROS 2 Jazzy 를 설치하세요." >&2
else
    # shellcheck disable=SC1090
    . "$ROS_SETUP_FILE"
fi

# ── 3. Qt 플랫폼 플러그인 설정 (PyQt6 앱용) ───────────────────────────────────
if [ "$(uname)" = "Darwin" ] && [ -n "$CONDA_BIN" ]; then
    _qt_plugins="$("$CONDA_BIN/python3" -c \
      "import PyQt6,os; print(os.path.join(os.path.dirname(PyQt6.__file__),'Qt6/plugins/platforms'))" \
      2>/dev/null || true)"
    [ -n "$_qt_plugins" ] && [ -d "$_qt_plugins" ] && \
        export QT_QPA_PLATFORM_PLUGIN_PATH="$_qt_plugins"

elif [ "$(uname)" = "Linux" ]; then
    if [ -n "$WAYLAND_DISPLAY" ]; then
        export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland}"
    else
        export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
    fi
    if [ -n "$CONDA_BIN" ]; then
        _qt_plugins="$("$CONDA_BIN/python3" -c \
          "import PyQt6,os; print(os.path.join(os.path.dirname(PyQt6.__file__),'Qt6/plugins/platforms'))" \
          2>/dev/null || true)"
        [ -n "$_qt_plugins" ] && [ -d "$_qt_plugins" ] && \
            export QT_QPA_PLATFORM_PLUGIN_PATH="$_qt_plugins"
    fi
fi

# ── 4. tmux send-keys 용 원라인 SRC 생성 ──────────────────────────────────────
# TMUX_SETUP_FILE(.zsh) 을 사용 — tmux 창은 zsh 로 실행되므로
_PATH_PREPEND=""
[ -n "$CMAKE_EXTRA_PATH" ] && _PATH_PREPEND="$CMAKE_EXTRA_PATH:"
[ -n "$CONDA_BIN" ]        && _PATH_PREPEND="${_PATH_PREPEND}${CONDA_BIN}:"

_tmux_src_file="${TMUX_SETUP_FILE:-$ROS_SETUP_FILE}"

if [ -n "$_PATH_PREPEND" ] && [ -n "$_tmux_src_file" ]; then
    TMUX_SRC="export PATH=${_PATH_PREPEND}\$PATH; source ${_tmux_src_file}"
elif [ -n "$_tmux_src_file" ]; then
    TMUX_SRC="source ${_tmux_src_file}"
else
    TMUX_SRC="echo '[_ros_env] ⚠️ ROS2 환경 없음 — setup.zsh 를 수동으로 source 하세요'"
fi
