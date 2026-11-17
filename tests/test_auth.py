from httpx import AsyncClient

REGISTER_PAYLOAD = {
    "email": "test@example.com",
    "student_no": "20220001",
    "password": "Passw0rd!",
    "name": "测试用户",
}


async def test_register_success(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "test@example.com"
    assert body["id"] == 1
    # 白名单：密码哈希绝不能出现在响应里
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_duplicate_email(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "邮箱或学号已被注册"


async def test_login_and_get_me(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "test@example.com", "password": "Passw0rd!"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    assert resp.json()["token_type"] == "bearer"

    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "test@example.com"


async def test_me_without_token(client: AsyncClient):
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401