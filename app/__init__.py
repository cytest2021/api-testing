import os
from flask import Flask
from .models import db, User  # 导入数据库实例、User 模型
from app.routes.main_routes import main_bp  # 导入主蓝图
from flask_login import LoginManager
import json
from jinja2 import Environment

# 初始化登录管理器
login_manager = LoginManager()


def create_app():
    # 1. 计算项目路径（确保模板、静态文件目录正确）
    current_file_path = os.path.abspath(__file__)  # 当前文件（__init__.py）的绝对路径
    app_dir = os.path.dirname(current_file_path)   # app 目录的路径
    project_root = os.path.dirname(app_dir)        # 项目根目录（app 的上级目录）

    # 模板目录路径：frontend/templates
    template_path = os.path.join(project_root, 'frontend', 'templates')
    # 静态文件目录路径：frontend/static
    static_path = os.path.join(project_root, 'frontend', 'static')  # 新增静态目录配置

    # 2. 创建 Flask 应用实例，指定模板和静态文件路径
    app = Flask(
        __name__,
        template_folder=template_path,  # 模板目录
        static_folder=static_path       # 静态文件目录（新增配置）
    )

    # 3. 配置应用参数（所有配置必须在初始化扩展前完成）
    # 数据库配置（SQLite）
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///api_test.db'  # 数据库文件生成在项目根目录
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # 关闭不必要的跟踪
    # 安全配置（Flask-Login 必须）
    app.config['SECRET_KEY'] = 'your-secure-secret-key-12345'  # 建议替换为随机字符串（至少24字符）

    # 自定义from_json过滤器
    def from_json(value):
        """将JSON字符串转换为Python对象"""
        try:
            return json.loads(value) if value else None
        except json.JSONDecodeError:
            app.logger.error(f"无法解析JSON字符串: {value}")
            return None

    # 注册过滤器到Jinja2环境
    app.jinja_env.filters['fromjson'] = from_json

    # 4. 初始化扩展（使用同一个 app 实例）
    login_manager.init_app(app)  # 初始化登录管理器

    @login_manager.user_loader
    def load_user(user_id):
        # 这里假设手动创建的用户已存在于数据库，或直接返回该用户
        return User.query.get(int(user_id))  # 或直接返回手动创建的 user（若固定为 user_id=1）

    db.init_app(app)  # 初始化数据库

    # 5. 注册蓝图（路由）
    app.register_blueprint(main_bp)  # 注册主路由蓝图

    # 6. 创建数据库表（在应用上下文中）
    with app.app_context():
        db.create_all()  # 根据模型自动创建表
        print("数据库表创建完成")

    # # 验证配置是否正确
    # print(f"模板目录验证: {template_path} (是否存在: {os.path.exists(template_path)})")
    # print(f"静态目录验证: {static_path} (是否存在: {os.path.exists(static_path)})")  # 新增静态目录验证
    # print(f"数据库URI配置: {app.config['SQLALCHEMY_DATABASE_URI']}")

    return app