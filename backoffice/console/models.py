"""映射 FastAPI 侧的五张业务表。

**managed = False 是这个文件的灵魂**：
- Django 不会为这些模型生成迁移，也不会在 migrate 时创建/修改它们；
- 表结构的唯一主人是 FastAPI 侧的 Alembic；
- Django 只是"另一个客户端"，借 ORM 来查询和展示。

字段必须和 Alembic 建出来的列**逐一对上**（列名、可空性、类型），
对不上的后果是后台页面报错，而不是自动改表——这正是我们想要的。
"""

from django.db import models

STATUS_CHOICES = [
    ("PENDING", "待签到"),
    ("CHECKED_IN", "已签到"),
    ("COMPLETED", "已完成"),
    ("CANCELLED", "已取消"),
    ("NO_SHOW", "爽约"),
]


class User(models.Model):
    id = models.AutoField(primary_key=True)
    email = models.CharField(max_length=255, unique=True)
    student_no = models.CharField(max_length=32, unique=True, null=True, blank=True)
    name = models.CharField(max_length=64)
    hashed_password = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    no_show_count = models.IntegerField(default=0)
    banned_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "users"
        verbose_name = "预约用户"
        verbose_name_plural = "预约用户"

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"


class Area(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "areas"
        verbose_name = "自习区"
        verbose_name_plural = "自习区"

    def __str__(self) -> str:
        return self.name


class Seat(models.Model):
    id = models.AutoField(primary_key=True)
    area = models.ForeignKey(
        Area, on_delete=models.DO_NOTHING, db_column="area_id", related_name="seats"
    )
    code = models.CharField(max_length=16)
    has_power = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "seats"
        verbose_name = "座位"
        verbose_name_plural = "座位"

    def __str__(self) -> str:
        return self.code


class Reservation(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        User, on_delete=models.DO_NOTHING, db_column="user_id", related_name="reservations"
    )
    seat = models.ForeignKey(
        Seat, on_delete=models.DO_NOTHING, db_column="seat_id", related_name="reservations"
    )
    date = models.DateField()
    start_slot = models.IntegerField()
    end_slot = models.IntegerField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="PENDING")
    checked_in_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "reservations"
        verbose_name = "预约单"
        verbose_name_plural = "预约单"
        ordering = ("-id",)

    def __str__(self) -> str:
        return f"#{self.id} {self.seat_id} {self.date}"


class ReservationSlot(models.Model):
    """占用格子：一行 = 一个座位在一天里的一个 30 分钟时段。"""

    id = models.AutoField(primary_key=True)
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.DO_NOTHING,
        db_column="reservation_id",
        related_name="slots",
    )
    seat = models.ForeignKey(
        Seat, on_delete=models.DO_NOTHING, db_column="seat_id", related_name="slots"
    )
    date = models.DateField()
    slot_index = models.IntegerField()

    class Meta:
        managed = False
        db_table = "reservation_slots"
        verbose_name = "占用格子"
        verbose_name_plural = "占用格子"
        ordering = ("-id",)

    def __str__(self) -> str:
        return f"{self.seat_id} {self.date} slot={self.slot_index}"