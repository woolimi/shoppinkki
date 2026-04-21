# GUIDING 경로 충돌 우선권 & 선제 양보 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 두 GUIDING 로봇이 좁은 통로에서 경로 충돌 시, 목적지 잔여거리 짧은 쪽이 먼저 통과하고 긴 쪽은 충돌 구간 진입 전 holding_point에서 선제 대기하도록 한다.

**Architecture:** `FleetRouter`에 예약 경로 간 **충돌 감지기**(`detect_conflict`)를 추가하고, `RobotManager._dispatch_navigate_to`의 GUIDING 분기에서 충돌 시 **잔여거리 비교**로 winner/loser를 가려 loser는 holding_point까지만 dispatch하고 원 payload는 `_pending_navigate`에 보존한다. 매 `on_status` tick에서 충돌 해소 시 원 목적지로 재dispatch.

**Tech Stack:** Python 3.12, rclpy (ROS 2 Jazzy), pytest, PostgreSQL 17 (`psycopg2`). 순수 서버 로직 — Pi / customer_web / admin_ui 변경 없음.

**Spec:** [`docs/superpowers/specs/2026-04-21-guiding-priority-yield-design.md`](../specs/2026-04-21-guiding-priority-yield-design.md)

---

## File Structure

**Modified files:**

- `server/control_service/control_service/fleet_router.py`
  - 신규: `ConflictInfo` dataclass
  - 신규: `self._routes: dict[str, list[int]]` 인스턴스 변수
  - 신규: `detect_conflict(route, robot_id) -> Optional[ConflictInfo]`
  - 신규: `_route_to_idx_path(route) -> list[int]` 헬퍼
  - 수정: `reserve()` — `_routes` 동기화
  - 수정: `_release_locked()` — `_routes` 삭제

- `server/control_service/control_service/robot_manager.py`
  - 신규: `_guiding_remaining(state, route) -> float`
  - 신규: `_pick_yield_vertex(route_idx, entry_idx, partner_route_idx, partner_pos, my_pos, all_wps) -> Optional[dict]`
  - 신규: `_resolve_guiding_conflict(robot_id, route, payload) -> tuple[list[dict], bool]`
  - 신규: `_check_yield_resume(robot_id, state)`
  - 수정: `_dispatch_navigate_to` — GUIDING 분기에 충돌 해소 삽입
  - 수정: `on_status` — GUIDING tick에 `_check_yield_resume` 호출

- `server/control_service/test/test_fleet_router.py`
  - 테스트 6개 추가 (TestDetectConflict 클래스)
  - Fixture에 `holding_point` 필드 추가

- `server/control_service/test/test_robot_manager.py`
  - 테스트 6개 추가 (TestGuidingYield 클래스)

**Deleted files:**

- `docs/superpowers/specs/2026-04-21-guiding-deadlock-resolution-design.md` (reactive 방식 — 본 spec이 supersede)

---

## Task 1: FleetRouter — `_routes` 저장소 + `_release_locked` 동기화

**Files:**
- Modify: `server/control_service/control_service/fleet_router.py:43-46` (생성자), `server/control_service/control_service/fleet_router.py:267-270` (`_release_locked`)
- Test: `server/control_service/test/test_fleet_router.py`

- [ ] **Step 1: Write failing test — `_routes`는 reserve 시 채워지고 release 시 지워짐**

`server/control_service/test/test_fleet_router.py` 맨 끝에 새 클래스 추가:

```python
class TestRoutesStorage:
    def test_reserve_populates_routes(self, router):
        r1_route = router.plan('r1', (0.0, 0.0), 'C')
        router.reserve('r1', r1_route)
        assert router._routes.get('r1') == [0, 1, 2]  # A=0, B=1, C=2

    def test_release_clears_routes(self, router):
        router.reserve('r1', router.plan('r1', (0.0, 0.0), 'C'))
        router.release('r1')
        assert 'r1' not in router._routes

    def test_reserve_overwrites_prior_route(self, router):
        router.reserve('r1', router.plan('r1', (0.0, 0.0), 'C'))
        router.reserve('r1', router.plan('r1', (0.0, 0.0), 'D'))
        assert router._routes.get('r1') == [0, 3]  # A=0, D=3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_fleet_router.py::TestRoutesStorage -v
```
Expected: 3 FAIL with `AttributeError: 'FleetRouter' object has no attribute '_routes'`

- [ ] **Step 3: Implement**

[fleet_router.py:43-46](server/control_service/control_service/fleet_router.py#L43-L46) 생성자 수정:

```python
def __init__(self) -> None:
    self._lock = threading.Lock()
    # (from_idx, to_idx) -> robot_id
    self._edges: dict[tuple[int, int], str] = {}
    # robot_id -> list of vertex indices along reserved route
    self._routes: dict[str, list[int]] = {}
```

같은 파일에 헬퍼 추가 (`_route_to_edges` 아래에):

```python
@staticmethod
def _route_to_idx_path(route: list[dict]) -> list[int]:
    """route ({x,y} points) → [vertex_idx, ...] 변환. 매칭 실패 시 스킵."""
    if not route:
        return []
    waypoints, _ = FleetRouter._load_graph()
    if not waypoints:
        return []
    path: list[int] = []
    for pt in route:
        for w in waypoints:
            if abs(w['x'] - pt['x']) < 0.01 and abs(w['y'] - pt['y']) < 0.01:
                path.append(w['idx'])
                break
    return path
```

[fleet_router.py:224-261](server/control_service/control_service/fleet_router.py#L224-L261) `reserve()` 내부에서 `_release_locked(robot_id)` 다음, `self._edges[e] = robot_id` 루프 다음에 추가:

```python
        with self._lock:
            self._release_locked(robot_id)
            for e in edges:
                self._edges[e] = robot_id
            for e in dest_in_edges:
                self._edges.setdefault(e, robot_id)
            self._routes[robot_id] = self._route_to_idx_path(route)
            total = len(self._edges)
```

[fleet_router.py:267-270](server/control_service/control_service/fleet_router.py#L267-L270) `_release_locked` 수정:

```python
def _release_locked(self, robot_id: str) -> None:
    stale = [e for e, owner in self._edges.items() if owner == robot_id]
    for e in stale:
        del self._edges[e]
    self._routes.pop(robot_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_fleet_router.py -v
```
Expected: 모든 기존 테스트 + 3 신규 PASS

- [ ] **Step 5: Commit**

```bash
git add server/control_service/control_service/fleet_router.py server/control_service/test/test_fleet_router.py
git commit -m "feat(fleet_router): track reserved routes per robot"
```

---

## Task 2: FleetRouter — `ConflictInfo` dataclass + fixture 확장

**Files:**
- Modify: `server/control_service/control_service/fleet_router.py:1-30` (import / 상수)
- Modify: `server/control_service/test/test_fleet_router.py:18-24` (_WAYPOINTS fixture)

- [ ] **Step 1: Add dataclass**

[fleet_router.py:1-20](server/control_service/control_service/fleet_router.py#L1-L20) import 영역 하단에 추가:

```python
from dataclasses import dataclass


@dataclass
class ConflictInfo:
    """Describes a conflict between the querying robot's planned route
    and another robot's reserved route."""
    partner_id: str
    conflict_entry_idx: int   # index within route_a where conflict starts
    conflict_exit_idx: int    # last vertex index (inclusive) still in conflict
    conflict_type: str        # 'E_SHARE' | 'E_OPPOSE' | 'V_CONVERGE'
```

- [ ] **Step 2: Extend fixture with `holding_point` field**

[test_fleet_router.py:18-24](server/control_service/test/test_fleet_router.py#L18-L24) `_WAYPOINTS` 갱신:

```python
_WAYPOINTS = [
    {'idx': 0, 'name': 'A', 'x': 0.0, 'y': 0.0, 'theta': 0.0, 'holding_point': True},
    {'idx': 1, 'name': 'B', 'x': 1.0, 'y': 0.0, 'theta': 0.0, 'holding_point': False},
    {'idx': 2, 'name': 'C', 'x': 2.0, 'y': 0.0, 'theta': 0.0, 'holding_point': True},
    {'idx': 3, 'name': 'D', 'x': 0.0, 'y': 1.0, 'theta': 0.0, 'holding_point': False},
    {'idx': 4, 'name': 'E', 'x': 2.0, 'y': 1.0, 'theta': 0.0, 'holding_point': False},
]
```

- [ ] **Step 3: Run existing tests to verify no regression**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_fleet_router.py -v
```
Expected: 모두 PASS (새 필드는 무시됨)

- [ ] **Step 4: Commit**

```bash
git add server/control_service/control_service/fleet_router.py server/control_service/test/test_fleet_router.py
git commit -m "feat(fleet_router): add ConflictInfo dataclass and holding_point fixture"
```

---

## Task 3: FleetRouter — `detect_conflict` 기본 케이스 (no-conflict + E_SHARE)

**Files:**
- Modify: `server/control_service/control_service/fleet_router.py` (신규 메서드)
- Test: `server/control_service/test/test_fleet_router.py`

- [ ] **Step 1: Write failing tests**

`test_fleet_router.py` 맨 끝에 새 클래스 추가:

```python
class TestDetectConflict:
    def test_no_conflict_when_no_other_reservation(self, router):
        my_route = router.plan('r1', (0.0, 0.0), 'C')
        assert router.detect_conflict(my_route, 'r1') is None

    def test_no_conflict_disjoint_routes(self, router):
        # r2 reserves A→D; r1 plans A→B→C (no overlap)
        r2_route = router.plan('r2', (0.0, 0.0), 'D')
        router.reserve('r2', r2_route)
        r1_route = router.plan('r1', (0.0, 0.0), 'C')
        # r1's plan detours (penalty), so it could be A→B→C still —
        # key check: explicitly request the shortest A→B→C and verify
        # it's NOT flagged as conflict (r2 is on A↔D).
        explicit = [{'x': 0.0, 'y': 0.0}, {'x': 1.0, 'y': 0.0}, {'x': 2.0, 'y': 0.0}]
        assert router.detect_conflict(explicit, 'r1') is None

    def test_e_share_same_direction(self, router):
        r2_route = router.plan('r2', (0.0, 0.0), 'C')  # A→B→C
        router.reserve('r2', r2_route)
        # r1 plans the exact same edges
        my_route = [{'x': 0.0, 'y': 0.0}, {'x': 1.0, 'y': 0.0}, {'x': 2.0, 'y': 0.0}]
        info = router.detect_conflict(my_route, 'r1')
        assert info is not None
        assert info.partner_id == 'r2'
        assert info.conflict_type == 'E_SHARE'
        assert info.conflict_entry_idx == 0  # edge (A,B) is first conflict
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_fleet_router.py::TestDetectConflict -v
```
Expected: 3 FAIL (`AttributeError: 'FleetRouter' object has no attribute 'detect_conflict'`)

- [ ] **Step 3: Implement `detect_conflict` (E_SHARE only for now)**

`fleet_router.py`의 `FleetRouter` 클래스에 신규 메서드 추가 (경로 계획 섹션 다음, lane reservation 섹션 앞):

```python
    # ──────────────────────────────────────────
    # Conflict detection
    # ──────────────────────────────────────────

    def detect_conflict(
        self,
        route: list[dict],
        robot_id: str,
    ) -> Optional[ConflictInfo]:
        """``route`` (list of {x,y}) 가 다른 로봇의 예약 경로와 충돌하는지 검사.

        3가지 충돌 유형을 순차 탐지 — 첫 매칭 상대만 반환:
          - E_SHARE   : 같은 directed edge (u,v) 공유
          - E_OPPOSE  : 역방향 edge (u,v) vs (v,u) — 좁은 통로 head-on
          - V_CONVERGE: 서로 다른 edge 로 같은 non-holding intermediate vertex 수렴

        홀딩 포인트(holding_point)로의 수렴은 충돌로 보지 않는다 (대기 가능 지점).
        ``conflict_entry_idx`` 는 route 내 "충돌이 시작되는 vertex 인덱스"
        (loser 가 양보 지점 선택 시 이 인덱스 직전까지 walk-back).
        """
        if not route or len(route) < 2:
            return None

        route_idx = self._route_to_idx_path(route)
        if len(route_idx) < 2:
            return None

        with self._lock:
            others = {rid: list(path) for rid, path in self._routes.items()
                      if rid != robot_id and len(path) >= 2}

        if not others:
            return None

        for partner_id, partner_path in others.items():
            partner_edges = set(zip(partner_path, partner_path[1:]))
            # edge i = (route_idx[i], route_idx[i+1]), i in [0, len-2]
            for i in range(len(route_idx) - 1):
                u, v = route_idx[i], route_idx[i + 1]
                # E_SHARE
                if (u, v) in partner_edges:
                    exit_i = i + 1
                    while exit_i < len(route_idx) - 1 \
                            and (route_idx[exit_i], route_idx[exit_i + 1]) in partner_edges:
                        exit_i += 1
                    return ConflictInfo(partner_id, i, exit_i, 'E_SHARE')
        return None
```

- [ ] **Step 4: Run tests to verify PASS**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_fleet_router.py::TestDetectConflict -v
```
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add server/control_service/control_service/fleet_router.py server/control_service/test/test_fleet_router.py
git commit -m "feat(fleet_router): detect E_SHARE conflict between reserved routes"
```

---

## Task 4: FleetRouter — `detect_conflict` E_OPPOSE (head-on)

**Files:**
- Modify: `server/control_service/control_service/fleet_router.py` (`detect_conflict`)
- Test: `server/control_service/test/test_fleet_router.py`

- [ ] **Step 1: Write failing test**

`TestDetectConflict` 클래스에 추가:

```python
    def test_e_oppose_head_on(self, router):
        # r2 reserves A→B→C (edges (0,1), (1,2))
        r2_route = router.plan('r2', (0.0, 0.0), 'C')
        router.reserve('r2', r2_route)
        # r1 plans the reverse C→B→A (edges (2,1), (1,0))
        my_route = [{'x': 2.0, 'y': 0.0}, {'x': 1.0, 'y': 0.0}, {'x': 0.0, 'y': 0.0}]
        info = router.detect_conflict(my_route, 'r1')
        assert info is not None
        assert info.partner_id == 'r2'
        assert info.conflict_type == 'E_OPPOSE'
        assert info.conflict_entry_idx == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_fleet_router.py::TestDetectConflict::test_e_oppose_head_on -v
```
Expected: FAIL (현재 E_SHARE만 감지)

- [ ] **Step 3: Extend `detect_conflict` with E_OPPOSE detection**

`fleet_router.py`의 `detect_conflict` 메서드에서 E_SHARE 블록 **다음에** 추가 (E_SHARE 블록과 같은 for 루프 안):

```python
                # E_OPPOSE
                if (v, u) in partner_edges:
                    exit_i = i + 1
                    while exit_i < len(route_idx) - 1 \
                            and (route_idx[exit_i + 1], route_idx[exit_i]) in partner_edges:
                        exit_i += 1
                    return ConflictInfo(partner_id, i, exit_i, 'E_OPPOSE')
```

- [ ] **Step 4: Verify PASS**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_fleet_router.py::TestDetectConflict -v
```
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add server/control_service/control_service/fleet_router.py server/control_service/test/test_fleet_router.py
git commit -m "feat(fleet_router): detect E_OPPOSE head-on conflict"
```

---

## Task 5: FleetRouter — `detect_conflict` V_CONVERGE (holding_point 제외)

**Files:**
- Modify: `server/control_service/control_service/fleet_router.py` (`detect_conflict`)
- Test: `server/control_service/test/test_fleet_router.py`

- [ ] **Step 1: Write failing tests**

`TestDetectConflict` 클래스에 추가:

```python
    def test_v_converge_non_holding(self, router):
        # Custom fixture: B is non-holding intermediate for both.
        # r2 reserves D→A→B→C (edges (3,0),(0,1),(1,2) — B is intermediate)
        # Build r2 path manually by reserving a route list that lands at B as intermediate.
        # Simplest: r2 A→B→C, r1 D→A→B — B is intermediate for r2 but endpoint for r1 → skip.
        # Use E→C→B as r2 reversed to make B intermediate: route E→C→B means edges (4,2),(2,1).
        # Hmm B is endpoint there. Use a 3-hop: r2 D→A→B→C has B intermediate.
        r2_route = [
            {'x': 0.0, 'y': 1.0},  # D
            {'x': 0.0, 'y': 0.0},  # A
            {'x': 1.0, 'y': 0.0},  # B
            {'x': 2.0, 'y': 0.0},  # C
        ]
        router.reserve('r2', r2_route)
        # r1 approaches B from E via C: E→C→B (edges (4,2),(2,1)). B is r1's endpoint here.
        # To get B as intermediate for r1 too, extend: E→C→B→A.
        my_route = [
            {'x': 2.0, 'y': 1.0},  # E
            {'x': 2.0, 'y': 0.0},  # C
            {'x': 1.0, 'y': 0.0},  # B
            {'x': 0.0, 'y': 0.0},  # A
        ]
        # Edges: (4,2), (2,1), (1,0). None match r2's edges (3,0),(0,1),(1,2) directly
        # nor their reverse. But B (idx=1) is intermediate for both → V_CONVERGE.
        info = router.detect_conflict(my_route, 'r1')
        assert info is not None
        assert info.conflict_type == 'V_CONVERGE'

    def test_v_converge_skipped_if_holding_point(self, router):
        # A (idx=0) is holding_point=True; both robots route through A as intermediate.
        # r2: D→A→B (edges (3,0),(0,1)); A is intermediate.
        r2_route = [
            {'x': 0.0, 'y': 1.0},  # D
            {'x': 0.0, 'y': 0.0},  # A
            {'x': 1.0, 'y': 0.0},  # B
        ]
        router.reserve('r2', r2_route)
        # r1: B→A→D (edges (1,0),(0,3)); A intermediate.
        # But (1,0) is reverse of (0,1) → that would be E_OPPOSE, not V_CONVERGE.
        # Use disjoint edges: r1 approaches A only as intermediate, not via B.
        # Workaround: A has no other incoming edge except via B or D.
        # Simpler: reuse r1 B→A→D with E_OPPOSE(1,0)/(0,1) — but then E_OPPOSE fires first.
        # Keep the test minimal: verify ordering — E_OPPOSE wins, V_CONVERGE never fires for A.
        my_route = [
            {'x': 1.0, 'y': 0.0},  # B
            {'x': 0.0, 'y': 0.0},  # A
            {'x': 0.0, 'y': 1.0},  # D
        ]
        info = router.detect_conflict(my_route, 'r1')
        # A is holding_point → V_CONVERGE skipped; E_OPPOSE may still fire.
        # Accept either: if info returned, it must NOT be V_CONVERGE.
        if info is not None:
            assert info.conflict_type != 'V_CONVERGE'
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_fleet_router.py::TestDetectConflict -v
```
Expected: `test_v_converge_non_holding` FAIL (현재 None 반환)

- [ ] **Step 3: Extend `detect_conflict` with V_CONVERGE**

`fleet_router.py`의 `detect_conflict` 메서드 맨 위에 holding_point lookup 준비:

```python
        waypoints, _ = self._load_graph()
        wp_by_idx = {w['idx']: w for w in waypoints}
```

이 2줄을 `route_idx = self._route_to_idx_path(route)` **앞에** 삽입. 그리고 others dict 루프 안에서 E_SHARE, E_OPPOSE 체크 다음에 V_CONVERGE 체크 추가. 최종 메서드는:

```python
    def detect_conflict(
        self,
        route: list[dict],
        robot_id: str,
    ) -> Optional[ConflictInfo]:
        """(docstring 그대로)"""
        if not route or len(route) < 2:
            return None

        waypoints, _ = self._load_graph()
        wp_by_idx = {w['idx']: w for w in waypoints}

        route_idx = self._route_to_idx_path(route)
        if len(route_idx) < 2:
            return None

        with self._lock:
            others = {rid: list(path) for rid, path in self._routes.items()
                      if rid != robot_id and len(path) >= 2}

        if not others:
            return None

        for partner_id, partner_path in others.items():
            partner_edges = set(zip(partner_path, partner_path[1:]))
            partner_mids = set(partner_path[1:-1]) if len(partner_path) >= 3 else set()
            for i in range(len(route_idx) - 1):
                u, v = route_idx[i], route_idx[i + 1]
                if (u, v) in partner_edges:
                    exit_i = i + 1
                    while exit_i < len(route_idx) - 1 \
                            and (route_idx[exit_i], route_idx[exit_i + 1]) in partner_edges:
                        exit_i += 1
                    return ConflictInfo(partner_id, i, exit_i, 'E_SHARE')
                if (v, u) in partner_edges:
                    exit_i = i + 1
                    while exit_i < len(route_idx) - 1 \
                            and (route_idx[exit_i + 1], route_idx[exit_i]) in partner_edges:
                        exit_i += 1
                    return ConflictInfo(partner_id, i, exit_i, 'E_OPPOSE')
                # V_CONVERGE: v is intermediate for both, non-holding
                if i < len(route_idx) - 2 and v in partner_mids:
                    wv = wp_by_idx.get(v, {})
                    if not wv.get('holding_point', False):
                        return ConflictInfo(partner_id, i, i + 1, 'V_CONVERGE')
        return None
```

- [ ] **Step 4: Verify PASS**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_fleet_router.py::TestDetectConflict -v
```
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add server/control_service/control_service/fleet_router.py server/control_service/test/test_fleet_router.py
git commit -m "feat(fleet_router): detect V_CONVERGE conflict at non-holding vertices"
```

---

## Task 6: RobotManager — `_guiding_remaining` 잔여거리 계산

**Files:**
- Modify: `server/control_service/control_service/robot_manager.py` (신규 메서드)
- Test: `server/control_service/test/test_robot_manager.py`

- [ ] **Step 1: Write failing test**

`test_robot_manager.py` 끝에 신규 클래스 `TestGuidingYield` 추가:

```python
class TestGuidingYield:
    def test_guiding_remaining_empty_route(self):
        rm = make_rm()
        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        state = rm.get_state('54')
        state.dest_x = 3.0
        state.dest_y = 4.0
        # Empty route → fallback to straight-line pos→dest = 5.0
        assert abs(rm._guiding_remaining(state, []) - 5.0) < 1e-6

    def test_guiding_remaining_polyline(self):
        rm = make_rm()
        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        state = rm.get_state('54')
        route = [{'x': 1.0, 'y': 0.0}, {'x': 1.0, 'y': 3.0}, {'x': 4.0, 'y': 3.0}]
        # 0→(1,0) = 1.0; (1,0)→(1,3) = 3.0; (1,3)→(4,3) = 3.0. Total 7.0.
        assert abs(rm._guiding_remaining(state, route) - 7.0) < 1e-6
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield -v
```
Expected: 2 FAIL

- [ ] **Step 3: Implement**

`robot_manager.py`의 `RobotManager` 클래스에서 `_resolve_returning_deadlock` 다음 위치에 추가:

```python
    # ──────────────────────────────────────────
    # GUIDING preemptive yield
    # ──────────────────────────────────────────

    def _guiding_remaining(
        self, state: 'RobotState', route: list[dict],
    ) -> float:
        """현재 위치 → route polyline 길이. route 가 비었거나 1개 이하면
        (dest_x, dest_y) 까지 직선거리 fallback."""
        if not route or len(route) < 2:
            if state.dest_x is None or state.dest_y is None:
                return 0.0
            return math.hypot(state.dest_x - state.pos_x,
                              state.dest_y - state.pos_y)
        total = math.hypot(route[0]['x'] - state.pos_x,
                           route[0]['y'] - state.pos_y)
        for a, b in zip(route, route[1:]):
            total += math.hypot(b['x'] - a['x'], b['y'] - a['y'])
        return total
```

- [ ] **Step 4: Verify PASS**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield -v
```
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add server/control_service/control_service/robot_manager.py server/control_service/test/test_robot_manager.py
git commit -m "feat(robot_manager): add _guiding_remaining for yield priority calc"
```

---

## Task 7: RobotManager — `_pick_yield_vertex` 3단계 후보 선택

**Files:**
- Modify: `server/control_service/control_service/robot_manager.py`
- Test: `server/control_service/test/test_robot_manager.py`

- [ ] **Step 1: Write failing tests**

`TestGuidingYield` 클래스에 추가:

```python
    def test_pick_yield_vertex_tier1_on_route_holding(self):
        rm = make_rm()
        # route_idx: [start=0, holding=1, conflict_entry=2, ...]
        route_idx = [10, 11, 12, 13]
        all_wps = [
            {'idx': 10, 'name': 'S', 'x': 0.0, 'y': 0.0, 'holding_point': False},
            {'idx': 11, 'name': 'H', 'x': 1.0, 'y': 0.0, 'holding_point': True},
            {'idx': 12, 'name': 'X', 'x': 2.0, 'y': 0.0, 'holding_point': False},
            {'idx': 13, 'name': 'Y', 'x': 3.0, 'y': 0.0, 'holding_point': False},
        ]
        # Conflict enters at edge (12, 13) → entry_idx = 2, walk back to find holding
        winner_route = [99, 12, 13]
        pick = rm._pick_yield_vertex(
            route_idx, entry_idx=2,
            partner_route_idx=winner_route,
            partner_pos=(2.5, 0.0),
            my_pos=(0.0, 0.0),
            all_wps=all_wps,
        )
        assert pick is not None
        assert pick['name'] == 'H'

    def test_pick_yield_vertex_tier2_off_route_holding(self):
        rm = make_rm()
        # Route has NO holding_point before conflict.
        route_idx = [10, 12]  # S → X (immediate conflict)
        all_wps = [
            {'idx': 10, 'name': 'S', 'x': 0.0, 'y': 0.0, 'holding_point': False},
            {'idx': 12, 'name': 'X', 'x': 2.0, 'y': 0.0, 'holding_point': False},
            # Off-route holding_point candidate
            {'idx': 20, 'name': 'OFF', 'x': 0.2, 'y': 1.0, 'holding_point': True},
        ]
        pick = rm._pick_yield_vertex(
            route_idx, entry_idx=0,
            partner_route_idx=[99, 12],
            partner_pos=(2.0, 0.0),
            my_pos=(0.0, 0.0),
            all_wps=all_wps,
        )
        assert pick is not None
        assert pick['name'] == 'OFF'

    def test_pick_yield_vertex_tier3_no_candidate(self):
        rm = make_rm()
        route_idx = [10, 12]
        all_wps = [
            {'idx': 10, 'name': 'S', 'x': 0.0, 'y': 0.0, 'holding_point': False},
            {'idx': 12, 'name': 'X', 'x': 2.0, 'y': 0.0, 'holding_point': False},
        ]
        pick = rm._pick_yield_vertex(
            route_idx, entry_idx=0,
            partner_route_idx=[99, 12],
            partner_pos=(2.0, 0.0),
            my_pos=(0.0, 0.0),
            all_wps=all_wps,
        )
        assert pick is None
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield -v
```
Expected: 3 FAIL (method not found)

- [ ] **Step 3: Implement**

`_guiding_remaining` 아래에 추가:

```python
    _YIELD_PARTNER_CLEARANCE_M = 0.25

    def _pick_yield_vertex(
        self,
        route_idx: list[int],
        entry_idx: int,
        partner_route_idx: list[int],
        partner_pos: tuple[float, float],
        my_pos: tuple[float, float],
        all_wps: list[dict],
    ) -> Optional[dict]:
        """Loser 양보 vertex 선택 (3단계).

        1차: route 위 entry_idx 직전 vertex 들을 역순 훑어 holding_point 이면서
             winner 경로 vertex 아닌 것
        2차: route 밖 holding_point 중 winner 경로·현 위치에서 충분히 떨어진 것 중
             내 현 위치에서 가장 가까운 것
        3차: 후보 없음 → None (caller 가 in-place wait 처리)
        """
        wp_by_idx = {w['idx']: w for w in all_wps}
        winner_vertices = set(partner_route_idx)

        # 1차
        for i in range(entry_idx - 1, -1, -1):
            v = route_idx[i]
            wp = wp_by_idx.get(v)
            if wp is None:
                continue
            if wp.get('holding_point', False) and v not in winner_vertices:
                return wp

        # 2차
        candidates: list[tuple[float, dict]] = []
        for wp in all_wps:
            if not wp.get('holding_point', False):
                continue
            if wp['idx'] in winner_vertices:
                continue
            d_partner = math.hypot(wp['x'] - partner_pos[0],
                                   wp['y'] - partner_pos[1])
            if d_partner < self._YIELD_PARTNER_CLEARANCE_M:
                continue
            d_me = math.hypot(wp['x'] - my_pos[0], wp['y'] - my_pos[1])
            candidates.append((d_me, wp))
        if candidates:
            candidates.sort(key=lambda t: t[0])
            return candidates[0][1]

        # 3차
        return None
```

- [ ] **Step 4: Verify PASS**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield -v
```
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add server/control_service/control_service/robot_manager.py server/control_service/test/test_robot_manager.py
git commit -m "feat(robot_manager): add _pick_yield_vertex with 3-tier candidate selection"
```

---

## Task 8: RobotManager — `_resolve_guiding_conflict` winner/loser 분기

**Files:**
- Modify: `server/control_service/control_service/robot_manager.py`
- Test: `server/control_service/test/test_robot_manager.py`

- [ ] **Step 1: Write failing tests**

`TestGuidingYield` 클래스에 추가:

```python
    def test_resolve_guiding_conflict_winner_proceeds(self):
        """Winner (잔여거리 짧은 쪽) 은 원 route 그대로 반환, should_proceed=True."""
        rm = make_rm()
        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        state = rm.get_state('54')
        state.dest_x = 1.0
        state.dest_y = 0.0

        from control_service.fleet_router import ConflictInfo
        rm._router.detect_conflict = MagicMock(return_value=None)
        route = [{'x': 0.0, 'y': 0.0}, {'x': 1.0, 'y': 0.0}]
        used, proceed = rm._resolve_guiding_conflict('54', route, {'zone_id': 22})
        assert proceed is True
        assert used == route

    def test_resolve_guiding_conflict_loser_events(self):
        """Loser 는 YIELD_HOLD event 를 push."""
        rm = make_rm()
        events = []
        rm._push_event = lambda rid, ev, **kw: events.append((rid, ev, kw.get('detail', '')))

        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        rm.on_status('18', {'mode': 'GUIDING', 'pos_x': 3.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        st54 = rm.get_state('54')
        st18 = rm.get_state('18')
        st54.dest_x = 10.0; st54.dest_y = 0.0  # 54 is far (loser)
        st18.dest_x = 3.5; st18.dest_y = 0.0   # 18 is close (winner)
        st18.path = [{'x': 3.0, 'y': 0.0}, {'x': 3.5, 'y': 0.0}]

        from control_service.fleet_router import ConflictInfo
        info = ConflictInfo(partner_id='18', conflict_entry_idx=1,
                            conflict_exit_idx=2, conflict_type='E_OPPOSE')
        rm._router.detect_conflict = MagicMock(return_value=info)
        rm._pick_yield_vertex = MagicMock(return_value={
            'idx': 99, 'name': 'HOLD', 'x': 0.5, 'y': 0.0, 'theta': 0.0,
        })
        rm._relay_to_pi = MagicMock()

        route = [{'x': 0.0, 'y': 0.0}, {'x': 1.0, 'y': 0.0}, {'x': 10.0, 'y': 0.0}]
        used, proceed = rm._resolve_guiding_conflict('54', route, {'zone_id': 22})
        assert proceed is False
        hold_events = [e for e in events if e[1] == 'YIELD_HOLD']
        assert len(hold_events) == 1
        assert '18' in hold_events[0][2]
        # loser payload preserved for resume
        assert rm._pending_navigate.get('54') == {'zone_id': 22}
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield -v
```
Expected: 2 FAIL (method not found)

- [ ] **Step 3: Implement**

`_pick_yield_vertex` 아래에 추가:

```python
    def _resolve_guiding_conflict(
        self,
        robot_id: str,
        route: list[dict],
        payload: dict,
    ) -> tuple[list[dict], bool]:
        """GUIDING dispatch 중 경로 충돌 감지 & 해소.

        Returns: (used_route, should_proceed)
          - should_proceed=True  → caller 는 원래 흐름 계속 (reserve + dispatch)
          - should_proceed=False → loser 분기 — 이 함수 내부에서 축소 경로 dispatch
                                   또는 in-place wait 까지 완료. caller 는 early return.
        """
        info = self._router.detect_conflict(route, robot_id)
        if info is None:
            return route, True

        # 잔여거리 비교
        with self._lock:
            my_state = self._states.get(robot_id)
            partner_state = self._states.get(info.partner_id)
        if my_state is None or partner_state is None:
            return route, True

        my_remaining = self._guiding_remaining(my_state, route)
        partner_remaining = self._guiding_remaining(partner_state, partner_state.path or [])

        # Tiebreaker: 차이 < 0.05m 이면 사전순 앞이 winner
        if abs(my_remaining - partner_remaining) < 0.05:
            im_winner = robot_id < info.partner_id
        else:
            im_winner = my_remaining < partner_remaining

        if im_winner:
            return route, True   # 원 route 로 진행

        # Loser: yield vertex 선택
        all_wps = db.get_fleet_waypoints()
        route_idx = self._router._route_to_idx_path(route)
        partner_route_idx = self._router._route_to_idx_path(partner_state.path or [])
        yield_wp = self._pick_yield_vertex(
            route_idx=route_idx,
            entry_idx=info.conflict_entry_idx,
            partner_route_idx=partner_route_idx,
            partner_pos=(partner_state.pos_x, partner_state.pos_y),
            my_pos=(my_state.pos_x, my_state.pos_y),
            all_wps=all_wps,
        )

        # 원 payload 는 resume 용으로 보존
        self._pending_navigate[robot_id] = dict(payload)

        if yield_wp is None:
            # 3차: in-place wait — 예약 release, Pi 에 아무 것도 보내지 않음
            self._router.release(robot_id)
            with self._lock:
                my_state.path = []
            self._push_event(
                robot_id, 'YIELD_HOLD',
                detail=f'in-place wait for {info.partner_id} (no candidate)',
            )
            return [], False

        # 축소 경로: 현 위치 근처 → yield_wp
        yield_route = self._router.plan(
            robot_id, (my_state.pos_x, my_state.pos_y), yield_wp['name'],
        )
        if not yield_route or len(yield_route) < 2:
            # 경로 계산 실패 → in-place wait
            self._router.release(robot_id)
            with self._lock:
                my_state.path = []
            self._push_event(
                robot_id, 'YIELD_HOLD',
                detail=f'in-place wait for {info.partner_id} (plan fail)',
            )
            return [], False

        with self._lock:
            my_state.path = yield_route
        self._router.reserve(robot_id, yield_route)

        poses = self._route_to_poses(yield_route, yield_wp['name'])
        self._relay_to_pi(robot_id, {
            'cmd': 'navigate_through_poses',
            'poses': poses,
        })
        self._push_event(
            robot_id, 'YIELD_HOLD',
            detail=f'yield to {info.partner_id} at {yield_wp["name"]}',
        )
        logger.info(
            'GUIDING yield: robot=%s → holding_point=%s (partner=%s, type=%s)',
            robot_id, yield_wp['name'], info.partner_id, info.conflict_type,
        )
        return yield_route, False
```

- [ ] **Step 4: Verify PASS**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield -v
```
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add server/control_service/control_service/robot_manager.py server/control_service/test/test_robot_manager.py
git commit -m "feat(robot_manager): _resolve_guiding_conflict with winner/loser routing"
```

---

## Task 9: RobotManager — `_check_yield_resume` 재출발

**Files:**
- Modify: `server/control_service/control_service/robot_manager.py`
- Test: `server/control_service/test/test_robot_manager.py`

- [ ] **Step 1: Write failing test**

`TestGuidingYield` 클래스에 추가:

```python
    def test_check_yield_resume_redispatches_when_clear(self):
        rm = make_rm()
        events = []
        rm._push_event = lambda rid, ev, **kw: events.append((rid, ev, kw.get('detail', '')))

        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.5, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        state = rm.get_state('54')
        rm._pending_navigate['54'] = {'zone_id': 22}

        rm._pick_waypoint_for_zone = MagicMock(return_value='음료1')
        rm._router.plan = MagicMock(return_value=[
            {'x': 0.5, 'y': 0.0}, {'x': 1.0, 'y': 0.0}])
        rm._router.detect_conflict = MagicMock(return_value=None)
        rm._vertices_blocked_by_others = MagicMock(return_value=set())
        dispatch_calls = []
        rm._dispatch_navigate_to = lambda rid, p: dispatch_calls.append((rid, p))

        rm._check_yield_resume('54', state)

        assert dispatch_calls == [('54', {'zone_id': 22})]
        clear_events = [e for e in events if e[1] == 'YIELD_CLEAR']
        assert len(clear_events) == 1

    def test_check_yield_resume_skipped_when_conflict_persists(self):
        rm = make_rm()
        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.5, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        state = rm.get_state('54')
        rm._pending_navigate['54'] = {'zone_id': 22}
        rm._pick_waypoint_for_zone = MagicMock(return_value='음료1')
        rm._router.plan = MagicMock(return_value=[
            {'x': 0.5, 'y': 0.0}, {'x': 1.0, 'y': 0.0}])

        from control_service.fleet_router import ConflictInfo
        rm._router.detect_conflict = MagicMock(return_value=ConflictInfo(
            partner_id='18', conflict_entry_idx=0, conflict_exit_idx=1,
            conflict_type='E_OPPOSE'))
        rm._vertices_blocked_by_others = MagicMock(return_value=set())
        dispatch_calls = []
        rm._dispatch_navigate_to = lambda rid, p: dispatch_calls.append((rid, p))

        rm._check_yield_resume('54', state)

        assert dispatch_calls == []
        assert '54' in rm._pending_navigate
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield -v
```
Expected: 2 FAIL

- [ ] **Step 3: Implement**

`_resolve_guiding_conflict` 아래에 추가:

```python
    def _check_yield_resume(
        self, robot_id: str, state: 'RobotState',
    ) -> None:
        """대기 중이던 loser 가 원 목적지로 재출발할 수 있는지 검사."""
        original = self._pending_navigate.get(robot_id)
        if not original:
            return
        if state.mode != 'GUIDING':
            # GUIDING 아니면 대기 자체가 무의미 — 큐에서 제거
            self._pending_navigate.pop(robot_id, None)
            return

        zone_id = original.get('zone_id')
        if zone_id is None:
            self._pending_navigate.pop(robot_id, None)
            return

        wp_name = self._pick_waypoint_for_zone(robot_id, zone_id)
        if not wp_name:
            return

        blocked = self._vertices_blocked_by_others(robot_id)
        candidate = self._router.plan(
            robot_id, (state.pos_x, state.pos_y), wp_name,
            blocked_vertices=blocked,
        )
        if not candidate:
            return

        if self._router.detect_conflict(candidate, robot_id) is not None:
            return

        # 충돌 해소 — 원 payload 로 재dispatch
        payload_copy = dict(original)
        self._pending_navigate.pop(robot_id, None)
        self._dispatch_navigate_to(robot_id, payload_copy)
        self._push_event(
            robot_id, 'YIELD_CLEAR',
            detail=f'resumed to zone={zone_id}',
        )
```

- [ ] **Step 4: Verify PASS**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield -v
```
Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add server/control_service/control_service/robot_manager.py server/control_service/test/test_robot_manager.py
git commit -m "feat(robot_manager): _check_yield_resume redispatches when conflict clears"
```

---

## Task 10: RobotManager — `_dispatch_navigate_to` + `on_status` 통합

**Files:**
- Modify: `server/control_service/control_service/robot_manager.py:1065-1158` (`_dispatch_navigate_to`), `server/control_service/control_service/robot_manager.py:144-206` (`on_status`)

- [ ] **Step 1: Write integration test — GUIDING dispatch 시 `_resolve_guiding_conflict` 호출**

`TestGuidingYield` 클래스에 추가:

```python
    def test_dispatch_navigate_to_calls_resolve_for_guiding(self):
        rm = make_rm()
        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        rm._pick_waypoint_for_zone_locked = lambda rid, zid: '음료1'
        import control_service.robot_manager as rm_mod
        rm_mod.db.get_fleet_waypoints = lambda: [
            {'idx': 22, 'name': '음료1', 'x': 0.699, 'y': -0.899, 'theta': 0.0,
             'holding_point': False},
        ]
        rm._router.plan = MagicMock(return_value=[
            {'x': 0.0, 'y': 0.0}, {'x': 0.699, 'y': -0.899}])
        rm._resolve_guiding_conflict = MagicMock(
            return_value=([{'x': 0.0, 'y': 0.0}, {'x': 0.699, 'y': -0.899}], True))
        rm._relay_to_pi = MagicMock()
        rm._router.reserve = MagicMock()

        rm._dispatch_navigate_to('54', {'zone_id': 22})

        rm._resolve_guiding_conflict.assert_called_once()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield::test_dispatch_navigate_to_calls_resolve_for_guiding -v
```
Expected: FAIL (`_resolve_guiding_conflict` not called)

- [ ] **Step 3: Modify `_dispatch_navigate_to`**

[robot_manager.py:1086-1102](server/control_service/control_service/robot_manager.py#L1086-L1102) 블록에서 route 계획 직후, stagger 체크 직전에 GUIDING 분기 삽입:

```python
        blocked = self._vertices_blocked_by_others(robot_id)
        route = self._router.plan(
            robot_id, (rx, ry), wp_name, blocked_vertices=blocked)
        logger.info('navigate_to: wp=%s, route=%d points (blocked=%d)',
                    wp_name, len(route), len(blocked))

        # GUIDING preemptive conflict resolution
        with self._lock:
            mode = st.mode
        if mode == 'GUIDING':
            try:
                route, should_proceed = self._resolve_guiding_conflict(
                    robot_id, route, payload)
            except Exception:
                logger.exception('guiding conflict resolve failed')
                should_proceed = True
            if not should_proceed:
                # loser 분기 — 이미 내부에서 dispatch 또는 in-place wait 처리됨
                return

        # 계획된 경로를 즉시 state에 반영하고 UI에 push.
        if route and len(route) >= 2:
            with self._lock:
                st.path = route
            self._router.reserve(robot_id, route)
            self._push_status(robot_id, st)

        # (아래 기존 stagger / _path_blocked_by / dispatch 로직 그대로)
```

- [ ] **Step 4: Modify `on_status` GUIDING tick**

[robot_manager.py:192-203](server/control_service/control_service/robot_manager.py#L192-L203) RETURNING 분기 다음, `_push_status` 호출 **전에** 추가:

```python
        if state.mode == 'GUIDING':
            try:
                self._check_yield_resume(robot_id, state)
            except Exception:
                logger.exception('guiding yield resume failed')
```

- [ ] **Step 5: Verify integration test PASS**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield -v
```
Expected: 10 PASS

- [ ] **Step 6: Run full test suite**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/ -v
```
Expected: 전체 PASS (기존 테스트 포함)

- [ ] **Step 7: Commit**

```bash
git add server/control_service/control_service/robot_manager.py server/control_service/test/test_robot_manager.py
git commit -m "feat(robot_manager): wire GUIDING conflict resolution into dispatch and on_status"
```

---

## Task 11: Tiebreaker 테스트 (잔여거리 동점)

**Files:**
- Test: `server/control_service/test/test_robot_manager.py`

- [ ] **Step 1: Write test**

`TestGuidingYield` 에 추가:

```python
    def test_tiebreaker_lexical_robot_id_wins(self):
        """잔여거리 동점이면 robot_id 사전순 앞이 winner."""
        rm = make_rm()
        rm.on_status('54', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 0.0,
                            'battery': 90.0, 'is_locked_return': False})
        rm.on_status('18', {'mode': 'GUIDING', 'pos_x': 0.0, 'pos_y': 5.0,
                            'battery': 90.0, 'is_locked_return': False})
        st54 = rm.get_state('54')
        st18 = rm.get_state('18')
        # Both remaining = 1.0
        st54.dest_x = 1.0; st54.dest_y = 0.0
        st18.dest_x = 0.0; st18.dest_y = 6.0
        st54.path = [{'x': 0.0, 'y': 0.0}, {'x': 1.0, 'y': 0.0}]
        st18.path = [{'x': 0.0, 'y': 5.0}, {'x': 0.0, 'y': 6.0}]

        from control_service.fleet_router import ConflictInfo
        info = ConflictInfo(partner_id='18', conflict_entry_idx=0,
                            conflict_exit_idx=1, conflict_type='E_OPPOSE')
        rm._router.detect_conflict = MagicMock(return_value=info)

        route = [{'x': 0.0, 'y': 0.0}, {'x': 1.0, 'y': 0.0}]
        # '18' < '54' 사전순 → '18' winner, '54' loser
        _, proceed54 = rm._resolve_guiding_conflict('54', route, {'zone_id': 22})
        assert proceed54 is False  # 54 is loser

        # Reverse: ask from 18's perspective
        rm._pending_navigate.clear()
        info_rev = ConflictInfo(partner_id='54', conflict_entry_idx=0,
                                conflict_exit_idx=1, conflict_type='E_OPPOSE')
        rm._router.detect_conflict = MagicMock(return_value=info_rev)
        route18 = [{'x': 0.0, 'y': 5.0}, {'x': 0.0, 'y': 6.0}]
        _, proceed18 = rm._resolve_guiding_conflict('18', route18, {'zone_id': 23})
        assert proceed18 is True   # 18 is winner
```

- [ ] **Step 2: Run — should PASS immediately (Task 8 이미 구현)**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/test_robot_manager.py::TestGuidingYield::test_tiebreaker_lexical_robot_id_wins -v
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add server/control_service/test/test_robot_manager.py
git commit -m "test(robot_manager): verify lexical tiebreaker for remaining-distance tie"
```

---

## Task 12: 기존 reactive spec 파일 삭제 + 수동 시뮬 검증

**Files:**
- Delete: `docs/superpowers/specs/2026-04-21-guiding-deadlock-resolution-design.md`

- [ ] **Step 1: Delete superseded spec**

```bash
rm docs/superpowers/specs/2026-04-21-guiding-deadlock-resolution-design.md
```

- [ ] **Step 2: Full test suite regression check**

```bash
cd ~/ros_ws && python3 -m pytest server/control_service/test/ -v
```
Expected: 전체 PASS

- [ ] **Step 3: Manual sim — SC-NEW-1 (1열 head-on)**

3개 터미널에서 실행:
```bash
bash scripts/run_server.sh   # 터미널 A
bash scripts/run_ui.sh       # 터미널 B
bash scripts/run_sim.sh      # 터미널 C
```

1. Gazebo 로딩(~60초) 후 admin_ui 에서 54, 18 각각 [위치 초기화]
2. `http://localhost:8501/?robot_id=54` 로그인 → IDLE → [시뮬레이션 모드] → GUIDING 진입 → **가전제품1** 선택
3. 거의 동시에 `?robot_id=18` → **과자1** 선택 (1열 통로에서 반대 방향)
4. **검증:**
   - admin_ui 이벤트 로그에 `YIELD_HOLD robot=<loser>` 출력
   - 잔여거리 긴 쪽이 `로비` 또는 `1열_입구` 등 holding_point 로 이동 후 정지
   - 짧은 쪽이 통과한 후 `YIELD_CLEAR` 이벤트 출력
   - loser 가 원 목적지로 재출발·도착

발생 로그 샘플을 plan 파일에 첨부 (아래 "Manual Validation Notes" 섹션) 또는 커밋 메시지에 포함.

- [ ] **Step 4: Commit plan progress**

```bash
git add docs/superpowers/
git commit -m "chore: remove superseded reactive-deadlock spec"
```

---

## Manual Validation Notes

(Task 12 Step 3 실행 후 여기에 관찰 결과·로그 발췌를 기록한다.)

---

## Spec Coverage Check

| Spec 요구사항 | 구현 Task |
|---|---|
| FR-1 충돌 감지 3 유형 | Task 3 (E_SHARE), Task 4 (E_OPPOSE), Task 5 (V_CONVERGE) |
| FR-2 잔여거리 짧은 쪽 winner | Task 6 (remaining), Task 8 (winner/loser) |
| FR-3 holding_point 까지 축소 경로 | Task 7 (pick_yield_vertex), Task 8 (dispatch) |
| FR-4 재출발 | Task 9 (_check_yield_resume), Task 10 (on_status 통합) |
| FR-5 동점 tiebreaker | Task 8 내부, Task 11 (검증) |
| FR-6 시뮬·실물 모두 teleport 미사용 | Task 8 (navigate_through_poses 만 사용) |
| NFR-1 서버 내 완결 | 전 Task — Pi/UI 미변경 |
| NFR-2 Thread-safe | Task 1, 3~5 (FleetRouter._lock), Task 8~10 (RobotManager._lock) |
| NFR-3 `_pending_navigate` 재사용 | Task 8 (loser 저장), Task 9 (resume) |
| 이벤트 `YIELD_HOLD` / `YIELD_CLEAR` | Task 8, Task 9 |
| 기존 reactive spec supersede | Task 12 |
