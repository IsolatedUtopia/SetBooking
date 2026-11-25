# SetBooking · 自习室座位预约

[![CI](https://github.com/IsolatedUtopia/SetBooking/actions/workflows/ci.yml/badge.svg)](https://github.com/IsolatedUtopia/SetBooking/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![Tests](https://img.shields.io/badge/tests-31%20passed-brightgreen)
![Coverage](https://img.shields.io/badge/coverage-89.79%25-green)

自习室座位预约后端：**用数据库唯一索引根治并发抢座超卖**，而不是靠应用层"先查再插"。

- **防超卖**：预约拆成 30 分钟格子 + `UNIQUE (seat_id, date, slot_index)`；20 并发抢座实测 **1 成功 / 19 冲突 / 0 超卖**，移除索引则 20 单全部落库（[压测记录](docs/benchmark.md)）
- **完整闭环**：JWT 鉴权、日历查询、签到窗口、超时自动释放、爽约 3 次自动封禁
- **工程化**：31 个测试、89.79% 覆盖率、ruff、GitHub Actions（真实 MySQL 迁移）

## 架构

```text
学生 ──▶ FastAPI :8000 ──┐
                         ├──▶ MySQL 8.0 (seat_booking)
运营 ──▶ Django Admin :8001 ┘
```

两个进程一个库：schema 由 Alembic 独占管理，Django 侧 `managed=False` 只读映射，仅开放两个安全写字段。

## 快速开始

```powershell
git clone git@github.com:IsolatedUtopia/SetBooking.git
cd SetBooking
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # 填入 MySQL 连接串与 JWT_SECRET
alembic upgrade head
python -m scripts.seed           # A 区 30 座 / B 区 12 座
uvicorn app.main:app --reload --port 8000
```

打开 <http://127.0.0.1:8000/docs> 直接调接口。详细的建库、运营后台启动与环境要求见 [docs/setup.md](docs/setup.md)。

## 技术栈

FastAPI · SQLAlchemy 2.0 (async) · MySQL 8.0 · Alembic · Pydantic v2 · PyJWT/bcrypt · APScheduler · Django 5.2 Admin · pytest · ruff · GitHub Actions

## 文档

| 文档 | 内容 |
|---|---|
| [docs/design.md](docs/design.md) | 防超卖方案推导、数据模型取舍、状态机 |
| [docs/benchmark.md](docs/benchmark.md) | 并发压测实验 A/B 的完整数据与复现方式 |
| [docs/api.md](docs/api.md) | 11 个端点 + 错误码约定 |
| [docs/setup.md](docs/setup.md) | 环境搭建、Django 后台、常见坑 |

## 已知限制

- 定时任务在进程内，仅支持单实例（多实例需 Redis 锁）
- 只有 access token，无 refresh token 与登出黑名单
- 业务时间固定北京时间，未做多时区
- 暂无前端，交互走 Swagger UI 与 Django Admin