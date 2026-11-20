"""让 PyMySQL 冒充 MySQLdb，Django 的 MySQL 后端才能加载它。"""

import pymysql

pymysql.install_as_MySQLdb()