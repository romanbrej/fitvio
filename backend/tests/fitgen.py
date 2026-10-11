"""A tiny FIT encoder for tests: just enough messages for GarminDB's and Fitvio's activity import."""
import datetime
import struct

EPOCH = datetime.datetime(1989, 12, 31, tzinfo=datetime.timezone.utc)
TYPES = {"s8": (0x01, "b"), "enum": (0x00, "B"), "u8": (0x02, "B"), "u16": (0x84, "H"), "u32": (0x86, "I"),
         "u32z": (0x8C, "I")}
CRC = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
       0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]
# user_profile fields holding the watch's own unit settings (0 metric, 1 statute)
SETTINGS = {"elev_setting": 6, "weight_setting": 7, "speed_setting": 13, "dist_setting": 14,
            "temperature_setting": 21, "height_setting": 30}


def crc16(data: bytes, crc: int = 0) -> int:
    for b in data:
        for nibble in (b & 0xF, b >> 4):
            t = CRC[crc & 0xF]
            crc = ((crc >> 4) & 0x0FFF) ^ t ^ CRC[nibble]
    return crc


def ts(dt: datetime.datetime) -> int:
    return int((dt - EPOCH).total_seconds())


class Fit:
    def __init__(self):
        self.body = b""
        self.defs: dict = {}

    def msg(self, glob: int, fields: list[tuple[int, str, int]]) -> None:
        """One data message; fields are (field number, type, raw value)."""
        key = (glob, tuple((n, t) for n, t, _ in fields))
        if key not in self.defs:
            self.defs[key] = len(self.defs) % 16
            self.body += struct.pack("<BBBHB", 0x40 | self.defs[key], 0, 0, glob, len(fields))
            for n, t, _ in fields:
                self.body += struct.pack("<BBB", n, struct.calcsize(TYPES[t][1]), TYPES[t][0])
        self.body += struct.pack("<B", self.defs[key])
        self.body += b"".join(struct.pack("<" + TYPES[t][1], v) for _, t, v in fields)

    def bytes(self) -> bytes:
        hdr = struct.pack("<BBHI4s", 14, 0x20, 2132, len(self.body), b".FIT")
        data = hdr + struct.pack("<H", crc16(hdr)) + self.body
        return data + struct.pack("<H", crc16(data))


def activity_fit(start: datetime.datetime, minutes: int, dist_m: float, ascent_m: float, settings: dict,
                 sport: int = 1, power: int | None = None, laps: int = 1, temp_c: int = 18) -> bytes:
    """A steady activity (1 running, 2 cycling) with records every 10 s, `laps` equal laps and a session."""
    f = Fit()
    t0, secs = ts(start), minutes * 60
    speed = dist_m / secs
    f.msg(0, [(0, "enum", 4), (1, "u16", 1), (2, "u16", 3113), (3, "u32z", 12345), (4, "u32", t0)])
    if settings:
        f.msg(3, [(4, "u16", 750)] + [(SETTINGS[k], "enum", v) for k, v in settings.items()])
    f.msg(21, [(253, "u32", t0), (0, "enum", 0), (1, "enum", 0)])  # timer start
    for i in range(0, secs + 1, 10):
        rec = [(253, "u32", t0 + i), (3, "u8", 130 + 20 * i // secs), (5, "u32", int(speed * i * 100)),
               (6, "u16", int(speed * 1000)), (2, "u16", int((600 + ascent_m * i / secs) * 5)),
               (13, "s8", temp_c), (4, "u8", 85 if sport == 1 else 90)]
        f.msg(20, rec + ([(7, "u16", power)] if power else []))
    f.msg(21, [(253, "u32", t0 + secs), (0, "enum", 0), (1, "enum", 4)])  # timer stop_all
    lap_s = secs // laps
    for k in range(laps):
        f.msg(19, [(253, "u32", t0 + (k + 1) * lap_s), (254, "u16", k), (2, "u32", t0 + k * lap_s),
                   (7, "u32", lap_s * 1000), (8, "u32", lap_s * 1000), (9, "u32", int(dist_m / laps * 100)),
                   (13, "u16", int(speed * 1000)), (15, "u8", 140), (0, "enum", 9), (1, "enum", 1)])
    f.msg(18, [(253, "u32", t0 + secs), (254, "u16", 0), (2, "u32", t0), (5, "enum", sport), (6, "enum", 0),
               (7, "u32", secs * 1000), (8, "u32", secs * 1000), (9, "u32", int(dist_m * 100)),
               (14, "u16", int(speed * 1000)), (22, "u16", int(ascent_m)), (16, "u8", 140), (17, "u8", 160),
               (25, "u16", 0), (26, "u16", laps), (0, "enum", 8), (1, "enum", 1)])
    f.msg(34, [(253, "u32", t0 + secs), (0, "u32", secs * 1000), (1, "u16", 1), (2, "enum", 0), (3, "enum", 26),
               (4, "enum", 1)])
    return f.bytes()
