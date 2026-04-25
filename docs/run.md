# 실행 (Run)

> **프로젝트:** 쑈삥끼 (ShopPinkki)
> 자세한 tmux 세션 구성 / 단축키 / 옵션은 [`scripts/index.md`](../scripts/index.md) 참조.
> AI 서버 없이 실행하고 싶으면 어디서든 `bash scripts/run_server.sh --no-ai` 사용.
> ROS_DOMAIN_ID 기본값은 `14` (`scripts/_ros_env.sh`에서 변경).

## 시뮬레이션 모드 (실물 로봇 없이)

3개 터미널에서 순서대로 실행:

```bash
# 터미널 A — 서버 (control_service + AI Docker)
bash scripts/run_server.sh

# 터미널 B — UI (admin_ui + customer_web)
bash scripts/run_ui.sh

# 터미널 C — Gazebo 시뮬 (로봇 54, 18 동시 띄움)
bash scripts/run_sim.sh
```

Gazebo 로딩 완료(~60초) 후:
1. **admin_ui** 의 각 로봇 카드에서 **[위치 초기화]** 버튼 클릭 — AMCL 초기 위치 설정
2. **customer_web** 에서 `http://localhost:8501/?robot_id=54` 로 로그인 → 상태가 CHARGING → IDLE 로 전환되면 준비 완료

> customer_web IDLE 패널의 **[시뮬레이션 모드]** 버튼으로 추종 없이 쇼핑 테스트 가능.

## 실물 로봇 모드

```bash
# [노트북] 터미널 A — 서버
bash scripts/run_server.sh

# [노트북] 터미널 B — UI
bash scripts/run_ui.sh

# [Pi 5 — 각 로봇에 SSH 접속 후 실행]
bash scripts/run_robot.sh 54   # 로봇 #54
bash scripts/run_robot.sh 18   # 로봇 #18 (다른 Pi에서)
```

Pi 쪽에 `ROBOT_ID`가 `~/.zshrc`에 영구 설정되어 있어야 함 ([`setup.md`](setup.md) §C.8 참조).

## DB 시딩 (최초 1회 또는 데이터 리셋 시)

```bash
bash scripts/seed.sh   # 대화형: reset / replace / (없는 항목만 추가)
```
