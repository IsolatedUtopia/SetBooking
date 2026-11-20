"""运营后台的展示配置。

当前一律**只读**，原因写在 ReadOnlyAdmin 的注释里：后台直接改表会绕过
FastAPI service 层的业务不变量。等 W3D2 再单独开放"安全的写"（例如座位启停用）。
"""

from django.contrib import admin
from django.db.models import Count

from console.models import Area, Reservation, ReservationSlot, Seat, User

admin.site.empty_value_display = "-"
admin.site.site_header = "SetBooking 运营后台"
admin.site.site_title = "SetBooking"
admin.site.index_title = "数据管理"

class ReadOnlyAdmin(admin.ModelAdmin):
    """只读后台的公共基类。

    直接改表会绕过这些不变量：
    - 把 reservations.status 改成 CHECKED_IN 不会补 checked_in_at；
    - 手删 reservation_slots 的一行不会同步取消预约单；
    - 改 reservation_slots.seat_id 会造成"幽灵占用"（座位被占但日历不显示）。
    所以后台先只做"看"，写操作留给后续单独的接口。
    """

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class SeatInline(ReadOnlyInline):
    model = Seat
    fields = ("code", "has_power", "is_active")
    readonly_fields = fields


class ReservationSlotInline(ReadOnlyInline):
    model = ReservationSlot
    fields = ("date", "slot_index")
    readonly_fields = fields


# @admin.register(User)
# class UserAdmin(ReadOnlyAdmin):
#     list_display = (
#         "id",
#         "name",
#         "email",
#         "student_no",
#         "is_active",
#         "no_show_count",
#         "banned_until",
#         "created_at",
#     )
#     list_filter = ("is_active",)
#     search_fields = ("email", "student_no", "name")
#     ordering = ("id",)
#     # 密码哈希永远不显示在后台
#     exclude = ("hashed_password",)
@admin.register(User)
class UserAdmin(ReadOnlyAdmin):
    list_display = (
        "id", "name", "email", "student_no", "is_active",
        "no_show_count", "banned_until", "created_at",
    )
    list_filter = ("is_active",)
    search_fields = ("email", "student_no", "name")
    ordering = ("id",)
    exclude = ("hashed_password",)

    readonly_fields = ("id", "created_at")
    fieldsets = (
        ("账号信息", {"fields": ("id", "name", "email", "student_no")}),
        ("账号状态", {"fields": ("is_active",)}),
        ("爽约与封禁", {
            "fields": ("no_show_count", "banned_until"),
            "description": "爽约满 3 次自动封禁 7 天；此处只读，解除封禁走运营操作。",
        }),
        ("时间", {"fields": ("created_at",), "classes": ("collapse",)}),
    )


# @admin.register(Area)
# class AreaAdmin(ReadOnlyAdmin):
#     list_display = ("id", "name", "description", "seat_count", "created_at")
#     search_fields = ("name",)
#     ordering = ("id",)
#     inlines = (SeatInline,)

#     def get_queryset(self, request):
#         # 用 annotate 一次算完，避免每行都查一次 count()（N+1）
#         return super().get_queryset(request).annotate(_seat_count=Count("seats"))

#     @admin.display(description="座位数", ordering="_seat_count")
#     def seat_count(self, obj: Area) -> int:
#         return obj._seat_count
@admin.register(Area)
class AreaAdmin(ReadOnlyAdmin):
    list_display = ("id", "name", "description", "seat_count", "created_at")
    search_fields = ("name",)
    ordering = ("id",)
    inlines = (SeatInline,)

    readonly_fields = ("id", "created_at", "seat_count")
    fieldsets = (
        ("基本信息", {"fields": ("id", "name", "description")}),
        ("统计", {"fields": ("seat_count",)}),
        ("时间", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_seat_count=Count("seats"))

    @admin.display(description="座位数", ordering="_seat_count")
    def seat_count(self, obj: Area) -> int:
        return obj._seat_count


# @admin.register(Seat)
# class SeatAdmin(ReadOnlyAdmin):
#     list_display = ("id", "code", "area", "has_power", "is_active")
#     list_filter = ("area", "has_power", "is_active")
#     search_fields = ("code", "area__name")
#     list_select_related = ("area",)
#     ordering = ("area__name", "code")
@admin.register(Seat)
class SeatAdmin(ReadOnlyAdmin):
    list_display = ("id", "code", "area", "has_power", "is_active")
    list_filter = ("area", "has_power", "is_active")
    search_fields = ("code", "area__name")
    list_select_related = ("area",)
    ordering = ("area__name", "code")
    list_per_page = 50

    readonly_fields = ("id", "created_at")
    fieldsets = (
        ("座位", {"fields": ("id", "code", "area")}),
        ("属性", {"fields": ("has_power", "is_active")}),
        ("时间", {"fields": ("created_at",), "classes": ("collapse",)}),
    )


# @admin.register(Reservation)
# class ReservationAdmin(ReadOnlyAdmin):
#     list_display = (
#         "id",
#         "user_email",
#         "seat_code",
#         "date",
#         "slot_range",
#         "status",
#         "created_at",
#     )
#     list_filter = ("status", "date")
#     search_fields = ("id", "user__email", "user__student_no", "seat__code")
#     date_hierarchy = "date"
#     list_select_related = ("user", "seat")
#     ordering = ("-id",)
#     inlines = (ReservationSlotInline,)

#     @admin.display(description="用户", ordering="user__email")
#     def user_email(self, obj: Reservation) -> str:
#         return obj.user.email

#     @admin.display(description="座位", ordering="seat__code")
#     def seat_code(self, obj: Reservation) -> str:
#         return obj.seat.code

#     @admin.display(description="时段（格子）")
#     def slot_range(self, obj: Reservation) -> str:
#         return f"{obj.start_slot}–{obj.end_slot}，共 {obj.end_slot - obj.start_slot} 格"
@admin.register(Reservation)
class ReservationAdmin(ReadOnlyAdmin):
    list_display = (
        "id", "user_email", "seat_code", "date", "slot_range", "status", "created_at",
    )
    list_filter = ("status", "date")
    search_fields = ("id", "user__email", "user__student_no", "seat__code")
    date_hierarchy = "date"
    list_select_related = ("user", "seat")
    ordering = ("-id",)
    inlines = (ReservationSlotInline,)

    readonly_fields = (
        "id", "user_email", "seat_code", "slot_range",
        "created_at", "checked_in_at", "cancelled_at",
    )
    fieldsets = (
        ("预约对象", {"fields": ("id", "user_email", "seat_code")}),
        ("时间占用", {"fields": ("date", "slot_range")}),
        ("状态与时间戳", {
            "fields": ("status", "created_at", "checked_in_at", "cancelled_at"),
        }),
        ("占用格子", {
            "fields": (),
            "description": "明细在下方内联表格中：一行 = 一个 30 分钟时段。",
        }),
    )

    @admin.display(description="用户", ordering="user__email")
    def user_email(self, obj: Reservation) -> str:
        return obj.user.email

    @admin.display(description="座位", ordering="seat__code")
    def seat_code(self, obj: Reservation) -> str:
        return obj.seat.code

    @admin.display(description="时段（格子）")
    def slot_range(self, obj: Reservation) -> str:
        return f"{obj.start_slot}–{obj.end_slot}，共 {obj.end_slot - obj.start_slot} 格"


# @admin.register(ReservationSlot)
# class ReservationSlotAdmin(ReadOnlyAdmin):
#     list_display = ("id", "reservation_id", "seat_id", "date", "slot_index")
#     list_filter = ("date",)
#     search_fields = ("reservation_id", "seat_id")
#     ordering = ("-id",)
@admin.register(ReservationSlot)
class ReservationSlotAdmin(ReadOnlyAdmin):
    list_display = ("id", "reservation_id", "seat_id", "date", "slot_index")
    list_filter = ("date",)
    search_fields = ("reservation_id", "seat_id")
    ordering = ("-id",)

    readonly_fields = ("id",)
    fieldsets = (
        ("占用", {"fields": ("id", "reservation", "seat", "date", "slot_index")}),
    )