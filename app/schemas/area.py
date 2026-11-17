from pydantic import BaseModel, ConfigDict


class AreaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None


class SeatRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    has_power: bool
    is_active: bool