#!/usr/bin/env python3
"""Nav graph 시각화 — 맵 위에 vertex + lane 오버레이."""

import yaml
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.font_manager as fm
from matplotlib.lines import Line2D
from PIL import Image
import os

# 한글 폰트
_font_path = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
if os.path.exists(_font_path):
    prop = fm.FontProperties(fname=_font_path)
    plt.rcParams['font.family'] = prop.get_name()

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAP_PGM    = os.path.join(BASE, 'src/pinky_pro/pinky_navigation/map/shop.pgm')
MAP_YAML   = os.path.join(BASE, 'src/pinky_pro/pinky_navigation/map/shop.yaml')
GRAPH_YAML = os.path.join(BASE, 'src/control_center/shoppinkki_rmf/maps/shop_nav_graph.yaml')

# ── 맵 로드 ──────────────────────────────────────────────────────────────────
with open(MAP_YAML) as f:
    map_meta = yaml.safe_load(f)

resolution = map_meta['resolution']
origin     = map_meta['origin']
img        = np.array(Image.open(MAP_PGM))
h, w       = img.shape

def world_to_px(x, y):
    px = (x - origin[0]) / resolution
    py = h - (y - origin[1]) / resolution
    return px, py

# ── nav graph 로드 ────────────────────────────────────────────────────────────
with open(GRAPH_YAML) as f:
    graph = yaml.safe_load(f)

vertices = graph['levels']['L1']['vertices']
lanes    = graph['levels']['L1']['lanes']

lane_set     = {(l[0], l[1]) for l in lanes}
drawn_bidir  = set()

# ── 레이아웃: 맵(왼쪽) + 범례(오른쪽) ─────────────────────────────────────────
fig = plt.figure(figsize=(20, 18), facecolor='#1a1a2e')
ax_map = fig.add_axes([0.02, 0.02, 0.72, 0.94])   # 맵 영역
ax_leg = fig.add_axes([0.76, 0.10, 0.22, 0.80])   # 범례 영역

ax_map.set_facecolor('#1a1a2e')
ax_leg.set_facecolor('#1a1a2e')
ax_leg.axis('off')

# ── 맵 이미지 (컬러맵 약간 밝게) ─────────────────────────────────────────────
ax_map.imshow(img, cmap='gray', origin='upper', alpha=0.75)
ax_map.set_title('ShopPinkki  Nav Graph', fontsize=17, color='white',
                 fontweight='bold', pad=10)
ax_map.axis('off')

# ── Lane ─────────────────────────────────────────────────────────────────────
BIDIR_COLOR  = '#00e676'   # 밝은 초록
UNIDIR_COLOR = '#29b6f6'   # 하늘색

for lane in lanes:
    fi, ti = lane[0], lane[1]
    x0, y0 = world_to_px(vertices[fi][0], vertices[fi][1])
    x1, y1 = world_to_px(vertices[ti][0], vertices[ti][1])
    is_bidir = (ti, fi) in lane_set
    pair     = tuple(sorted([fi, ti]))

    if is_bidir:
        if pair in drawn_bidir:
            continue
        drawn_bidir.add(pair)
        ax_map.annotate('', xy=(x1, y1), xytext=(x0, y0),
                        arrowprops=dict(arrowstyle='<->', color=BIDIR_COLOR,
                                        lw=1.8, mutation_scale=16))
    else:
        ax_map.annotate('', xy=(x1, y1), xytext=(x0, y0),
                        arrowprops=dict(arrowstyle='->', color=UNIDIR_COLOR,
                                        lw=1.8, mutation_scale=16))

# ── Vertex ───────────────────────────────────────────────────────────────────
STYLES = {
    'charger':       dict(color='#69ff47', marker='*', ms=20, ec='white',  ew=1.2),
    'holding_point': dict(color='#ffa726', marker='D', ms=13, ec='white',  ew=1.0),
    'pickup_zone':   dict(color='#ffee58', marker='o', ms=11, ec='#555',   ew=0.8),
    'detour':        dict(color='#ef9a9a', marker='^', ms=10, ec='white',  ew=0.8),
    'default':       dict(color='#e0e0e0', marker='o', ms=9,  ec='#555',   ew=0.8),
}

for i, v in enumerate(vertices):
    vx, vy = world_to_px(v[0], v[1])
    params = v[2] if len(v) > 2 else {}
    name   = params.get('name', str(i))

    if params.get('is_charger'):
        s = STYLES['charger']
    elif params.get('is_holding_point'):
        s = STYLES['holding_point']
    elif '우회' in name:
        s = STYLES['detour']
    elif params.get('pickup_zone'):
        s = STYLES['pickup_zone']
    else:
        s = STYLES['default']

    ax_map.plot(vx, vy, marker=s['marker'], color=s['color'], markersize=s['ms'],
                markeredgecolor=s['ec'], markeredgewidth=s['ew'], zorder=6)

    ax_map.text(vx + 6, vy - 6, f'{i}: {name}', fontsize=9.5, color='white',
                fontweight='bold', zorder=7,
                bbox=dict(boxstyle='round,pad=0.25', fc='#111827', alpha=0.72, ec='none'))

# ── 범례 패널 ─────────────────────────────────────────────────────────────────
ax_leg.text(0.5, 0.97, 'Legend', transform=ax_leg.transAxes,
            ha='center', va='top', fontsize=14, color='white', fontweight='bold')

legend_items = [
    ('Vertex', None),
    ('충전소 (charger)',        dict(color='#69ff47', marker='*', ms=14)),
    ('결제구역 (holding point)', dict(color='#ffa726', marker='D', ms=11)),
    ('픽업존 (pickup zone)',    dict(color='#ffee58', marker='o', ms=10)),
    ('우회점 (detour)',         dict(color='#ef9a9a', marker='^', ms=10)),
    ('일반 waypoint',           dict(color='#e0e0e0', marker='o', ms=9)),
    ('Lane', None),
    ('양방향 ↔',               dict(line=True, color='#00e676')),
    ('단방향 →',               dict(line=True, color='#29b6f6')),
]

y = 0.90
for item in legend_items:
    label, style = item
    if style is None:
        ax_leg.text(0.05, y, label, transform=ax_leg.transAxes,
                    fontsize=11, color='#aaaaaa', fontweight='bold')
        y -= 0.06
        continue
    if style.get('line'):
        ax_leg.plot([0.05, 0.25], [y, y], transform=ax_leg.transAxes,
                    color=style['color'], lw=2.5)
    else:
        ax_leg.plot(0.12, y, transform=ax_leg.transAxes,
                    marker=style['marker'], color=style['color'],
                    markersize=style['ms'], markeredgecolor='white', markeredgewidth=0.8)
    ax_leg.text(0.30, y, label, transform=ax_leg.transAxes,
                fontsize=11, color='white', va='center')
    y -= 0.075

# 인덱스 목록
ax_leg.text(0.05, y - 0.02, 'Waypoint Index', transform=ax_leg.transAxes,
            fontsize=11, color='#aaaaaa', fontweight='bold')
y -= 0.08
for i, v in enumerate(vertices):
    params = v[2] if len(v) > 2 else {}
    name   = params.get('name', str(i))
    ax_leg.text(0.05, y, f'{i:2d}  {name}', transform=ax_leg.transAxes,
                fontsize=8.5, color='#cccccc')
    y -= 0.037
    if y < 0.01:
        break

out = os.path.join(BASE, 'docs/nav_graph_viz.png')
plt.savefig(out, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
print(f'저장: {out}')
plt.show()
