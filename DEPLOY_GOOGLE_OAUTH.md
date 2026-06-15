# Deploy note — Google Drive (per-user OAuth) trên AgentBase

> **Trạng thái:** THIẾT KẾ — tính năng Drive CHƯA code. File này ghi lại điều kiện
> deploy + rủi ro để khi triển khai không quên. Xem thêm: thiết kế flow ở lịch sử
> chat / `BE_CHANGES_FOR_FE.md` (FE impact).

## TL;DR

AgentBase **chạy được** luồng OAuth Drive — vì nó dùng **đúng cùng cơ chế với Google
login** đã có trong app và đã nằm trong kế hoạch deploy PUBLIC. Không cần năng lực đặc
biệt nào của AgentBase ngoài cái login đã cần.

> Phép kiểm rút gọn: **nếu Google login chạy được trên endpoint AgentBase PUBLIC →
> OAuth Drive chạy được theo.** Cùng pattern: browser → Google → callback về URL public
> → exchange token server-side → cookie.

---

## Điều kiện deploy (đã có sẵn)

| Yêu cầu | AgentBase | Ghi chú |
|---|---|---|
| URL public HTTPS, hostname ổn định cho `redirect_uri` | Custom Agent runtime PUBLIC (design Flow 7) | Đăng ký callback trong Google Console + set `GOOGLE_REDIRECT_BASE` |
| Browser gọi thẳng route `/auth/...`, `/web/` | App serve full web UI + `/auth` từ container (port 8080) | Runtime expose HTTP port as-is |
| Egress ra Google APIs (`oauth2.googleapis.com`, `www.googleapis.com/drive`) | App đã gọi Google (login) + MaaS + DuckDuckGo | Test 1 call Drive khi deploy phòng egress bị allowlist |

---

## 🔴 2 rủi ro PHẢI xử lý (config, không phải blocker kiến trúc)

### 1. Lưu trữ bền vững cho refresh_token
- `Dockerfile`: *"data/ là **ephemeral** nếu không mount volume"*.
- Refresh_token nằm trong bảng `oauth_credentials` (SQLite). Restart/redeploy không mount
  volume → **mất token** → user phải kết nối lại. (Rủi ro dùng chung với cả registry
  agents/skills/users.)
- **Cách xử lý:** dùng volume mount đã verify (plan 13/06), HOẶC production swap
  **Postgres** (`DATABASE_URL=postgresql://...` — design đã chừa sẵn DSN swap).

### 2. Secret phải ỔN ĐỊNH qua restart / instance
- `JWT_SECRET`: hiện fallback **random mỗi boot** (`app/auth/jwt_utils.py`). Không set →
  mỗi restart **văng hết session**. → **bắt buộc set env cố định** khi deploy.
- `OAUTH_ENC_KEY` (khóa mã hóa token Drive, env MỚI sẽ thêm): đổi/random → **không giải
  mã được token đã lưu**. → set env cố định.
- AgentBase **Identity module** giữ các secret này ổn định — miễn là đặt vào env.

---

## Multi-instance (nếu Runtime scale > 1)

| Thành phần | 1 instance (demo) | Nhiều instance |
|---|---|---|
| JWT session (stateless) | ✅ | ✅ nếu chung `JWT_SECRET` |
| OAuth `state` (cookie) | ✅ | ✅ stateless |
| Token store SQLite local | ✅ | ❌ mỗi instance 1 file riêng → **bắt buộc Postgres** |

Contest 1 instance + volume → ổn. Scale về sau → Postgres.

---

## Làm rõ: Identity module ≠ kho token per-user

AgentBase **Identity** inject **credential của chính app** (Google client_id/secret,
MaaS key, `OAUTH_ENC_KEY`) — **KHÔNG** phải nơi lưu token Google **của từng user**.
Token per-user do app tự quản (bảng `oauth_credentials` mã hóa). Đừng kỳ vọng Identity
thay phần đó.

---

## Env cần set khi deploy (cho Drive)

```
GOOGLE_CLIENT_ID=...            # đã có (login)
GOOGLE_CLIENT_SECRET=...        # đã có (login)
GOOGLE_REDIRECT_BASE=https://<agentbase-public-host>   # cố định, tránh host-header injection
JWT_SECRET=<chuỗi cố định>      # KHÔNG để trống (tránh random mỗi boot)
OAUTH_ENC_KEY=<Fernet key cố định>   # MỚI — khóa mã hóa refresh_token at-rest
DATABASE_URL=...                # volume-mounted SQLite hoặc Postgres (bền vững)
```

Google Cloud Console:
- Thêm **Authorized redirect URI**: `https://<host>/auth/google/drive/callback`
  (và `/auth/google/callback` cho login — nếu chưa).
- Bật **Google Drive API** cho project.
- Scope: `drive.readonly` (rộng, tiện demo) hoặc `drive.file` (least-privilege + Picker).

---

## Checklist verify khi deploy (test thật, đừng giả định)

- [ ] Google **login** chạy trên endpoint public (callback nhận được, cookie set).
- [ ] Hostname **HTTPS ổn định**, không đổi mỗi redeploy (để đăng ký redirect_uri).
- [ ] **Volume mount** giữ `hub.db` qua restart (refresh_token sống sót).
- [ ] Egress tới `www.googleapis.com` không bị chặn (gọi thử 1 API Drive).
- [ ] `JWT_SECRET` + `OAUTH_ENC_KEY` set **cố định** trong env container.
- [ ] (Nếu scale) `DATABASE_URL` trỏ Postgres dùng chung.

---

## Kết luận

Không có blocker kiến trúc. AgentBase chạy được luồng này như chạy Google login.
Hai điều kiện cần đảm bảo — **persistence (volume/Postgres)** và **secret ổn định** —
đều là cấu hình deploy, đã được design lường trước (volume mount + Postgres DSN swap +
Identity module).
