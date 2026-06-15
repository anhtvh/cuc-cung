"""Fetch HTTP an toàn — chặn SSRF kể cả khi server redirect về IP nội mạng.

Guard cũ (web_search._ssrf_check / master._safe_url) chỉ kiểm IP của URL GỐC rồi
để httpx `follow_redirects=True` tự đi tiếp → một server ngoài hợp lệ có thể trả
`302 → http://169.254.169.254/...` (metadata cloud) hoặc IP nội mạng và VƯỢT QUA
guard. Helper này tự đi từng hop, kiểm SSRF LẠI ở mỗi lần redirect.
"""

import ipaddress
import socket as _socket
from urllib.parse import urljoin, urlparse

import httpx

# Dải IP nội bộ + metadata endpoint cloud (AWS/GCP 169.254.169.254) — cấm fetch tới.
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class SsrfBlocked(Exception):
    """URL trỏ vào mạng nội bộ — chặn vì lý do bảo mật."""


def ssrf_check(url: str) -> str | None:
    """Trả message lỗi nếu URL resolve ra IP nội mạng, None nếu an toàn.

    Bảo thủ: không resolve được host → None (để httpx báo lỗi mạng tự nhiên),
    không chặn nhầm domain hợp lệ.
    """
    host = urlparse(url).hostname or ""
    if not host:
        return "URL thiếu hostname"
    try:
        resolved = _socket.gethostbyname(host)
        ip = ipaddress.ip_address(resolved)
        if any(ip in net for net in _PRIVATE_NETS):
            return f"URL trỏ đến địa chỉ nội mạng ({resolved}) — không được phép vì lý do bảo mật"
    except (_socket.gaierror, ValueError):
        pass  # không resolve được → để tầng httpx xử lý lỗi tự nhiên
    return None


def safe_get(
    url: str,
    *,
    timeout: float,
    headers: dict | None = None,
    max_redirects: int = 5,
) -> httpx.Response:
    """GET tự đi từng redirect, kiểm SSRF lại MỖI hop. Raise SsrfBlocked nếu bị chặn.

    Trả về Response cuối cùng (đã raise_for_status ở caller nếu cần). follow_redirects
    để False để tự kiểm soát — không để httpx âm thầm nhảy tới IP nội mạng.
    """
    current = url
    with httpx.Client(follow_redirects=False, timeout=timeout, headers=headers) as client:
        for _ in range(max_redirects + 1):
            err = ssrf_check(current)
            if err:
                raise SsrfBlocked(err)
            resp = client.get(current)
            if resp.is_redirect:
                loc = resp.headers.get("location")
                if not loc:
                    return resp  # redirect nhưng thiếu Location → trả nguyên trạng
                current = urljoin(current, loc)
                continue
            return resp
    raise SsrfBlocked(f"Quá nhiều redirect (>{max_redirects}) — nghi ngờ redirect loop/bypass")
