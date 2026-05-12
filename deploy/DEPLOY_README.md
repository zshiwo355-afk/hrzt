# 怀仁 AI 中台部署说明

## 目录内容

- `app/`：FastAPI 后端源码
- `static/`：前端静态页面
- `data/`：PPT 模板等运行数据
- `requirements.txt`：Python 依赖
- `compose.yaml`：MySQL 8.4 容器配置
- `.env.example`：环境变量模板，请复制成 `.env` 并填写真实密钥
- `database/ai_mid_platform.sql`：当前数据库结构和数据导出

## 部署步骤

1. 安装 Python 3.10+、Docker、Docker Compose。

2. 复制环境变量：

   ```bash
   cp .env.example .env
   ```

   然后编辑 `.env`，至少填写：

   ```text
   OFOX_API_KEY
   APP_SESSION_SECRET
   MYSQL_HOST
   MYSQL_PORT
   MYSQL_USER
   MYSQL_PASSWORD
   MYSQL_DATABASE
   ```

3. 启动 MySQL：

   ```bash
   docker compose up -d mysql
   ```

4. 恢复数据库：

   ```bash
   docker exec -i ai_mid_mysql mysql -uroot -proot123456 < database/ai_mid_platform.sql
   ```

5. 安装 Python 依赖：

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

6. 启动项目：

   ```bash
   python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

7. 浏览器访问：

   ```text
   http://服务器IP:8000
   ```

## 登录说明

- 员工账号：手机号
- 初始密码：手机号后 6 位
- 管理员账号以 `.env` 中 `ACCESS_USERNAME` / `ACCESS_PASSWORD` 为准；如果数据库中已有同名账号，不会覆盖密码。

## 注意事项

- 交付包不包含真实 `.env`，避免 API Key、OSS 密钥泄露。
- 交付包不包含 `uploads/` 历史上传附件目录；项目启动时会自动创建运行所需目录。
- 数据库 SQL 包含当前用户表、聊天会话和消息数据，请按内部资料妥善保管。
