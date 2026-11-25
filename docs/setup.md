# 环境搭建

面向"我要在本地把它跑起来"的读者。项目概览请回 [README](../README.md)，设计细节见 [design.md](design.md)。

---

## 0. 前置要求

| 依赖 | 版本 | 备注 |
|---|---|---|
| Python | 3.12+ | 本项目在 3.14.10 上开发 |
| MySQL | 8.0.11+ | 用 8.0.46 验证；**不要用 8.4 以下 + Django 6**（见文末坑 1） |
| Git | 任意 | 克隆仓库用 |

检查：

```powershell
python --version
mysql --version
```

---

## 1. 建库与专用账号

用 root 登录 MySQL：

```powershell
mysql -u root -p
```

```sql
CREATE DATABASE seat_booking CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER 'seat'@'localhost'  IDENTIFIED BY 'your-password';
CREATE USER 'seat'@'127.0.0.1' IDENTIFIED BY 'your-password';

GRANT ALL PRIVILEGES ON seat_booking.* TO 'seat'@'localhost';
GRANT ALL PRIVILEGES ON seat_booking.* TO 'seat'@'127.0.0.1';
FLUSH PRIVILEGES;
```

两点说明：

- MySQL 的账号是"**用户名 + 来源主机**"，`'seat'@'localhost'` 走 socket，`'seat'@'127.0.0.1'` 走 TCP。应用连的是后者，但两个都建可以避免"命令行能连、程序连不上"的困惑。
- 程序使用 `seat` 这个最小权限账号；`root` 只用来建库和排障。

---

## 2. 克隆与虚拟环境

```powershell
git clone git@github.com:IsolatedUtopia/SetBooking.git
cd SetBooking

python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux：

```bash
source .venv/bin/activate
```

若 PowerShell 报 `Activate.ps1 cannot be loaded because running scripts is disabled`：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

确认虚拟环境生效：

```powershell
python -c "import sys; print(sys.executable)"
# 应输出 ...\SetBooking\.venv\Scripts\python.exe
```

---

## 3. 安装依赖

```powershell
pip install -r requirements.txt
```

国内网络慢可加镜像：

```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

关键依赖里有两个容易被忽略、但缺了就报错的：

- `cryptography`：MySQL 8 默认 `caching_sha2_password`，PyMySQL/aiomysql 首次认证需要它做 RSA 交换
- `tzdata`：Windows 上 `zoneinfo` 没有系统时区库，缺了会 `ZoneInfoNotFoundError: No time zone found with key Asia/Shanghai`

---

## 4. 配置 `.env`

```powershell
Copy-Item .env.example .env
```

生成一个 JWT 密钥：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

写入 `E:\Projects\SetBooking\.env`：

```ini
DATABASE_URL=mysql+aiomysql://seat:your-password@127.0.0.1:3306/seat_booking?charset=utf8mb4
JWT_SECRET=粘贴上一步生成的长随机串
```

注意事项：

- 密码里有 `@ : / ?` 等字符时需要 URL 编码（`@` → `%40`）；
- `.env` 已在 `.gitignore` 中，**不要**提交；
- `settings` 用了 `@lru_cache`，改完 `.env` 必须重启服务才生效。

---

## 5. 建表与种子数据

```powershell
alembic upgrade head
python -m scripts.seed
```

期望输出：

```text
created area id=1 name=A 区·靠窗
area=A 区·靠窗 id=1, new seats=30
created area id=2 name=B 区·静音
area=B 区·静音 id=2, new seats=12
created area id=3 name=C 区·维修中
area=C 区·维修中 id=3, new seats=0
done, total new seats=42
```

- 种子脚本是**幂等**的（按区域名查、不存在才插），重复跑输出 `new seats=0`；
- C 区故意 0 座，用来测"区域存在但无座位"的边界；
- 中文显示成方块是终端编码问题，不影响数据库内容：`chcp 65001` 或 `$env:PYTHONIOENCODING="utf-8"` 可解决。

验证表结构：

```powershell
python -m sqlite3 --version   # 不需要
mysql -u seat -p seat_booking -e "SHOW CREATE TABLE reservation_slots\G"
```

确认里面有：

```text
UNIQUE KEY uq_reservation_slots_seat_slot (seat_id,date,slot_index)
```

**这行就是防超卖的全部秘密**，务必亲眼确认。

---

## 6. 启动 API

```powershell
uvicorn app.main:app --reload --port 8000
```

启动日志应包含：

```text
INFO:app.main:定时任务已启动：每 60 秒扫描一次超时未签到
INFO:     Application startup complete.
```

验证：

```powershell
curl.exe http://127.0.0.1:8000/health
# {"status":"ok"}
```

浏览器打开 <http://127.0.0.1:8000/docs>，依次：

1. `POST /api/v1/auth/register` 注册一个账号；
2. 点右上角 **Authorize**，`username` 填邮箱、`password` 填密码，`client_id` / `client_secret` 留空；
3. `POST /api/v1/reservations` 试创建预约。

> 刷新页面后授权会丢失，需要重新 Authorize；token 1 小时过期。

---

## 7. 启动运营后台（可选）

另开一个终端（`--reload` 的 uvicorn 会占住当前窗口）：

```powershell
cd E:\Projects\SetBooking\backoffice
.\.venv\Scripts\Activate.ps1     # 若新终端未激活
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 8001
```

访问 <http://127.0.0.1:8001/admin/>。

说明：

- `migrate` 只会建 Django 自己的表（`auth_*`、`django_admin_log`、`django_session`…），业务 5 张表是 `managed=False`，不受影响；
- 后台默认**全字段只读**，仅开放两个安全写：座位的「Is active」、账号的「Banned until」；
- 所有写操作会记录在 `django_admin_log`。

---

## 8. 跑测试

```powershell
cd E:\Projects\SetBooking
python -m pytest -q --cov=app --cov-report=term-missing
```

期望：

```text
31 passed
TOTAL   568   58   90%
Required test coverage of 85.0% reached.
```

必须用 `python -m pytest`（把项目根加入 `sys.path`），直接敲 `pytest` 可能报 `ModuleNotFoundError: No module named 'app'`。

测试不连真实 MySQL——用内存 SQLite + `httpx.ASGITransport` 进程内调用，因此不需要启动服务。

---

## 9. 常见坑

**坑 1：`NotSupportedError: MySQL 8.4 or later is required (found 8.0.46)`**
Django 6.x 要求 MySQL 8.4+。本项目固定 **Django 5.2 LTS**（支持 MySQL 8.0.11+）。
若 `pip install` 自动装了 6.x，改 `requirements.txt` 或用 `pip install "django>=5.2,<6.0"`。

**坑 2：`'cryptography' package is required for sha256_password or caching_sha2_password`**
只出现在"新进程第一次连 MySQL"时，因为服务器缓存了上一次认证的摘要。
`pip install cryptography` 即可（已在 requirements 中）。

**坑 3：`ZoneInfoNotFoundError`**
Windows 缺时区数据，`pip install tzdata`。

**坑 4：时区差 8 小时**
`app/db/session.py` 里 `init_command = "SET time_zone = '+08:00'"` 必须存在。
验证：

```powershell
python -c "import asyncio; from sqlalchemy import text; from app.db.session import engine
async def m():
    async with engine.connect() as c:
        print((await c.execute(text('SELECT @@session.time_zone'))).scalar())
asyncio.run(m())"
```

期望 `+08:00`。

**坑 5：`alembic downgrade` 报 `Cannot drop index ... needed in a foreign key constraint`**
MySQL 里外键会"借用"索引，删除顺序必须正确。本项目的 `downgrade()` 只按倒序 `drop_table`，不单独 `drop_index`。
做实验（如临时删除唯一索引验证超卖）时，先补一个普通索引再删：

```sql
ALTER TABLE reservation_slots ADD INDEX ix_tmp_seat_id (seat_id);
ALTER TABLE reservation_slots DROP INDEX uq_reservation_slots_seat_slot;
-- 实验结束务必换回来
ALTER TABLE reservation_slots ADD CONSTRAINT uq_reservation_slots_seat_slot
  UNIQUE (seat_id, date, slot_index);
ALTER TABLE reservation_slots DROP INDEX ix_tmp_seat_id;
```

**坑 6：`Access denied ... (using password: NO)`**
`.env` 没被读到（文件名写错、放在错误目录、或 `local_settings` 里密码为空）。
用这条确认：

```powershell
python -c "from app.core.config import settings; print(settings.database_url)"
```

**坑 7：端口被占用**
`8000` 被别的东西占了就换：`uvicorn app.main:app --reload --port 8010`，同时改前端/Swagger 的地址。

---

## 10. CI 在本机复现

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q --cov=app --cov-report=term-missing
cd backoffice; python manage.py check --database default
```

三条命令与 `.github/workflows/ci.yml` 里的步骤一一对应。**本地跑的和 CI 跑的不一致，是 CI 红的头号原因**（比如只 lint `app/` 而 CI lint 全仓库）。