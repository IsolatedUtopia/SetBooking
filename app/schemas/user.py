import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STUDENT_NO_RE = re.compile(r"^\d{8,12}$")

# 密码上限 16 个字符：产品决定，且保证 UTF-8 编码后不超过 64 字节，
# 永远低于 bcrypt 的 72 字节硬限制，所以 security.py 里的切片实际不会触发（仅兜底）。
MAX_PASSWORD_CHARS = 16


class UserRegister(BaseModel):
    student_no: str = Field(min_length=8, max_length=12)
    email: str
    password: str
    name: str = Field(min_length=1, max_length=64)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        v = v.strip().lower()  #邮箱归一化
        if not EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if len(v) < 8 or len(v) > MAX_PASSWORD_CHARS:
            raise ValueError(f"密码长度需为 8-{MAX_PASSWORD_CHARS} 个字符")
        return v

    @field_validator("student_no")
    @classmethod
    def check_student_no(cls, v: str) -> str:
        v = v.strip()
        if not STUDENT_NO_RE.match(v):
            raise ValueError("学号应为 8-12 位数字")
        return v


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    student_no: str | None
    name: str
    created_at: datetime