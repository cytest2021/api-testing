import os
from flask import Blueprint, render_template

main_bp = Blueprint('main', __name__)

@main_bp.route('/edit_case')
def edit_case():
    # 使用绝对路径加载模板
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'templates', 'edit_case.html')
    return render_template(template_path)  