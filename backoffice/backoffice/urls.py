from django.contrib import admin
from django.urls import path

admin.site.site_header = "SetBooking 运营后台"
admin.site.site_title = "SetBooking 运营后台"
admin.site.index_title = "自习室座位预约 · 数据管理"

urlpatterns = [
    path("admin/", admin.site.urls),
]