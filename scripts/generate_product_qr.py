#!/usr/bin/env python3
"""
ShopPinkki 상품 QR 코드 생성 스크립트.

사용법:
    python3 scripts/generate_qr.py              # PNG 개별 파일 생성
    python3 scripts/generate_qr.py --sheet      # HTML 시트 생성 (브라우저에서 인쇄)
    python3 scripts/generate_qr.py --out DIR    # 출력 디렉터리 지정 (기본: scripts/qr_codes)

QR 인코딩 형식: {"product_name": "콜라", "price": 1500}
"""

import argparse
import base64
import io
import json
import os
import sys

try:
    import qrcode
    from qrcode.image.pure import PyPNGImage
except ImportError:
    sys.exit("qrcode 패키지가 필요합니다: pip install qrcode")

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PILLOW = True
except ImportError:
    _HAS_PILLOW = False


# ── 상품 데이터 (seed_data.sql 기준, 가격 단위: 원) ─────────────
PRODUCTS = [
    # 가전제품
    {"name": "TV",         "price": 1_500_000, "zone": "가전제품"},
    {"name": "냉장고",     "price": 800_000,   "zone": "가전제품"},
    {"name": "에어컨",     "price": 1_200_000, "zone": "가전제품"},
    # 과자
    {"name": "새우깡",     "price": 1_500,     "zone": "과자"},
    {"name": "포카칩",     "price": 1_800,     "zone": "과자"},
    {"name": "오레오",     "price": 2_500,     "zone": "과자"},
    # 해산물
    {"name": "연어",       "price": 12_000,    "zone": "해산물"},
    {"name": "새우",       "price": 8_000,     "zone": "해산물"},
    # 육류
    {"name": "소고기",     "price": 25_000,    "zone": "육류"},
    {"name": "돼지고기",   "price": 10_000,    "zone": "육류"},
    # 채소
    {"name": "당근",       "price": 2_000,     "zone": "채소"},
    {"name": "브로콜리",   "price": 3_000,     "zone": "채소"},
    {"name": "상추",       "price": 1_500,     "zone": "채소"},
    # 음료
    {"name": "콜라",       "price": 1_500,     "zone": "음료"},
    {"name": "사이다",     "price": 1_500,     "zone": "음료"},
    {"name": "물",         "price": 800,       "zone": "음료"},
    {"name": "오렌지주스", "price": 2_000,     "zone": "음료"},
    # 베이커리
    {"name": "식빵",       "price": 3_500,     "zone": "베이커리"},
    {"name": "크루아상",   "price": 2_500,     "zone": "베이커리"},
    # 음식
    {"name": "김밥",       "price": 4_000,     "zone": "음식"},
    {"name": "라면",       "price": 1_200,     "zone": "음식"},
]


def _qr_data(product: dict) -> str:
    """QR에 인코딩할 JSON 문자열 반환."""
    return json.dumps({"product_name": product["name"], "price": product["price"]},
                      ensure_ascii=False)


def _make_qr_png_bytes(data: str) -> bytes:
    """QR 코드 PNG를 바이트로 반환 (순수 Python, Pillow 불필요)."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=PyPNGImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


def _make_qr_with_label(data: str, product: dict) -> bytes:
    """상품명·가격 레이블이 붙은 QR PNG 바이트 반환 (Pillow 필요)."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    label_h = 60
    canvas = Image.new("RGB", (qr_img.width, qr_img.height + label_h), "white")
    canvas.paste(qr_img, (0, 0))

    draw = ImageDraw.Draw(canvas)
    _KO_FONTS = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    _KO_FONT_PATH = next((p for p in _KO_FONTS if os.path.exists(p)), None)
    try:
        font_name  = ImageFont.truetype(_KO_FONT_PATH, 16) if _KO_FONT_PATH else ImageFont.load_default()
        font_price = ImageFont.truetype(_KO_FONT_PATH, 13) if _KO_FONT_PATH else ImageFont.load_default()
    except OSError:
        font_name = font_price = ImageFont.load_default()

    price_str = f"{product['price']:,}원"
    draw.text((qr_img.width // 2, qr_img.height + 6),
              product["name"], fill="black", font=font_name, anchor="mt")
    draw.text((qr_img.width // 2, qr_img.height + 30),
              price_str, fill="#4f46e5", font=font_price, anchor="mt")
    draw.text((qr_img.width // 2, qr_img.height + 46),
              f"[{product['zone']}]", fill="#94a3b8", font=font_price, anchor="mt")

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def generate_png_files(out_dir: str) -> None:
    """각 상품을 개별 PNG 파일로 저장."""
    os.makedirs(out_dir, exist_ok=True)
    for p in PRODUCTS:
        data = _qr_data(p)
        if _HAS_PILLOW:
            png = _make_qr_with_label(data, p)
        else:
            png = _make_qr_png_bytes(data)
        fname = os.path.join(out_dir, f"{p['zone']}_{p['name']}.png")
        with open(fname, "wb") as f:
            f.write(png)
        print(f"  {fname}")
    print(f"\n총 {len(PRODUCTS)}개 파일 생성 완료 → {out_dir}/")


def generate_html_sheet(out_dir: str) -> None:
    """인쇄용 HTML 시트 생성 (브라우저에서 Ctrl+P)."""
    os.makedirs(out_dir, exist_ok=True)

    cards = []
    for p in PRODUCTS:
        data = _qr_data(p)
        if _HAS_PILLOW:
            png = _make_qr_with_label(data, p)
        else:
            png = _make_qr_png_bytes(data)
        b64 = base64.b64encode(png).decode()
        cards.append(
            f'<div class="card">'
            f'<img src="data:image/png;base64,{b64}" alt="{p["name"]}">'
            f'<div class="name">{p["name"]}</div>'
            f'<div class="price">{p["price"]:,}원</div>'
            f'<div class="zone">[{p["zone"]}]</div>'
            f'</div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>ShopPinkki QR 코드 시트</title>
<style>
  body {{ font-family: sans-serif; margin: 20px; background: #f8fafc; }}
  h1 {{ font-size: 18px; color: #4f46e5; margin-bottom: 16px; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
  }}
  .card {{
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 10px;
    text-align: center;
    page-break-inside: avoid;
  }}
  .card img {{ width: 100%; max-width: 160px; }}
  .name  {{ font-size: 13px; font-weight: 700; margin-top: 4px; }}
  .price {{ font-size: 12px; color: #4f46e5; }}
  .zone  {{ font-size: 11px; color: #94a3b8; }}
  @media print {{
    body {{ background: white; margin: 0; }}
    h1   {{ display: none; }}
    .grid {{ gap: 6px; }}
  }}
</style>
</head>
<body>
<h1>ShopPinkki 상품 QR 코드 — 브라우저에서 Ctrl+P 로 인쇄</h1>
<div class="grid">
{''.join(cards)}
</div>
</body>
</html>"""

    out_file = os.path.join(out_dir, "qr_sheet.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML 시트 생성 완료 → {out_file}")
    print("브라우저에서 열어 Ctrl+P 로 인쇄하세요.")


def main():
    parser = argparse.ArgumentParser(description="ShopPinkki QR 코드 생성")
    parser.add_argument(
        "--sheet", action="store_true",
        help="개별 PNG 대신 인쇄용 HTML 시트 생성"
    )
    parser.add_argument(
        "--out", default=os.path.join(os.path.dirname(__file__), "qr_codes"),
        metavar="DIR", help="출력 디렉터리 (기본: scripts/qr_codes)"
    )
    args = parser.parse_args()

    print(f"QR 코드 생성 중... (Pillow {'사용' if _HAS_PILLOW else '없음 — 레이블 미표시'})\n")

    if args.sheet:
        generate_html_sheet(args.out)
    else:
        generate_png_files(args.out)


if __name__ == "__main__":
    main()
