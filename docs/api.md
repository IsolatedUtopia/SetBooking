# API 文档

- Base URL：`http://127.0.0.1:8000`
- 交互式文档：`/docs`（Swagger UI）、`/redoc`
- 机器可读描述：`/openapi.json`
- 鉴权方式：`Authorization: Bearer <access_token>`

---

## 认证流程

```text
POST /api/v1/auth/register  → 201  创建账号
POST /api/v1/auth/login     → 200  { access_token, token_type }
后续请求携带 Header: Authorization: Bearer <access_token>
```

登录使用 OAuth2 密码流，`Content-Type: application/x-www-form-urlencoded`，字段 `username`（邮箱或学号）与 `password`。
token 有效期 60 分钟（`ACCESS_TOKEN_EXPIRE_MINUTES`）。

---

## 端点一览

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/health` | – | 探活，含数据库连通性 |
| POST | `/api/v1/auth/register` | – | 注册 |
| POST | `/api/v1/auth/login` | – | 登录，签发 token |
| GET | `/api/v1/users/me` | ✔ | 当前用户 |
| GET | `/api/v1/areas` | – | 区域列表 |
| GET | `/api/v1/areas/{area_id}/seats` | – | 区域下的座位 |
| GET | `/api/v1/areas/{area_id}/calendar?date=YYYY-MM-DD` | – | 某日座位矩阵与占用情况 |
| POST | `/api/v1/reservations` | ✔ | 创建预约 |
| GET | `/api/v1/reservations/me` | ✔ | 我的预约（最近 50 条） |
| POST | `/api/v1/reservations/{id}/check-in` | ✔ | 签到 |
| DELETE | `/api/v1/reservations/{id}` | ✔ | 取消并释放座位 |

---

## 详细说明

### GET /health

```json
{ "status": "ok" }
```

数据库不可用时返回 503。

### POST /api/v1/auth/register

```json
{
  "email": "student@example.com",
  "student_no": "20220001",
  "password": "Passw0rd!",
  "name": "张三"
}
```

- `student_no`：8–12 位数字
- `password`：8–16 个字符
- `email` 会做 `strip().lower()` 归一化

成功 `201`：

```json
{
  "id": 1,
  "email": "student@example.com",
  "student_no": "20220001",
  "name": "张三",
  "created_at": "2026-11-25T09:12:00"
}
```

冲突 `409`：`{"detail": "邮箱或学号已被注册"}`

### POST /api/v1/auth/login

表单提交：`username=student@example.com&password=Passw0rd!`

成功 `200`：

```json
{ "access_token": "eyJhbGciOi...", "token_type": "bearer" }
```

失败 `401`：`{"detail": "邮箱或密码错误"}`（用户不存在与密码错误共用同一文案，避免用户枚举）

### GET /api/v1/areas

```json
[
  { "id": 1, "name": "A 区·靠窗", "description": "安静、靠窗、有插座" },
  { "id": 2, "name": "B 区·静音", "description": "全程禁言，适合刷题" }
]
```

### GET /api/v1/areas/{area_id}/seats

```json
[
  { "id": 1, "code": "A-01", "has_power": true, "is_active": true },
  { "id": 2, "code": "A-02", "has_power": false, "is_active": true }
]
```

区域不存在返回 `404`。

### GET /api/v1/areas/{area_id}/calendar?date=2026-11-26

```json
{
  "area_id": 1,
  "date": "2026-11-26",
  "slot_count": 28,
  "slots": [
    { "slot_index": 0, "label": "08:00-08:30" },
    { "slot_index": 1, "label": "08:30-09:00" }
  ],
  "seats": [
    { "seat_id": 1, "code": "A-01", "has_power": true, "occupied_slots": [0, 1] },
    { "seat_id": 2, "code": "A-02", "has_power": false, "occupied_slots": [] }
  ]
}
```

- `slots` 固定 28 项，前端可直接拿来画时间轴；
- 每个座位只回**已占用**的格子（稀疏数组），30 座满座也只有几百个整数；
- 过去日期或超出 7 天窗口返回 `400`。

### POST /api/v1/reservations

```json
{
  "seat_id": 1,
  "date": "2026-11-26",
  "start_slot": 0,
  "end_slot": 2
}
```

`end_slot` 不含（上例 = 08:00–09:00 两个格）。

成功 `201`：

```json
{
  "id": 1,
  "seat_id": 1,
  "seat": { "id": 1, "code": "A-01" },
  "date": "2026-11-26",
  "start_slot": 0,
  "end_slot": 2,
  "status": "PENDING",
  "created_at": "2026-11-25T14:03:11",
  "checked_in_at": null,
  "cancelled_at": null
}
```

| 状态码 | 场景 |
|---|---|
| 400 | 超过 4 格 / 时段越界 / 昨天 / 已开始的时段 / 当日已满 2 单 |
| 403 | 账号处于封禁期 |
| 404 | 座位不存在或已停用 |
| 409 | 座位已被占；或你在该时段已有预约 |
| 422 | 请求体格式错误（Pydantic） |

### GET /api/v1/reservations/me

返回 `ReservationRead` 数组，按日期倒序、开始时段正序，最多 50 条。

### POST /api/v1/reservations/{id}/check-in

- 成功 `200`，状态变为 `CHECKED_IN`，返回更新后的预约；
- `400`：还没到签到时间 / 签到已截止（文案带具体时间，如 `08:30 后视为爽约`）；
- `409`：已签到、已取消、已结束；
- `404`：不存在或不属于当前用户。

### DELETE /api/v1/reservations/{id}

- 成功 `204`（无响应体），预约状态改为 `CANCELLED`，占用格子被删除，座位立刻可再约；
- `409`：已经取消过 / 已结束；
- `404`：不存在或不属于当前用户（不返回 403，避免通过状态码探测他人预约是否存在）。

---

## 错误响应约定

所有业务错误统一为：

```json
{ "detail": "人类可读的中文说明" }
```

| 状态码 | 含义 |
|---|---|
| 400 | 请求语义不合法（时间窗口、配额、越界） |
| 401 | 未认证 / token 无效或过期 |
| 403 | 已认证但被禁止（封禁中） |
| 404 | 资源不存在或无权访问 |
| 409 | 与当前资源状态冲突（占座、重复操作） |
| 422 | 请求体校验失败（字段类型/长度/格式） |
| 503 | 依赖不可用（健康检查） |

**401 的两种文案**可以帮助排查：

- `Not authenticated`：根本没带 token（FastAPI 内建）
- `无效或已过期的凭证`：带了 token 但签名错/过期（应用层校验）

---

## 约定与限制

- 无分页：`/reservations/me` 固定返回最近 50 条。
- 无 refresh token：过期需重新登录。
- 时间均为北京时间，字符串不带时区后缀。
- 目前只有 JSON 接口，没有前端页面；交互请用 `/docs`。