# 쑈삥끼 (ShopPinkki)

> **에드인에듀 자율주행 프로젝트 2팀 | 팀명: 삥끼랩**

Pinky Pro 로봇을 활용한 미니어처 마트 스마트 카트 데모 프로젝트.
고객이 스마트폰으로 로봇에 등록하면, 쑈삥끼가 마트 안에서 고객을 인식하고 따라다니며 쇼핑을 보조합니다.

---

## 프로젝트 컨텍스트

| 항목 | 내용 |
|---|---|
| 팀명 | 삥끼랩 |
| 소속 | 에드인에듀 자율주행 프로젝트 2팀 |
| 로봇 플랫폼 | Pinky Pro (by Pinklab), Raspberry Pi 5 (8GB) |
| 보유 로봇 | 2대 — Pinky #54, Pinky #18 |
| 데모 환경 | 1.4 × 1.8 m 미니어처 마트 |
| ROS 버전 | ROS 2 Jazzy / Ubuntu 24.04 |

---

## 핵심 기능

- **주인 추적** — 등록된 고객을 YOLO+ReID 또는 ArUco 마커로 인식해 졸졸 따라다님
- **앱 연동** — 스마트폰 웹앱으로 모드 전환, 장바구니 관리, 매장 지도 확인
- **물건 찾기** — 텍스트/STT로 상품을 검색하면 로봇이 해당 진열대로 안내
- **도난 감지** — 매장 경계 이탈 시 알람 발생
- **가상 결제** — 결제 구역 진입 시 장바구니 자동 결제 (데모용)
- **관제 대시보드** — PyQt 앱으로 전체 로봇 상태·위치·알람 실시간 모니터링

---

## 시스템 구성

```
스마트폰 브라우저
      ↕ WebSocket
customer_web (Flask, 포트 8501)
      ↕ TCP
control_service + admin_app (ROS2, 서버 PC)
      ↕ ROS DDS (ROS_DOMAIN_ID=14)
shoppinkki_core (ROS2, Raspberry Pi 5)
```

---

## 관련 문서

| 문서 | 내용 |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | 개발 가이드 (빌드·실행·아키텍처 상세) |
| [`docs/scaffold_plan.md`](docs/scaffold_plan.md) | 패키지 구조 및 구현 계획 |
| [`docs/scenarios/index.md`](docs/scenarios/index.md) | 시나리오 목록 (총 18개) |
| [`docs/erd.md`](docs/erd.md) | DB 스키마 |
| [`docs/state_machine.md`](docs/state_machine.md) | 로봇 State Machine |
| [`cheatsheet.md`](cheatsheet.md) | SLAM·네비게이션 명령 모음 |
