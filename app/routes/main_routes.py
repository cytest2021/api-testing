from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from app.services.excel_parser import parse_excel
from app.services.postman_parser import PostmanParser
from app.services.testcase_generator import generate_test_cases
from app.models import db, Project, User, Interface, InterfaceParam, TestCase, ParamType
from flask_login import current_user, login_user
import datetime
from sqlalchemy.orm import joinedload
import os
import json


main_bp = Blueprint('main', __name__)

# --------------------- 系统首页（分栏布局） ---------------------
@main_bp.route('/')
def home():
    return render_template('index.html')

# --------------------- 功能页面路由 ---------------------
@main_bp.route('/upload')
def show_upload_page():
    return render_template('upload.html')

@main_bp.route('/test-case-management')
def test_case_generate():
    return render_template('test_case_management.html')

# --------------------- 接口管理页面路由 ---------------------
@main_bp.route('/interface-management')
def interface_management():
    return render_template('interface_management.html')

# --------------------- 新增：接口编辑页面路由 ---------------------
@main_bp.route('/interface/edit/<int:interface_id>')
def interface_edit(interface_id):
    # 查询接口详情
    interface = Interface.query.filter_by(interface_id=interface_id) \
        .options(joinedload(Interface.params)) \
        .first()

    if not interface:
        return jsonify({"code": 404, "msg": "接口不存在"}), 404

    # 筛选不同类型的参数
    header_params = []
    request_params = []
    response_params = []
    for param in interface.params:
        param_info = {
            "param_id": param.param_id,
            "param_name": param.param_name,
            "data_type": param.data_type,
            "is_required": param.is_required,
            "example_value": param.example_value,
            "constraint": param.constraint
        }
        if param.param_type == ParamType.HEADER:
            header_params.append(param_info)
        elif param.param_type in [ParamType.PATH, ParamType.QUERY, ParamType.BODY]:
            request_params.append(param_info)
        elif param.param_type == ParamType.RESPONSE:
            response_params.append(param_info)

    interface_detail = {
        "interface_id": interface.interface_id,
        "name": interface.interface_name,
        "url": interface.url,
        "method": interface.method.name.upper(),
        "header_params": header_params,
        "request_params": request_params,
        "response_params": response_params
    }

    return render_template('interface_edit.html', interface=interface_detail)

# --------------------- 删除接口 ---------------------
@main_bp.route('/api/interface/<int:interface_id>', methods=['DELETE'])
def delete_interface(interface_id):
    interface = Interface.query.get(interface_id)
    if not interface:
        return jsonify({"code": 404, "msg": "接口不存在"}), 404
    try:
        db.session.delete(interface)
        db.session.commit()
        return jsonify({"code": 200, "msg": "删除成功"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"删除失败：{str(e)}"}), 500

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

# --------------------- 新增：获取单个接口详情（含请求头、请求、响应参数） ---------------------
@main_bp.route('/api/interface/<int:interface_id>/detail', methods=['GET'])
def get_interface_detail(interface_id):
    try:
        # 1. 查询接口 + 关联所有参数
        interface = Interface.query.filter_by(interface_id=interface_id) \
            .options(joinedload(Interface.params)) \
            .first()

        if not interface:
            return jsonify({"code": 404, "msg": "接口不存在"}), 404

        # 2. 筛选出 PATH、QUERY、BODY 类型的请求参数
        request_params = []
        for param in interface.params:
            if param.param_type in [ParamType.PATH, ParamType.QUERY, ParamType.BODY]:
                param_info = {
                    "param_id": param.param_id,
                    "param_name": param.param_name,
                    "data_type": param.data_type,
                    "is_required": param.is_required,
                    "example_value": param.example_value,
                    "constraint": param.constraint
                }
                request_params.append(param_info)

        # 3. 筛选出 HEADER 类型的请求头参数
        header_params = []
        for param in interface.params:
            if param.param_type == ParamType.HEADER:
                param_info = {
                    "param_id": param.param_id,
                    "param_name": param.param_name,
                    "data_type": param.data_type,
                    "is_required": param.is_required,
                    "example_value": param.example_value,
                    "constraint": param.constraint
                }
                header_params.append(param_info)

        # 4. 筛选出 RESPONSE 类型的响应参数
        response_params = []
        for param in interface.params:
            if param.param_type == ParamType.RESPONSE:
                param_info = {
                    "param_id": param.param_id,
                    "param_name": param.param_name,
                    "data_type": param.data_type,
                    "is_required": param.is_required,
                    "example_value": param.example_value,
                    "constraint": param.constraint
                }
                response_params.append(param_info)

        # 5. 构造返回数据
        detail = {
            "interface_id": interface.interface_id,
            "name": interface.interface_name,
            "url": interface.url,
            "method": interface.method.name.upper(),  # 枚举转大写
            "header_params": header_params,
            "request_params": request_params,
            "response_params": response_params
        }

        return jsonify({"code": 200, "data": detail}), 200

    except Exception as e:
        print(f"获取接口详情失败: {str(e)}")
        return jsonify({"code": 500, "msg": f"服务器内部错误: {str(e)}"}), 500

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

# 处理更新项目的文件上传和接口解析更新路由
@main_bp.route('/api/project/update', methods=['POST'])
def update_project():
    # 获取并验证项目ID
    project_id = request.form.get('project_id')
    if not project_id:
        return jsonify({"code": 400, "msg": "project_id 不能为空"})
    try:
        project_id = int(project_id)
    except ValueError:
        return jsonify({"code": 400, "msg": "project_id 必须为整数"})

    # 验证项目存在性
    project = Project.query.get(project_id)
    if not project:
        return jsonify({"code": 404, "msg": "项目不存在"})

    # 获取创建者ID
    creator_id = current_user.user_id if hasattr(current_user, 'user_id') else 1

    # 检查文件上传
    if 'file' not in request.files:
        return jsonify({"code": 400, "msg": "未选择文件"})
    file = request.files['file']
    if file.filename == '':
        return jsonify({"code": 400, "msg": "文件名为空"})

    # 获取文件扩展名
    file_ext = os.path.splitext(file.filename)[1].lower()
    parse_result = None
    interfaces = []

    try:
        if file_ext == '.json':
            # 解析Postman JSON文件
            parser = PostmanParser(
                postman_file=file,
                project_name=project.project_name,
                project_desc=project.description
            )
            parse_result = parser.parse()
            interfaces = parse_result.get('data', {}).get('interfaces', [])

        elif file_ext in ['.xlsx', '.xls']:
            # 解析Excel文件
            parse_result = parse_excel(
                file=file,
                project_id=project_id,
                creator_id=creator_id
            )
            interfaces = parse_result.get('data', {}).get('interfaces', [])

        else:
            return jsonify({"code": 400, "msg": "不支持的文件类型，仅支持 JSON 和 Excel 文件"})

        # 处理解析结果
        if not parse_result or not parse_result.get('success'):
            error_msg = parse_result.get('error', '解析失败') if parse_result else '解析返回空结果'
            return jsonify({"code": 500, "msg": f"文件解析失败：{error_msg}"})

        # 遍历接口列表，处理接口及参数
        for interface_data in interfaces:
            interface_name = interface_data.get('name')
            if not interface_name:
                continue

            # 获取去重后的参数列表
            request_params = deduplicate_params(interface_data.get('request_params', []))
            response_params = deduplicate_params(interface_data.get('response_params', []))

            # 查找或创建接口
            existing_interface = Interface.query.filter_by(
                project_id=project_id,
                name=interface_name
            ).first()

            if existing_interface:
                # 更新现有接口基本信息
                existing_interface.method = interface_data.get('method', existing_interface.method)
                existing_interface.url = interface_data.get('url', existing_interface.url)

                # 处理请求参数：更新已有参数，新增新参数
                updated_request_params = update_interface_params(
                    existing_params=json.loads(existing_interface.request_params or '[]'),
                    new_params=request_params
                )

                # 处理响应参数：更新已有参数，新增新参数
                updated_response_params = update_interface_params(
                    existing_params=json.loads(existing_interface.response_params or '[]'),
                    new_params=response_params
                )

                # 保存更新后的参数
                existing_interface.request_params = json.dumps(updated_request_params)
                existing_interface.response_params = json.dumps(updated_response_params)

            else:
                # 创建新接口
                new_interface = Interface(
                    project_id=project_id,
                    name=interface_name,
                    method=interface_data.get('method', ''),
                    url=interface_data.get('url', ''),
                    request_params=json.dumps(request_params),
                    response_params=json.dumps(response_params)
                )
                db.session.add(new_interface)

        db.session.commit()
        return jsonify({
            "code": 200,
            "msg": parse_result.get('message', '项目接口更新成功'),
            "project_id": project_id,
            "updated_interfaces": len(interfaces)
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"处理失败：{str(e)}"})


def deduplicate_params(params):
    """对参数列表进行去重，保留最后出现的参数"""
    if not isinstance(params, list):
        return []

    unique_params = {}
    for param in params:
        param_name = param.get('name')
        if param_name:
            unique_params[param_name] = param

    return list(unique_params.values())


def update_interface_params(existing_params, new_params):
    """
    更新接口参数：相同名称的参数进行更新，新参数进行新增
    :param existing_params: 数据库中已有的参数列表
    :param new_params: 新解析得到的参数列表
    :return: 更新后的参数列表
    """
    # 转换为字典便于查找，键为参数名
    param_dict = {p.get('name'): p for p in existing_params if p.get('name')}

    # 遍历新参数，更新或新增
    for new_param in new_params:
        param_name = new_param.get('name')
        if param_name:
            # 存在则更新，不存在则新增
            param_dict[param_name] = new_param

    # 转换回列表
    return list(param_dict.values())


# 删除项目的路由
@main_bp.route('/api/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    # 根据项目ID查询项目
    project = Project.query.get(project_id)
    if not project:
        return jsonify({"code": 404, "msg": "项目不存在"}), 404

    try:
        # 1. 查询该项目下的所有接口
        interfaces = Interface.query.filter_by(project_id=project_id).all()

        if interfaces:
            # 2. 先删除所有关联的接口（接口参数通常通过级联删除或接口删除自动删除）
            for interface in interfaces:
                db.session.delete(interface)

        # 3. 最后删除项目本身
        db.session.delete(project)
        db.session.commit()

        return jsonify({
            "code": 200,
            "msg": "项目及关联接口删除成功",
            "deleted_interfaces": len(interfaces)  # 返回删除的接口数量
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"删除失败：{str(e)}"}), 500


# 在原有的代码文件 main_routes.py 中添加以下代码
@main_bp.route('/api/interface/save', methods=['POST'])
def save_interface():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"code": 400, "msg": "未提交有效数据"}), 400

        interface_id = data.get('interface_id')
        interface = Interface.query.get(interface_id)
        if not interface:
            return jsonify({"code": 404, "msg": "接口不存在"}), 404

        interface.interface_name = data.get('name', interface.interface_name)
        interface.url = data.get('url', interface.url)
        interface.method = data.get('method', interface.method)

        # 更新请求头参数
        header_params = data.get('header_params', [])
        for param in header_params:
            param_id = param.get('param_id')
            if param_id:
                db_param = InterfaceParam.query.get(param_id)
                if db_param:
                    db_param.param_name = param.get('param_name', db_param.param_name)
                    db_param.data_type = param.get('data_type', db_param.data_type)
                    db_param.is_required = param.get('is_required', db_param.is_required)
                    db_param.example_value = param.get('example_value', db_param.example_value)
                    db_param.constraint = param.get('constraint', db_param.constraint)
            else:
                new_param = InterfaceParam(
                    interface_id=interface_id,
                    param_name=param.get('param_name'),
                    data_type=param.get('data_type'),
                    is_required=param.get('is_required'),
                    example_value=param.get('example_value'),
                    constraint=param.get('constraint'),
                    param_type=ParamType.HEADER
                )
                db.session.add(new_param)

        # 更新请求参数（PATH、QUERY、BODY）
        request_params = data.get('request_params', [])
        for param in request_params:
            param_id = param.get('param_id')
            if param_id:
                db_param = InterfaceParam.query.get(param_id)
                if db_param:
                    db_param.param_name = param.get('param_name', db_param.param_name)
                    db_param.data_type = param.get('data_type', db_param.data_type)
                    db_param.is_required = param.get('is_required', db_param.is_required)
                    db_param.example_value = param.get('example_value', db_param.example_value)
                    db_param.constraint = param.get('constraint', db_param.constraint)
            else:
                new_param = InterfaceParam(
                    interface_id=interface_id,
                    param_name=param.get('param_name'),
                    data_type=param.get('data_type'),
                    is_required=param.get('is_required'),
                    example_value=param.get('example_value'),
                    constraint=param.get('constraint'),
                    param_type=ParamType.PATH if 'path' in param.get('param_type', '').lower() \
                        else ParamType.QUERY if 'query' in param.get('param_type', '').lower() \
                        else ParamType.BODY
                )
                db.session.add(new_param)

        # 更新响应参数
        response_params = data.get('response_params', [])
        for param in response_params:
            param_id = param.get('param_id')
            if param_id:
                db_param = InterfaceParam.query.get(param_id)
                if db_param:
                    db_param.param_name = param.get('param_name', db_param.param_name)
                    db_param.data_type = param.get('data_type', db_param.data_type)
                    db_param.is_required = param.get('is_required', db_param.is_required)
                    db_param.example_value = param.get('example_value', db_param.example_value)
            else:
                new_param = InterfaceParam(
                    interface_id=interface_id,
                    param_name=param.get('param_name'),
                    data_type=param.get('data_type'),
                    is_required=param.get('is_required'),
                    example_value=param.get('example_value'),
                    param_type=ParamType.RESPONSE
                )
                db.session.add(new_param)

        db.session.commit()
        return jsonify({"code": 200, "msg": "接口保存成功"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"保存接口失败：{str(e)}"}), 500

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
    return render_template('test_case_management.html')

# --------------------- 编辑接口信息后保存 ---------------------
@main_bp.route('/case/list/<int:interface_id>')
def case_list(interface_id):
    return render_template('case_list.html', interface_id=interface_id)



# 生成项目下的测试用例
@main_bp.route('/api/project/<int:project_id>/generate_cases', methods=['GET'])
def generate_cases(project_id):
    project = Project.query.get(project_id)
    if not project:
        return jsonify({"error": "项目不存在"}), 404

    all_test_cases = []
    for interface in project.interfaces:
        cases = generate_test_cases(interface)
        all_test_cases.extend(cases)

    return jsonify(all_test_cases), 200


# 获取项目下的用例列表（支持搜索）
@main_bp.route('/api/project/<int:project_id>/cases', methods=['GET'])
def get_project_cases(project_id):
    keyword = request.args.get('keyword', '')
    # 联表查询用例和所属接口
    query = db.session.query(TestCase, Interface.interface_name) \
        .join(Interface, TestCase.interface_id == Interface.interface_id) \
        .filter(Interface.project_id == project_id)

    # 搜索逻辑（模糊匹配用例名称、参数、断言）
    if keyword:
        query = query.filter(
            db.or_(
                TestCase.case_name.like(f'%{keyword}%'),
                TestCase.param_values.like(f'%{keyword}%'),
                TestCase.assert_rule.like(f'%{keyword}%')
            )
        )

    cases = query.all()
    result = []
    for case, interface_name in cases:
        result.append({
            "case_id": case.case_id,
            "case_name": case.case_name,
            "interface_name": interface_name,
            "param_values": case.param_values,
            "assert_rule": case.assert_rule
        })

    return jsonify({"code": 200, "data": result})


# 删除用例
@main_bp.route('/api/case/<int:case_id>', methods=['DELETE'])
def delete_case(case_id):
    case = TestCase.query.get(case_id)
    if not case:
        return jsonify({"code": 404, "msg": "用例不存在"})

    db.session.delete(case)
    db.session.commit()
    return jsonify({"code": 200, "msg": "用例删除成功"})