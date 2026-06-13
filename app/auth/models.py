from dataclasses import dataclass, field


@dataclass
class UserInfo:
    id: str
    email: str
    name: str
    picture: str
    role: str   # "user" | "admin"


@dataclass
class GuestUser:
    role: str = field(default="guest")
    id: str = field(default="guest")
    email: str = field(default="guest")
    name: str = field(default="Khách")
    picture: str = field(default="")
