"""抖音 imapi protobuf 工具: 解码 get_by_conversation 响应(消息/游标), 解码请求(游标定位)。

用法:
  python im_pb.py decode-resp <resp.bin> <out.json>    # 抽消息+翻页游标
  python im_pb.py decode-req <req.bin>                 # 打印请求游标位置/值
  python im_pb.py patch-req <req.bin> <cursor> <out.bin>  # 改写请求游标

配合抓包: 浏览器 DevTools -> Network -> get_by_conversation -> "Copy response"/保存为二进制。
消息结构(实测): 消息节点含 int 字段7(sender uid) + bytes 字段8(JSON 内容);
扩展字段9里 s:server_message_create_time 为微秒时间戳; 游标在请求 field 5 (0x28)。
"""
import json
import sys
from datetime import datetime
from pathlib import Path


def read_varint(b, i):
    v, shift = 0, 0
    while True:
        x = b[i]
        i += 1
        v |= (x & 0x7F) << shift
        if not x & 0x80:
            return v, i
        shift += 7


def enc_varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def parse(b):
    out, i = [], 0
    while i < len(b):
        try:
            tag, i = read_varint(b, i)
            field, wt = tag >> 3, tag & 7
            if wt == 0:
                v, i = read_varint(b, i)
                out.append((field, "int", v))
            elif wt == 2:
                ln, i = read_varint(b, i)
                out.append((field, "bytes", b[i : i + ln]))
                i += ln
            elif wt == 5:
                out.append((field, "i32", b[i : i + 4]))
                i += 4
            elif wt == 1:
                out.append((field, "i64", b[i : i + 8]))
                i += 8
            else:
                break
        except Exception:
            break
    return out


def find_ext_time(fields):
    for f, t, v in fields:
        if f == 9 and t == "bytes":
            name, val = None, None
            for f2, t2, v2 in parse(v):
                if f2 == 1 and t2 == "bytes":
                    s = v2.decode("utf-8", "replace")
                    if s.startswith("s:"):
                        name = s
                if f2 == 2:
                    for f3, t3, v3 in parse(v2):
                        if t3 == "int":
                            val = v3
            if name == "s:server_message_create_time" and val:
                return val
    return None


def dig_text(c):
    if isinstance(c, dict):
        for key in ("text", "content"):
            v = c.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for v in c.values():
            r = dig_text(v)
            if r:
                return r
    elif isinstance(c, list):
        for v in c:
            r = dig_text(v)
            if r:
                return r
    return None


def walk_messages(node, found):
    fields = parse(node) if isinstance(node, (bytes, bytearray)) else node
    f7 = [v for f, t, v in fields if f == 7 and t == "int"]
    f8 = [v for f, t, v in fields if f == 8 and t == "bytes"]
    if f7 and f8:
        try:
            content = f8[0].decode("utf-8")
            if content.startswith("{"):
                found.append({"uid": f7[0], "ext_time": find_ext_time(fields), "content": content})
        except Exception:
            pass
    for f, t, v in fields:
        if t == "bytes" and len(v) > 8:
            walk_messages(v, found)


def decode_resp(path, out_path):
    data = Path(path).read_bytes()
    msgs = []
    walk_messages(data, msgs)
    seen, uniq = set(), []
    for m in msgs:
        key = (m["uid"], m["ext_time"] or 0, m["content"][:60])
        if key not in seen:
            seen.add(key)
            uniq.append(m)
    uniq.sort(key=lambda m: m["ext_time"] or 0)
    out = []
    for m in uniq:
        ts = (m["ext_time"] or 0) / 1_000_000
        tstr = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M:%S") if ts > 1e9 else "?"
        try:
            c = json.loads(m["content"])
            text = dig_text(c) or json.dumps(c, ensure_ascii=False)[:150]
        except Exception:
            text = m["content"][:150]
        out.append({"time": tstr, "uid": m["uid"], "text": text})
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"messages: {len(out)} -> {out_path}")
    # 顶层游标: 外层 field6 > 301 > field5{3:min_cursor,4:max_cursor}, field3=has_more
    top = parse(data)
    print("top-level:", [(f, t, v if t == "int" else f"bytes({len(v)})") for f, t, v in top])


def decode_req(path):
    data = Path(path).read_bytes()
    print("size:", len(data))
    for f, t, v in parse(data):
        if t == "int":
            print("field", f, "=", v)
        else:
            try:
                s = v.decode("utf-8")
                print("field", f, f"str({len(s)})", s[:60].replace("\n", " "))
            except Exception:
                print("field", f, f"bytes({len(v)})")


def patch_req(path, cursor, out_path):
    """把 field5 游标(0x28 varint)改写为指定值。请求结构需与 get_by_conversation 一致。"""
    data = Path(path).read_bytes()
    # 内层: <str convid> \x10\x02 \x18<varint> \x20\x01 \x28<cursor> \x30<limit>
    i = data.find(b"ConversationIdNotFound")  # 不存在, 仅占位
    raise SystemExit("patch-req 需按实际报文定位: 用 decode-req 找到 field5 的字节区间后自行改写, 或参照 SKILL.md")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "decode-resp":
        decode_resp(sys.argv[2], sys.argv[3])
    elif cmd == "decode-req":
        decode_req(sys.argv[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
