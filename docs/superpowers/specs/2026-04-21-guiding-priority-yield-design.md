# GUIDING 경로 충돌 우선권 & 선제 양보 설계

**Date:** 2026-04-21
**Status:** Design approved, pending implementation
**Supersedes:** `docs/superpowers/specs/2026-04-21-guiding-deadlock-resolution-design.md` (reactive 방식 — 본 spec의 preemptive 방식으로 대체)
**Related:**
- `server/control_service/control_service/fleet_router.py`
- `server/control_service/control_service/robot_manager.py`
- `server/control_service/map/shop_nav_graph.yaml`

## 1. 배경

ShopPinkki 매장은 **1.88×1.4m 미니어처 마트**로 통로 폭이 약 0.30m, 로봇 크기는 110×120mm다. 두 로봇이 같은 통로에서 마주치면 **옆으로 비킬 물리적 여유가 없다.**

현재 `fleet_router`는 Dijkstra에 soft penalty(예약 edge·점유 vertex)만 쓰므로, 두 GUIDING 로봇이 좁은 통로를 동시에 사용하려 하면 서로 피할 경로를 찾지 못하고 정지한다.

기존 reactive 해소 로직(`_resolve_returning_deadlock` — 5초 정지 감지 후 teleport/후진)은:
- 좁은 통로에서 양보 공간 자체가 없음
- 5초 대기 + 후진의 시간 낭비
- teleport는 시뮬 전용, 실물에 미적용

본 설계는 **경로 계획 시점(preemptive)** 에 충돌을 감지하고, **잔여거리 긴 쪽 로봇이 통로 진입 전 holding_point에서 대기**하도록 하여 좁은 통로에서도 효율적으로 다중 로봇 GUIDING을 수행한다.

## 2. 요구사항

### 기능 요구

- **FR-1**: GUIDING dispatch / 재계획 시점에 다른 로봇의 예약 경로와 충돌을 감지한다 (3가지 유형 — § 3.1).
- **FR-2**: 충돌 시 **목적지까지 잔여거리가 짧은 쪽**이 우선권(winner)을 가진다. 긴 쪽(loser)이 양보한다.
- **FR-3**: Loser는 "충돌 구간 진입 직전의 holding_point"까지의 축소 경로로 이동해 대기한다.
- **FR-4**: Loser는 매 `on_status` tick에서 충돌 해소 여부를 확인하고, 해소되면 원 목적지로 재출발한다.
- **FR-5**: 잔여거리가 동일한 경우(차이 < 0.05m) `robot_id` 사전순 앞이 winner.
- **FR-6**: 시뮬·실물 양쪽에서 동작한다. teleport 사용 없음.

### 비기능 요구

- **NFR-1**: `control_service` 서버 내에서만 처리 — Pi SM/BT, customer_web, admin_ui 수정 없음.
- **NFR-2**: Thread-safe (기존 `FleetRouter._lock`, `RobotManager._lock` 재사용).
- **NFR-3**: 기존 `_pending_navigate` 대기 큐 메커니즘을 확장해 사용 — 새로운 상태 저장소 최소화.

### 범위 밖 (YAGNI)

- Reactive fallback (winner가 오랫동안 정지 시 loser가 추가 양보 vertex로 이동) — 후속 작업
- 3대 이상 로봇 지원 — 현 시스템은 2대 한정
- Pi LCD 알림 / Customer Web 양보 토스트
- Pull-over 전용 vertex 맵 태깅 — 기존 `is_holding_point` 플래그로 충분
- Nav2 local recovery 튜닝 — 별건

## 3. 아키텍처

### 3.1 충돌의 3가지 유형

두 로봇 A, B의 예약 경로 사이 다음 중 하나라도 발생하면 **충돌**로 판정:

| 유형 | 조건 | 예시 (1열 통로) |
|---|---|---|
| **E_SHARE (tailgate)** | 같은 directed edge `(u,v)`를 둘 다 예약 | 둘 다 `25→18→19→28` |
| **E_OPPOSE (head-on)** | A가 `(u,v)`, B가 `(v,u)` 예약 | A: `25→18→19`, B: `28→19→18` |
| **V_CONVERGE** | 서로 다른 edge로 같은 **non-holding_point** intermediate vertex에 수렴 | A: `...→18`, B: `6→18` |

- 목적지 vertex 자체의 겹침은 기존 `reserve()` 내 `dest_in_edges` 로직으로 이미 차단 — 본 감지는 **중간 구간만** 다룬다.
- `holding_point`는 "여러 로봇이 대기 가능"한 지점이므로 V_CONVERGE에서 제외.

### 3.2 전체 흐름

```
[GUIDING navigate_to dispatch 또는 재계획]
      │
      ▼
router.plan → 최단 경로 후보 route_a
      │
      ▼
router.detect_conflict(route_a, robot_id) → ConflictInfo | None
      │
      ├─ None → 정상 reserve + dispatch (기존 흐름)
      │
      └─ ConflictInfo(partner, entry_idx, type)
            │
            ▼
        remaining(self) vs remaining(partner)
            │
            ├─ self가 짧음 (winner)
            │    → 원 경로 reserve + dispatch
            │    → partner에게 next tick에 yield가 일어나도록 둠
            │
            └─ self가 김 (loser)
                 → _pick_yield_vertex(route_a, entry_idx, partner_route)
                 → 축소 경로 reserve (충돌 구간 edge 미예약)
                 → 원 payload를 _pending_navigate[self]에 저장
                 → Pi에 축소 경로 dispatch
                 → _push_event('YIELD_HOLD')

[매 on_status tick, GUIDING & loser인 로봇]
      │
      ▼
_check_yield_resume:
  candidate = router.plan(loser, loser_pos, original_dest)
  if detect_conflict(candidate) is None:
      _dispatch_navigate_to(loser, original_payload)
      _pending_navigate.pop(loser)
      _push_event('YIELD_CLEAR')
```

### 3.3 신규 구조 (FleetRouter)

```python
# 로봇별 예약 경로 (vertex idx 리스트) — detect_conflict 조회용 O(1)
self._routes: dict[str, list[int]] = {}

@dataclass
class ConflictInfo:
    partner_id: str
    conflict_entry_idx: int   # route_a 내 vertex 인덱스
    conflict_exit_idx: int    # 충돌이 끝나는 vertex 인덱스 (포함)
    conflict_type: str        # 'E_SHARE' | 'E_OPPOSE' | 'V_CONVERGE'

def detect_conflict(
    self,
    route: list[dict],
    robot_id: str,
) -> Optional[ConflictInfo]:
    """route가 다른 로봇의 예약 경로와 충돌하는지 검사.

    첫 매칭된 상대만 반환 (현 시스템 2대 한정 — 3대 이상은 범위 밖).
    """
```

`reserve()` / `release()`는 `self._routes[robot_id]`도 함께 갱신.

### 3.4 신규 메서드 (RobotManager)

| 메서드 | 책임 |
|---|---|
| `_resolve_guiding_conflict(robot_id, route, payload)` | `_dispatch_navigate_to` 내부에서 호출. 충돌 감지 후 winner/loser 판정, loser면 축소 경로로 dispatch + `_pending_navigate` 보존. 반환: `(used_route, should_proceed)` — 호출자가 기존 reserve/dispatch 흐름을 이어가거나 early return 하도록 |
| `_guiding_remaining(state, route) -> float` | 현재 위치 → route polyline 길이. route가 비어있거나 1개면 `(dest_x, dest_y)`까지 직선거리 fallback |
| `_pick_yield_vertex(route, entry_idx, partner_route, partner_pos) -> Optional[dict]` | Yield point 선택 (§ 3.5). 반환: `{'x','y','name','idx'}` 또는 None |
| `_check_yield_resume(robot_id, state)` | `on_status` GUIDING tick에서 호출. 충돌 해소 시 원 payload 재dispatch |

### 3.5 Yield vertex 선택 알고리즘

목표: loser가 **충돌 구간에 진입하지 않고**, **winner의 경로 및 현 위치에서 벗어난** holding_point에서 대기.

**3단계 후보 선택:**

```
# 1차: route 위에서 entry 직전 vertex들을 역순으로 훑어 holding_point 찾기
for i in range(entry_idx - 1, -1, -1):
    v = route[i]
    if wp_by_idx[v].is_holding_point and v not in winner_route_vertices:
        return wp_by_idx[v]

# 2차: route 밖의 holding_point 중
#      - winner의 예약 경로 vertex에 포함 안 되고
#      - winner 현 위치에서 0.25m 이상 떨어진
#      - 내 현재 위치에서 가장 가까운
candidates = [
    w for w in all_waypoints
    if w.is_holding_point
    and w.idx not in winner_route_vertices
    and dist(w, winner_pos) >= 0.25
]
return nearest_to(my_pos, candidates) or None

# 3차: 후보 없음 → caller가 in-place wait로 처리
#      (축소 경로 = 빈 리스트, 예약 release, Pi에 아무 goal도 보내지 않음)
return None
```

### 3.6 재출발 (Resume)

매 `on_status` tick에서 `state.mode == 'GUIDING'` 이고 `robot_id in _pending_navigate`인 로봇에 대해 수행:

```python
def _check_yield_resume(self, robot_id, state):
    original = self._pending_navigate.get(robot_id)
    if not original: return
    if state.mode != 'GUIDING':
        # 상태가 바뀌면 대기도 취소
        self._pending_navigate.pop(robot_id, None)
        return

    # 원 목적지로 재계획 후 충돌 재검사
    wp_name = self._pick_waypoint_for_zone(robot_id, original['zone_id'])
    if not wp_name: return
    candidate = self._router.plan(
        robot_id, (state.pos_x, state.pos_y), wp_name,
        blocked_vertices=self._vertices_blocked_by_others(robot_id))
    if self._router.detect_conflict(candidate, robot_id) is None:
        self._dispatch_navigate_to(robot_id, dict(original))
        self._push_event(robot_id, 'YIELD_CLEAR',
                         detail=f'resumed to zone={original["zone_id"]}')
```

기존 `_retry_pending_navigates`와 분리해 GUIDING 전용 로직으로 둔다 (RETURNING/충전 이동 등에는 적용 안 함).

### 3.7 이벤트

| Event | 시점 | detail 예시 |
|---|---|---|
| `YIELD_HOLD` | Loser가 yield point로 축소 경로 dispatch | `yield to 54 at 1열_입구` |
| `YIELD_CLEAR` | Loser가 원 목적지로 재dispatch | `resumed to zone=22` |

기존 `_push_event(robot_id, event, detail)` 패턴 그대로 — admin_ui 이벤트 로그에 자동 노출.

## 4. 주요 플로우

### 4.1 Dispatch 시 충돌 감지 → loser 분기

`_dispatch_navigate_to` 내부의 기존 흐름:
```
1. zone_id → waypoint name
2. router.plan → route
3. reserve route
4. stagger 체크
5. _path_blocked_by 체크 (live position 기반)
6. Pi에 navigate_through_poses dispatch
```

위의 **3과 4 사이**에 `_resolve_guiding_conflict(robot_id, route, payload)`를 삽입:

```python
# GUIDING일 때만 preemptive 충돌 감지 적용
if state.mode == 'GUIDING':
    used_route, should_proceed = self._resolve_guiding_conflict(
        robot_id, route, payload)
    if not should_proceed:
        return   # loser가 축소 경로로 dispatch 완료 or in-place wait
    route = used_route  # winner면 원 route 그대로
```

### 4.2 Resume 트리거

`on_status` 내 GUIDING 분기에 한 줄 추가:

```python
if state.mode == 'GUIDING':
    try:
        self._check_yield_resume(robot_id, state)
    except Exception:
        logger.exception('guiding yield resume failed')
```

## 5. 엣지 케이스

| # | 상황 | 처리 |
|---|---|---|
| 1 | Loser에 원 경로 holding_point 없고 주변에도 없음 | 3차 in-place wait. 예약 release. 다음 tick `_check_yield_resume`에서 재계획. |
| 2 | Winner가 GUIDING 중 장시간 정지 (배터리·센서) | Conflict 계속 있으면 loser 대기 유지. **장시간 정지 시 reactive fallback은 범위 밖** — 필요 시 후속 작업. |
| 3 | Winner가 RETURNING/IDLE 전환 → 예약 해제 | 다음 tick `_check_yield_resume`가 conflict=None 판정 → 즉시 재출발. |
| 4 | Loser 원 zone의 대표 waypoint를 그 사이 다른 로봇이 점유 | 재출발 시 `_pick_waypoint_for_zone`이 대체 waypoint 자동 선택 (기존 동작). |
| 5 | 양쪽 동시 dispatch (race) | `FleetRouter._lock`으로 직렬화. 먼저 lock 잡은 쪽이 reserve 완료 → 두 번째가 `detect_conflict`에서 발견 → 잔여거리 비교. 순서 무관하게 결과 동일. |
| 6 | Loser가 이미 충돌 구간 안에 있음 (판정 늦음) | 1차 후보 없음 → 2차·3차로 폴백. Nav2 local avoidance에 위임. `logger.warning`. |
| 7 | Winner 방향 전환으로 loser가 yield point 이동 중 partner_route 갱신 | 매 tick `_check_yield_resume`이 신 `partner_route` 기준으로 재검사 → 자동 대응. 과도한 dispatch는 기존 `_STAGGER_WINDOW_S`가 억제. |
| 8 | 3대 이상 로봇 | **범위 밖**. `detect_conflict`는 첫 매칭만 반환 — 코드 주석에 명시. |
| 9 | TRACKING 로봇과 GUIDING 로봇 충돌 | TRACKING은 라우터 미사용 → 예약 경로 없음 → `detect_conflict` 대상 외. 기존 `_vertices_blocked_by_others` + Nav2 local avoidance로 대응. |
| 10 | RETURNING 로봇과 GUIDING 로봇 충돌 | RETURNING도 예약 경로 있음 → `detect_conflict` 포함. 우선권 동일 규칙(잔여거리 짧은 쪽). |

## 6. 테스트

### 6.1 Unit tests (신규)

**`test_fleet_router.py` 확장:**

1. `test_detect_conflict_no_overlap` — 서로 다른 통로 사용 시 None
2. `test_detect_conflict_e_share` — 같은 directed edge 공유 → `E_SHARE`
3. `test_detect_conflict_e_oppose` — 역방향 edge → `E_OPPOSE` (1열 head-on)
4. `test_detect_conflict_v_converge` — 서로 다른 edge로 같은 non-holding vertex 수렴 → `V_CONVERGE`
5. `test_detect_conflict_holding_point_shared_ok` — 같은 holding_point 수렴은 충돌 아님
6. `test_detect_conflict_ignores_unreserved` — 예약 경로 없는 로봇(예: TRACKING)은 대상 외

**`test_robot_manager.py` 확장:**

7. `test_guiding_winner_shorter_remaining_proceeds` — 잔여거리 짧은 쪽이 원 경로 dispatch, 긴 쪽이 `_pending_navigate`에 보존
8. `test_guiding_loser_routes_to_holding_point` — loser가 충돌 직전 holding_point로 축소 경로 reserve
9. `test_guiding_loser_no_holding_point_in_place_wait` — 후보 없으면 제자리 정지 + reserve release
10. `test_guiding_yield_clear_resumes_original_dest` — winner 통과 후 loser가 원 zone_id로 재dispatch
11. `test_guiding_tiebreaker_lexical_robot_id` — 잔여거리 동점 시 사전순 앞이 winner
12. `test_guiding_yield_emits_events` — `YIELD_HOLD`, `YIELD_CLEAR` 이벤트 순서대로 `_push_event`

### 6.2 수동 시나리오 (시뮬)

```bash
bash scripts/run_server.sh   # 터미널 A
bash scripts/run_ui.sh       # 터미널 B
bash scripts/run_sim.sh      # 터미널 C
```

**SC-NEW-1: 1열 head-on**
1. admin_ui에서 54, 18 각각 [위치 초기화]
2. customer_web `?robot_id=54` → IDLE → TRACKING → 가전제품1 선택 (GUIDING)
3. customer_web `?robot_id=18` → 거의 동시에 과자1 선택 (반대 방향)
4. 확인:
   - 잔여거리 짧은 쪽이 원 경로 유지
   - 긴 쪽이 `로비` / `1열_입구` 등에서 대기
   - admin_ui 이벤트 로그 `YIELD_HOLD` → `YIELD_CLEAR` 순서
   - 두 로봇 모두 정상 도착

**SC-NEW-2: 우선권 스왑**
- 54를 목적지 근처 미리 이동시킨 후 18과 동시에 반대 방향 GUIDING → 54가 winner 확정 검증

**SC-NEW-3: Loser 후보 없음 (3차 fallback)**
- Loser 주변 holding_point를 일부러 점유 → in-place wait 발동 로그 확인

### 6.3 실물 검증 (선택)

Pinky #54, #18로 SC-NEW-1 재현. teleport 미사용(`adjust_position_in_sim` 미호출) 로그 검증.

## 7. 영향 범위

| 파일 | 변경 |
|---|---|
| `server/control_service/control_service/fleet_router.py` | 신규: `ConflictInfo` dataclass, `detect_conflict`, `_routes` 로봇별 경로 저장. `reserve`/`release`에서 `_routes` 동기화 |
| `server/control_service/control_service/robot_manager.py` | 신규 메서드 4개 (`_resolve_guiding_conflict`, `_guiding_remaining`, `_pick_yield_vertex`, `_check_yield_resume`). `_dispatch_navigate_to` GUIDING 분기 삽입. `on_status` GUIDING tick 삽입 |
| `server/control_service/test/test_fleet_router.py` | 테스트 6개 추가 |
| `server/control_service/test/test_robot_manager.py` | 테스트 6개 추가 |
| `docs/superpowers/specs/2026-04-21-guiding-deadlock-resolution-design.md` | **삭제** (본 spec으로 supersede) |
| Pi 패키지 (`shoppinkki_core`, `shoppinkki_nav` 등) / customer_web / admin_ui | 변경 없음 |

## 8. 롤백 전략

- 기능 토글 없이, `_dispatch_navigate_to` GUIDING 분기의 `_resolve_guiding_conflict` 호출 + `on_status`의 `_check_yield_resume` 호출 2줄을 주석 처리하면 기존 동작으로 완전 복귀
- DB 스키마 변경 없음
- 상태는 모두 `RobotManager` / `FleetRouter` 메모리 내 — 재시작 시 자동 초기화
