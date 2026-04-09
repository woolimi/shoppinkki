# 시스템 요구사항 구현 체크 결과

- 원본 문서: `docs/system_requirements.md`
- 생성 시각: 2026-04-10 03:32
- 전체: 56, 완료: 18, 미완료: 38, 진행률: 32%

---

## 하드웨어 / 플랫폼

- [x] **SR-01** (UR-21) 쑈삥끼 LCD(ST7789, 2.4인치)는 터치 입력을 지원하지 않는다. 모든 사용자 조작은 웹앱을 통해 이루어진다.

## 네트워크

- [x] **SR-02** (전체) 모든 Pinky와 중앙 관제 노트북은 동일한 WiFi 네트워크(LAN)에 연결되어야 한다.
- [x] **SR-03** (전체) Pinky는 AP 모드가 아닌 클라이언트(Station) 모드로 동작하며, 기존 WiFi 네트워크에 접속한다.
- [x] **SR-04** (전체) 각 Pinky는 환경변수 `PINKY_ID`에 자신의 ID(예: `54`, `18`)를 저장한다. 모든 ROS 2 노드는 시작 시 `PINKY_ID`를 읽어 `/robot_<PINKY_ID>` 네임스페이스를 생성하고, 해당 네임스페이스 하위의 토픽·서비스로만 통신한다. 모든 ROS 2 통신은 `ROS_DOMAIN_ID=14`를 사용한다. 이를 통해 동일 네트워크의 여러 로봇을 독립적으로 제어할 수 있다.

## 계정 및 세션

- [x] **SR-05** (UR-02) 사용자 계정(ID, 비밀번호, 이름, 전화번호, 카드 정보)은 Control Center DB에 영구 보관된다. Pi 5는 계정 DB를 보유하지 않으며 로그인 흐름에 관여하지 않는다. 로그인 요청은 Customer Web → Control Device(채널 C) 경로로 처리된다.
- [x] **SR-06** (UR-04) 세션 쿠키가 유효한 경우 QR 재접속 시 로그인 및 인형 등록을 건너뛰고 메인화면으로 이동한다.
- [x] **SR-07** (UR-05, UR-06) Control Device는 로그인 요청 처리 시 해당 user_id가 다른 로봇에 이미 활성 세션으로 등록되어 있는지 확인한다. 중복 활성 세션이 존재하면 로그인을 거부한다.
- [ ] **SR-08** (UR-43) 정상 귀환(RETURNING) 시 충전소 도착(`enter_charging` 전환)과 함께 세션을 종료하고 인형 등록 데이터를 삭제한다. LOCKED 귀환의 경우 `staff_resolved` 처리 완료 후 세션을 종료한다.

## 주인 인형 인식

- [ ] **SR-09** (UR-03) 인형 탐지(YOLO 추론)는 AI Server(TCP:5005)에서 수행한다. Pi 5 카메라 프레임은 채널 H(UDP)로 Control Device에 전송되고, Control Device가 채널 F(TCP+UDP)로 AI Server에 추론을 요청한다. 탐지 결과(bbox, 클래스)는 채널 F → Control Device → 채널 G(ROS DDS) → Pi 5 순서로 전달된다.
- [x] **SR-10** (UR-03) 인형 탐지 모델은 custom-trained YOLOv8n (단일 클래스: 인형)이며 AI Server Docker 컨테이너 내에서 실행된다.
- [ ] **SR-11** (UR-03) 주인 재식별(ReID)은 Pi 5에서 로컬로 수행한다. AI Server로부터 bbox를 수신한 후 Pi 5가 보유한 ReID 특징 벡터 + HSV 색상 히스토그램(상/하의 분리) 템플릿과 비교하여 주인 인형을 식별한다.
- [ ] **SR-12** (UR-03) IDLE 상태에서 AI Server YOLO가 인형을 최초 감지하면 Pi 5가 ReID/색상 템플릿을 등록하고 `enter_tracking` 전환을 수행한다.

## 상태 머신 (SM)

- [x] **SR-13** (전체) 로봇 동작 모드는 10개 상태(CHARGING / IDLE / TRACKING / TRACKING_CHECKOUT / GUIDING / SEARCHING / WAITING / LOCKED / RETURNING / HALTED)로 정의된 State Machine으로 관리한다. (`docs/state_machine.md` 참조)
- [ ] **SR-14** (UR-14) 배터리 잔량이 임계값 이하로 떨어지면 **어떤 상태에서든** (`source='*'`) 즉시 `enter_halted` 전환을 수행하여 그 자리에서 정지한다. 앱과 LCD에 배터리 부족 알림을 표시한다.
- [ ] **SR-15** (UR-40) BoundaryMonitor가 AMCL pose 기준으로 결제 구역(ID 150) 진입을 감지하면 SM 상태는 TRACKING을 유지한 채 앱에 결제 알람 팝업을 전송하고 LCD에 결제 진행 안내 메시지를 표시한다.
- [ ] **SR-16** (UR-40a) 결제 미완료(TRACKING) 상태에서 BoundaryMonitor가 출구 방향 경계 초과를 감지하면 로봇을 정지시키고 앱에 결제 필요 알림을 표시한다. 결제 완료 후 `enter_tracking_checkout` 전환을 수행하여 출구 통과를 허용한다.
- [ ] **SR-17** (UR-40b) TRACKING_CHECKOUT 상태에서 로봇이 결제 구역 안쪽으로 복귀하면 `enter_tracking` 전환을 수행한다. Cart 테이블에서 이미 결제된 항목(`is_paid=1`)과 미결제 항목(`is_paid=0`)을 구분하여 관리하며, 다음 결제 시 미결제 항목만 결제 대상으로 처리한다.
- [ ] **SR-18** (UR-42) "보내주기" 명령 수신 시(TRACKING, TRACKING_CHECKOUT, WAITING 상태) 미결제 항목 없음 → `enter_returning`, 미결제 항목 있음 → `enter_locked` 전환을 수행한다.
- [ ] **SR-19** (UR-12) WAITING 상태에서 타임아웃 발생 시 미결제 항목 없음 → `enter_returning`, 미결제 항목 있음 → `enter_locked` 전환을 수행한다.
- [ ] **SR-20** (UR-43) RETURNING 상태에서 Nav2 Goal 성공(충전소 도착) 시 `enter_charging` 전환을 수행한다.
- [ ] **SR-21** (UR-52) 관제 강제 종료 명령(`force_terminate`) 수신 시 세션을 종료하고 CHARGING 상태로 초기화한다. Admin UI에서는 CHARGING·OFFLINE·HALTED·LOCKED 상태에서 비활성화한다. HALTED·LOCKED는 `staff_resolved` 절차를 통해 처리하며, CHARGING·OFFLINE은 활성 세션이 없으므로 강제 종료 대상이 아니다.

## 주행 / 네비게이션

- [ ] **SR-22** (UR-10) 주인 추종 주행(TRACKING / TRACKING_CHECKOUT)은 인식된 인형의 bbox 중심·크기를 기반으로 P-Control을 사용한다.
- [ ] **SR-23** (UR-10) 추종 중 장애물 회피는 RPLiDAR C1 스캔 데이터를 모니터링하여 전방 일정 거리 이내에 장애물 감지 시 속도를 감소하거나 정지하는 반응형 회피 레이어로 처리한다.
- [ ] **SR-24** (UR-11) SEARCHING 상태에서는 제자리에서 일정 각도씩 회전하며 YOLOv8n으로 인형을 탐색한다. 360° 탐색 후에도 찾지 못하면 `enter_waiting` 전환을 수행한다.
- [ ] **SR-25** (UR-13) WAITING 상태에서 RPLiDAR C1으로 근접 통행자를 감지하면 Nav2를 통해 소폭 이동하여 통행로를 확보한다.
- [ ] **SR-26** (UR-33, UR-42) GUIDING / RETURNING / LOCKED(자동 귀환) 주행은 Nav2 Waypoint Navigation을 사용한다.
- [ ] **SR-27** (UR-62) LOCKED 상태 진입 시 `on_enter_LOCKED` 콜백이 즉시 Nav2 충전 스테이션 Goal을 전송하여 자동 귀환을 시작한다.
- [ ] **SR-28** (UR-14) HALTED 상태에서는 모든 모터 출력을 즉시 0으로 설정하고 Nav2 Goal을 취소한다. 자동 전환 없음.

## LED 동작

- [ ] **SR-29** (UR-60) LED 색 결정 시 `is_locked_return` 플래그를 상태보다 우선 확인한다. `is_locked_return=True`이면 상태(RETURNING / CHARGING)에 관계없이 잠금 LED 색(빨간색 점멸)을 표시한다.
- [ ] **SR-30** (UR-62) `staff_resolved` 처리 완료 시 `is_locked_return=False`로 초기화하고 LED를 정상 충전 색으로 복귀시킨다.
- [ ] **SR-31** (—) 상태별 기본 LED 색상표 (`is_locked_return=False` 일 때 적용):

## 잠금 귀환 플래그 (is_locked_return)

- [ ] **SR-32** (UR-60) `is_locked_return` 플래그는 SM 인스턴스 변수로 관리한다. `on_enter_LOCKED` 콜백에서 `True`로 설정되며, `staff_resolved` 처리 완료 시 `False`로 초기화된다.
- [ ] **SR-33** (UR-60) `is_locked_return=True` 상태에서 RETURNING → CHARGING 전환이 발생해도 플래그는 유지된다. 정상 CHARGING과 LOCKED 귀환 후 CHARGING을 LED로 구분할 수 있다.

## HALTED / LOCKED 스태프 처리

- [ ] **SR-34** (UR-61) HALTED 상태에서는 앱과 LCD에 배터리 부족 및 스태프 호출 알림을 표시한다. 자동 전환이 없으므로 관제 대시보드에서 스태프가 `staff_resolved` 명령을 수동으로 실행해야 CHARGING 상태로 전환된다.
- [ ] **SR-35** (UR-62) LOCKED 카트가 충전 스테이션에 도착하면(`enter_charging` 전환) `is_locked_return=True` 플래그로 인해 LED가 잠금 신호(빨간색 점멸)를 유지한다. 관제 대시보드에 LOCKED 알람이 표시된다.
- [ ] **SR-36** (UR-53) 관제 대시보드에서 `staff_resolved` 명령 실행 시 `/robot_<PINKY_ID>/cmd`: `{"cmd": "staff_resolved"}` 를 Pi 5로 전송한다. Pi 5는 `is_locked_return=False` 초기화 및 세션 종료를 수행하고 CHARGING 상태를 유지한다.

## 쇼핑 리스트 / QR 스캔

- [x] **SR-37** (UR-30) 상품 QR 코드 스캔은 OpenCV `QRCodeDetector`를 사용한다.
- [x] **SR-38** (UR-30) 상품 QR 코드에는 상품명과 가격 정보가 인코딩된다.
- [x] **SR-39** (UR-30) 웹앱에서 "물건 추가" 모드를 선택하면 주인 추종을 일시 정지하고 QR 스캔 모드로 전환한다. 스캔 완료 또는 취소 시 추종을 재개한다.

## 상품 및 구역 데이터

- [x] **SR-40** (UR-32, UR-33) 상품 구역(ID 1~8) 및 특수 구역(ID 100~)의 Nav2 Waypoint 좌표는 Control Center DB에서 관리한다.
- [ ] **SR-41** (UR-32) 물건 찾기 요청 시 Customer Web이 LLM 서버(AI Server, REST :8000)에 자연어 질의하여 zone_id를 응답받아 앱에 전달한다.
- [ ] **SR-42** (UR-33) 안내 요청 흐름: Customer Web → Control Device(채널 C, `navigate_to zone_id`) → Control Device가 DB에서 waypoint 좌표를 조회 → 채널 G(ROS DDS) `/robot_<PINKY_ID>/cmd`로 Pi 5에 전달. Pi 5는 수신한 좌표로 Nav2 Goal을 전송하여 GUIDING 이동을 시작한다.
- [ ] **SR-43** (UR-40) 결제 구역(ID 150) 진입 좌표 임계값은 Control Center DB에서 관리한다.
- [ ] **SR-44** (UR-42) 귀환 목적지는 충전소 Waypoint(CHARGING 위치)를 사용한다.

## 웹앱 (Customer Web)

- [x] **SR-45** (UR-01) LCD에 표시되는 QR 코드는 Mini Server(Customer Web) 주소를 인코딩한다. IDLE 상태에서만 표시되며, 다른 상태에서는 QR 코드 대신 상태 안내 메시지가 표시된다.
- [x] **SR-46** (UR-20) Customer Web은 Control Device와 TCP(채널 C)로 연결하여 모든 로봇의 상태(위치, 모드, 배터리 잔량, is_locked_return)를 실시간으로 수신한다.
- [ ] **SR-47** (UR-20) 웹앱 맵에서 본인 로봇은 불투명 마커로, 타 로봇은 투명도를 낮춘 마커로 표시한다.
- [ ] **SR-48** (UR-32) 웹앱의 물건 찾기 STT 기능은 브라우저 Web Speech API를 사용한다.
- [ ] **SR-49** (UR-41) 결제는 등록된 카드 정보를 기반으로 가상 결제로 처리한다. 실제 결제 API 연동은 없다.

## 중앙 관제 (Control Center)

- [x] **SR-50** (UR-50) 관제 대시보드(Admin UI)는 Control Device와 TCP(채널 B)로 연결한다.
- [x] **SR-51** (UR-50) 각 Pi 5는 Control Device에 위치, 동작 모드, 배터리 잔량, `is_locked_return` 플래그를 1~2Hz 주기로 실시간 전송한다. 토픽명은 `PINKY_ID` 기반 네임스페이스를 사용한다. (예: `/robot_54/status`, `/robot_18/status`)
- [x] **SR-52** (UR-50) 관제 대시보드는 마트 맵 이미지 위에 각 로봇의 실시간 위치를 오버레이하여 표시한다.
- [ ] **SR-53** (UR-51) HALTED / LOCKED 이벤트 발생 시 `/robot_<PINKY_ID>/alarm` ROS 토픽으로 Control Device에 즉시 전송하고 관제 대시보드에 알람을 표시하며 로그에 기록한다.
- [ ] **SR-54** (UR-52) 관제 강제 종료는 Admin UI → Control Device(채널 B) → `/robot_<PINKY_ID>/cmd`: `{"cmd": "force_terminate"}` 경로로 전달된다.
- [ ] **SR-55** (UR-53) 스태프 처리는 Admin UI → Control Device(채널 B) → `/robot_<PINKY_ID>/cmd`: `{"cmd": "staff_resolved"}` 경로로 전달된다.

## 배터리

- [ ] **SR-56** (UR-14) 배터리 잔량은 pinkylib API를 통해 주기적으로 읽는다. 잔량이 임계값(기본 20%) 이하로 떨어지면 현재 상태에 관계없이 `enter_halted` 전환을 수행한다(`source='*'`). 앱·LCD에 배터리 부족 알림을 표시한다.

---

## 원본 문서

```md
# 시스템 요구사항 구현 체크 결과

- 원본 문서: `docs/system_requirements.md`
- 생성 시각: 2026-04-10 03:28
- 전체: 56, 완료: 18, 미완료: 38, 진행률: 32%

---

## 하드웨어 / 플랫폼

- [x] **SR-01** (UR-21) 쑈삥끼 LCD(ST7789, 2.4인치)는 터치 입력을 지원하지 않는다. 모든 사용자 조작은 웹앱을 통해 이루어진다.

## 네트워크

- [x] **SR-02** (전체) 모든 Pinky와 중앙 관제 노트북은 동일한 WiFi 네트워크(LAN)에 연결되어야 한다.
- [x] **SR-03** (전체) Pinky는 AP 모드가 아닌 클라이언트(Station) 모드로 동작하며, 기존 WiFi 네트워크에 접속한다.
- [x] **SR-04** (전체) 각 Pinky는 환경변수 `PINKY_ID`에 자신의 ID(예: `54`, `18`)를 저장한다. 모든 ROS 2 노드는 시작 시 `PINKY_ID`를 읽어 `/robot_<PINKY_ID>` 네임스페이스를 생성하고, 해당 네임스페이스 하위의 토픽·서비스로만 통신한다. 모든 ROS 2 통신은 `ROS_DOMAIN_ID=14`를 사용한다. 이를 통해 동일 네트워크의 여러 로봇을 독립적으로 제어할 수 있다.

## 계정 및 세션

- [x] **SR-05** (UR-02) 사용자 계정(ID, 비밀번호, 이름, 전화번호, 카드 정보)은 Control Center DB에 영구 보관된다. Pi 5는 계정 DB를 보유하지 않으며 로그인 흐름에 관여하지 않는다. 로그인 요청은 Customer Web → Control Device(채널 C) 경로로 처리된다.
- [x] **SR-06** (UR-04) 세션 쿠키가 유효한 경우 QR 재접속 시 로그인 및 인형 등록을 건너뛰고 메인화면으로 이동한다.
- [x] **SR-07** (UR-05, UR-06) Control Device는 로그인 요청 처리 시 해당 user_id가 다른 로봇에 이미 활성 세션으로 등록되어 있는지 확인한다. 중복 활성 세션이 존재하면 로그인을 거부한다.
- [ ] **SR-08** (UR-43) 정상 귀환(RETURNING) 시 충전소 도착(`enter_charging` 전환)과 함께 세션을 종료하고 인형 등록 데이터를 삭제한다. LOCKED 귀환의 경우 `staff_resolved` 처리 완료 후 세션을 종료한다.

## 주인 인형 인식

- [ ] **SR-09** (UR-03) 인형 탐지(YOLO 추론)는 AI Server(TCP:5005)에서 수행한다. Pi 5 카메라 프레임은 채널 H(UDP)로 Control Device에 전송되고, Control Device가 채널 F(TCP+UDP)로 AI Server에 추론을 요청한다. 탐지 결과(bbox, 클래스)는 채널 F → Control Device → 채널 G(ROS DDS) → Pi 5 순서로 전달된다.
- [x] **SR-10** (UR-03) 인형 탐지 모델은 custom-trained YOLOv8n (단일 클래스: 인형)이며 AI Server Docker 컨테이너 내에서 실행된다.
- [ ] **SR-11** (UR-03) 주인 재식별(ReID)은 Pi 5에서 로컬로 수행한다. AI Server로부터 bbox를 수신한 후 Pi 5가 보유한 ReID 특징 벡터 + HSV 색상 히스토그램(상/하의 분리) 템플릿과 비교하여 주인 인형을 식별한다.
- [ ] **SR-12** (UR-03) IDLE 상태에서 AI Server YOLO가 인형을 최초 감지하면 Pi 5가 ReID/색상 템플릿을 등록하고 `enter_tracking` 전환을 수행한다.

## 상태 머신 (SM)

- [x] **SR-13** (전체) 로봇 동작 모드는 10개 상태(CHARGING / IDLE / TRACKING / TRACKING_CHECKOUT / GUIDING / SEARCHING / WAITING / LOCKED / RETURNING / HALTED)로 정의된 State Machine으로 관리한다. (`docs/state_machine.md` 참조)
- [ ] **SR-14** (UR-14) 배터리 잔량이 임계값 이하로 떨어지면 **어떤 상태에서든** (`source='*'`) 즉시 `enter_halted` 전환을 수행하여 그 자리에서 정지한다. 앱과 LCD에 배터리 부족 알림을 표시한다.
- [ ] **SR-15** (UR-40) BoundaryMonitor가 AMCL pose 기준으로 결제 구역(ID 150) 진입을 감지하면 SM 상태는 TRACKING을 유지한 채 앱에 결제 알람 팝업을 전송하고 LCD에 결제 진행 안내 메시지를 표시한다.
- [ ] **SR-16** (UR-40a) 결제 미완료(TRACKING) 상태에서 BoundaryMonitor가 출구 방향 경계 초과를 감지하면 로봇을 정지시키고 앱에 결제 필요 알림을 표시한다. 결제 완료 후 `enter_tracking_checkout` 전환을 수행하여 출구 통과를 허용한다.
- [ ] **SR-17** (UR-40b) TRACKING_CHECKOUT 상태에서 로봇이 결제 구역 안쪽으로 복귀하면 `enter_tracking` 전환을 수행한다. Cart 테이블에서 이미 결제된 항목(`is_paid=1`)과 미결제 항목(`is_paid=0`)을 구분하여 관리하며, 다음 결제 시 미결제 항목만 결제 대상으로 처리한다.
- [ ] **SR-18** (UR-42) "보내주기" 명령 수신 시(TRACKING, TRACKING_CHECKOUT, WAITING 상태) 미결제 항목 없음 → `enter_returning`, 미결제 항목 있음 → `enter_locked` 전환을 수행한다.
- [ ] **SR-19** (UR-12) WAITING 상태에서 타임아웃 발생 시 미결제 항목 없음 → `enter_returning`, 미결제 항목 있음 → `enter_locked` 전환을 수행한다.
- [ ] **SR-20** (UR-43) RETURNING 상태에서 Nav2 Goal 성공(충전소 도착) 시 `enter_charging` 전환을 수행한다.
- [ ] **SR-21** (UR-52) 관제 강제 종료 명령(`force_terminate`) 수신 시 세션을 종료하고 CHARGING 상태로 초기화한다. Admin UI에서는 CHARGING·OFFLINE·HALTED·LOCKED 상태에서 비활성화한다. HALTED·LOCKED는 `staff_resolved` 절차를 통해 처리하며, CHARGING·OFFLINE은 활성 세션이 없으므로 강제 종료 대상이 아니다.

## 주행 / 네비게이션

- [ ] **SR-22** (UR-10) 주인 추종 주행(TRACKING / TRACKING_CHECKOUT)은 인식된 인형의 bbox 중심·크기를 기반으로 P-Control을 사용한다.
- [ ] **SR-23** (UR-10) 추종 중 장애물 회피는 RPLiDAR C1 스캔 데이터를 모니터링하여 전방 일정 거리 이내에 장애물 감지 시 속도를 감소하거나 정지하는 반응형 회피 레이어로 처리한다.
- [ ] **SR-24** (UR-11) SEARCHING 상태에서는 제자리에서 일정 각도씩 회전하며 YOLOv8n으로 인형을 탐색한다. 360° 탐색 후에도 찾지 못하면 `enter_waiting` 전환을 수행한다.
- [ ] **SR-25** (UR-13) WAITING 상태에서 RPLiDAR C1으로 근접 통행자를 감지하면 Nav2를 통해 소폭 이동하여 통행로를 확보한다.
- [ ] **SR-26** (UR-33, UR-42) GUIDING / RETURNING / LOCKED(자동 귀환) 주행은 Nav2 Waypoint Navigation을 사용한다.
- [ ] **SR-27** (UR-62) LOCKED 상태 진입 시 `on_enter_LOCKED` 콜백이 즉시 Nav2 충전 스테이션 Goal을 전송하여 자동 귀환을 시작한다.
- [ ] **SR-28** (UR-14) HALTED 상태에서는 모든 모터 출력을 즉시 0으로 설정하고 Nav2 Goal을 취소한다. 자동 전환 없음.

## LED 동작

- [ ] **SR-29** (UR-60) LED 색 결정 시 `is_locked_return` 플래그를 상태보다 우선 확인한다. `is_locked_return=True`이면 상태(RETURNING / CHARGING)에 관계없이 잠금 LED 색(빨간색 점멸)을 표시한다.
- [ ] **SR-30** (UR-62) `staff_resolved` 처리 완료 시 `is_locked_return=False`로 초기화하고 LED를 정상 충전 색으로 복귀시킨다.
- [ ] **SR-31** (—) 상태별 기본 LED 색상표 (`is_locked_return=False` 일 때 적용):

## 잠금 귀환 플래그 (is_locked_return)

- [ ] **SR-32** (UR-60) `is_locked_return` 플래그는 SM 인스턴스 변수로 관리한다. `on_enter_LOCKED` 콜백에서 `True`로 설정되며, `staff_resolved` 처리 완료 시 `False`로 초기화된다.
- [ ] **SR-33** (UR-60) `is_locked_return=True` 상태에서 RETURNING → CHARGING 전환이 발생해도 플래그는 유지된다. 정상 CHARGING과 LOCKED 귀환 후 CHARGING을 LED로 구분할 수 있다.

## HALTED / LOCKED 스태프 처리

- [ ] **SR-34** (UR-61) HALTED 상태에서는 앱과 LCD에 배터리 부족 및 스태프 호출 알림을 표시한다. 자동 전환이 없으므로 관제 대시보드에서 스태프가 `staff_resolved` 명령을 수동으로 실행해야 CHARGING 상태로 전환된다.
- [ ] **SR-35** (UR-62) LOCKED 카트가 충전 스테이션에 도착하면(`enter_charging` 전환) `is_locked_return=True` 플래그로 인해 LED가 잠금 신호(빨간색 점멸)를 유지한다. 관제 대시보드에 LOCKED 알람이 표시된다.
- [ ] **SR-36** (UR-53) 관제 대시보드에서 `staff_resolved` 명령 실행 시 `/robot_<PINKY_ID>/cmd`: `{"cmd": "staff_resolved"}` 를 Pi 5로 전송한다. Pi 5는 `is_locked_return=False` 초기화 및 세션 종료를 수행하고 CHARGING 상태를 유지한다.

## 쇼핑 리스트 / QR 스캔

- [x] **SR-37** (UR-30) 상품 QR 코드 스캔은 OpenCV `QRCodeDetector`를 사용한다.
- [x] **SR-38** (UR-30) 상품 QR 코드에는 상품명과 가격 정보가 인코딩된다.
- [x] **SR-39** (UR-30) 웹앱에서 "물건 추가" 모드를 선택하면 주인 추종을 일시 정지하고 QR 스캔 모드로 전환한다. 스캔 완료 또는 취소 시 추종을 재개한다.

## 상품 및 구역 데이터

- [x] **SR-40** (UR-32, UR-33) 상품 구역(ID 1~8) 및 특수 구역(ID 100~)의 Nav2 Waypoint 좌표는 Control Center DB에서 관리한다.
- [ ] **SR-41** (UR-32) 물건 찾기 요청 시 Customer Web이 LLM 서버(AI Server, REST :8000)에 자연어 질의하여 zone_id를 응답받아 앱에 전달한다.
- [ ] **SR-42** (UR-33) 안내 요청 흐름: Customer Web → Control Device(채널 C, `navigate_to zone_id`) → Control Device가 DB에서 waypoint 좌표를 조회 → 채널 G(ROS DDS) `/robot_<PINKY_ID>/cmd`로 Pi 5에 전달. Pi 5는 수신한 좌표로 Nav2 Goal을 전송하여 GUIDING 이동을 시작한다.
- [ ] **SR-43** (UR-40) 결제 구역(ID 150) 진입 좌표 임계값은 Control Center DB에서 관리한다.
- [ ] **SR-44** (UR-42) 귀환 목적지는 충전소 Waypoint(CHARGING 위치)를 사용한다.

## 웹앱 (Customer Web)

- [x] **SR-45** (UR-01) LCD에 표시되는 QR 코드는 Mini Server(Customer Web) 주소를 인코딩한다. IDLE 상태에서만 표시되며, 다른 상태에서는 QR 코드 대신 상태 안내 메시지가 표시된다.
- [x] **SR-46** (UR-20) Customer Web은 Control Device와 TCP(채널 C)로 연결하여 모든 로봇의 상태(위치, 모드, 배터리 잔량, is_locked_return)를 실시간으로 수신한다.
- [ ] **SR-47** (UR-20) 웹앱 맵에서 본인 로봇은 불투명 마커로, 타 로봇은 투명도를 낮춘 마커로 표시한다.
- [ ] **SR-48** (UR-32) 웹앱의 물건 찾기 STT 기능은 브라우저 Web Speech API를 사용한다.
- [ ] **SR-49** (UR-41) 결제는 등록된 카드 정보를 기반으로 가상 결제로 처리한다. 실제 결제 API 연동은 없다.

## 중앙 관제 (Control Center)

- [x] **SR-50** (UR-50) 관제 대시보드(Admin UI)는 Control Device와 TCP(채널 B)로 연결한다.
- [x] **SR-51** (UR-50) 각 Pi 5는 Control Device에 위치, 동작 모드, 배터리 잔량, `is_locked_return` 플래그를 1~2Hz 주기로 실시간 전송한다. 토픽명은 `PINKY_ID` 기반 네임스페이스를 사용한다. (예: `/robot_54/status`, `/robot_18/status`)
- [x] **SR-52** (UR-50) 관제 대시보드는 마트 맵 이미지 위에 각 로봇의 실시간 위치를 오버레이하여 표시한다.
- [ ] **SR-53** (UR-51) HALTED / LOCKED 이벤트 발생 시 `/robot_<PINKY_ID>/alarm` ROS 토픽으로 Control Device에 즉시 전송하고 관제 대시보드에 알람을 표시하며 로그에 기록한다.
- [ ] **SR-54** (UR-52) 관제 강제 종료는 Admin UI → Control Device(채널 B) → `/robot_<PINKY_ID>/cmd`: `{"cmd": "force_terminate"}` 경로로 전달된다.
- [ ] **SR-55** (UR-53) 스태프 처리는 Admin UI → Control Device(채널 B) → `/robot_<PINKY_ID>/cmd`: `{"cmd": "staff_resolved"}` 경로로 전달된다.

## 배터리

- [ ] **SR-56** (UR-14) 배터리 잔량은 pinkylib API를 통해 주기적으로 읽는다. 잔량이 임계값(기본 20%) 이하로 떨어지면 현재 상태에 관계없이 `enter_halted` 전환을 수행한다(`source='*'`). 앱·LCD에 배터리 부족 알림을 표시한다.

---

## 원본 문서

```md
# 시스템 요구사항 (System Requirements)

> **프로젝트:** 쑈삥끼 (ShopPinkki)
> **팀:** 삥끼랩 | 에드인에듀 자율주행 프로젝트 2팀

시스템 요구사항은 사용자 요구사항(UR)을 시스템이 어떻게 구현하는지를 정의합니다.

---

## SR 테이블

### 하드웨어 / 플랫폼

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-01 | UR-21 | 쑈삥끼 LCD(ST7789, 2.4인치)는 터치 입력을 지원하지 않는다. 모든 사용자 조작은 웹앱을 통해 이루어진다. |

### 네트워크

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-02 | 전체 | 모든 Pinky와 중앙 관제 노트북은 동일한 WiFi 네트워크(LAN)에 연결되어야 한다. |
| SR-03 | 전체 | Pinky는 AP 모드가 아닌 클라이언트(Station) 모드로 동작하며, 기존 WiFi 네트워크에 접속한다. |
| SR-04 | 전체 | 각 Pinky는 환경변수 `PINKY_ID`에 자신의 ID(예: `54`, `18`)를 저장한다. 모든 ROS 2 노드는 시작 시 `PINKY_ID`를 읽어 `/robot_<PINKY_ID>` 네임스페이스를 생성하고, 해당 네임스페이스 하위의 토픽·서비스로만 통신한다. 모든 ROS 2 통신은 `ROS_DOMAIN_ID=14`를 사용한다. 이를 통해 동일 네트워크의 여러 로봇을 독립적으로 제어할 수 있다. |

### 계정 및 세션

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-05 | UR-02 | 사용자 계정(ID, 비밀번호, 이름, 전화번호, 카드 정보)은 Control Center DB에 영구 보관된다. Pi 5는 계정 DB를 보유하지 않으며 로그인 흐름에 관여하지 않는다. 로그인 요청은 Customer Web → Control Device(채널 C) 경로로 처리된다. |
| SR-06 | UR-04 | 세션 쿠키가 유효한 경우 QR 재접속 시 로그인 및 인형 등록을 건너뛰고 메인화면으로 이동한다. |
| SR-07 | UR-05, UR-06 | Control Device는 로그인 요청 처리 시 해당 user_id가 다른 로봇에 이미 활성 세션으로 등록되어 있는지 확인한다. 중복 활성 세션이 존재하면 로그인을 거부한다. |
| SR-08 | UR-43 | 정상 귀환(RETURNING) 시 충전소 도착(`enter_charging` 전환)과 함께 세션을 종료하고 인형 등록 데이터를 삭제한다. LOCKED 귀환의 경우 `staff_resolved` 처리 완료 후 세션을 종료한다. |

### 주인 인형 인식

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-09 | UR-03 | 인형 탐지(YOLO 추론)는 AI Server(TCP:5005)에서 수행한다. Pi 5 카메라 프레임은 채널 H(UDP)로 Control Device에 전송되고, Control Device가 채널 F(TCP+UDP)로 AI Server에 추론을 요청한다. 탐지 결과(bbox, 클래스)는 채널 F → Control Device → 채널 G(ROS DDS) → Pi 5 순서로 전달된다. |
| SR-10 | UR-03 | 인형 탐지 모델은 custom-trained YOLOv8n (단일 클래스: 인형)이며 AI Server Docker 컨테이너 내에서 실행된다. |
| SR-11 | UR-03 | 주인 재식별(ReID)은 Pi 5에서 로컬로 수행한다. AI Server로부터 bbox를 수신한 후 Pi 5가 보유한 ReID 특징 벡터 + HSV 색상 히스토그램(상/하의 분리) 템플릿과 비교하여 주인 인형을 식별한다. |
| SR-12 | UR-03 | IDLE 상태에서 AI Server YOLO가 인형을 최초 감지하면 Pi 5가 ReID/색상 템플릿을 등록하고 `enter_tracking` 전환을 수행한다. |

### 상태 머신 (SM)

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-13 | 전체 | 로봇 동작 모드는 10개 상태(CHARGING / IDLE / TRACKING / TRACKING_CHECKOUT / GUIDING / SEARCHING / WAITING / LOCKED / RETURNING / HALTED)로 정의된 State Machine으로 관리한다. (`docs/state_machine.md` 참조) |
| SR-14 | UR-14 | 배터리 잔량이 임계값 이하로 떨어지면 **어떤 상태에서든** (`source='*'`) 즉시 `enter_halted` 전환을 수행하여 그 자리에서 정지한다. 앱과 LCD에 배터리 부족 알림을 표시한다. |
| SR-15 | UR-40 | BoundaryMonitor가 AMCL pose 기준으로 결제 구역(ID 150) 진입을 감지하면 SM 상태는 TRACKING을 유지한 채 앱에 결제 알람 팝업을 전송하고 LCD에 결제 진행 안내 메시지를 표시한다. |
| SR-16 | UR-40a | 결제 미완료(TRACKING) 상태에서 BoundaryMonitor가 출구 방향 경계 초과를 감지하면 로봇을 정지시키고 앱에 결제 필요 알림을 표시한다. 결제 완료 후 `enter_tracking_checkout` 전환을 수행하여 출구 통과를 허용한다. |
| SR-17 | UR-40b | TRACKING_CHECKOUT 상태에서 로봇이 결제 구역 안쪽으로 복귀하면 `enter_tracking` 전환을 수행한다. Cart 테이블에서 이미 결제된 항목(`is_paid=1`)과 미결제 항목(`is_paid=0`)을 구분하여 관리하며, 다음 결제 시 미결제 항목만 결제 대상으로 처리한다. |
| SR-18 | UR-42 | "보내주기" 명령 수신 시(TRACKING, TRACKING_CHECKOUT, WAITING 상태) 미결제 항목 없음 → `enter_returning`, 미결제 항목 있음 → `enter_locked` 전환을 수행한다. |
| SR-19 | UR-12 | WAITING 상태에서 타임아웃 발생 시 미결제 항목 없음 → `enter_returning`, 미결제 항목 있음 → `enter_locked` 전환을 수행한다. |
| SR-20 | UR-43 | RETURNING 상태에서 Nav2 Goal 성공(충전소 도착) 시 `enter_charging` 전환을 수행한다. |
| SR-21 | UR-52 | 관제 강제 종료 명령(`force_terminate`) 수신 시 세션을 종료하고 CHARGING 상태로 초기화한다. Admin UI에서는 CHARGING·OFFLINE·HALTED·LOCKED 상태에서 비활성화한다. HALTED·LOCKED는 `staff_resolved` 절차를 통해 처리하며, CHARGING·OFFLINE은 활성 세션이 없으므로 강제 종료 대상이 아니다. |

### 주행 / 네비게이션

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-22 | UR-10 | 주인 추종 주행(TRACKING / TRACKING_CHECKOUT)은 인식된 인형의 bbox 중심·크기를 기반으로 P-Control을 사용한다. |
| SR-23 | UR-10 | 추종 중 장애물 회피는 RPLiDAR C1 스캔 데이터를 모니터링하여 전방 일정 거리 이내에 장애물 감지 시 속도를 감소하거나 정지하는 반응형 회피 레이어로 처리한다. |
| SR-24 | UR-11 | SEARCHING 상태에서는 제자리에서 일정 각도씩 회전하며 YOLOv8n으로 인형을 탐색한다. 360° 탐색 후에도 찾지 못하면 `enter_waiting` 전환을 수행한다. |
| SR-25 | UR-13 | WAITING 상태에서 RPLiDAR C1으로 근접 통행자를 감지하면 Nav2를 통해 소폭 이동하여 통행로를 확보한다. |
| SR-26 | UR-33, UR-42 | GUIDING / RETURNING / LOCKED(자동 귀환) 주행은 Nav2 Waypoint Navigation을 사용한다. |
| SR-27 | UR-62 | LOCKED 상태 진입 시 `on_enter_LOCKED` 콜백이 즉시 Nav2 충전 스테이션 Goal을 전송하여 자동 귀환을 시작한다. |
| SR-28 | UR-14 | HALTED 상태에서는 모든 모터 출력을 즉시 0으로 설정하고 Nav2 Goal을 취소한다. 자동 전환 없음. |

### LED 동작

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-29 | UR-60 | LED 색 결정 시 `is_locked_return` 플래그를 상태보다 우선 확인한다. `is_locked_return=True`이면 상태(RETURNING / CHARGING)에 관계없이 잠금 LED 색(빨간색 점멸)을 표시한다. |
| SR-30 | UR-62 | `staff_resolved` 처리 완료 시 `is_locked_return=False`로 초기화하고 LED를 정상 충전 색으로 복귀시킨다. |
| SR-31 | — | 상태별 기본 LED 색상표 (`is_locked_return=False` 일 때 적용): |

**SR-31 상태별 LED 색상표:**

| 상태 | LED 색 |
|---|---|
| `CHARGING` | 빨간색 (충전 중) |
| `IDLE` | 파란색 점멸 (등록 대기) |
| `TRACKING` | 초록색 |
| `TRACKING_CHECKOUT` | 초록색 (TRACKING과 동일) |
| `GUIDING` | 노란색 |
| `SEARCHING` | 주황색 |
| `WAITING` | 파란색 |
| `LOCKED` | 빨간색 점멸 (잠금 신호) |
| `RETURNING` | 보라색 |
| `HALTED` | 흰색 점멸 (배터리 부족, 스태프 호출) |

### 잠금 귀환 플래그 (is_locked_return)

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-32 | UR-60 | `is_locked_return` 플래그는 SM 인스턴스 변수로 관리한다. `on_enter_LOCKED` 콜백에서 `True`로 설정되며, `staff_resolved` 처리 완료 시 `False`로 초기화된다. |
| SR-33 | UR-60 | `is_locked_return=True` 상태에서 RETURNING → CHARGING 전환이 발생해도 플래그는 유지된다. 정상 CHARGING과 LOCKED 귀환 후 CHARGING을 LED로 구분할 수 있다. |

### HALTED / LOCKED 스태프 처리

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-34 | UR-61 | HALTED 상태에서는 앱과 LCD에 배터리 부족 및 스태프 호출 알림을 표시한다. 자동 전환이 없으므로 관제 대시보드에서 스태프가 `staff_resolved` 명령을 수동으로 실행해야 CHARGING 상태로 전환된다. |
| SR-35 | UR-62 | LOCKED 카트가 충전 스테이션에 도착하면(`enter_charging` 전환) `is_locked_return=True` 플래그로 인해 LED가 잠금 신호(빨간색 점멸)를 유지한다. 관제 대시보드에 LOCKED 알람이 표시된다. |
| SR-36 | UR-53 | 관제 대시보드에서 `staff_resolved` 명령 실행 시 `/robot_<PINKY_ID>/cmd`: `{"cmd": "staff_resolved"}` 를 Pi 5로 전송한다. Pi 5는 `is_locked_return=False` 초기화 및 세션 종료를 수행하고 CHARGING 상태를 유지한다. |

### 쇼핑 리스트 / QR 스캔

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-37 | UR-30 | 상품 QR 코드 스캔은 OpenCV `QRCodeDetector`를 사용한다. |
| SR-38 | UR-30 | 상품 QR 코드에는 상품명과 가격 정보가 인코딩된다. |
| SR-39 | UR-30 | 웹앱에서 "물건 추가" 모드를 선택하면 주인 추종을 일시 정지하고 QR 스캔 모드로 전환한다. 스캔 완료 또는 취소 시 추종을 재개한다. |

### 상품 및 구역 데이터

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-40 | UR-32, UR-33 | 상품 구역(ID 1~8) 및 특수 구역(ID 100~)의 Nav2 Waypoint 좌표는 Control Center DB에서 관리한다. |
| SR-41 | UR-32 | 물건 찾기 요청 시 Customer Web이 LLM 서버(AI Server, REST :8000)에 자연어 질의하여 zone_id를 응답받아 앱에 전달한다. |
| SR-42 | UR-33 | 안내 요청 흐름: Customer Web → Control Device(채널 C, `navigate_to zone_id`) → Control Device가 DB에서 waypoint 좌표를 조회 → 채널 G(ROS DDS) `/robot_<PINKY_ID>/cmd`로 Pi 5에 전달. Pi 5는 수신한 좌표로 Nav2 Goal을 전송하여 GUIDING 이동을 시작한다. |
| SR-43 | UR-40 | 결제 구역(ID 150) 진입 좌표 임계값은 Control Center DB에서 관리한다. |
| SR-44 | UR-42 | 귀환 목적지는 충전소 Waypoint(CHARGING 위치)를 사용한다. |

### 웹앱 (Customer Web)

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-45 | UR-01 | LCD에 표시되는 QR 코드는 Mini Server(Customer Web) 주소를 인코딩한다. IDLE 상태에서만 표시되며, 다른 상태에서는 QR 코드 대신 상태 안내 메시지가 표시된다. |
| SR-46 | UR-20 | Customer Web은 Control Device와 TCP(채널 C)로 연결하여 모든 로봇의 상태(위치, 모드, 배터리 잔량, is_locked_return)를 실시간으로 수신한다. |
| SR-47 | UR-20 | 웹앱 맵에서 본인 로봇은 불투명 마커로, 타 로봇은 투명도를 낮춘 마커로 표시한다. |
| SR-48 | UR-32 | 웹앱의 물건 찾기 STT 기능은 브라우저 Web Speech API를 사용한다. |
| SR-49 | UR-41 | 결제는 등록된 카드 정보를 기반으로 가상 결제로 처리한다. 실제 결제 API 연동은 없다. |

### 중앙 관제 (Control Center)

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-50 | UR-50 | 관제 대시보드(Admin UI)는 Control Device와 TCP(채널 B)로 연결한다. |
| SR-51 | UR-50 | 각 Pi 5는 Control Device에 위치, 동작 모드, 배터리 잔량, `is_locked_return` 플래그를 1~2Hz 주기로 실시간 전송한다. 토픽명은 `PINKY_ID` 기반 네임스페이스를 사용한다. (예: `/robot_54/status`, `/robot_18/status`) |
| SR-52 | UR-50 | 관제 대시보드는 마트 맵 이미지 위에 각 로봇의 실시간 위치를 오버레이하여 표시한다. |
| SR-53 | UR-51 | HALTED / LOCKED 이벤트 발생 시 `/robot_<PINKY_ID>/alarm` ROS 토픽으로 Control Device에 즉시 전송하고 관제 대시보드에 알람을 표시하며 로그에 기록한다. |
| SR-54 | UR-52 | 관제 강제 종료는 Admin UI → Control Device(채널 B) → `/robot_<PINKY_ID>/cmd`: `{"cmd": "force_terminate"}` 경로로 전달된다. |
| SR-55 | UR-53 | 스태프 처리는 Admin UI → Control Device(채널 B) → `/robot_<PINKY_ID>/cmd`: `{"cmd": "staff_resolved"}` 경로로 전달된다. |

### 배터리

| SR ID | 연관 UR | Description |
|---|---|---|
| SR-56 | UR-14 | 배터리 잔량은 pinkylib API를 통해 주기적으로 읽는다. 잔량이 임계값(기본 20%) 이하로 떨어지면 현재 상태에 관계없이 `enter_halted` 전환을 수행한다(`source='*'`). 앱·LCD에 배터리 부족 알림을 표시한다. |
```
```
