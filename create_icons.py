import math
import struct
import zlib

BACKGROUND_TOP = (245, 248, 252)
BACKGROUND_BOTTOM = (220, 229, 242)
FRONT_TOP = (66, 165, 245)
FRONT_BOTTOM = (18, 86, 180)
BACK_TOP = (20, 72, 150)
BACK_BOTTOM = (8, 35, 86)
SHADOW = (15, 23, 42, 72)
STRIP = (17, 24, 39)
SIGNATURE = (245, 248, 255)
CHIP_TOP = (251, 210, 95)
CHIP_BOTTOM = (215, 143, 35)
CHIP_LINE = (137, 86, 19)
DETAIL = (255, 255, 255)
ORANGE = (242, 118, 48)
YELLOW = (252, 191, 54)
SS = 2

DIGITS = {
    '0': 'abcdef',
    '1': 'bc',
    '2': 'abged',
    '3': 'abgcd',
    '4': 'fgbc',
    '5': 'afgcd',
    '6': 'afgecd',
    '7': 'abc',
    '8': 'abcdefg',
    '9': 'abfgcd',
}


def _chunk(chunk_type, data):
    body = chunk_type + data
    return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)


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
    t = max(0.0, min(1.0, t))
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))


def _blend(dst, src):
    sr, sg, sb, sa = src
    if sa >= 255:
        return sr, sg, sb, 255
    dr, dg, db, da = dst
    out_a = sa + da * (255 - sa) // 255
    if out_a == 0:
        return 0, 0, 0, 0
    r = (sr * sa + dr * da * (255 - sa) // 255) // out_a
    g = (sg * sa + dg * da * (255 - sa) // 255) // out_a
    b = (sb * sa + db * da * (255 - sa) // 255) // out_a
    return r, g, b, out_a


def _rgba(color):
    return color if len(color) == 4 else color + (255,)


def _inside_round_rect(px, py, x0, y0, x1, y1, radius):
    if px < x0 or px > x1 or py < y0 or py > y1:
        return False
    cx = min(max(px, x0 + radius), x1 - radius)
    cy = min(max(py, y0 + radius), y1 - radius)
    dx = px - cx
    dy = py - cy
    return dx * dx + dy * dy <= radius * radius


def _inside_circle(px, py, cx, cy, radius):
    return (px - cx) ** 2 + (py - cy) ** 2 <= radius * radius


def _local(px, py, cx, cy, angle):
    dx = px - cx
    dy = py - cy
    cos_a = math.cos(-angle)
    sin_a = math.sin(-angle)
    return dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a


def _inside_rot_round_rect(px, py, cx, cy, width, height, radius, angle):
    lx, ly = _local(px, py, cx, cy, angle)
    return _inside_round_rect(lx, ly, -width / 2, -height / 2, width / 2, height / 2, radius)


def _paint(canvas, y0, y1, x0, x1, test, color_fn):
    out_w = len(canvas)
    for y in range(max(0, int(y0)), min(out_w, int(y1) + 1)):
        py = y + 0.5
        row = canvas[y]
        for x in range(max(0, int(x0)), min(out_w, int(x1) + 1)):
            px = x + 0.5
            if test(px, py):
                color = color_fn(px, py)
                if color is not None:
                    row[x] = _blend(row[x], _rgba(color))


def _paint_round(canvas, x0, y0, x1, y1, radius, color):
    _paint(
        canvas, y0, y1, x0, x1,
        lambda px, py: _inside_round_rect(px, py, x0, y0, x1, y1, radius),
        lambda px, py: color,
    )


def _paint_card(canvas, cx, cy, width, height, radius, angle, top, bottom):
    pad = max(width, height)
    _paint(
        canvas, cy - pad, cy + pad, cx - pad, cx + pad,
        lambda px, py: _inside_rot_round_rect(px, py, cx, cy, width, height, radius, angle),
        lambda px, py: _lerp(top, bottom, (_local(px, py, cx, cy, angle)[1] + height / 2) / height),
    )


def _paint_rot_local_rect(canvas, cx, cy, width, height, angle, lx0, ly0, lx1, ly1, radius, color):
    pad = max(width, height)
    def test(px, py):
        lx, ly = _local(px, py, cx, cy, angle)
        return _inside_round_rect(lx, ly, lx0, ly0, lx1, ly1, radius)
    _paint(canvas, cy - pad, cy + pad, cx - pad, cx + pad, test, lambda px, py: color)


def _draw_digit(canvas, x0, y0, width, height, digit, color):
    thick = max(width * 0.18, height * 0.10)
    radius = thick / 2
    x1 = x0 + width
    y1 = y0 + height
    ym = y0 + height / 2
    specs = {
        'a': (x0 + thick, y0, x1 - thick, y0 + thick),
        'b': (x1 - thick, y0 + thick, x1, ym - thick / 2),
        'c': (x1 - thick, ym + thick / 2, x1, y1 - thick),
        'd': (x0 + thick, y1 - thick, x1 - thick, y1),
        'e': (x0, ym + thick / 2, x0 + thick, y1 - thick),
        'f': (x0, y0 + thick, x0 + thick, ym - thick / 2),
        'g': (x0 + thick, ym - thick * 0.45, x1 - thick, ym + thick * 0.45),
    }
    for segment in DIGITS[digit]:
        sx0, sy0, sx1, sy1 = specs[segment]
        _paint_round(canvas, sx0, sy0, sx1, sy1, radius, color)


def _draw_card_number(canvas, card_x0, card_y0, card_w, card_h):
    groups = ['0123', '4567', '8910', '1112']
    y0 = card_y0 + card_h * 0.66
    digit_h = card_h * 0.13
    group_w = card_w * 0.17
    group_gap = card_w * 0.055
    start_x = card_x0 + card_w * 0.105
    digit_gap = group_w * 0.065
    digit_w = (group_w - digit_gap * 3) / 4
    for group_index, group in enumerate(groups):
        x = start_x + group_index * (group_w + group_gap)
        for digit in group:
            _draw_digit(canvas, x, y0, digit_w, digit_h, digit, DETAIL)
            x += digit_w + digit_gap


def _draw_icon(size, maskable=False):
    scale = size * SS
    canvas = [[(0, 0, 0, 0) for _ in range(scale)] for _ in range(scale)]

    if maskable:
        for y in range(scale):
            row = canvas[y]
            for x in range(scale):
                vertical = (y + 0.5) / scale
                radial = (((x + 0.5 - scale / 2) ** 2 + (y + 0.5 - scale / 2) ** 2) ** 0.5) / (scale * 0.72)
                row[x] = _lerp(BACKGROUND_TOP, BACKGROUND_BOTTOM, vertical * 0.62 + radial * 0.38) + (255,)
    else:
        x0, x1 = 0.04 * scale, 0.96 * scale
        y0, y1 = 0.04 * scale, 0.96 * scale
        _paint(
            canvas, y0, y1, x0, x1,
            lambda px, py: _inside_round_rect(px, py, x0, y0, x1, y1, 0.20 * scale),
            lambda px, py: _lerp(BACKGROUND_TOP, BACKGROUND_BOTTOM, (py - y0) / (y1 - y0)),
        )

    if maskable:
        front_x0, front_x1 = 0.14 * scale, 0.90 * scale
        front_y0, front_y1 = 0.33 * scale, 0.81 * scale
        back_cx, back_cy = 0.47 * scale, 0.40 * scale
        back_w, back_h = 0.63 * scale, 0.40 * scale
    else:
        front_x0, front_x1 = 0.11 * scale, 0.91 * scale
        front_y0, front_y1 = 0.33 * scale, 0.83 * scale
        back_cx, back_cy = 0.48 * scale, 0.39 * scale
        back_w, back_h = 0.68 * scale, 0.43 * scale

    front_w = front_x1 - front_x0
    front_h = front_y1 - front_y0
    front_r = 0.055 * scale
    back_r = 0.05 * scale
    back_angle = -0.20

    _paint_card(canvas, back_cx + 0.014 * scale, back_cy + 0.024 * scale, back_w, back_h, back_r, back_angle, SHADOW[:3], SHADOW[:3])
    _paint_card(canvas, back_cx, back_cy, back_w, back_h, back_r, back_angle, BACK_TOP, BACK_BOTTOM)
    _paint_rot_local_rect(canvas, back_cx, back_cy, back_w, back_h, back_angle, -back_w * 0.50, -back_h * 0.22, back_w * 0.50, -back_h * 0.06, 0, STRIP)
    _paint_rot_local_rect(canvas, back_cx, back_cy, back_w, back_h, back_angle, -back_w * 0.36, back_h * 0.08, back_w * 0.26, back_h * 0.24, back_h * 0.035, SIGNATURE)

    _paint_round(canvas, front_x0 + 0.016 * scale, front_y0 + 0.024 * scale, front_x1 + 0.016 * scale, front_y1 + 0.024 * scale, front_r, SHADOW)
    _paint(
        canvas, front_y0, front_y1, front_x0, front_x1,
        lambda px, py: _inside_round_rect(px, py, front_x0, front_y0, front_x1, front_y1, front_r),
        lambda px, py: _lerp(FRONT_TOP, FRONT_BOTTOM, (py - front_y0) / front_h),
    )

    chip_x0 = front_x0 + front_w * 0.105
    chip_y0 = front_y0 + front_h * 0.28
    chip_x1 = chip_x0 + front_w * 0.16
    chip_y1 = chip_y0 + front_h * 0.27
    _paint(
        canvas, chip_y0, chip_y1, chip_x0, chip_x1,
        lambda px, py: _inside_round_rect(px, py, chip_x0, chip_y0, chip_x1, chip_y1, (chip_y1 - chip_y0) * 0.18),
        lambda px, py: _lerp(CHIP_TOP, CHIP_BOTTOM, (py - chip_y0) / (chip_y1 - chip_y0)),
    )
    line_t = (chip_y1 - chip_y0) * 0.08
    _paint_round(canvas, chip_x0 + (chip_x1 - chip_x0) * 0.45, chip_y0, chip_x0 + (chip_x1 - chip_x0) * 0.55, chip_y1, line_t, CHIP_LINE)
    _paint_round(canvas, chip_x0, chip_y0 + (chip_y1 - chip_y0) * 0.45, chip_x1, chip_y0 + (chip_y1 - chip_y0) * 0.55, line_t, CHIP_LINE)

    logo_r = front_h * 0.105
    logo_y = front_y0 + front_h * 0.23
    left_cx = front_x1 - front_w * 0.20
    right_cx = left_cx + logo_r * 1.15
    _paint(canvas, logo_y - logo_r, logo_y + logo_r, left_cx - logo_r, right_cx + logo_r, lambda px, py: _inside_circle(px, py, left_cx, logo_y, logo_r), lambda px, py: ORANGE)
    _paint(canvas, logo_y - logo_r, logo_y + logo_r, left_cx - logo_r, right_cx + logo_r, lambda px, py: _inside_circle(px, py, right_cx, logo_y, logo_r), lambda px, py: YELLOW)

    _draw_card_number(canvas, front_x0, front_y0, front_w, front_h)
    _paint_round(canvas, front_x0 + front_w * 0.11, front_y0 + front_h * 0.84, front_x0 + front_w * 0.36, front_y0 + front_h * 0.885, front_h * 0.02, DETAIL)
    _paint_round(canvas, front_x0 + front_w * 0.68, front_y0 + front_h * 0.84, front_x0 + front_w * 0.83, front_y0 + front_h * 0.885, front_h * 0.02, DETAIL)

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
