import struct
import zlib


def create_png(width, height, color):
    def make_chunk(chunk_type, data):
        chunk = chunk_type + data
        return struct.pack('>I', len(data)) + chunk + struct.pack('>I', zlib.crc32(chunk) & 0xffffffff)

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = make_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))

    raw_data = b''
    for y in range(height):
        raw_data += b'\x00'
        for x in range(width):
            raw_data += bytes(color)

    idat = make_chunk(b'IDAT', zlib.compress(raw_data))
    iend = make_chunk(b'IEND', b'')

    return sig + ihdr + idat + iend


icon_192 = create_png(192, 192, (26, 115, 232))
icon_512 = create_png(512, 512, (26, 115, 232))

with open('app/static/icons/icon-192.png', 'wb') as f:
    f.write(icon_192)

with open('app/static/icons/icon-512.png', 'wb') as f:
    f.write(icon_512)

print("İkonlar oluşturuldu.")
