# 部署说明

> **验证状态**：本文档中的「容器编排、健康检查、时区、静态资源」四部分已在本地
> Windows + Docker Desktop 实测通过（见 `docs/benchmark.md`）；标注 ❌ 的章节
> （Nginx 反代、HTTPS、云主机、备份恢复演练）**没有条件实测**，是按官方文档
> 写出的方案，请自行验证后再用于生产。

## 1. 目标架构

```text
浏览器
  │ 443
  ▼
Nginx（❌ 未验证）
  ├─ /api/  /docs  /openapi.json  /health ──► 127.0.0.1:8000  FastAPI
  └─ /admin/  /static/                    ──► 127.0.0.1:8001  Django Admin
                         │
                         ▼
        docker compose: api + admin + mysql（仅内部网络，不对外发布端口）
```

两个应用进程、一个数据库。`api` 与 `admin` 不直接对外暴露端口，只由 Nginx 转发；
MySQL 端口不映射到宿主机，只在 compose 内部网络可达。

## 2. 前置条件

| 项 | 要求 | 检查命令 |
|---|---|---|
| 系统 | Ubuntu 22.04 / 24.04 LTS | `lsb_release -a` |
| Docker | ≥ 27（含 Compose v2 插件） | `docker --version` / `docker compose version` |
| 端口 | 80、443 对外；8000/8001 **不**对外 | `sudo ufw status` |
| 内存 | ≥ 2 GB（mysql + 两个容器） | `free -h` |
| 域名 | 可选；无域名可先用 IP + 自签证书 | — |

## 3. 服务器准备

```bash
# 3.1 时区：影响日志可读性。业务时区已在连接层钉死（SET time_zone='+08:00'），
#     所以即使服务器是 UTC，写库时间也不会错——但日志时间会差 8 小时。
sudo timedatectl set-timezone Asia/Shanghai
timedatectl

# 3.2 非 root 用户
sudo adduser deploy
sudo usermod -aG sudo deploy
sudo usermod -aG docker deploy      # 免 sudo 用 docker，需重新登录生效

# 3.3 防火墙：只开 SSH / HTTP / HTTPS
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## 4. 获取代码与配置 ❌ 未验证（云主机环境）

```bash
su - deploy
git clone https://github.com/<你的账号>/SetBooking.git
cd SetBooking
```

### 4.1 生成 `.env`

密钥必须随机生成，**不要用仓库里 `docker-compose.yml` 的默认值**。三个随机值先算出来
再拼文件，避免「API 用的密码」和「MySQL 初始化的密码」写成两个不同的值：

```bash
APP_DB_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=\n')
ROOT_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=\n')
JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')

cat > .env <<EOF
DATABASE_URL=mysql+aiomysql://seat:${APP_DB_PASSWORD}@mysql:3306/seat_booking?charset=utf8mb4
JWT_SECRET=${JWT_SECRET}
MYSQL_PASSWORD=${APP_DB_PASSWORD}
MYSQL_ROOT_PASSWORD=${ROOT_PASSWORD}
EOF
chmod 600 .env
```

> `DATABASE_URL` 里的密码与 `MYSQL_PASSWORD` **必须完全相同**：前者给 API 连库用，
> 后者给 mysql 容器初始化 `seat` 账号用。两者不一致的表现是 API 启动后
> `Access denied for user 'seat'@'%' (using password: YES)`。

### 4.2 后台数据库连接

Django 的 `settings.py` 优先读环境变量，其次读 `local_settings.py`（已被 `.gitignore` 忽略）。
容器里没有环境变量，所以写 `local_settings.py`：

```bash
cat > backoffice/backoffice/local_settings.py <<EOF
DB_NAME = "seat_booking"
DB_USER = "seat"
DB_PASSWORD = "${APP_DB_PASSWORD}"
DB_HOST = "mysql"
DB_PORT = "3306"
EOF
chmod 600 backoffice/backoffice/local_settings.py
```

## 5. 启动与自检 ✅ 已在本地验证

```bash
# 5.1 构建（国内服务器建议指定镜像源，否则 pip 安装会很慢）
docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 5.2 启动（带生产覆盖文件：端口只绑回环地址）
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 5.3 等健康检查变 healthy：mysql 约 20s，api 约 30s
docker compose ps
```

期望输出：

```text
NAME                 SERVICE   STATUS
setbooking-api-1     api       Up (healthy)
setbooking-admin-1   admin     Up
setbooking-mysql-1   mysql     Up (healthy)
```

```bash
# 5.4 自检四项
curl -s http://127.0.0.1:8000/health                                  # {"status":"ok","database":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/docs   # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/admin/ # 200
docker compose logs api --tail 20

# 5.5 首次初始化（只需执行一次）
docker compose exec api python -m scripts.seed                        # 3 个区域 / 42 个座位，可重复执行
docker compose exec admin python manage.py createsuperuser            # 建后台管理员
```

> 容器内的数据库是**独立的一份**，与开发机上的 MySQL80 不共享数据。所以首次启动后
> `users` 表是空的，需要重新注册学生账号（`POST /api/v1/auth/register`）。

## 6. 生产覆盖文件

`docker-compose.prod.yml`（仓库根目录）：

```yaml
services:
  api:
    ports:
      - "127.0.0.1:8000:8000"
  admin:
    ports:
      - "127.0.0.1:8001:8001"
```

作用：把 8000/8001 从「绑定所有网卡」改成「只绑定回环地址」，外部只能经 Nginx 访问。
Compose 会用后加载的文件覆盖前面的 `ports` 列表。

## 7. Nginx 反代 ❌ 未验证

```bash
sudo apt install -y nginx
sudo cp deploy/nginx.conf /etc/nginx/sites-available/setbooking
sudo ln -s /etc/nginx/sites-available/setbooking /etc/nginx/sites-enabled/setbooking
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

配置要点（完整样例见 `deploy/nginx.conf`）：

- `/api/`、`/docs`、`/redoc`、`/openapi.json`、`/health` → `127.0.0.1:8000`
- `/admin/`、`/static/` → `127.0.0.1:8001`
- **`/openapi.json` 必须单独转发**：漏了它 Swagger 页面能打开但接口列表是空的
- 传 `X-Forwarded-For` / `X-Forwarded-Proto`，否则应用日志里全是 `127.0.0.1`

## 8. HTTPS ❌ 未验证

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d booking.example.com      # 按提示选择「自动跳转到 HTTPS」
sudo systemctl list-timers | grep certbot        # 确认自动续期任务存在
```

续期由 `certbot.timer` 负责，不需要手写 cron。

## 9. 备份与恢复

### 9.1 每日备份（03:00）❌ 未验证

```bash
sudo mkdir -p /var/backups/setbooking
sudo apt install -y cron
sudo tee /etc/cron.d/setbooking-backup > /dev/null <<'EOF'
0 3 * * * deploy cd /home/deploy/SetBooking && \
  docker compose exec -T mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --quick seat_booking' \
  | gzip > /var/backups/setbooking/seat_booking-$(date +\%F).sql.gz && \
  find /var/backups/setbooking -name '*.sql.gz' -mtime +14 -delete
EOF
```

> `MYSQL_ROOT_PASSWORD` 是容器内部的环境变量，在 `sh -c` 里直接展开，**不会**出现在
> 宿主机的进程列表里。备份文件建议再同步到对象存储或另一台机器（本机备份挡不住磁盘故障）。

### 9.2 恢复演练 ❌ 未验证

```bash
gunzip -c /var/backups/setbooking/seat_booking-2026-11-27.sql.gz \
  | docker compose exec -T mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" seat_booking'
```

**没演练过的备份等于没有备份**——上线前至少恢复一次到临时库，确认行数对得上。

### 9.3 数据卷备份（可选）

业务数据全在 MySQL 里；`mysql-data` 卷属于双保险：

```bash
docker run --rm -v setbooking_mysql-data:/data -v /var/backups:/backup alpine \
  tar czf /backup/mysql-volume-$(date +%F).tar.gz -C /data .
```

## 10. 升级与回滚

```bash
# 10.1 升级前给当前镜像打 tag，作为回滚锚点
docker tag setbooking-api:latest   setbooking-api:2026-11-27
docker tag setbooking-admin:latest setbooking-admin:2026-11-27

# 10.2 拉代码 → 重建 → 看健康
git pull
docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
docker compose up -d
docker compose ps

# 10.3 回滚（镜像层）
docker tag setbooking-api:2026-11-27 setbooking-api:latest
docker compose up -d
```

**迁移回滚要谨慎**：`alembic downgrade` 会 DROP 表/列，数据不可恢复。线上优先「向前修复」
（新写一条迁移），而不是 downgrade。这一点在 `docs/design.md` 的迁移章节也提到过。

## 11. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `api` 一直 `starting` | MySQL 未就绪或密码不匹配 | `docker compose logs mysql`；核对 `.env` 与 `local_settings.py` |
| `Access denied ... (using password: NO)` | `local_settings.py` 里 `DB_PASSWORD` 为空 | 检查 `settings.py` 的 `except ModuleNotFoundError` 是否吞掉了真实错误 |
| `RuntimeError: 'cryptography' package is required` | MySQL 8 `caching_sha2_password` 首次认证需要 RSA | 确认 `requirements.txt` 含 `cryptography` |
| 后台是裸 HTML（无样式） | 静态文件没收集 / WhiteNoise 位置不对 | 镜像里是否执行 `collectstatic`；middleware 是否紧跟 `SecurityMiddleware` |
| 时间差 8 小时 | 连接层时区没有钉死 | 核对 `app/db/session.py` 的 `init_command` |
| `bind: address already in use` | 宿主机已有服务占用端口 | `sudo ss -lntp \| grep 800`；或改用生产覆盖文件绑回环地址 |
| `Health check failed` 但服务能访问 | healthcheck 用的是 `127.0.0.1` | 容器内自检命令要在容器视角执行 |

## 12. 上线前安全清单

- [ ] `.env` 中 `JWT_SECRET`、`MYSQL_PASSWORD`、`MYSQL_ROOT_PASSWORD` 全部随机生成，未沿用仓库默认值
- [ ] `.env` 与 `local_settings.py` 权限为 `600`，两者都不在 git 里
- [ ] `docker compose ps` 中 mysql 的 PORTS 列不含 `0.0.0.0:3306`
- [ ] `DEBUG = False`，`ALLOWED_HOSTS` 只含真实域名（见下方「生产化改造清单」）
- [ ] 学生账号密码 ≠ 后台管理员密码 ≠ 数据库密码
- [ ] 备份 cron 已生效（`ls /var/backups/setbooking`），**恢复步骤演练过**
- [ ] HTTPS 已启用，HTTP 自动跳转
- [ ] 已知未做：登录限流、异常告警、监控面板、日志轮转

## 13. 生产化改造清单（未在仓库中实现）

仓库当前是**开发默认值**，正式上线前需要改这几处：

### 13.1 `backoffice/backoffice/settings.py`

```python
import os

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]
```

并在 compose 的 `admin` 服务里加：

```yaml
    environment:
      DJANGO_DEBUG: "0"
      DJANGO_ALLOWED_HOSTS: "booking.example.com"
```

### 13.2 `app/core/config.py`（FastAPI）

`debug` 默认 `True`，生产建议通过环境变量覆盖为 `false`；`settings.jwt_secret` 必须来自 `.env`
（仓库默认值仅用于本地开发）。

### 13.3 尚未实现、但面试会问的

- 登录限流（防暴力破解）：接口层加滑动窗口或 Redis 计数
- 跨进程状态（多 worker 下线时 JWT 无法主动失效）：需要 Redis 黑名单
- 应用日志落到文件 + 轮转：目前是 stdout，由 `docker compose logs` 收集
