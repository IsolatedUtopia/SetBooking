# 设计说明

本文解释 SetBooking 的关键设计决策：为什么这样建模、并发下如何保证不超卖、时间与状态如何流转。
快速了解项目请回 [README](../README.md)。

---

## 1. 业务规则

| 规则 | 取值 |
|---|---|
| 营业时间 | 08:00 – 22:00 |
| 时段粒度 | 30 分钟一格，每天 28 格（`slot_index` 0–27，0 = 08:00–08:30） |
| 单次时长 | 1 – 4 格 |
| 每人每日上限 | 2 单 |
| 可预约范围 | 未来 7 天（含今天，已开始的时段不可约） |
| 签到窗口 | 开始前 15 分钟 ~ 开始后 30 分钟 |
| 超时未签到 | 开始 30 分钟后自动置为 `NO_SHOW` 并释放座位 |
| 爽约惩罚 | 累计 3 次 → 封禁 7 天（`banned_until` 到期自动解除） |
| 取消 | 立即释放座位，可重新预约 |

---

## 2. 核心问题：并发抢座会超卖

最直觉的写法是"先查再插"（check-then-act）：

```python
count = await session.scalar(
    select(func.count()).where(
        Reservation.seat_id == seat_id,
        Reservation.date == day,
    )
)
if count >= 1:
    raise ConflictError("已被预约")

session.add(Reservation(...))
await session.commit()
```

两个请求的时间线：

```text
请求 A: count → 0 ────────────────────────┐
请求 B:      count → 0 ───────────────┐   │
请求 A:                          INSERT ✔  │   ← 两条都成功
请求 B:                             INSERT ✔
```

**问题不在隔离级别**：这不是脏读，而是"查"与"插"之间存在时间窗口，两个事务都基于同一份旧快照做了决策。
即使把隔离级别提到 `REPEATABLE READ`，`SELECT COUNT(*)` 也不会阻塞另一个事务的 `INSERT`。

---

## 3. 解法：拆成时段格子 + 唯一索引

### 3.1 两张表

- `reservations`：业务单据（谁、哪个座位、哪天、从第几格到第几格、状态）。
- `reservation_slots`：占用明细，一次预约展开成 N 行，每行一个 30 分钟格子。

```sql
CREATE TABLE reservation_slots (
    id             BIGINT PRIMARY KEY AUTO_INCREMENT,
    reservation_id BIGINT NOT NULL,
    seat_id        BIGINT NOT NULL,
    date           DATE   NOT NULL,
    slot_index     INT    NOT NULL,

    CONSTRAINT uq_reservation_slots_seat_slot
        UNIQUE (seat_id, date, slot_index)
);
```

### 3.2 为什么这样就防住了

- 两个预约若要"抢同一个座位"，**必然至少共享一个 `(seat_id, date, slot_index)` 格子**；
- 共享格子 ⇒ 违反唯一索引 ⇒ 第二个事务的 `INSERT` 直接失败；
- 08:00–09:00 与 09:00–10:00 **不共享**格子（含头不含尾），所以相邻预约互不影响。

写入逻辑：

```python
reservation = Reservation(user_id=..., seat_id=..., date=day,
                          start_slot=start, end_slot=end)
reservation.slots = [
    ReservationSlot(seat_id=seat_id, date=day, slot_index=i)
    for i in range(start, end)
]
session.add(reservation)

try:
    await session.commit()
except IntegrityError:
    await session.rollback()      # 必须回滚，否则后续操作会 PendingRollbackError
    raise ConflictError("该座位在所选时段已被预约") from None
```

`from None` 用于掐断异常链，避免把底层 SQL 与约束名泄露给客户端。

### 3.3 取消 = 删格子

```python
reservation.status = ReservationStatus.CANCELLED
reservation.cancelled_at = _local_now()
reservation.slots.clear()        # delete-orphan，commit 时 DELETE 掉明细行
await session.commit()
```

单据保留（可审计），占用行删除（座位释放）。

---

## 4. 为什么不用其他两种建模

### 方案 A：用 24 位字符串存一天的占用（`"0011111000..."`）

- 无法建索引，无法用约束兜底；
- 更新需要"读 → 改字符串 → 写回"，并发下会**丢更新**；
- 查询"某时段哪些座位空"需要全表扫描 + 字符串运算。

（这是不少学生项目的做法，也是本项目刻意避开的反例。）

### 方案 B：存 `start_at` / `end_at` 两个时间列

- 冲突检测本质是"区间是否重叠"，即 `start_at < other.end_at AND end_at > other.start_at`；
- MySQL **没有** PostgreSQL 的 `EXCLUDE USING gist (seat_id WITH =, tsrange(start_at, end_at) WITH &&)`；
- 用普通索引无法表达"区间不重叠"，最终仍要退回应用层判重 → 回到超卖问题。

**代价**：格子化把粒度锁死在 30 分钟，无法实现"08:10–08:50"这种预约。对自习室场景可接受。

---

## 5. 数据模型

| 表 | 作用 | 关键约束 / 索引 |
|---|---|---|
| `users` | 学生账号 | `email`、`student_no` 唯一；`no_show_count`、`banned_until` |
| `areas` | 区域 | `name` 唯一 |
| `seats` | 座位 | `UNIQUE (area_id, code)`；`is_active`、`has_power` |
| `reservations` | 预约单据 | `(user_id, date)`、`(seat_id, date)` 索引；`CHECK (start_slot < end_slot)` |
| `reservation_slots` | 占用明细 | **`UNIQUE (seat_id, date, slot_index)`**；`reservation_id` 索引 |

### 追问 1：`reservation_slots` 为什么冗余存 `seat_id`？

唯一索引只能引用**本表**的列。若不存 `seat_id`，约束会退化成 `(reservation_id, date, slot_index)`——
不同预约的 `reservation_id` 各不相同，于是两张单可以同时写 `slot_index=4`，超卖照旧（实测过）。

第二个视角：这张表的主语其实是"**座位 × 日期 × 时段**"，`reservation_id` 才是附加属性。

**收益**：约束可用 + 日历查询免 join（`WHERE seat_id IN (...) AND date = ?` 走覆盖索引）。
**代价**：与 `reservations.seat_id` 存在漂移风险，因此约定：创建后不可变、只由单点写入、不支持换座。
（未来要支持换座，做法是删旧 slot 行 + 建新行，而不是 UPDATE `seat_id`。）

### 追问 2：为什么时间段用 `date + start_slot` 而不是两个 `DATETIME`？

见第 4 节：离散格子才能被唯一索引约束；同时 `date + slot_index` 让日历查询变成一次范围扫描，比时间区间比较更快也更简单。

---

## 6. 状态机

```text
                 ┌──────────────┐
   创建预约 ───▶  │   PENDING    │ ──签到──▶ CHECKED_IN ──结束──▶ COMPLETED
                 └──────┬───────┘
                        │
         ┌──────────────┼────────────────┐
         │              │                │
      用户取消        超时未签到         (超时扫描)
         │              │                │
         ▼              ▼                │
     CANCELLED       NO_SHOW ────────────┘
                        │
                   no_show_count += 1
                        │
              累计 >= 3 → banned_until = now + 7d，计数清零
```

| 迁移 | 触发者 | 条件 | 副作用 |
|---|---|---|---|
| `PENDING → CHECKED_IN` | 学生 | 开始前 15 分钟 ~ 开始后 30 分钟 | 写 `checked_in_at` |
| `PENDING → CANCELLED` | 学生 | 未结束的单 | 删 slot 行释放座位 |
| `PENDING → NO_SHOW` | 定时任务 | 当前时间 > 开始 + 30 分钟 | 删 slot 行、`no_show_count += 1` |
| `NO_SHOW → 封禁` | 定时任务 | 同一用户累计 3 次 | `banned_until = now + 7 天`，计数清零 |

**幂等**：定时任务用守卫式更新

```python
result = await session.execute(
    update(Reservation)
    .where(Reservation.id == rid, Reservation.status == ReservationStatus.PENDING)
    .values(status=ReservationStatus.NO_SHOW)
)
if result.rowcount == 0:
    continue          # 已被别的实例/上一轮处理过
```

只有 `rowcount == 1` 才继续删格子、加爽约次数——保证任务重跑不会重复计数、误封用户。

---

## 7. 时间语义

同一张表里绝不能混存两种时间基准。本项目约定：

| 用途 | 实现 | 原因 |
|---|---|---|
| 数据库存储（`created_at` / `checked_in_at` / `cancelled_at` / `banned_until`） | **北京时间**，连接层 `SET time_zone = '+08:00'` | 单区域业务，裸 SQL 可读；不依赖宿主机时区 |
| Python 侧取"现在" | `_local_now()` = `datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)` | 换机器 / CI 也不会漂移 |
| JWT 的 `iat` / `exp` | **UTC 秒级时间戳** | 协议要求 Unix 时间，与业务时间无关 |

连接层钉死写在 `app/db/session.py`：

```python
_connect_args = {}
if settings.database_url.startswith("mysql"):
    _connect_args["init_command"] = "SET time_zone = '+08:00'"
```

Windows 上 `ZoneInfo("Asia/Shanghai")` 需要 `tzdata` 包（已写入 `requirements.txt`），否则 `ZoneInfoNotFoundError`。

---

## 8. 有意的取舍

1. **`reservation_slots` 冗余 `seat_id`** —— 用一点冗余换取数据库级防超卖。
2. **时间段落在 `date + slot_index`** —— 让唯一索引可用，代价是粒度固定 30 分钟。
3. **Django Admin 与 FastAPI 共库** —— schema 只由 Alembic 管理，Django 模型 `managed=False`，避免两套迁移打架。
4. **一个进程内跑定时任务** —— 降低部署复杂度，代价是不支持多实例（见 README「已知限制」）。