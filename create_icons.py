"""PWA ikonlarını Material Design 3 dilinde üretir.

Harici bağımlılık kullanmaz; PNG'yi struct/zlib ile doğrudan yazar.
M3 öğeleri: tonal renk geçişi, büyük yuvarlatılmış köşeler, contactless dalgası.
"""

import struct
import zlib

# Material 3 tonal palet (primary / primary container / surface variant)
CARD_TOP = (42, 118, 234)
CARD_BOTTOM = (11, 87, 208)
STRIPE = (232, 234, 237)
CHIP_TOP = (246, 211, 101)
CHIP_BOTTOM = (217, 164, 65)
CHIP_LINE = (150, 112, 30)
DETAIL = (255, 255, 255)

SS = 3  # supersampling katsayısı


def _chunk(chunk_type, data):
    body = chunk_type + data
    return struct.pack('>I', len(data)) + body + struct.pack(
        '>I', zlib.crc32(body) & 0xFFFFFFFF
    )


def _write_png(path, width, height, pixels):
    raw = b''
    for y in range(height):
        raw += b'\x00'
        for r, g, b, a in pixels[y]:
            raw += bytes((r, g, b, a))

    png = b'\x89PNG\r\n\x1a\n'
    png += _chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
    png += _chunk(b'IDAT', zlib.compress(raw, 9))
    png += _chunk(b'IEND', b'')
    with open(path, 'wb') as handle:
        handle.write(png)


def _lerp(c1, c2, t):
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))


def _inside_round_rect(px, py, x0, y0, x1, y1, radius):
    """Yuvarlatılmış dikdörtgenin içinde mi? Sürekli kenar testi."""
    if px < x0 or px > x1 or py < y0 or py > y1:
        return False
    cx = min(max(px, x0 + radius), x1 - radius)
    cy = min(max(py, y0 + radius), y1 - radius)
    dx = px - cx
    dy = py - cy
    return dx * dx + dy * dy <= radius * radius


def _inside_arc(px, py, cx, cy, radius, thickness, angle_min, angle_max):
    """Yayın içinde mi? ( contactless dalgası için )"""
    dx = px - cx
    dy = py - cy
    dist = (dx * dx + dy * dy) ** 0.5
    if abs(dist - radius) > thickness / 2:
        return False
    if dist == 0:
        return False
    # -pi..pi aralığında açı; dalgalar sağa doğru açılır.
    angle = _atan2(dy, dx)
    half = (angle_max - angle_min) / 2
    mid = (angle_max + angle_min) / 2
    diff = (angle - mid + 3.141592653589793) % (2 * 3.141592653589793) - 3.141592653589793
    return abs(diff) <= half


def _atan2(y, x):
    import math
    return math.atan2(y, x)


def _paint(canvas, y0, y1, x0, x1, test, color_fn):
    """Yalnızca verilen sınırlar içindeki pikselleri sırayla boyar."""
    out_w = len(canvas)
    for y in range(max(0, int(y0)), min(out_w, int(y1) + 1)):
        py = y + 0.5
        row = canvas[y]
        for x in range(max(0, int(x0)), min(out_w, int(x1) + 1)):
            px = x + 0.5
            if test(px, py):
                color = color_fn(px, py)
                if color is not None:
                    row[x] = (color[0], color[1], color[2], 255)


def _draw_icon(size, maskable=False):
    scale = size * SS
    out_w = size * SS
    canvas = [[(0, 0, 0, 0) for _ in range(out_w)] for _ in range(out_w)]

    if maskable:
        # Android maskesi kenarı kırpar; içerik dairenin içinde kalmalı.
        # Bu yüzden tüm kanvas mavi tonlu zeminle doldurulur ve kart %56
        # çapın içine küçültülür.
        for y in range(out_w):
            row = canvas[y]
            for x in range(out_w):
                t = (y + 0.5) / out_w
                row[x] = _lerp(CARD_TOP, CARD_BOTTOM, t) + (255,)

        shrink = 0.72
        cx, cy = 0.5 * scale, 0.5 * scale
        half = 0.5 * shrink * scale
        card_x0, card_x1 = cx - half, cx + half
        card_y0, card_y1 = cy - half * 0.62, cy + half * 0.62
        card_r = 0.055 * scale
    else:
        # M3 "large" köşe yarıçapı; ölçüler dairesel maskeye de sığacak şekilde.
        card_x0, card_x1 = 0.15 * scale, 0.85 * scale
        card_y0, card_y1 = 0.30 * scale, 0.70 * scale
        card_r = 0.08 * scale

    card_w = card_x1 - card_x0
    card_h = card_y1 - card_y0
    card_mid_x = (card_x0 + card_x1) / 2
    card_mid_y = (card_y0 + card_y1) / 2

    # Dikey yerleşim: serit kartın üst kenarına yakın, çip orta-altta,
    # numara çizgisi en altta; her biri kart içinde eşit boşluk bırakır.
    stripe_h = 0.11 * card_h
    stripe_y0 = card_y0 + 0.145 * card_h
    stripe_y1 = stripe_y0 + stripe_h
    stripe_x0, stripe_x1 = card_x0 + 0.03 * card_w, card_x1 - 0.03 * card_w
    stripe_r = stripe_h / 2

    chip_h = 0.24 * card_h
    chip_w = 0.105 * card_w
    chip_x0, chip_x1 = card_x0 + 0.095 * card_w, card_x0 + 0.095 * card_w + chip_w
    chip_y0, chip_y1 = card_y0 + 0.39 * card_h, card_y0 + 0.39 * card_h + chip_h
    chip_r = chip_h * 0.24

    # Kart numarası yerine geçen beyaz çizgi, çip ile sol kenar arasında.
    text_h = 0.038 * card_h
    text_x0 = card_x0 + 0.125 * card_w
    text_x1 = text_x0 + 0.34 * card_w
    text_y0 = card_y0 + 0.79 * card_h
    text_y1 = text_y0 + text_h

    # Kart gövdesi: dikey tonal geçiş.
    _paint(
        canvas, card_y0, card_y1, card_x0, card_x1,
        lambda px, py: _inside_round_rect(
            px, py, card_x0, card_y0, card_x1, card_y1, card_r
        ),
        lambda px, py: _lerp(
            CARD_TOP, CARD_BOTTOM, (py - card_y0) / (card_y1 - card_y0)
        ),
    )

    # Manyetik şerit: kart yüzeyine hafif gömülü, yuvarlatılmış uçlar.
    _paint(
        canvas, stripe_y0, stripe_y1, stripe_x0, stripe_x1,
        lambda px, py: _inside_round_rect(
            px, py, stripe_x0, stripe_y0, stripe_x1, stripe_y1, stripe_r
        ),
        lambda px, py: STRIPE,
    )

    # Çip: altın tonal geçiş, yuvarlatılmış köşeli M3 yüzeyi.
    def chip_test(px, py):
        return _inside_round_rect(
            px, py, chip_x0, chip_y0, chip_x1, chip_y1, chip_r
        )

    def chip_color(px, py):
        color = _lerp(
            CHIP_TOP, CHIP_BOTTOM, (py - chip_y0) / (chip_y1 - chip_y0)
        )
        mid_x = (chip_x0 + chip_x1) / 2
        mid_y = (chip_y0 + chip_y1) / 2
        if abs(px - mid_x) < chip_w * 0.07 or abs(py - mid_y) < chip_h * 0.07:
            return CHIP_LINE
        return color

    _paint(canvas, chip_y0, chip_y1, chip_x0, chip_x1, chip_test, chip_color)

    # Kartın sağ altında contactless (NFC) dalgası: ödeme çağrışımı.
    # Merkez kartın sağ kenarından en az yarıçap kadar içeride olmalı, yoksa
    # yay kart dışına taşar.
    wave_thickness = card_h * 0.026
    wave_outer = card_h * 0.115
    wave_cx = card_x1 - wave_outer - card_w * 0.06
    wave_cy = card_y0 + card_h * 0.545
    for radius in (wave_outer * 0.57, wave_outer):
        _paint(
            canvas,
            wave_cy - radius, wave_cy + radius,
            wave_cx - radius, wave_cx + radius,
            lambda px, py, r=radius, t=wave_thickness: (
                _inside_round_rect(
                    px, py, card_x0, card_y0, card_x1, card_y1, card_r
                )
                and _inside_arc(px, py, wave_cx, wave_cy, r, t, -0.9, 0.9)
            ),
            lambda px, py: DETAIL,
        )

    # Kartın sol altında kart numarası yerine geçen beyaz çizgi.
    _paint(
        canvas, text_y0, text_y1, text_x0, text_x1,
        lambda px, py: (
            _inside_round_rect(
                px, py, card_x0, card_y0, card_x1, card_y1, card_r
            )
            and _inside_round_rect(
                px, py, text_x0, text_y0, text_x1, text_y1, text_h / 2
            )
        ),
        lambda px, py: DETAIL,
    )

    # 4x4 yerine SSxSS blok ortalamasıyla alfa kenar yumuşatma.
    final = []
    total = SS * SS
    for y in range(size):
        row = []
        for x in range(size):
            r = g = b = a = 0
            for dy in range(SS):
                for dx in range(SS):
                    pr, pg, pb, pa = canvas[y * SS + dy][x * SS + dx]
                    r += pr * pa
                    g += pg * pa
                    b += pb * pa
                    a += pa
            if a == 0:
                row.append((0, 0, 0, 0))
            else:
                row.append((r // a, g // a, b // a, a // total))
        final.append(row)
    return final


def main():
    for size in (192, 512):
        for maskable in (False, True):
            suffix = 'maskable-' if maskable else ''
            _write_png(
                f'app/static/icons/icon-{suffix}{size}.png',
                size,
                size,
                _draw_icon(size, maskable=maskable),
            )
            print(f'icon-{suffix}{size}.png olusturuldu')


if __name__ == '__main__':
    main()
