#!/usr/bin/env sh
# _ros_env.sh — ROS 2 환경 자동 감지 헬퍼
#
# 지원 환경:
#   macOS  + conda (RoboStack)
#   Ubuntu + apt   (/opt/ros/jazzy)
#
# 사용법 (다른 스크립트에서):
#   source "$(dirname "$0")/_ros_env.sh"    # bash/zsh 모두 동작
#
# 이후 사용 가능한 변수:
#   TMUX_SRC   — tmux send-keys 용 원라인 (항상 zsh 호환 파일 사용)
#   CONDA_BIN  — conda env bin 경로 (없으면 "")

# $0 은 source 시 상위 스크립트 이름일 수 있음(bash); bash -c 'source …' 는 $0=bash 가 되기도 함
_ROS_ENV_SELF="$0"
if [ -n "${BASH_VERSION:-}" ]; then
    # dash 등에서는 BASH_SOURCE 를 건드리지 않음
    # shellcheck disable=SC3054
    [ -n "${BASH_SOURCE[0]:-}" ] && _ROS_ENV_SELF="${BASH_SOURCE[0]}"
fi
_SCRIPTS_DIR="$(cd "$(dirname "$_ROS_ENV_SELF")" && pwd)"
_ROS_WS="$(dirname "$_SCRIPTS_DIR")"

# ── 공통 ROS 설정 ──────────────────────────────────────────────────────────────
# 모든 tmux 실행 스크립트에서 단일 소스로 사용한다.
# 외부에서 ROS_DOMAIN_ID 를 지정하면 그 값을 우선 사용한다.
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-14}"

# FastDDS 유니캐스트 — WiFi 멀티캐스트 트래픽 제거
_FASTDDS_XML="$_SCRIPTS_DIR/fastdds_unicast.xml"
if [ -f "$_FASTDDS_XML" ]; then
    export FASTRTPS_DEFAULT_PROFILES_FILE="$_FASTDDS_XML"
fi

TMUX_ROS_ENV="export ROS_DOMAIN_ID=${ROS_DOMAIN_ID} && export FASTRTPS_DEFAULT_PROFILES_FILE=$_SCRIPTS_DIR/fastdds_unicast.xml"

# ── 1. conda env 탐색 ─────────────────────────────────────────────────────────
# conda env 가 존재하면 activate 하여 pip 패키지를 사용할 수 있도록 한다.
CONDA_BIN=""
CMAKE_EXTRA_PATH=""
_CONDA_ENV_DIR=""

# 현재 활성 conda env 먼저 확인
if [ -n "$CONDA_PREFIX" ] && [ -d "$CONDA_PREFIX/bin" ]; then
    _CONDA_ENV_DIR="$CONDA_PREFIX"
fi

# 없으면 공통 설치 경로 스캔 (setup.zsh 유무와 무관하게 env 존재만 확인)
if [ -z "$_CONDA_ENV_DIR" ]; then
    for _base in \
        "$HOME/miniconda3" "$HOME/miniforge3" "$HOME/mambaforge" \
        "$HOME/anaconda3"  "/opt/conda" "/usr/local/conda" \
        "/opt/homebrew/Caskroom/miniconda/base"
    do
        for _name in jazzy ros2 ros; do
            _p="$_base/envs/$_name"
            if [ -d "$_p/bin" ]; then
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

# 현재 스크립트 환경 설정: conda activate + ROS setup source
# conda activate (현재 셸에서도 실행하여 python3 등이 conda env 를 가리키도록)
if [ -n "$_CONDA_ENV_DIR" ]; then
    _conda_env_name="$(basename "$_CONDA_ENV_DIR")"
    _conda_exe=""
    for _d in "$(dirname "$(dirname "$_CONDA_ENV_DIR")")/condabin" \
              "$(dirname "$(dirname "$_CONDA_ENV_DIR")")/bin"; do
        if [ -x "$_d/conda" ]; then
            _conda_exe="$_d/conda"
            break
        fi
    done
    if [ -n "$_conda_exe" ]; then
        # conda 함수 로드 후 activate (bash/zsh 자동 감지)
        if [ -n "$BASH_VERSION" ]; then
            eval "$("$_conda_exe" shell.bash hook)"
        else
            eval "$("$_conda_exe" shell.zsh hook)"
        fi
        conda activate "$_conda_env_name" 2>/dev/null || true
    fi
fi

if [ -z "$ROS_SETUP_FILE" ]; then
    echo "[_ros_env] ⚠️  ROS 2 환경을 찾을 수 없습니다." >&2
    echo "           apt 로 ROS 2 Jazzy 를 설치하거나 macOS 에서 conda(RoboStack) 를 사용하세요." >&2
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

# conda activate 명령 구성 (conda init 없이도 동작하도록 conda 실행파일 경로 사용)
_CONDA_ACTIVATE=""
if [ -n "$_CONDA_ENV_DIR" ]; then
    _conda_env_name="$(basename "$_CONDA_ENV_DIR")"
    # conda 실행파일 경로 탐색
    _conda_bin_path=""
    for _d in "$(dirname "$(dirname "$_CONDA_ENV_DIR")")/condabin" \
              "$(dirname "$(dirname "$_CONDA_ENV_DIR")")/bin"; do
        if [ -x "$_d/conda" ]; then
            _conda_bin_path="$_d/conda"
            break
        fi
    done
    if [ -n "$_conda_bin_path" ]; then
        # eval "$(conda shell.zsh hook)" 로 conda 함수를 현재 셸에 로드 후 activate
        _CONDA_ACTIVATE="eval \"\$($_conda_bin_path shell.zsh hook)\" && conda activate $_conda_env_name"
    fi
fi

_tmux_src_file="${TMUX_SETUP_FILE:-$ROS_SETUP_FILE}"

# apt 설치 jazzy underlay 경로 (conda 환경 없는 Ubuntu에서 workspace setup.zsh 단독 소싱 시
# rclpy 등 ROS 패키지 경로가 누락되는 문제 방지)
_APT_JAZZY_SETUP=""
for _f in "/opt/ros/jazzy/setup.zsh" "/opt/ros/jazzy/setup.bash"; do
    [ -f "$_f" ] && { _APT_JAZZY_SETUP="$_f"; break; }
done

# workspace setup.zsh 가 colcon 빌드 시 underlay 체인을 포함하지 않을 수 있으므로
# apt jazzy가 있고 workspace setup 파일이 workspace 경로인 경우 jazzy를 먼저 source
_needs_jazzy_prefix=""
if [ -n "$_APT_JAZZY_SETUP" ] && [ -z "$_CONDA_ENV_DIR" ] && [ -n "$_tmux_src_file" ]; then
    case "$_tmux_src_file" in
        "$_ROS_WS/"*) _needs_jazzy_prefix="$_APT_JAZZY_SETUP" ;;
    esac
fi

if [ -n "$_CONDA_ACTIVATE" ] && [ -n "$_tmux_src_file" ]; then
    # setup.zsh 가 PATH 를 재배치할 수 있으므로, source 후 conda env bin 을 맨 앞에 복원
    TMUX_SRC="$_CONDA_ACTIVATE; source ${_tmux_src_file}; export PATH=${CONDA_BIN}:\$PATH"
elif [ -n "$_CONDA_ACTIVATE" ]; then
    TMUX_SRC="$_CONDA_ACTIVATE"
elif [ -n "$_needs_jazzy_prefix" ] && [ -n "$_tmux_src_file" ]; then
    # apt jazzy를 먼저 source한 뒤 workspace local_setup 추가
    TMUX_SRC="source ${_needs_jazzy_prefix} && source ${_tmux_src_file}"
elif [ -n "$_tmux_src_file" ]; then
    TMUX_SRC="source ${_tmux_src_file}"
else
    TMUX_SRC="echo '[_ros_env] ⚠️ ROS2 환경 없음 — setup.zsh 를 수동으로 source 하세요'"
fi
