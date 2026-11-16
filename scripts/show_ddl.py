from sqlalchemy.schema import CreateTable

import app.models  # noqa: F401  触发模型注册，否则 metadata 里没有表
from app.db.base import Base
from app.db.session import engine

for table in Base.metadata.sorted_tables:
    print(CreateTable(table).compile(engine))
    print("-" * 60)