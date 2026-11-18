from httpx import AsyncClient

PASSWORD = "Passw0rd!"


async def register_and_login(
    client: AsyncClient,
    email: str = "student@example.com",
    student_no: str = "20220001",
) -> dict[str, str]:
    """注册一个用户并登录，返回可直接用的 Authorization 头。"""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "student_no": student_no,
            "password": PASSWORD,
            "name": "测试用户",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
