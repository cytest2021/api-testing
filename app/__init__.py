from flask import Flask
from .models import db


def create_app():
    app = Flask(__name__)
    # 配置SQLite数据库（文档指定开发环境用SQLite）
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///api_test.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    # 创建数据表
    with app.app_context():
        db.create_all()
    return app