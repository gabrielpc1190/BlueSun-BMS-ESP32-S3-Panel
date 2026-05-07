"""Parse btsnoop_hci.log and extract GATT/ATT traffic relevant to the Octopus BMS.

Prints ATT operations (writes, notifications, read responses) in order with
direction tags and hex payloads — enough to reverse-engineer the command/response
framing used by the Octopus BMS app.
"""
import struct
import sys
from pathlib import Path

ATT_OPCODES = {
    0x01: "ERROR_RSP",
    0x02: "MTU_REQ",
    0x03: "MTU_RSP",
    0x04: "FIND_INFO_REQ",
    0x05: "FIND_INFO_RSP",
    0x06: "FIND_BY_TYPE_REQ",
    0x07: "FIND_BY_TYPE_RSP",
    0x08: "READ_BY_TYPE_REQ",
    0x09: "READ_BY_TYPE_RSP",
    0x0A: "READ_REQ",
    0x0B: "READ_RSP",
    0x0C: "READ_BLOB_REQ",
    0x0D: "READ_BLOB_RSP",
    0x0E: "READ_MULT_REQ",
    0x0F: "READ_MULT_RSP",
    0x10: "READ_BY_GROUP_REQ",
    0x11: "READ_BY_GROUP_RSP",
    0x12: "WRITE_REQ",
    0x13: "WRITE_RSP",
    0x16: "PREPARE_WRITE_REQ",
    0x17: "PREPARE_WRITE_RSP",
    0x18: "EXECUTE_WRITE_REQ",
    0x19: "EXECUTE_WRITE_RSP",
    0x1B: "HANDLE_VALUE_NOTIFY",
    0x1D: "HANDLE_VALUE_INDICATE",
    0x1E: "HANDLE_VALUE_CONFIRM",
    0x52: "WRITE_CMD",
    0xD2: "SIGNED_WRITE_CMD",
}

INTERESTING_OPS = {0x0A, 0x0B, 0x12, 0x13, 0x16, 0x17, 0x18, 0x19, 0x1B, 0x1D, 0x52}


def parse(path):
    data = Path(path).read_bytes()
    if data[:8] != b"btsnoop\x00":
        print(f"BAD btsnoop header: {data[:8]!r}")
        return
    # 16-byte file header: identifier(8) + version(4) + datalink(4)
    ver, dlt = struct.unpack(">II", data[8:16])
    print(f"# {path}  version={ver} datalink={dlt}  size={len(data)}")
    off = 16
    rec_i = 0
    t0 = None
    handle_cache = {}  # conn_handle -> {att_handle: 'uuid'} (we won't fill this, just record)

    while off + 24 <= len(data):
        orig_len, incl_len, flags, drops, ts_hi, ts_lo = struct.unpack(">IIIIII", data[off:off+24])
        off += 24
        ts = (ts_hi << 32) | ts_lo  # microseconds since 2000-01-01
        if t0 is None:
            t0 = ts
        ts_rel = (ts - t0) / 1_000_000.0
        payload = data[off:off + incl_len]
        off += incl_len
        rec_i += 1

        # Direction: flag bit 0: 0=sent, 1=received (host perspective)
        #            flag bit 1: 0=data, 1=command/event
        direction = "RX" if (flags & 1) else "TX"
        is_cmd_evt = bool(flags & 2)

        if len(payload) < 1:
            continue
        pkt_type = payload[0]
        # We only care about ACL data (0x02) for ATT
        if pkt_type != 0x02:
            continue
        if len(payload) < 5:
            continue
        handle_flags, acl_len = struct.unpack("<HH", payload[1:5])
        conn_handle = handle_flags & 0x0FFF
        pb_flag = (handle_flags >> 12) & 0x3
        acl_payload = payload[5:5 + acl_len]

        # L2CAP: len(2) + cid(2) + payload
        if len(acl_payload) < 4:
            continue
        l2cap_len, l2cap_cid = struct.unpack("<HH", acl_payload[0:4])
        if l2cap_cid != 0x0004:  # ATT channel
            continue
        att = acl_payload[4:4 + l2cap_len]
        if not att:
            continue
        op = att[0]
        op_name = ATT_OPCODES.get(op, f"op_0x{op:02x}")
        body = att[1:]

        # Extract handle and value for common ops
        extra = ""
        if op in (0x12, 0x52, 0x16):  # write req, write cmd, prepare write
            if len(body) >= 2:
                ah = struct.unpack("<H", body[:2])[0]
                val = body[2:]
                extra = f" h=0x{ah:04x} val={val.hex()}"
        elif op in (0x1B, 0x1D):  # notify, indicate
            if len(body) >= 2:
                ah = struct.unpack("<H", body[:2])[0]
                val = body[2:]
                extra = f" h=0x{ah:04x} val={val.hex()}"
        elif op == 0x0A:  # read req
            if len(body) >= 2:
                ah = struct.unpack("<H", body[:2])[0]
                extra = f" h=0x{ah:04x}"
        elif op == 0x0B:  # read rsp
            extra = f" val={body.hex()}"
        elif op == 0x08:  # read by type req
            if len(body) >= 6:
                start, end = struct.unpack("<HH", body[:4])
                t = body[4:]
                extra = f" range=0x{start:04x}-0x{end:04x} type={t.hex()}"
        elif op == 0x09:  # read by type rsp
            if len(body) >= 1:
                entry_len = body[0]
                extra = f" entry_len={entry_len} data={body[1:].hex()}"
        else:
            extra = f" body={body.hex()}"

        if op in INTERESTING_OPS:
            print(f"{ts_rel:8.3f}s  {direction}  conn=0x{conn_handle:03x}  {op_name:22s}{extra}")

    print(f"# records parsed: {rec_i}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        parse(p)
        print()
