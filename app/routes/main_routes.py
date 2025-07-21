from flask import Blueprint

# 创建蓝图（也可直接用 app 实例，蓝图更适合复杂项目分层）
main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return "Hello, Flask! 路由已配置"