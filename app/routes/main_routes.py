from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from app.services.excel_parser import parse_excel
from app.models import db, Project, User, Interface, InterfaceParam, TestCase
from flask_login import current_user, login_user, UserMixin
import datetime
from sqlalchemy.orm import joinedload  # 导入预加载工具

main_bp = Blueprint('main', __name__)


# --------------------- 系统首页（分栏布局） ---------------------
@main_bp.route('/')
def home():
    return render_template('index.html')


# --------------------- 功能页面路由 ---------------------
@main_bp.route('/upload')
def show_upload_page():
    return render_template('upload.html')


@main_bp.route('/test-case-generate')
def test_case_generate():
    return render_template('test_case_generate.html')


@main_bp.route('/dependency-manage')
def dependency_manage():
    return render_template('dependency_manage.html')


@main_bp.route('/test-execution')
def test_execution():
    return render_template('test_execution.html')


@main_bp.route('/case/edit/<int:project_id>')
def edit_case(project_id):
    return render_template('edit_case.html', project_id=project_id)


# --------------------- 接口管理页面路由 ---------------------
@main_bp.route('/interface-management')
def interface_management():
    """
    接口管理页面：先展示所有项目，点击项目后展示该项目下的接口数据
    """
    return render_template('interface_management.html')


# --------------------- 新增：获取所有项目列表 ---------------------
@main_bp.route('/api/all-projects', methods=['GET'])
def get_all_projects():
    """
    获取所有项目信息（用于前端渲染项目列表）
    """
    try:
        # 查询所有项目（可按需添加筛选条件）
        projects = Project.query.all()

        # 组装项目数据（仅返回必要字段，也可扩展项目描述等）
        project_list = [{"id": p.project_id, "name": p.project_name} for p in projects]
        return jsonify({"code": 200, "data": project_list})

        # 手动打印查询结果
        projects = Project.query.all()
        print("数据库查询到的项目：", [p.project_name for p in projects])

        project_list = [{"id": p.project_id, "name": p.project_name} for p in projects]
        return jsonify({"code": 200, "data": project_list})

    except Exception as e:
        return jsonify({"code": 500, "msg": f"查询项目失败：{str(e)}"}), 500


# --------------------- 调整：获取指定项目的接口数据 ---------------------
from sqlalchemy.orm import joinedload  # 导入预加载工具

@main_bp.route('/api/project/<int:project_id>/interfaces', methods=['GET'])
def get_project_interfaces(project_id):
    try:
        project = Project.query.get(project_id)
        if not project:
            return jsonify({"code": 404, "msg": "项目不存在"}), 404

        # 优化：一次性预加载接口、参数、用例的关联数据
        interfaces = Interface.query.filter_by(project_id=project_id)\
            .options(
                joinedload(Interface.params),  # 预加载参数
                joinedload(Interface.cases)    # 预加载测试用例（需在模型中定义关系）
            ).all()

        if not interfaces:
            return jsonify({"code": 200, "data": [], "msg": "该项目下暂无接口"}), 200

        interface_list = []
        for interface in interfaces:
            # 直接从预加载的数据中获取，无需再次查询数据库
            param_list = [
                {
                    "param_id": p.param_id,
                    "param_name": p.param_name,
                    "param_type": p.param_type.value,
                    "data_type": p.data_type,
                    "is_required": p.is_required,
                    "constraint": p.constraint,
                    "example_value": p.example_value
                }
                for p in interface.params  # 直接使用预加载的 params
            ]

            case_list = [
                {
                    "case_id": c.case_id,
                    "case_name": c.case_name
                }
                for c in interface.cases  # 直接使用预加载的 cases
            ]

            method_upper = interface.method.value.upper() if hasattr(interface.method, 'value') else interface.method.upper()

            interface_info = {
                "interface": {
                    "id": interface.interface_id,
                    "name": interface.interface_name,
                    "url": interface.url,
                    "method": method_upper
                },
                "params": param_list,
                "cases": case_list
            }
            interface_list.append(interface_info)

        return jsonify({"code": 200, "data": interface_list}), 200

    except Exception as e:
        print(f"查询项目接口失败: {str(e)}")
        return jsonify({"code": 500, "msg": f"服务器内部错误: {str(e)}"}), 500

# --------------------- 上传及解析逻辑 ---------------------
@main_bp.route('/api/import-excel', methods=['POST'])
def handle_import():
    try:
        # 1. 用户身份处理（保持现有逻辑）
        user = User(
            user_id=1,
            username="fixed_user",
            password="dummy",
            role='admin',
            create_time=datetime.datetime.now()
        )
        if not user:
            return jsonify({"result": "错误：用户构造失败"}), 500
        login_user(user)

        if not current_user or not hasattr(current_user, 'user_id'):
            return jsonify({"result": "错误：请先登录"}), 401

        # 2. 项目名称校验（保持现有逻辑）
        project_name = request.form.get('project_name')
        if not project_name:
            return jsonify({"result": "错误：请输入项目名称"}), 400

        existing_project = Project.query.filter_by(project_name=project_name).first()
        if existing_project:
            return jsonify({"result": f"错误：项目「{project_name}」已存在，请更换名称"}), 400

        if current_user.user_id is None:
            return jsonify({"result": "错误：用户信息异常，请重新登录"}), 401

        # 3. 创建项目（保持现有逻辑）
        new_project = Project(
            project_name=project_name,
            description="通过Excel导入创建",
            owner_id=current_user.user_id,
            create_time=datetime.datetime.now()
        )
        db.session.add(new_project)
        db.session.commit()
        project_id = new_project.project_id

        # 4. 文件校验（保持现有逻辑）
        if 'file' not in request.files:
            return jsonify({"result": "错误：未选择文件"}), 400
        file = request.files['file']
        if file.filename == '' or not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            return jsonify({"result": "错误：仅支持.xlsx和.xls格式"}), 400

        # 5. 解析Excel并返回JSON（核心修改：移除redirect，返回项目ID）
        parse_result = parse_excel(file, project_id)
        # 返回成功信息和项目ID，让前端决定跳转
        return jsonify({
            "result": "上传接口成功",  # 明确的成功提示
            "project_id": project_id,  # 传递项目ID给前端
            "success": True
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"result": f"服务器错误：{str(e)}"}), 500



# --------------------- 数据更新接口 ---------------------
@main_bp.route('/api/interface/<int:interface_id>', methods=['PUT'])
def update_interface(interface_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"code": 400, "msg": "未提交更新数据"}), 400

        interface = Interface.query.get(interface_id)
        if not interface:
            return jsonify({"code": 404, "msg": "接口不存在"}), 404

        interface.interface_name = data.get('name', interface.interface_name)
        interface.url = data.get('url', interface.url)
        interface.method = data.get('method', interface.method)
        interface.request_header = data.get('request_header', interface.request_header)

        db.session.commit()

        return jsonify({"code": 200, "msg": "接口信息更新成功"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"更新失败：{str(e)}"}), 500


@main_bp.route('/api/param/<int:param_id>', methods=['PUT'])
def update_param(param_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"code": 400, "msg": "未提交更新数据"}), 400

        param = InterfaceParam.query.get(param_id)
        if not param:
            return jsonify({"code": 404, "msg": "参数不存在"}), 404

        param.param_name = data.get('name', param.param_name)
        param.param_type = data.get('type', param.param_type)
        param.data_type = data.get('data_type', param.data_type)
        param.is_required = data.get('is_required', param.is_required)
        param.example_value = data.get('example_value', param.example_value)

        db.session.commit()

        return jsonify({"code": 200, "msg": "参数信息更新成功"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"更新失败：{str(e)}"}), 500


@main_bp.route('/api/case/<int:case_id>', methods=['PUT'])
def update_case(case_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"code": 400, "msg": "未提交更新数据"}), 400

        test_case = TestCase.query.get(case_id)
        if not test_case:
            return jsonify({"code": 404, "msg": "用例不存在"}), 404

        test_case.case_name = data.get('name', test_case.case_name)
        test_case.expected_result = data.get('expected_result', test_case.expected_result)
        test_case.param_values = data.get('param_values', test_case.param_values)
        test_case.assert_rule = data.get('assert_rule', test_case.assert_rule)

        db.session.commit()

        return jsonify({"code": 200, "msg": "用例信息更新成功"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"更新失败：{str(e)}"}), 500