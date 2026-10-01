"""账号:注册、登录、登出、当前用户。

登录是**可选的**:找房、对话、地图等功能不要求登录(见 docs/DECISIONS.md)。
- passwords.py  密码哈希(scrypt,标准库,无新依赖)
- store.py      users / sessions 两张表(Postgres,启动时幂等建表)
- routes.py     /api/auth/* 四个端点 + 失败限流
"""
