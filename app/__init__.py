import os
from flask import Flask
from .models import db, User  # 导入数据库实例
from app.routes.main_routes import main_bp  # 导入主蓝图
from flask_login import LoginManager

# 初始化登录管理器
login_manager = LoginManager()


def create_app():
    # 1. 计算项目路径（确保模板目录正确）
    # 获取当前文件(__init__.py)的绝对路径
    current_file_path = os.path.abspath(__file__)
    # 获取app目录的路径
    app_dir = os.path.dirname(current_file_path)
    # 项目根目录（app的上级目录）
    project_root = os.path.dirname(app_dir)
    # 模板目录路径（frontend/templates）
    template_path = os.path.join(project_root, 'frontend', 'templates')

    # 2. 只创建一次Flask应用实例
    app = Flask(__name__, template_folder=template_path)

    # 3. 配置应用参数（所有配置必须在初始化扩展前完成）
    # 数据库配置
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///api_test.db'  # 数据库文件将生成在项目根目录
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # 关闭不必要的跟踪
    # 安全配置（Flask-Login必须）
    app.config['SECRET_KEY'] = 'your-secure-secret-key-12345'  # 替换为随机字符串（建议至少24个字符）

    # 4. 初始化扩展（使用同一个app实例）
    login_manager.init_app(app)  # 初始化登录管理器

    @login_manager.user_loader
    def load_user(user_id):
        # 写死返回 ID 为 1 的用户，需确保数据库有这条数据；
        # 若数据库没数据，可改成直接实例化，比如 User(1, "test@example.com", "test_password")
        # 具体参数根据你的 User 模型 __init__ 方法调整
        return User.query.get(1)
    db.init_app(app)  # 初始化数据库

    # 5. 注册蓝图（路由）
    app.register_blueprint(main_bp)  # 注册主路由蓝图

    # 6. 创建数据库表（在应用上下文中）
    with app.app_context():
        db.create_all()  # 根据模型自动创建表
        print("数据库表创建完成")

    # 验证配置是否正确
    print(f"模板目录验证: {template_path} (是否存在: {os.path.exists(template_path)})")
    print(f"数据库URI配置: {app.config['SQLALCHEMY_DATABASE_URI']}")

    return app
