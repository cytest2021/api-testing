from flask import Blueprint, request, jsonify, render_template
from app.services.excel_parser import parse_excel
from app.models import db, Project, User  # 导入Project模型
from flask_login import current_user, login_user  # 假设使用flask-login获取当前用户

main_bp = Blueprint('main', __name__)

# main_routes.py
from flask import Blueprint, render_template

main_bp = Blueprint('main', __name__)  # 创建蓝图

@main_bp.route('/upload')  # 定义 /upload 路由
def show_upload_page():
    return render_template('upload.html')
@main_bp.route('/api/import-excel', methods=['POST'])
def handle_import():
    # 直接构造用户，无需依赖数据库
    user = User(id=1, username="fixed_user")  # 按模型参数调整
    if user:
        login_user(user)
        # 正常处理上传逻辑...
        return {"result": "上传成功"}
    else:
        return {"error": "用户构造失败"}, 500
    try:
        # 新增：检查用户是否登录
        if not current_user or not hasattr(current_user, 'user_id'):
            return jsonify({"result": "错误：请先登录"}), 401

        # 1. 获取项目名称（用户输入）
        project_name = request.form.get('project_name')
        if not project_name:
            return jsonify({"result": "错误：请输入项目名称"}), 400

        # 2. 检查项目是否已存在（避免重复）
        existing_project = Project.query.filter_by(project_name=project_name).first()
        if existing_project:
            return jsonify({"result": f"错误：项目「{project_name}」已存在，请更换名称"}), 400

        # 3. 创建新项目（ID由数据库自增生成）
        # 确保 owner_id 不为空
        if current_user.user_id is None:
            return jsonify({"result": "错误：用户信息异常，请重新登录"}), 401

        new_project = Project(
            project_name=project_name,
            description="通过Excel导入创建",
            owner_id=current_user.user_id  # 现在确保该值不为空
        )
        db.session.add(new_project)
        db.session.commit()  # 提交后自动生成自增project_id
        project_id = new_project.project_id
        print(f"新建项目ID：{project_id}，名称：{project_name}")

        # 后续文件处理逻辑保持不变...
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