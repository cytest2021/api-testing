from json import JSONDecodeError
from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from app.services.excel_parser import parse_excel
from app.services.postman_parser import PostmanParser
from app.services.testcase_generator import generate_test_cases,generate_test_cases_by_project
from app.models import db, Project, User, Interface, InterfaceParam, TestCase, ParamType,InterfaceDependency
from flask_login import current_user, login_user
import datetime
from sqlalchemy.orm import joinedload
import os
import json
from sqlalchemy.exc import SQLAlchemyError
from openpyxl import Workbook
import io


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

# # 依赖配置页面路由
# @main_bp.route('/interface/dependency/config')
# def interface_dependency_config():
#     # 可以从请求参数中获取 interface_id
#     interface_id = request.args.get('interface_id')
#     # 这里可以添加获取接口信息等业务逻辑
#     return render_template('interface_dependency_config.html', interface_id=interface_id)

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

# --------------------- 路由与页面关联调整（新增） ---------------------
@main_bp.route('/project-management')
def project_management():
    return render_template('test_case_management.html')


@main_bp.route('/api/project/<int:project_id>/generate_cases', methods=['GET'])
def generate_cases(project_id):
    """为项目下所有接口生成测试用例，按接口ID顺序生成，支持跳过已存在用例、补充缺失用例"""
    try:
        # 1. 验证项目是否存在
        project = Project.query.get(project_id)
        if not project:
            return jsonify({"code": 404, "message": "项目不存在"}), 404

        # 检查项目是否包含 creator_id 字段
        if not hasattr(project, 'creator_id'):
            return jsonify({"code": 500, "message": "项目模型缺少creator_id字段"}), 500

        # 2. 调用项目维度生成用例函数
        result = generate_test_cases_by_project(
            project_id=project_id,
            creator_id=project.creator_id
        )

        # 3. 解析生成结果（适配新函数返回，区分新增、已存在统计）
        # 示例返回格式："用例生成完成：新增 3 条，已存在 5 条（未重复生成）"
        if "新增" in result and "已存在" in result:
            return jsonify({
                "code": 200,
                "message": result
            }), 200
        elif "成功生成" in result:  # 兼容旧格式（如果有需要）
            parts = result.split("成功生成 ")
            if len(parts) > 1:
                num_part = parts[1].split(" 条用例")[0].strip()
                if num_part.isdigit():
                    total_cases = int(num_part)
                    return jsonify({
                        "code": 200,
                        "message": f"项目测试用例生成完成，共生成{total_cases}条用例"
                    }), 200
                else:
                    return jsonify({
                        "code": 500,
                        "message": f"解析用例数量失败：结果格式不正确，原始结果：{result}"
                    }), 500
            else:
                return jsonify({
                    "code": 500,
                    "message": f"解析用例数量失败：结果格式不正确，原始结果：{result}"
                }), 500
        else:
            # 生成失败场景，直接返回失败信息
            return jsonify({
                "code": 500,
                "message": f"生成用例失败：{result}"
            }), 500

    except Exception as e:
        # 捕获所有未处理异常并返回详细信息
        return jsonify({
            "code": 500,
            "message": f"服务器内部错误：{str(e)}"
        }), 500


@main_bp.route('/api/project/<int:project_id>/cases', methods=['GET'])
def get_project_cases(project_id):
    try:
        # 联表查询用例和所属接口，获取项目下所有用例
        cases = db.session.query(TestCase).join(Interface, TestCase.interface_id == Interface.interface_id).filter(
            Interface.project_id == project_id).all()
        result = []
        for case in cases:
            result.append({
                "case_id": case.case_id,
                "case_name": case.case_name,
                "request_header": case.request_header,
                "request_param": case.request_param,
                "expected_result": case.expected_result,
                "assert_rule": case.assert_rule
            })
        return jsonify({"code": 200, "data": result}), 200
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取项目用例失败：{str(e)}"}), 500


# # 修改获取单个接口下用例列表接口
# @main_bp.route('/api/interface/<int:interface_id>/cases', methods=['GET'])
# def get_interface_cases(interface_id):
#     try:
#         cases = TestCase.query.filter_by(interface_id=interface_id).all()
#         case_list = []
#         for case in cases:
#             case_list.append({
#                 "case_id": case.case_id,
#                 "case_name": case.case_name,
#                 "request_header": case.request_header,
#                 "request_param": case.request_param,
#                 "expected_result": case.expected_result,
#                 "assert_rule": case.assert_rule
#             })
#         return jsonify({"code": 200, "data": case_list}), 200
#     except Exception as e:
#         return jsonify({"code": 500, "msg": f"获取用例失败：{str(e)}"}), 500

# 1. 拉取用例详情（增强空值与异常处理）
@main_bp.route('/api/case/<int:case_id>', methods=['GET'])
def get_case_detail(case_id):
    try:
        case = TestCase.query.get(case_id)
        if not case:
            return jsonify({"code": 404, "message": "用例不存在"}), 404

        # 防御性解析：空值或无效JSON时返回空字典
        def safe_json_loads(field_value):
            if not field_value:
                return {}
            try:
                return json.loads(field_value)
            except JSONDecodeError:
                return {}  # 无效JSON时返回空字典，避免前端报错

        return jsonify({
            "code": 200,
            "data": {
                "case_id": case.case_id,
                "case_name": case.case_name,
                "request_header_params": safe_json_loads(case.request_header),
                "request_params": safe_json_loads(case.request_param),
                "expected_result": safe_json_loads(case.expected_result),
                "rules": safe_json_loads(case.assert_rule)
            }
        }), 200

    except JSONDecodeError as e:
        return jsonify({"code": 500, "message": f"解析数据失败：{str(e)}"}), 500
    except Exception as e:
        return jsonify({"code": 500, "message": f"服务器异常：{str(e)}"}), 500


# 2. 保存编辑后的用例（确保数据正确序列化）
@main_bp.route('/api/case/edit', methods=['PUT'])
def edit_case():
    data = request.json
    case_id = data.get('case_id')
    if not case_id:
        return jsonify({"code": 400, "message": "缺少 case_id"}), 400

    try:
        case = TestCase.query.get(case_id)
        if not case:
            return jsonify({"code": 404, "message": "用例不存在"}), 404

        # 字段更新：空值处理 + 强制序列化（避免非字典类型）
        def safe_json_dumps(value, default={}):
            if not value:
                return json.dumps(default, ensure_ascii=False)
            # 确保是可序列化类型（如字典），否则用默认值
            return json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else json.dumps(default, ensure_ascii=False)

        case.case_name = data.get('case_name', case.case_name)
        case.request_header = safe_json_dumps(data.get('request_header_params'))
        case.request_param = safe_json_dumps(data.get('request_params'))
        case.expected_result = safe_json_dumps(data.get('expected_result'))
        case.assert_rule = safe_json_dumps(data.get('rules'))

        db.session.commit()
        return jsonify({"code": 200, "message": "保存成功"}), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({"code": 500, "message": f"数据库操作失败：{str(e)}"}), 500
    except Exception as e:
        return jsonify({"code": 500, "message": f"服务器异常：{str(e)}"}), 500


# 3. 渲染编辑页面（增强前端初始化兼容性）
@main_bp.route('/case/edit/<int:case_id>')
def render_case_edit(case_id):
    try:
        # 直接查询用例
        case = TestCase.query.get(case_id)
        print(f"获取到的用例: {case}")  # 添加这行代码，打印获取到的用例对象
        if not case:
            return jsonify({"code": 404, "message": "用例不存在"}), 404

        # 安全解析 JSON 字段
        def safe_load(field):
            print(f"解析字段: {field}")
            if not field or field.strip() == "":
                print("字段为空，返回空对象")
                return {}

        # 显式构建 case_data，确保包含 case_id
        case_data = {
            "case_id": case.case_id,
            "case_name": case.case_name,
            "request_header_params": safe_load(case.request_header),
            "request_params": safe_load(case.request_param),
            "expected_result": safe_load(case.expected_result),
            "rules": safe_load(case.assert_rule)
        }
        return render_template('case_edit.html', case=case_data)
    except Exception as e:
        print(f"JSON 解析失败:{e}")
        return f"服务器异常：{str(e)}", 500


# 删除用例
@main_bp.route('/api/case/<int:case_id>', methods=['DELETE'])
def delete_case(case_id):
    case = TestCase.query.get(case_id)
    if not case:
        return jsonify({"code": 404, "msg": "用例不存在"})

    db.session.delete(case)
    db.session.commit()
    return jsonify({"code": 200, "msg": "用例删除成功"})


# -------------------- 新增复制测试用例的路由 --------------------
@main_bp.route('/api/case/<int:caseId>/copy', methods=['POST'])
def copy_test_case(caseId):
    try:
        # 1. 查询原用例信息
        original_case = TestCase.query.filter_by(case_id=caseId).first()
        if not original_case:
            return jsonify({
                "code": 404,
                "message": "原用例不存在"
            }), 200

        # 2. 校验当前用户是否登录（flask_login 核心功能）
        if not current_user.is_authenticated:
            return jsonify({
                "code": 401,
                "message": "用户未登录，无法复制用例"
            }), 401  # 返回 401 更符合未授权场景

        # 3. 复制用例数据（排除自动生成字段，补充必要字段）
        copy_data = {
            "case_name": original_case.case_name + "（复制）",
            "request_header": original_case.request_header,
            "request_param": original_case.request_param,
            "expected_result": original_case.expected_result,
            "assert_rule": original_case.assert_rule,
            "interface_id": original_case.interface_id,  # 继承原用例的 interface_id
            "creator_id": current_user.user_id,  # 使用当前登录用户的 ID 作为 creator_id
            # 若有其他非空字段（如 project_id 等），需在此补充
        }

        # 4. 保存新用例到数据库
        new_case = TestCase(**copy_data)
        db.session.add(new_case)
        db.session.commit()

        # 5. 返回成功响应，包含新用例 ID
        return jsonify({
            "code": 200,
            "message": "用例复制成功",
            "data": {
                "new_case_id": new_case.case_id
            }
        }), 200

    except SQLAlchemyError as e:
        db.session.rollback()  # 回滚事务，避免脏数据
        print("数据库操作失败:", str(e))  # 记录详细错误
        return jsonify({
            "code": 500,
            "message": "服务器错误，复制用例失败（数据库操作异常）"
        }), 500
    except Exception as e:
        print("未知错误:", str(e))  # 捕获其他异常
        return jsonify({
            "code": 500,
            "message": "服务器错误，复制用例失败（未知异常）"
        }), 500


@main_bp.route('/api/export-cases', methods=['POST'])
def export_cases():
    """
    接收前端传递的用例 ID 列表，从 TestCase 模型查询数据并生成 Excel 导出
    """
    try:
        # 获取前端传递的 JSON 数据，提取要导出的用例 ID 列表
        data = request.get_json()
        case_ids = data.get('case_ids', [])

        if not case_ids:
            return jsonify({"code": 400, "message": "请选择要导出的用例"}), 400

        # 使用 SQLAlchemy 从数据库查询对应的用例数据
        # 假设 TestCase 模型中有 case_id、case_name、request_header 等字段
        test_cases = TestCase.query.filter(TestCase.case_id.in_(case_ids)).all()

        if not test_cases:
            return jsonify({"code": 404, "message": "未查询到对应测试用例"}), 404

        # 创建 Excel 工作簿和工作表
        wb = Workbook()
        ws = wb.active
        ws.title = "测试用例导出"

        # 写入表头（根据 TestCase 模型字段调整）
        headers = ["用例 ID", "用例名称", "请求头参数", "请求参数", "预期结果", "判定规则"]
        ws.append(headers)

        # 遍历查询到的用例数据，写入 Excel 行
        for case in test_cases:
            row_data = [
                case.case_id,
                case.case_name,
                case.request_header,
                case.request_param,
                case.expected_result,
                case.assert_rule
            ]
            ws.append(row_data)

        # 将生成的 Excel 保存到内存缓冲区
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)  # 将指针移到缓冲区开头，方便后续读取

        # 设置响应头，让浏览器触发文件下载
        return buffer.read(), 200, {
            'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'Content-Disposition': 'attachment; filename=test_cases.xlsx'
        }
    except Exception as e:
        # 捕获异常，返回错误信息
        print(f"导出用例失败: {e}")
        return jsonify({"code": 500, "message": "服务器内部错误，导出失败"}), 500


# 核心：接口依赖配置页面路由
# --------------------------
@main_bp.route('/interface/dependency/config')
def interface_dependency_config():
    # 1. 从URL参数中获取当前接口ID（必传参数）
    interface_id = request.args.get('interface_id')
    if not interface_id:
        return render_template('error.html', msg="缺少参数：interface_id"), 400

    # 2. 查询当前接口信息（预加载关联的参数，避免后续模板渲染时二次查询）
    # 使用 joinedload 预加载接口的参数列表（Interface.param 关系）
    current_interface = Interface.query.filter_by(interface_id=interface_id).options(
        joinedload(Interface.params)  # 预加载接口的所有参数
    ).first()

    # 处理接口不存在的情况
    if not current_interface:
        return render_template('error.html', msg=f"接口ID {interface_id} 不存在"), 404

    # 3. 查询所有接口（用于前置接口选择下拉框，排除当前接口自身）
    all_interfaces = Interface.query.filter(
        Interface.interface_id != interface_id  # 禁止选择自身作为前置接口
    ).all()

    # 4. 查询当前接口的「前置依赖」（当前接口作为后置接口）
    # 关联查询前置接口的基础信息（避免模板中访问 pre_interface 时出现空值）
    front_dependencies = InterfaceDependency.query.filter_by(
        post_interface_id=interface_id
    ).all()
    # 为每个依赖补充前置接口的完整信息（通过接口ID关联）
    for dep in front_dependencies:
        dep.pre_interface = Interface.query.get(dep.pre_interface_id)

    # 5. 查询当前接口的「被依赖情况」（当前接口作为前置接口）
    back_dependencies = InterfaceDependency.query.filter_by(
        pre_interface_id=interface_id
    ).all()
    # 为每个依赖补充后置接口的完整信息
    for dep in back_dependencies:
        dep.post_interface = Interface.query.get(dep.post_interface_id)

    # 6. 将所有变量传递给模板（与模板中使用的变量名完全对应）
    return render_template(
        'interface_dependency_config.html',
        # 当前接口信息（模板中用 current_interface 访问）
        current_interface=current_interface,
        # 所有接口列表（模板中用于选择前置接口）
        all_interfaces=all_interfaces,
        # 当前接口的前置依赖（模板中用 dependencies 访问）
        dependencies=front_dependencies,
        # 当前接口的被依赖情况（模板中用 dependent_interfaces 访问）
        dependent_interfaces=back_dependencies
    )


# --------------------------
# 辅助接口：获取接口参数（供前端加载目标参数下拉框）
# --------------------------
@main_bp.route('/api/interface/<int:interface_id>/parameters')
def get_interface_parameters(interface_id):
    """根据接口ID和参数类型（header/path/query/body）获取参数列表"""
    # 获取参数类型（默认请求头参数）
    param_type = request.args.get('type', 'header').upper()  # 转为大写，匹配 ParamType 枚举

    # 查询接口的参数（过滤指定类型）
    params = InterfaceParam.query.filter_by(
        interface_id=interface_id,
        param_type=param_type  # 匹配 ParamType 枚举（如 HEADER/PATH/QUERY/BODY）
    ).all()

    # 构造返回数据（供前端下拉框使用）
    result = [
        {
            'param_name': param.param_name,
            'data_type': param.data_type,
            'example_value': param.example_value
        }
        for param in params
    ]

    return jsonify({
        'code': 200,
        'data': result
    })


# --------------------------
# 辅助接口：获取接口响应示例（供前端预览提取规则）
# --------------------------
@main_bp.route('/api/interface/<int:interface_id>/response-example')
def get_interface_response_example(interface_id):
    """获取接口的真实响应示例（从数据库 InterfaceParam 表中读取）"""
    # 查询 InterfaceParam 表中，interface_id 匹配且参数名为 body 且 param_type 为 RESPONSE 的记录
    response_param = InterfaceParam.query.filter_by(
        interface_id=interface_id,
        param_name='body',
        param_type='RESPONSE'
    ).first()

    if not response_param:
        # 如果没有找到对应的响应参数，返回模拟数据或错误提示
        mock_response = {
            "code": 200,
            "data": {},
            "msg": "未找到接口响应示例"
        }
        return jsonify({
            'code': 200,
            'data': json.dumps(mock_response)
        })

    try:
        # 将数据库中存储的 example_value（JSON 字符串）转换为 Python 对象
        real_response = json.loads(response_param.example_value)
        return jsonify({
            'code': 200,
            'data': json.dumps(real_response)
        })
    except json.JSONDecodeError as e:
        # 如果 example_value 不是有效的 JSON 格式，返回错误
        return jsonify({
            'code': 500,
            'msg': f"响应示例 JSON 解析错误: {str(e)}"
        })


# --------------------------
# 辅助接口：保存/更新依赖配置
# --------------------------
@main_bp.route('/api/dependency/save', methods=['POST'])
def save_dependency():
    """保存或更新接口依赖配置"""
    import json
    data = request.form.get('data')
    if not data:
        return jsonify({'code': 400, 'msg': '缺少依赖配置数据'})

    try:
        dep_data = json.loads(data)
        dependency_id = dep_data.get('dependency_id')  # 有值则为更新，无值则为新增
        pre_interface_id = dep_data.get('pre_interface_id')
        post_interface_id = dep_data.get('post_interface_id')
        param_pass_rule = dep_data.get('param_pass_rule')
        dep_type = dep_data.get('dep_type', 'normal')

        # 验证必填字段
        if not (pre_interface_id and post_interface_id and param_pass_rule):
            return jsonify({'code': 400, 'msg': '前置接口ID、后置接口ID、参数传递规则为必填项'})

        # 新增依赖
        if not dependency_id:
            # 检查是否已存在相同依赖（避免重复）
            existing_dep = InterfaceDependency.query.filter_by(
                pre_interface_id=pre_interface_id,
                post_interface_id=post_interface_id
            ).first()
            if existing_dep:
                return jsonify({'code': 400, 'msg': '该前置-后置接口依赖已存在'})

            new_dep = InterfaceDependency(
                pre_interface_id=pre_interface_id,
                post_interface_id=post_interface_id,
                param_pass_rule=param_pass_rule,
                dep_type=dep_type
            )
            db.session.add(new_dep)
            db.session.commit()
            return jsonify({'code': 200, 'msg': '依赖添加成功'})

        # 更新依赖
        else:
            dep = InterfaceDependency.query.get(dependency_id)
            if not dep:
                return jsonify({'code': 404, 'msg': '依赖记录不存在'})

            dep.pre_interface_id = pre_interface_id
            dep.post_interface_id = post_interface_id
            dep.param_pass_rule = param_pass_rule
            dep.dep_type = dep_type
            db.session.commit()
            return jsonify({'code': 200, 'msg': '依赖更新成功'})

    except json.JSONDecodeError:
        return jsonify({'code': 400, 'msg': '配置数据格式错误（需JSON格式）'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'code': 500, 'msg': f'服务器错误：{str(e)}'})


# --------------------------
# 辅助接口：删除依赖配置
# --------------------------
@main_bp.route('/api/dependency/<int:dependency_id>', methods=['DELETE'])
def delete_dependency(dependency_id):
    """删除指定ID的依赖配置"""
    dep = InterfaceDependency.query.get(dependency_id)
    if not dep:
        return jsonify({'code': 404, 'msg': '依赖记录不存在'})

    try:
        db.session.delete(dep)
        db.session.commit()
        return jsonify({'code': 200, 'msg': '依赖删除成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'code': 500, 'msg': f'删除失败：{str(e)}'})


# --------------------------
# 辅助接口：获取依赖详情
# --------------------------
@main_bp.route('/api/dependency/<int:dependency_id>')
def get_dependency_detail(dependency_id):
    """获取指定ID的依赖配置详情"""
    dep = InterfaceDependency.query.get(dependency_id)
    if not dep:
        return jsonify({'code': 404, 'msg': '依赖记录不存在'})

    # 补充前置/后置接口信息
    pre_interface = Interface.query.get(dep.pre_interface_id)
    post_interface = Interface.query.get(dep.post_interface_id)

    return jsonify({
        'code': 200,
        'data': {
            'dependency_id': dep.dependency_id,
            'pre_interface_id': dep.pre_interface_id,
            'pre_interface': {
                'name': pre_interface.interface_name if pre_interface else '未知接口',
                'method': pre_interface.method.name if (pre_interface and pre_interface.method) else '',
                'url': pre_interface.url if pre_interface else ''
            },
            'post_interface_id': dep.post_interface_id,
            'post_interface': {
                'name': post_interface.interface_name if post_interface else '未知接口',
                'method': post_interface.method.name if (post_interface and post_interface.method) else '',
                'url': post_interface.url if post_interface else ''
            },
            'param_pass_rule': dep.param_pass_rule,
            'dep_type': dep.dep_type,
            'create_time': dep.create_time.strftime('%Y-%m-%d %H:%M:%S') if dep.create_time else ''
        }
    })






