import os
# 从 flask 导入 Flask 类，用于创建应用实例
from flask import Flask
# 从当前包（app）的 models 模块导入 db（需确保 models.py 中正确初始化了 db）
from .models import db
# 从 app.routes 下的 main_routes 模块导入蓝图 main_bp
from app.routes.main_routes import main_bp
from flask_login import LoginManager

login_manager = LoginManager()


def create_app():

    # 创建 Flask 应用实例，指定模板文件夹路径（根据你的工程结构，模板在 frontend/templates）
    # app = Flask(__name__, template_folder='frontend/templates')
    # 获取 frontend/templates 绝对路径
    # 获取项目根目录（即 api-test 目录）
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

    # 构造 frontend/templates 的绝对路径
    template_path = os.path.abspath(os.path.join(PROJECT_ROOT, '..', 'frontend', 'templates'))

    # 创建 Flask 应用，强制使用绝对路径
    app = Flask(__name__, template_folder=template_path)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///your_database.db'
    # 打印路径验证
    print(f"模板目录: {template_path}")  # 应该输出: /Users/.../api-testing/frontend/templates

    # 配置 SQLite 数据库（文档指定开发环境用 SQLite）
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///api_test.db'
    # 关闭 SQLAlchemy 的修改跟踪（减少不必要的开销）
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    #登录
    app = Flask(__name__)
    login_manager.init_app(app)
    # 初始化 db，将 Flask 应用与 SQLAlchemy 的 db 实例关联
    db.init_app(app)

    # 注册蓝图，让 main_routes 中定义的路由生效
    app.register_blueprint(main_bp)

    # 创建数据表：在应用上下文内执行，确保 Flask - SQLAlchemy 能正确操作数据库
    with app.app_context():
        # 根据 models 中定义的模型类，创建对应的数据库表
        db.create_all()

        # 返回创建好的 Flask 应用实例，供 run.py 等入口文件使用
    return app