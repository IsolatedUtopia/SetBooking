"""运营后台的展示配置。

当前一律**只读**，原因写在 ReadOnlyAdmin 的注释里：后台直接改表会绕过
FastAPI service 层的业务不变量。等 W3D2 再单独开放"安全的写"（例如座位启停用）。
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django import forms
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

    默认全部只读。子类用 editable_fields 显式声明"经评估可以安全修改"的字段，
    其余字段由 get_readonly_fields 自动补成只读。
    """

    editable_fields: tuple[str, ...] = ()

    def get_readonly_fields(self, request, obj=None):
        declared = list(super().get_readonly_fields(request, obj))
        editable = set(self.editable_fields)
        excluded = set(self.get_exclude(request, obj) or ())  
        for field in self.model._meta.fields:
            name = field.name
            if name in editable or name in excluded or name in declared:
                continue
            declared.append(name)
        return declared

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        # 只有声明了可编辑白名单的页面才出现"保存"按钮
        return bool(self.editable_fields)

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

class _UserAdminForm(forms.ModelForm):
    """封禁/解封的业务校验。"""

    class Meta:
        model = User
        fields = "__all__"

    def clean_banned_until(self):
        value = self.cleaned_data.get("banned_until")
        if value is None:
            return value
        now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
        if value <= now:
            raise forms.ValidationError(
                "封禁截止时间必须晚于当前时间；要解封请清空这个字段后保存。"
            )
        return value
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

    # 只放开"封禁截止时间"，其余字段仍由基类机械地补成只读
    editable_fields = ("banned_until",)
    form = _UserAdminForm

    readonly_fields = ("id", "created_at")
    fieldsets = (
        ("账号信息", {"fields": ("id", "name", "email", "student_no")}),
        ("账号状态", {"fields": ("is_active",)}),
        ("爽约与封禁", {
            "fields": ("no_show_count", "banned_until"),
            "description": (
                "爽约满 3 次自动封禁 7 天；"
                "运营也可在此手动封禁（填未来时间）或解封（清空后保存，同时清零爽约次数）。"
            ),
        }),
        ("时间", {"fields": ("created_at",), "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change) -> None:
        # 从"有封禁"变成"无封禁" = 运营手动解封，顺手把爽约次数清零，
        # 否则用户解封后只要再爽约 1 次就会被立刻重新封禁。
        if change and form.initial.get("banned_until") and obj.banned_until is None:
            obj.no_show_count = 0
        super().save_model(request, obj, form, change)


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

class _SeatAdminForm(forms.ModelForm):
    """座位启停用的业务校验：不允许把"还有未完成预约"的座位停掉。"""

    class Meta:
        model = Seat
        fields = ("code", "area", "has_power", "is_active")

    def clean_is_active(self) -> bool:
        is_active: bool = self.cleaned_data["is_active"]
        if is_active or self.instance.pk is None:
            return is_active

        busy = Reservation.objects.filter(
            seat_id=self.instance.pk,
            status__in=("PENDING", "CHECKED_IN"),
        ).exists()
        if busy:
            raise forms.ValidationError("该座位还有未完成的预约，请先处理后再停用。")
        return is_active
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

    editable_fields = ("is_active",)      # ← 新增：只放开这一个字段
    form = _SeatAdminForm                 # ← 新增：挂业务校验
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