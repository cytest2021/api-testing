from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from app.services.excel_parser import parse_excel
from app.services.postman_parser import PostmanParser
from app.models import db, Project, User, Interface, InterfaceParam, TestCase
from flask_login import current_user, login_user
import datetime
from sqlalchemy.orm import joinedload


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

@main_bp.route('/case/edit/<int:project_id>')
def edit_case(project_id):
    return render_template('edit_case.html', project_id=project_id)

# --------------------- 接口管理页面路由 ---------------------
@main_bp.route('/interface-management')
def interface_management():
    return render_template('interface_management.html')

# --------------------- 新增：获取所有项目列表 ---------------------
@main_bp.route('/api/all-projects', methods=['GET'])
def get_all_projects():
    try:
        projects = Project.query.all()
        project_list = [{"id": p.project_id, "name": p.project_name} for p in projects]
        print("数据库查询到的项目：", [p.project_name for p in projects])
        return jsonify({"code": 200, "data": project_list})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"查询项目失败：{str(e)}"}), 500

# --------------------- 调整：获取指定项目的接口数据（按需加载 TestCase） ---------------------
@main_bp.route('/api/project/<int:project_id>/interfaces', methods=['GET'])
def get_project_interfaces(project_id):
    try:
        project = Project.query.get(project_id)
        if not project:
            return jsonify({"code": 404, "msg": "项目不存在"}), 404

        # 关键修改：仅加载 Interface 和 params，不主动加载 test_cases
        interfaces = Interface.query.filter_by(project_id=project_id)\
            .options(joinedload(Interface.params))\
            .all()

        if not interfaces:
            return jsonify({"code": 200, "data": [], "msg": "该项目下暂无接口"}), 200

        interface_list = []
        for interface in interfaces:
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
                for p in interface.params
            ]

            # 关键修改：正确处理枚举类型的 method（直接取枚举名称并大写）
            method_upper = interface.method.name.upper()

            interface_info = {
                "interface": {
                    "id": interface.interface_id,
                    "name": interface.interface_name,
                    "url": interface.url,
                    "method": method_upper,  # 使用修正后的 method
                    "request_header": interface.request_header
                },
                "params": param_list,
                "cases": []  # 暂时返回空列表，后续按需填充
            }
            interface_list.append(interface_info)

        return jsonify({"code": 200, "data": interface_list}), 200
    except Exception as e:
        print(f"查询项目接口失败: {str(e)}")
        return jsonify({"code": 500, "msg": f"服务器内部错误: {str(e)}"}), 500



# --------------------- 合并后的上传及解析逻辑 ---------------------
@main_bp.route('/api/import', methods=['POST'])
def handle_import():
    response = {
        "success": False,
        "parse_success": False,
        "error": "",
        "project_id": None
    }

    try:
        # 1. 用户身份处理
        # 检查current_user是否已登录且有user_id属性
        if not current_user or not hasattr(current_user, 'user_id'):
            # 若未登录，创建并登录固定用户
            user = User(
                user_id=1,
                username="fixed_user",
                role='admin',
                create_time=datetime.datetime.now()
            )
            # 添加用户到数据库（如果需要）
            existing_user = User.query.filter_by(user_id=1).first()
            if not existing_user:
                db.session.add(user)
                db.session.commit()
            login_user(user)
        # 再次检查用户信息
        if not current_user or current_user.user_id is None:
            response["error"] = "用户信息异常，请重新登录"
            return jsonify(response), 401

        print(f"current_user 类型: {type(current_user)}")
        print(f"current_user.user_id: {current_user.user_id}")

        # 2. 项目名称 & 描述校验
        project_name = request.form.get('project_name')
        project_desc = request.form.get('project_desc', '')
        if not project_name:
            response["error"] = "项目名称不能为空"
            return jsonify(response), 400
        existing_project = Project.query.filter_by(project_name=project_name).first()
        if existing_project:
            response["error"] = f"项目「{project_name}」已存在，请更换名称"
            return jsonify(response), 400

        # 3. 文件校验
        if 'file' not in request.files:
            response["error"] = "未选择文件"
            return jsonify(response), 400
        file = request.files['file']
        if file.filename == '':
            response["error"] = "请选择有效的文件"
            return jsonify(response), 400

        # 4. 通过请求头判断文件类型
        file_type = request.headers.get('X-File-Type')
        if file_type == 'excel':
            if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
                response["error"] = "Excel 导入仅支持 .xlsx 和 .xls 格式"
                return jsonify(response), 400
            # 5. 创建项目并解析 Excel
            new_project = Project(
                project_name=project_name,
                description=project_desc,
                creator_id=current_user.user_id,
                create_time=datetime.datetime.now()
            )
            db.session.add(new_project)
            db.session.commit()
            project_id = new_project.project_id
            parse_result = parse_excel(file, project_id, current_user.user_id)
            if not parse_result["success"]:
                db.session.delete(new_project)
                db.session.commit()
                response["error"] = parse_result["error"]
                return jsonify(response), 400
        elif file_type == 'postman':
            if not file.filename.endswith('.json'):
                response["error"] = "Postman 导入仅支持 .json 格式"
                return jsonify(response), 400
            # 5. 解析 Postman JSON
            parser = PostmanParser(file, project_name, project_desc)
            project = parser.parse()
            # 因为parser.parse()返回的是字典，所以取project_id要从字典中获取
            project_id = project["project_id"]
        else:
            response["error"] = "不支持的文件类型"
            return jsonify(response), 400

        # 6. 解析成功，返回结果
        response["success"] = True
        response["parse_success"] = True
        response["project_id"] = project_id
        return jsonify(response), 200

    except Exception as e:
        db.session.rollback()
        response["error"] = str(e)
        return jsonify(response), 500

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

# --------------------- 项目管理功能（新增） ---------------------
@main_bp.route('/api/projects/<int:project_id>', methods=['PUT'])
def update_project(project_id):
    project = Project.query.get(project_id)
    if not project:
        return jsonify({"code": 404, "msg": "项目不存在"}), 404

    data = request.get_json()
    if 'project_name' in data:
        project.project_name = data['project_name']
    if 'description' in data:
        project.description = data['description']
    db.session.commit()
    return jsonify({"code": 200, "msg": "项目已更新"})

# --------------------- 用例管理功能（新增，按需获取用例） ---------------------
@main_bp.route('/api/interface/<int:interface_id>/cases', methods=['GET'])
def get_interface_cases(interface_id):
    # 显式加载指定接口的用例
    cases = TestCase.query.filter_by(interface_id=interface_id).all()
    return jsonify({
        "code": 200,
        "data": [
            {
                "case_id": c.case_id,
                "case_name": c.case_name,
                "param_values": c.param_values,
                "expected_result": c.expected_result,
                "assert_rule": c.assert_rule,
                "create_time": c.create_time.strftime("%Y-%m-%d %H:%M:%S")
            } for c in cases
        ]
    })

# --------------------- 路由与页面关联调整（新增） ---------------------
@main_bp.route('/project-management')
def project_management():
    return render_template('project_management.html')

@main_bp.route('/case/list/<int:interface_id>')
def case_list(interface_id):
    return render_template('case_list.html', interface_id=interface_id)

@main_bp.route('/api/generate-cases', methods=['POST'])
def generate_test_cases():
    interface_id = request.args.get('interface_id')
    if not interface_id:
        return jsonify({"code": 400, "msg": "接口ID不能为空"}), 400
    return jsonify({"code": 200, "msg": "用例生成逻辑待完善"}), 200