from flask import Blueprint, request, jsonify, render_template
from app.services.excel_parser import parse_excel
from app.models import db, Project  # 导入Project模型
from flask_login import current_user  # 假设使用flask-login获取当前用户

main_bp = Blueprint('main', __name__)

# main_routes.py
from flask import Blueprint, render_template

main_bp = Blueprint('main', __name__)  # 创建蓝图

@main_bp.route('/upload')  # 定义 /upload 路由
def show_upload_page():
    return render_template('upload.html')
@main_bp.route('/api/import-excel', methods=['POST'])
def handle_import():
    try:
        # 1. 获取项目名称（用户输入）
        project_name = request.form.get('project_name')
        if not project_name:
            return jsonify({"result": "错误：请输入项目名称"}), 400

        # 2. 检查项目是否已存在（避免重复）
        existing_project = Project.query.filter_by(project_name=project_name).first()
        if existing_project:
            return jsonify({"result": f"错误：项目「{project_name}」已存在，请更换名称"}), 400

        # 3. 创建新项目（ID由数据库自增生成）
        new_project = Project(
            project_name=project_name,
            description="通过Excel导入创建",  # 可留空或让用户在前端补充
            owner_id=current_user.user_id  # 关联当前登录用户为项目负责人
        )
        db.session.add(new_project)
        db.session.commit()  # 提交后自动生成自增project_id
        project_id = new_project.project_id  # 获取系统生成的项目ID
        print(f"新建项目ID：{project_id}，名称：{project_name}")

        # 4. 处理文件上传（复用原逻辑）
        if 'file' not in request.files:
            return jsonify({"result": "错误：未选择文件"}), 400
        file = request.files['file']
        if file.filename == '' or not file.filename.endswith(('.xlsx', '.xls')):
            return jsonify({"result": "错误：仅支持.xlsx和.xls格式"}), 400

        # 5. 调用解析函数，传入系统生成的project_id
        parse_result = parse_excel(file, project_id)
        return jsonify({"result": parse_result})

    except Exception as e:
        db.session.rollback()
        return jsonify({"result": f"服务器错误：{str(e)}"}), 500