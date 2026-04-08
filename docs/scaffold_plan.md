# Scaffold 계획

> **프로젝트:** 쑈삥끼 (ShopPinkki)
> 시나리오(SC-01~SC-82) 구현을 위한 폴더 구조 계획.
> 시스템 아키텍처(`docs/system_architecture.md`) 기준 3-레이어(EQUIP / SERVER / UI) 매핑.

---

## 전체 폴더 트리

```
ros_ws/
├── src/
│   ├── pinky_pro/                      ← git submodule (수정 금지)
│   ├── shoppinkki/                     ← EQUIP 레이어 — Pi 5 실행 ROS2 패키지
│   │   ├── shoppinkki_interfaces/
│   │   ├── shoppinkki_core/
│   │   ├── shoppinkki_nav/
│   │   └── shoppinkki_perception/
│   └── control_center/                 ← SERVER 레이어 — 서버 PC 실행 ROS2 패키지
│       ├── control_service/
│       ├── admin_ui/
│       └── shoppinkki_rmf/             ← Open-RMF 연동 — Fleet Adapter (서버 PC 실행)
├── services/                           ← SERVER / UI 레이어 — Non-ROS 서비스
│   ├── customer_web/
│   └── ai_server/
└── scripts/                            ← 실행 스크립트 + DB 관리
    └── db/
```

---

## EQUIP 레이어 — `src/shoppinkki/`

Pi 5에서 실행되는 ROS2 패키지 4개. 공통 구조:

```
<package_name>/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/<package_name>       ← ament marker
├── <package_name>/               ← Python 모듈
│   └── __init__.py
└── test/
    ├── test_copyright.py
    ├── test_flake8.py
    └── test_pep257.py
```

---

### `shoppinkki_interfaces/`

다른 패키지들이 공유하는 Protocol 인터페이스와 Mock 구현체. 실행 노드 없음(라이브러리 전용).

```
shoppinkki_interfaces/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/shoppinkki_interfaces
├── shoppinkki_interfaces/
│   ├── __init__.py
│   ├── protocols.py              ← Protocol 인터페이스 (DollDetectorInterface,
│   │                                QRScannerInterface, NavBTInterface,
│   │                                BoundaryMonitorInterface, RobotPublisherInterface)
│   └── mocks.py                  ← Mock 구현체 (단위 테스트용)
└── test/
    └── test_protocols.py
```

**핵심 파일:**
- `protocols.py` — `docs/interface_specification.md` §1 Python 모듈 간 인터페이스 전체 정의. `Detection`, `CartItem` 데이터클래스 포함.
- `mocks.py` — 각 Protocol에 대한 Mock 구현. BT/SM 단위 테스트 시 실제 HW/Nav2 없이 사용.

---

### `shoppinkki_core/`

SM + BT Runner + HW 제어 통합 노드. 시나리오 전 범위의 핵심 구현체.

```
shoppinkki_core/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/shoppinkki_core
├── shoppinkki_core/
│   ├── __init__.py
│   ├── config.py                 ← 전역 상수 (BATTERY_THRESHOLD, ROBOT_TIMEOUT_SEC,
│   │                                N_MISS_FRAMES, SEARCH_TIMEOUT, WAITING_TIMEOUT,
│   │                                TARGET_AREA, KP_ANGLE, KP_DIST, LINEAR_X_MAX,
│   │                                ANGULAR_Z_MAX, MIN_DIST, IMAGE_WIDTH)
│   ├── main_node.py              ← ROS2 Node 진입점. 각 모듈을 조합하여 spin()
│   ├── state_machine.py          ← ShoppinkiSM (transitions 라이브러리)
│   │                                - 10개 상태 정의
│   │                                - on_enter_* / on_exit_* 콜백
│   │                                - is_locked_return, previous_tracking_state
│   │                                - resume_tracking(), on_staff_resolved()
│   │                                - charging_required: IDLE 상태 + 활성 세션 없음 +
│   │                                  배터리 < BATTERY_THRESHOLD 일 때만 → CHARGING
│   ├── bt_runner.py              ← 현재 SM 상태에 따라 BT 선택 + tick() 루프 실행
│   │                                - BT1~BT5 인스턴스 보유 (NavBTInterface 타입)
│   │                                - on_enter_*/on_exit_* 콜백과 연동
│   ├── hw_controller.py          ← HW 서비스 호출 래퍼
│   │                                - set_led(color): /set_led
│   │                                - set_lcd(text): /set_emotion 또는 LCD 직접 제어
│   │                                - buzz(pattern): 부저
│   │                                - get_led_color(): is_locked_return 우선 확인
│   └── cmd_handler.py            ← /robot_<id>/cmd JSON 파싱 → SM 트리거 분기
│                                    - start_session, mode, resume_tracking,
│                                      navigate_to, payment_success, delete_item,
│                                      force_terminate, staff_resolved, admin_goto
└── test/
    ├── test_state_machine.py     ← SM 전환 단위 테스트 (mocks 사용)
    └── test_cmd_handler.py
```

**핵심 파일:**
- `state_machine.py` — `docs/state_machine.md` 구현 노트 기반. `transitions` 라이브러리로 10개 상태 선언.
- `bt_runner.py` — `docs/behavior_tree.md` SM↔BT 역할 분담 기반. 상태 진입 시 해당 BT 시작, 상태 이탈 시 BT 중단.
- `cmd_handler.py` — `docs/interface_specification.md` 채널 G `/robot_<id>/cmd` 페이로드 목록 전체 처리.

---

### `shoppinkki_nav/`

BT1~BT5 구현체 + BoundaryMonitor + Nav2 설정 파일.

```
shoppinkki_nav/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/shoppinkki_nav
├── config/
│   ├── nav2_params.yaml          ← Nav2 AMCL, planner, controller 파라미터 (공통)
│   ├── nav2_params_robot_54.yaml ← 로봇 54 전용 Nav2 파라미터
│   ├── nav2_params_robot_18.yaml ← 로봇 18 전용 Nav2 파라미터
│   ├── bridge_robot_54.yaml      ← ros_gz_bridge 토픽 매핑 (로봇 54)
│   ├── bridge_robot_18.yaml      ← ros_gz_bridge 토픽 매핑 (로봇 18)
│   └── keepout_mask.yaml         ← Keepout Filter 마스크 설정
├── launch/
│   ├── navigation.launch.py      ← Nav2 스택 + BoundaryMonitor 노드 통합 실행
│   └── gz_multi_robot.launch.py  ← Gazebo 멀티로봇 시뮬레이션 실행
├── shoppinkki_nav/
│   ├── __init__.py
│   ├── bt_tracking.py            ← BT1: P-Control 추종 + RPLiDAR 장애물 회피 (Parallel)
│   ├── bt_searching.py           ← BT2: 제자리 회전 탐색 + 방향 전환 + 30s 타임아웃
│   ├── bt_waiting.py             ← BT3: 정지 대기 + 통행자 감지 시 소폭 회피
│   ├── bt_guiding.py             ← BT4: Nav2 Waypoint 이동 → SUCCESS: enter_waiting
│   │                                                              FAILURE: resume_tracking()
│   ├── bt_returning.py           ← BT5: Keepout ON → /zone/parking/available 조회
│   │                                     → Nav2 슬롯 이동 → enter_charging / Keepout OFF
│   └── boundary_monitor.py       ← BoundaryMonitor: AMCL pose 기반 결제구역 감시
│                                    - on_checkout_enter (TRACKING → 결제 팝업)
│                                    - on_checkout_exit_blocked (출구 차단)
│                                    - on_checkout_reenter (TRACKING_CHECKOUT → TRACKING)
│                                    - SM 상태가 TRACKING / TRACKING_CHECKOUT 일 때만
│                                      활성 감시. 나머지 상태에서는 pose 이벤트 무시
└── test/
    ├── test_boundary_monitor.py
    └── test_bt_searching.py
```

**핵심 파일:**
- `bt_tracking.py` — `docs/behavior_tree.md` BT1 flowchart 구현. `cmd_vel` 퍼블리시 + LiDAR 감시 Parallel 구조.
- `bt_returning.py` — `docs/behavior_tree.md` BT5 구현. `_set_keepout_filter(node, enable)` 헬퍼 포함.
- `boundary_monitor.py` — `docs/interface_specification.md` `BoundaryMonitorInterface` 구현체. `/amcl_pose` 구독.

---

### `shoppinkki_perception/`

YOLO bbox 수신(채널 G) → ReID + HSV 매칭, QR 스캔.

```
shoppinkki_perception/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/shoppinkki_perception
├── shoppinkki_perception/
│   ├── __init__.py
│   ├── doll_detector.py          ← DollDetectorInterface 구현체
│   │                                - register(frame): IDLE 단계 ReID+색상 템플릿 등록
│   │                                - run(frame): TRACKING 단계 매칭 → 버퍼 저장
│   │                                - get_latest() → Optional[Detection]
│   │                                - is_ready() → bool
│   ├── reid_engine.py            ← ReID 특징 벡터 추출 엔진
│   │                                - 임베딩 생성 + 코사인 유사도 매칭
│   ├── iou_tracker.py            ← bbox IoU 기반 프레임 간 추적기
│   │                                - 연속 프레임 bbox 연결 (ID 유지)
│   └── qr_scanner.py             ← QRScannerInterface 구현체
│                                    - OpenCV QRCodeDetector 기반
│                                    - start(on_scanned, on_timeout)
│                                    - 30s 무활동 타임아웃
└── test/
    └── test_doll_detector.py
```

---

## SERVER 레이어 — `src/control_center/`

서버 PC에서 실행되는 ROS2 패키지 2개.

---

### `control_service/`

ROS2 노드 + TCP 서버(채널 B·C) + REST API + MySQL 접근 + UDP 카메라 수신을 하나의 프로세스로 통합.

```
control_service/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/control_service
├── control_service/
│   ├── __init__.py
│   ├── main.py                   ← 진입점. ROS2 init + TCP 서버 + REST 서버 + cleanup 스레드
│   │                                스레드/asyncio 구조로 ROS spin과 TCP loop 병렬 실행
│   ├── ros_node.py               ← ROS2 Node (채널 G)
│   │                                - 구독: /robot_<id>/status, /robot_<id>/alarm,
│   │                                         /robot_<id>/cart
│   │                                - 발행: /robot_<id>/cmd
│   ├── tcp_server.py             ← TCP 서버 (포트 8080, 채널 B·C 통합)
│   │                                - 채널 B: Admin UI 연결 관리 (admin_clients)
│   │                                - 채널 C: customer_web 연결 관리 (web_clients)
│   │                                - JSON 개행 구분 파싱
│   │                                - push_to_admin(), push_to_web() 헬퍼
│   │                                - process_payment 수신 시 DB CART_ITEM.is_paid 갱신
│   │                                  + payment_success cmd → Pi relay
│   │                                - admin_goto 수신 시 IDLE 여부 확인 → 거부 시
│   │                                  admin_goto_rejected 응답 (채널 B)
│   ├── rest_api.py               ← REST API 엔드포인트 (포트 8080, 채널 C HTTP 겸용)
│   │                                - GET  /zone/<zone_id>/waypoint
│   │                                - GET  /zone/parking/available
│   │                                - GET  /boundary
│   │                                - GET  /events
│   │                                - POST/GET/PATCH /session, /session/<id>
│   │                                - POST/DELETE /cart/<id>/item, /item/<id>
│   │                                - PATCH /cart/<id>/items/mark_paid
│   │                                - GET  /cart/<id>/has_unpaid
│   │                                - GET  /camera/<robot_id>  ← MJPEG re-stream
│   ├── db.py                     ← MySQL 연결 풀 (pool_size=5) + 쿼리 함수
│   │                                - 환경 변수: MYSQL_HOST/PORT/USER/PASSWORD/DATABASE
│   │                                - 플레이스홀더 %s, cursor(dictionary=True)
│   │                                - 테이블별 CRUD 함수 (robot, session, cart, event_log 등)
│   ├── robot_manager.py          ← 로봇 상태 캐시 + 비즈니스 로직
│   │                                - RobotState 딕셔너리 (robot_id → 현재 상태)
│   │                                - cleanup 스레드 (10s 주기): last_seen + 30s → OFFLINE
│   │                                - 채널 B→G 명령 relay 로직
│   │                                - bbox 캐시 (채널 F 수신 → 채널 B status push 포함)
│   │                                - IDLE→TRACKING 모드 변화 감지 시 registration_done
│   │                                  이벤트 push → 채널 C customer_web 알림
│   └── camera_stream.py          ← 채널 H UDP 카메라 수신 + MJPEG re-stream
│                                    - 채널 H UDP 소켓으로 Pi 카메라 프레임 수신
│                                    - /camera/<robot_id> GET 요청 시 MJPEG 응답 생성
│                                    - 채널 F: 프레임 → AI Server YOLO(TCP:5005) 전달
│                                      + bbox TCP 응답 수신 → robot_manager bbox 캐시 갱신
└── test/
    ├── test_db.py
    └── test_robot_manager.py
```

**핵심 파일:**
- `tcp_server.py` — 채널 B(Admin)·C(customer_web) 모두 처리. 각 연결 식별 후 라우팅.
- `robot_manager.py` — OFFLINE cleanup, 명령 relay, bbox 집계. 비즈니스 로직 중심.
- `rest_api.py` — `docs/interface_specification.md` §3 REST API 전체 구현. `/camera/<robot_id>` MJPEG 포함.

---

### `admin_ui/`

PyQt6 관제 데스크톱 앱. `ros2 run admin_ui admin_ui` 로 실행.

```
admin_ui/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/admin_ui
├── assets/
│   └── shop_map.png              ← 관제 맵 이미지 (맵 오버레이 배경)
├── admin_ui/
│   ├── __init__.py
│   ├── main.py                   ← QApplication + QMainWindow 진입점
│   ├── main_window.py            ← 전체 레이아웃 조립 (splitter 기반)
│   │                                - MapWidget (좌상)
│   │                                - RobotCardPanel (우상)
│   │                                - CameraDebugPanel (우중, 기본 닫힘)
│   │                                - StaffCallPanel (하좌)
│   │                                - EventLogPanel (하우)
│   ├── tcp_client.py             ← TCP 클라이언트 (채널 B, QThread)
│   │                                - 수신 루프 → pyqtSignal로 Qt 메인 스레드 전달
│   │                                - send_cmd(payload: dict) 헬퍼
│   ├── map_widget.py             ← MapWidget (QLabel + QPixmap)
│   │                                - shop_map.png 오버레이
│   │                                - 로봇 아이콘 (yaw 방향, is_locked_return 테두리)
│   │                                - 오프라인: × 표시, 마지막 위치 유지
│   │                                - 클릭 → 월드 좌표 변환 → admin_goto 마커
│   ├── robot_card.py             ← RobotCard 위젯 (로봇 1대)
│   │                                - 모드 뱃지, 배터리 바, 좌표, 활성 사용자
│   │                                - 상태 전환 버튼 ([대기]/[추종]/[복귀]) 활성화 규칙
│   │                                - [강제 종료] / [이동 명령] / [잠금 해제] 버튼
│   ├── camera_panel.py           ← CameraDebugPanel (QWidget)
│   │                                - QThread에서 GET /camera/<robot_id> MJPEG 수신
│   │                                - QLabel에 프레임 표시 (QPixmap)
│   │                                - status bbox 필드로 바운딩박스 QPainter 오버레이
│   │                                - 로봇 선택 드롭다운, [닫기] 버튼
│   ├── robot_detail_dialog.py    ← RobotDetailDialog (QDialog)
│   │                                - 로봇 상세 정보 팝업
│   ├── staff_panel.py            ← StaffCallPanel (QListWidget 기반)
│   │                                - LOCKED/HALTED 이벤트 항목 추가
│   │                                - [잠금 해제]/[초기화] → staff_resolved 전송
│   │                                - "✓ 처리됨" 회색 처리
│   └── event_log_panel.py        ← EventLogPanel (QTableWidget)
│                                    - 이벤트 색상 구분 (SESSION_START/LOCKED/HALTED 등)
│                                    - 필터 버튼 [전체]/[스태프호출]/[세션]/[이벤트]
│                                    - 최대 200건. 행 클릭 → 로봇 카드 하이라이트
└── test/
    └── test_admin_ui.py
```

**핵심 파일:**
- `tcp_client.py` — QThread 기반 수신 루프. `pyqtSignal` 발행으로 UI 갱신 보장(thread-safe).
- `camera_panel.py` — `GET /camera/<robot_id>` MJPEG 스트림을 별도 QThread로 수신 후 `QPixmap`으로 표시.

---

### `shoppinkki_rmf/`

Open-RMF Fleet Adapter. 서버 PC에서 실행. RMF Traffic Negotiation으로 다중 로봇 경로 충돌을 자동 조정하고, RMF Task Dispatcher로 임무 배정을 중앙 관리.

**의존 패키지 (apt/pip):**
```bash
sudo apt install ros-jazzy-rmf-fleet-adapter ros-jazzy-rmf-traffic ros-jazzy-rmf-task
pip install rmf-adapter  # Python binding
```

**Traffic Map 사전 준비:**
- `traffic_editor` GUI로 `shop.building.yaml` 작성 (기존 `shop.pgm` 기반)
- 로봇 이동 레인(Lane) + 웨이포인트 정의 → RMF가 충돌 협상에 사용

```
shoppinkki_rmf/
├── package.xml
├── setup.py
├── setup.cfg
├── resource/shoppinkki_rmf
├── config/
│   └── fleet_config.yaml             ← Fleet 파라미터
│                                        - fleet_name: "pinky_fleet"
│                                        - robots: [54, 18]
│                                        - profile:
│                                            footprint: 0.08  # 반지름(m), Pinky 110mm
│                                            vicinity: 0.20
│                                        - limits:
│                                            linear: [0.3, 0.5]   # [velocity, accel]
│                                            angular: [1.0, 1.5]
├── maps/
│   ├── shop.building.yaml            ← traffic_editor 산출물 (레인 + 웨이포인트)
│   └── shop_nav_graph.yaml           ← rmf_building_map_tools 변환 결과
├── launch/
│   └── rmf_fleet.launch.py           ← RMF core + fleet adapter 통합 실행
│                                        - rmf_traffic_schedule_node
│                                        - rmf_traffic_blockade_node
│                                        - PinkyFleetAdapter 노드
├── shoppinkki_rmf/
│   ├── __init__.py
│   ├── fleet_adapter.py              ← 진입점. RobotCommandHandle × 2 생성 후 spin
│   │                                    - fleet_adapter.add_fleet("pinky_fleet", nav_graph)
│   │                                    - RobotUpdateHandle 등록 (robot_id 54, 18)
│   │                                    - /robot_<id>/status mode 변화 감지 →
│   │                                      close_lanes() / open_lanes() 호출
│   │                                      (TRACKING 진입 시 결제구역 레인 차단 등)
│   ├── robot_command_handle.py       ← RobotCommandHandle 구현체 (로봇 1대)
│   │                                    - navigate(pose, ...):
│   │                                        RMF 목표 → /robot_<id>/cmd navigate_to 변환
│   │                                        (control_service REST 경유)
│   │                                    - stop():
│   │                                        /robot_<id>/cmd mode WAITING 전송
│   │                                    - dock(dock_name, ...):
│   │                                        충전소 진입 시 enter_returning 트리거
│   │                                    - update_loop():
│   │                                        /robot_<id>/status 구독 →
│   │                                        handle.update(pose, velocity) 주기 호출
│   ├── task_dispatcher.py            ← RMF Task API 연동
│   │                                    - dispatch_navigate(robot_id, zone_id):
│   │                                        기존 control_service navigate_to를
│   │                                        RMF TaskRequest로 래핑하여 제출
│   │                                    - dispatch_dock(robot_id):
│   │                                        귀환 임무를 RMF Dock task로 제출
│   └── status_bridge.py              ← /robot_<id>/status → RMF pose 변환 브리지
│                                        - JSON status 파싱 → geometry_msgs/PoseStamped
│                                        - RobotUpdateHandle.update() 호출 (1~2Hz)
└── test/
    └── test_robot_command_handle.py  ← navigate/stop/dock mock 테스트
```

**핵심 파일:**
- `robot_command_handle.py` — RMF가 "여기로 가" 명령을 내릴 때 기존 `control_service`의 `/robot_<id>/cmd navigate_to`로 변환하는 어댑터. **기존 control_service를 그대로 재활용** — RMF 레이어는 중간에 끼어들 뿐 Pi SM·BT 구조는 변경 없음.
- `status_bridge.py` — 기존 `/robot_<id>/status` 토픽을 구독해 RMF가 요구하는 pose 업데이트를 공급. 별도 Pi 코드 수정 불필요.
- `fleet_adapter.py` — `rmf_fleet_adapter.easy_full_control()` API 사용. Nav graph + robot profile 로딩 후 두 로봇 핸들 등록.
  > ⚠️ **API 확인 필요:** `easy_full_control()`는 rmf_fleet_adapter 2.x 기준. 설치된 버전(`pip show rmf-adapter`)에서 심볼 존재 여부를 빌드 전 확인할 것.

**기존 아키텍처와의 관계:**

```
[RMF Traffic Schedule]
        │ 경로 충돌 협상
        ▼
[PinkyFleetAdapter]  ←── status_bridge (pose 업데이트)
        │ navigate(pose) / stop() / dock()
        ▼
[control_service]    ←── 기존 그대로
        │ /robot_<id>/cmd
        ▼
[Pi 5: shoppinkki_core SM + BT]  ←── 기존 그대로
```

**GUIDING 시나리오에서의 동작 변화:**

| 항목 | RMF 도입 전 | RMF 도입 후 |
|---|---|---|
| navigate_to 발행 | control_service가 직접 Pi에 전송 | task_dispatcher → RMF → FleetAdapter → control_service |
| 경로 충돌 | LiDAR 로컬 회피만 | RMF가 사전에 대기/우회 협상 |
| 충전소 슬롯 배정 | `/zone/parking/available` REST | RMF Dock task (레인 그래프 기반) |
| 상태 모니터링 | ROBOT 테이블 직접 | RMF fleet state + ROBOT 테이블 병행 |

---

## SERVER / UI 레이어 — `services/`

Non-ROS 서비스. ROS2 빌드 시스템 외부.

---

### `services/customer_web/`

Flask + SocketIO 고객 웹앱. 포트 8501.

```
customer_web/
├── app.py                        ← Flask + SocketIO 진입점 (포트 8501)
├── socket_handlers.py            ← SocketIO 이벤트 핸들러 (채널 A 수신 처리)
│                                    - mode, resume_tracking, return, navigate_to,
│                                      delete_item → control_client 중계
├── control_client.py             ← TCP 클라이언트 (채널 C, 포트 8080)
│                                    - send(cmd: dict), recv loop → SocketIO emit 중계
├── llm_client.py                 ← REST 클라이언트 (채널 D, AI Server :8000)
│                                    - query(name: str) → zone_id, zone_name
├── templates/
│   ├── login.html                ← 로그인 화면 (UR-02)
│   ├── register.html             ← 회원가입 화면
│   ├── blocked.html              ← 중복 사용 차단 화면 (UR-05)
│   ├── error.html                ← 오류 화면
│   └── main.html                 ← 단일 페이지 메인 (3-A~3-J 전체 패널)
├── static/
│   ├── js/
│   │   ├── socket.js             ← SocketIO 연결 + 이벤트 핸들러
│   │   ├── map.js                ← 맵 오버레이 Canvas 렌더링 (좌표 변환, 마커)
│   │   └── cart.js               ← 장바구니 UI 갱신 (is_paid ✓ 표시)
│   └── css/
│       └── style.css
├── tests/
│   ├── conftest.py               ← ControlClient TCP mock, _ctrl_rest mock
│   ├── test_auth_flow.py         ← 인증 플로우 테스트 (22케이스)
│   └── test_cart_feature.py      ← 장바구니 기능 테스트
└── requirements.txt              ← flask, flask-socketio, ...
```

**핵심 파일:**
- `control_client.py` — 채널 C TCP 상시 연결 유지. 수신 스레드에서 `socketio.emit()`으로 고객 앱에 push.
- `main.html` — 단일 페이지. mode에 따라 패널 전환. `docs/customer_ui.md` 화면 구성 전체 구현.

---

### `services/ai_server/`

Docker Compose. YOLO 추론 서버 + LLM 자연어 검색 서버.

```
ai_server/
├── docker-compose.yml            ← yolo + llm 서비스 정의
├── yolo/
│   ├── Dockerfile
│   ├── yolo_server.py            ← TCP:5005 YOLO 추론 서버
│   │                                - UDP 영상 프레임 수신 (채널 F)
│   │                                - YOLOv8n 추론 → bbox TCP 응답
│   │                                  {"cx": 320, "area": 12000, "confidence": 0.92}
│   ├── requirements.txt          ← ultralytics, ...
│   └── models/
│       └── doll_yolov8n.pt       ← 인형 전용 custom-trained 가중치
└── llm/
    ├── Dockerfile
    ├── llm_server.py             ← REST:8000 자연어 상품 위치 검색
    │                                - GET /query?name=콜라 → {"zone_id": 3, "zone_name": "음료 코너"}
    └── requirements.txt
```

---

## 실행 스크립트 — `scripts/`

```
scripts/
├── run_server.sh                 ← [노트북] control_service + customer_web + AI Docker tmux 세션
├── run_ui.sh                     ← [노트북] admin_ui + customer_web tmux 세션
├── run_sim.sh                    ← [노트북] Gazebo + Nav2 x2 + shoppinkki_core x2 tmux 세션
├── run_robot.sh                  ← [Pi 5] 로봇 단독 실행 (인수: 54 또는 18)
├── run_ai.sh                     ← [노트북] ai_server Docker 단독 실행
├── seed.sh                       ← DB 시딩 대화형 스크립트 (reset / replace / 기본)
├── generate_product_qr.py        ← 상품 QR 코드 이미지 생성 스크립트
├── _ros_env.sh                   ← ROS 환경변수 공통 설정 (source 용)
├── .zshrc.pinky                  ← Pi 5 전용 zshrc 설정
├── index.md                      ← 스크립트 사용법 및 tmux 세션 구성 상세
├── qr_codes/                     ← 생성된 QR 코드 PNG 이미지들
└── db/
    ├── schema.sql                ← 전체 DDL (CREATE TABLE IF NOT EXISTS)
    │                                USER, CARD, ZONE, PRODUCT, BOUNDARY_CONFIG,
    │                                ROBOT, STAFF_CALL_LOG, EVENT_LOG,
    │                                SESSION, CART, CART_ITEM
    ├── seed_data.sql             ← 기본 데이터 (ZONE, PRODUCT, BOUNDARY_CONFIG,
    │                                ROBOT #54/#18, USER test01/test02, CARD)
    ├── fill_product_embeddings.py ← 상품 임베딩 벡터 DB 삽입 스크립트
    └── README.md
```

