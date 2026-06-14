"""E2E live (MaaS THẬT) — verify 2 tính năng cốt lõi ở góc nhìn user trước khi deploy:
  1. Chat với agent có sẵn (Em Bé CS) → nhận được câu trả lời streaming.
  2. Tạo agent mới qua master (create_skill → create_agent → attach_skill) → agent xuất hiện trong registry.

Chạy trên server uvicorn CÔ LẬP (DB tạm, JWT cố định) nhưng dùng MaaS thật từ .env →
KHÔNG đụng data/hub.db thật. Đăng nhập giả lập bằng cookie JWT (bypass Google OAuth).

    .venv/bin/python scripts/verify_live.py

Lưu ý: gọi MaaS thật nên tốn credit + chậm (vài phút cho luồng tạo agent).
"""
import datetime
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import httpx
import jwt

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
JWT_SECRET = "verify-live-secret-key-32-bytes-long!!"
USER_EMAIL = "an@verify.local"


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _wait(base, timeout=45):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.4)
    raise RuntimeError("server không lên")


def _cookie():
    exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
    return jwt.encode({"sub": USER_EMAIL, "email": USER_EMAIL, "name": "An", "picture": "",
                       "role": "user", "exp": exp}, JWT_SECRET, algorithm="HS256")


def chat(client, message, agent_name=None, timeout=300):
    """POST /chat, đọc SSE, trả về list (event, data)."""
    events = []
    body = {"message": message, "agent_name": agent_name, "attachment": None}
    with client.stream("POST", "/chat", json=body, timeout=timeout) as r:
        r.raise_for_status()
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                ev = da = None
                for line in frame.splitlines():
                    if line.startswith("event: "):
                        ev = line[7:]
                    elif line.startswith("data: "):
                        da = line[6:]
                if ev and da:
                    try:
                        events.append((ev, json.loads(da)))
                    except json.JSONDecodeError:
                        events.append((ev, {}))
    return events


def main():
    port = _free_port()
    db = tempfile.mktemp(suffix="_verify.db")
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "JWT_SECRET": JWT_SECRET,
           "SELF_TEST_ENABLED": "false", "GUEST_MODE": "true", "RATE_LIMIT_PER_MINUTE": "0"}
    proc = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                            cwd=str(ROOT), env=env)
    base = f"http://127.0.0.1:{port}"
    results = []
    try:
        _wait(base)
        client = httpx.Client(base_url=base, cookies={"session": _cookie()})

        # ── Flow 1: chat với agent có sẵn ───────────────────────────────
        print("\n[1/2] Chat với agent 'Em Bé CS'...")
        evs = chat(client, "Làm sao để nạp tiền vào ví?", agent_name="Em Bé CS")
        text = "".join(d.get("text", "") for e, d in evs if e == "delta")
        done = [d for e, d in evs if e == "done"]
        ok1 = len(text.strip()) > 20
        print(f"    deltas={sum(1 for e,_ in evs if e=='delta')} | len(text)={len(text)} | stop={done[-1].get('stop_reason') if done else '?'}")
        print(f"    preview: {text.strip()[:120]!r}")
        results.append(("Chat với agent có sẵn trả lời được", ok1))

        # ── Flow 2: tạo agent mới qua master ────────────────────────────
        print("\n[2/2] Tạo agent mới qua master (directive, 1 lượt)...")
        before = client.get("/agents").json()
        before_names = {a["name"] for a in before}
        prompt = (
            "Tạo giúp tôi agent tên 'Bé Test Live' để tư vấn chọn mua laptop văn phòng. "
            "Persona thân thiện, hỏi nhu cầu/ngân sách rồi gợi ý 2-3 model kèm lý do. "
            "Cứ tạo luôn skill + agent với nội dung hợp lý, không cần hỏi lại tôi, "
            "đây là agent private của tôi dùng thử."
        )
        evs2 = chat(client, prompt, agent_name="master")
        tools = [(d.get("name"), d.get("is_error")) for e, d in evs2 if e == "tool"]
        print(f"    tool calls: {tools}")
        after = client.get("/agents").json()
        new_agents = [a for a in after if a["name"] not in before_names]
        created = any(n in (t[0] or "") for t, in [(t,) for t in tools] for n in ["create_agent"]) \
            and any(not err for name, err in tools if name and "create_agent" in name)
        # Tiêu chí chắc chắn: có agent mới xuất hiện trong registry
        ok2 = len(new_agents) > 0
        print(f"    agent mới trong registry: {[a['name'] for a in new_agents]}")
        results.append(("Tạo agent mới qua master", ok2))

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        for suf in ("", "-shm", "-wal"):
            try:
                os.remove(db + suf)
            except OSError:
                pass

    print("\n" + "=" * 50)
    allok = True
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        allok = allok and ok
    print("=" * 50)
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
