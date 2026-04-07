# Scripts 사용법

## 스크립트 구조

```
scripts/
├── run_server.sh       ← 노트북: control_service + AI 서버
├── run_ui.sh           ← 노트북: admin_ui + customer_web
├── run_sim.sh          ← 노트북: Gazebo 시뮬레이션 (로봇 코어 포함)
├── run_robot.sh        ← Pi 5 : 실물 로봇 전체 스택
├── run_ai.sh           ← 단독: AI 서버 Docker만 실행
├── seed.sh             ← MySQL DB 시딩
└── _ros_env.sh         ← 공통 ROS 환경 감지 (직접 실행 X)
```

---

## ROS_DOMAIN_ID 관리

tmux 기반 실행 스크립트(`run_server.sh`, `run_ui.sh`, `run_sim.sh`, `run_robot.sh`)는
모두 `scripts/_ros_env.sh`에서 `ROS_DOMAIN_ID`를 공통으로 설정해 사용합니다.

- 기본값: `14`
- 설정 위치: `scripts/_ros_env.sh`
  - `export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-14}"`

기본값을 바꾸고 싶다면 위 줄의 `14`만 변경하면 전체 스크립트에 반영됩니다.

실행 시 1회성으로 덮어쓰려면 환경변수로 지정하세요:

```bash
ROS_DOMAIN_ID=20 bash scripts/run_server.sh
ROS_DOMAIN_ID=20 bash scripts/run_ui.sh
ROS_DOMAIN_ID=20 bash scripts/run_sim.sh
ROS_DOMAIN_ID=20 bash scripts/run_robot.sh 54
```

---

## 개발 워크플로우

### 시뮬레이션 (실물 없을 때)

터미널 3개를 열고 순서대로 실행:

```bash
# 터미널 A — 서버
bash scripts/run_server.sh

# 터미널 B — UI
bash scripts/run_ui.sh

# 터미널 C — Gazebo 시뮬
bash scripts/run_sim.sh
```

Gazebo 로딩 완료(~60초) 후:
1. **admin_ui** 에서 각 로봇 카드의 **[위치 초기화]** 버튼 클릭 (AMCL 초기 위치 설정)
2. **customer_web** 에서 `http://localhost:8501/?robot_id=54` 로 로그인 → CHARGING → IDLE 전환

> customer_web IDLE 패널의 **[시뮬레이션 모드]** 버튼으로 추종 없이 쇼핑 테스트 가능.

---

### 실물 로봇

```bash
# [노트북] 터미널 A — 서버
bash scripts/run_server.sh

# [노트북] 터미널 B — UI
bash scripts/run_ui.sh

# [Pi 5] SSH 접속 후
bash scripts/run_robot.sh 54   # 로봇 54번
bash scripts/run_robot.sh 18   # 로봇 18번 (다른 Pi에서)
```

---

## 각 스크립트 상세

### `run_server.sh` — 서버 스택

| 옵션 | 설명 |
|---|---|
| (없음) | control_service + AI 서버 (Docker) |
| `--no-ai` | AI 서버 제외 (YOLO/LLM 불필요 시) |

```bash
bash scripts/run_server.sh
bash scripts/run_server.sh --no-ai
```

tmux 창:
- `0. control` — control_service (TCP:8080 / REST:8081)
- `1. ai` — YOLO TCP:5005 / LLM REST:8000
- `2. shell` — 디버깅 셸

---

### `run_ui.sh` — UI 스택

```bash
bash scripts/run_ui.sh
```

> 로봇 접속은 URL 쿼리 파라미터로 구분:
> `http://localhost:8501/?robot_id=54` 또는 `?robot_id=18`

tmux 창:
- `0. admin` — admin_ui (PyQt6 관제)
- `1. customer` — customer_web (http://localhost:8501)

---

### `run_sim.sh` — Gazebo 시뮬레이션

```bash
bash scripts/run_sim.sh
```

tmux 창:
- `0. gz` — Gazebo + Nav2 (로봇 54, 18)
- `1. core54` — shoppinkki_core 로봇 54
- `2. core18` — shoppinkki_core 로봇 18
- `3. init` — 초기화 셸 (gz_init_robots.sh 수동 실행)
- `4. shell` — 디버깅 셸

---

### `run_robot.sh` — 실물 로봇 (Pi 5 실행)

```bash
bash scripts/run_robot.sh      # ROBOT_ID=54
bash scripts/run_robot.sh 18   # ROBOT_ID=18
```

tmux 창 (자동 순차 시작):
- `0. bringup` — 모터/IMU/TF (즉시)
- `1. nav` — Nav2 + AMCL (10초 후)
- `2. core` — shoppinkki_core SM+BT (30초 후)
- `3. shell` — 디버깅 셸

---

### `seed.sh` — DB 시딩

```bash
bash scripts/seed.sh
```

실행 시 대화형으로 모드 선택:
- `reset` — 전체 초기화 후 시딩
- `replace` — 기존 데이터 교체
- (기본) — 없는 항목만 추가

---

## tmux 기본 조작

| 단축키 | 동작 |
|---|---|
| `Ctrl+b` → 숫자 | 창 전환 |
| `Ctrl+b` → `d` | 세션 분리 (프로세스 유지) |
| `Ctrl+b` → `[` | 스크롤 모드 (방향키, `q` 종료) |
| 마우스 클릭 | 창 전환 / 스크롤 (mouse on 설정 시) |

세션 재접속:
```bash
tmux attach -t sp_server   # 서버
tmux attach -t sp_ui       # UI
tmux attach -t sp_sim      # 시뮬
tmux attach -t sp_robot    # 실물 로봇
```

전체 종료:
```bash
tmux kill-server
```
