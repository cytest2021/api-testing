from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from app.services.excel_parser import parse_excel
from app.models import db, Project, User, Interface, InterfaceParam, TestCase
from flask_login import current_user, login_user, UserMixin
import datetime

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
@main_bp.route('/api/project/<int:project_id>/interfaces', methods=['GET'])
def get_project_interfaces(project_id):
    try:
        # 1. 查询项目是否存在
        project = Project.query.get(project_id)
        if not project:
            return jsonify({"code": 404, "msg": "项目不存在"}), 404

        # 2. 查询该项目下的所有接口
        interfaces = Interface.query.filter_by(project_id=project_id).all()
        if not interfaces:
            return jsonify({"code": 200, "data": [], "msg": "该项目下暂无接口"}), 200

        # 3. 组装接口数据（包含关联的接口参数）
        interface_list = []
        for interface in interfaces:
            # 查询接口关联的参数
            params = InterfaceParam.query.filter_by(interface_id=interface.interface_id).all()
            param_list = [
                {
                    "param_id": p.param_id,
                    "param_name": p.param_name,
                    "param_type": p.param_type.value,  # 枚举转字符串
                    "data_type": p.data_type,
                    "is_required": p.is_required,
                    "constraint": p.constraint,
                    "example_value": p.example_value
                }
                for p in params
            ]

            # 4. 转换 method 为大写（核心修改）
            #    如果是枚举值，先取 value 再转大写；如果是字符串，直接转大写
            method_upper = interface.method.value.upper() if hasattr(interface.method, 'value') else interface.method.upper()

            # 组装接口信息
            interface_info = {
                "interface_id": interface.interface_id,
                "interface_name": interface.interface_name,
                "url": interface.url,
                "method": method_upper,  # 使用转换后的大写 method
                "request_header": interface.request_header,
                "create_time": interface.create_time.strftime('%Y-%m-%d %H:%M:%S'),  # 格式化时间
                "params": param_list  # 关联的参数列表
            }
            interface_list.append(interface_info)

        return jsonify({"code": 200, "data": interface_list}), 200

    except Exception as e:
        # 记录详细错误日志（生产环境建议用 logging 模块）
        print(f"查询项目接口失败: {str(e)}")
        return jsonify({"code": 500, "msg": f"服务器内部错误: {str(e)}"}), 500

# --------------------- 上传及解析逻辑 ---------------------
@main_bp.route('/api/import-excel', methods=['POST'])
def handle_import():
    try:
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

        project_name = request.form.get('project_name')
        if not project_name:
            return jsonify({"result": "错误：请输入项目名称"}), 400

        existing_project = Project.query.filter_by(project_name=project_name).first()
        if existing_project:
            return jsonify({"result": f"错误：项目「{project_name}」已存在，请更换名称"}), 400

        if current_user.user_id is None:
            return jsonify({"result": "错误：用户信息异常，请重新登录"}), 401

        new_project = Project(
            project_name=project_name,
            description="通过Excel导入创建",
            owner_id=current_user.user_id,
            create_time=datetime.datetime.now()
        )
        db.session.add(new_project)
        db.session.commit()
        project_id = new_project.project_id

        if 'file' not in request.files:
            return jsonify({"result": "错误：未选择文件"}), 400
        file = request.files['file']
        if file.filename == '' or not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            return jsonify({"result": "错误：仅支持.xlsx和.xls格式"}), 400

        parse_result = parse_excel(file, project_id)
        return redirect(url_for('main.edit_case', project_id=project_id))

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