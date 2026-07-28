import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import time
import uuid


def recv_exact(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise RuntimeError("WebSocket connection closed")
        data += chunk
    return data


def recv_frame(sock):
    first, second = recv_exact(sock, 2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, 8))[0]
    mask = recv_exact(sock, 4) if masked else b""
    payload = recv_exact(sock, length)
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    if opcode == 8:
        raise RuntimeError("WebSocket closed by peer")
    if opcode != 1:
        return None
    return json.loads(payload.decode("utf-8"))


def send_frame(sock, message):
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    header = bytearray([0x81])
    if len(payload) < 126:
        header.append(0x80 | len(payload))
    elif len(payload) <= 0xFFFF:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", len(payload)))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", len(payload)))
    mask = os.urandom(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def auth_string(password, salt, challenge):
    secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest()).decode("ascii")
    return base64.b64encode(hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode("ascii")


def connect_obs(host, port, password, timeout):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=2)
            break
        except OSError as exc:
            last_error = exc
            time.sleep(0.4)
    else:
        raise RuntimeError(f"Could not connect to obs-websocket: {last_error}")

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET / HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Protocol: obswebsocket.json\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        response += recv_exact(sock, 1)
    if b" 101 " not in response.split(b"\r\n", 1)[0]:
        raise RuntimeError(response.decode("utf-8", errors="replace"))

    hello = recv_frame(sock)
    data = dict(hello.get("d") or {})
    identify = {
        "rpcVersion": min(int(data.get("rpcVersion", 1) or 1), 1),
        "eventSubscriptions": 0,
    }
    auth = data.get("authentication")
    if auth:
        identify["authentication"] = auth_string(password, auth["salt"], auth["challenge"])
    send_frame(sock, {"op": 1, "d": identify})
    identified = recv_frame(sock)
    if identified.get("op") != 2:
        raise RuntimeError(f"OBS did not identify the client: {identified}")
    return sock


def request(sock, request_type, request_data=None):
    request_id = str(uuid.uuid4())
    send_frame(sock, {
        "op": 6,
        "d": {
            "requestType": request_type,
            "requestId": request_id,
            "requestData": request_data or {},
        },
    })
    while True:
        message = recv_frame(sock)
        if message is None:
            continue
        data = message.get("d") or {}
        if message.get("op") == 7 and data.get("requestId") == request_id:
            status = data.get("requestStatus") or {}
            if not status.get("result"):
                raise RuntimeError(f"{request_type} failed: {status}")
            return data.get("responseData") or {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4455)
    parser.add_argument("--password", required=True)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()

    sock = connect_obs(args.host, args.port, args.password, args.timeout)
    try:
        print(json.dumps(request(sock, "GetVersion"), indent=2))
        print(json.dumps(request(sock, "GetInputKindList", {"unversioned": True}), indent=2))
    finally:
        sock.close()


if __name__ == "__main__":
    main()
