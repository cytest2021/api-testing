from app.models import Interface, InterfaceParam, TestCase, db, ParamType, Project
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
import json
import datetime


def generate_test_cases_by_project(project_id, creator_id):
    """
    按项目维度生成用例：仅生成数据库中不存在的用例
    :param project_id: 项目ID
    :param creator_id: 创建者ID
    :return: 生成结果描述
    """
    # 1. 获取项目下所有接口（按 interface_id 升序排序）
    interfaces = Interface.query.filter_by(
        project_id=project_id
    ).order_by(Interface.interface_id.asc()).all()

    if not interfaces:
        return "项目下无接口，无法生成用例"

    total_cases = 0  # 新增用例总数
    existing_cases = 0  # 已存在用例总数

    for interface in interfaces:
        # 2. 为单个接口生成用例（返回新增数量和已存在数量）
        new_count, exist_count = generate_test_cases(
            interface_id=interface.interface_id,
            creator_id=creator_id
        )
        total_cases += new_count
        existing_cases += exist_count

    return (f"用例生成完成：新增 {total_cases} 条，"
            f"已存在 {existing_cases} 条（未重复生成）")


def generate_test_cases(interface_id, creator_id):
    """
    为单个接口生成用例：仅生成数据库中不存在的用例
    :param interface_id: 接口ID
    :param creator_id: 创建者ID
    :return: (新增用例数, 已存在用例数)
    """
    # 1. 基础校验：接口是否存在
    interface = Interface.query.get(interface_id)
    if not interface:
        raise ValueError(f"接口不存在（ID: {interface_id}）")

    # 2. 获取接口参数
    header_params = InterfaceParam.query.filter_by(
        interface_id=interface_id,
        param_type=ParamType.HEADER
    ).order_by(InterfaceParam.param_id).all()
    path_params = InterfaceParam.query.filter_by(
        interface_id=interface_id,
        param_type=ParamType.PATH
    ).order_by(InterfaceParam.param_id).all()
    query_params = InterfaceParam.query.filter_by(
        interface_id=interface_id,
        param_type=ParamType.QUERY
    ).order_by(InterfaceParam.param_id).all()
    body_params = InterfaceParam.query.filter_by(
        interface_id=interface_id,
        param_type=ParamType.BODY
    ).order_by(InterfaceParam.param_id).all()
    response_params = InterfaceParam.query.filter_by(
        interface_id=interface_id,
        param_type=ParamType.RESPONSE
    ).order_by(InterfaceParam.param_id).all()

    # 3. 生成所有可能的用例（先在内存中构造）
    candidate_cases = []

    # 3.1 正常用例
    normal_header = {p.param_name: p.example_value for p in header_params if p.example_value}
    normal_request = {p.param_name: p.example_value for p in path_params + query_params + body_params if
                      p.example_value}
    normal_response = {p.param_name: p.example_value for p in response_params if p.example_value}

    normal_case_name = f"{interface.interface_name} - 正常用例"
    candidate_cases.append(TestCase(
        interface_id=interface_id,
        case_name=normal_case_name,
        request_header=json.dumps(normal_header, ensure_ascii=False),
        request_param=json.dumps(normal_request, ensure_ascii=False),
        expected_result=json.dumps(normal_response, ensure_ascii=False),
        assert_rule="响应状态码为200且参数匹配",
        creator_id=creator_id,
        create_time=datetime.datetime.now()
    ))

    # 3.2 异常用例：必填参数缺失
    required_params = InterfaceParam.query.filter(
        and_(
            InterfaceParam.interface_id == interface_id,
            InterfaceParam.is_required == True,
            InterfaceParam.param_type.in_([ParamType.PATH, ParamType.QUERY, ParamType.BODY, ParamType.HEADER])
        )
    ).order_by(InterfaceParam.param_id).all()

    for param in required_params:
        err_header = normal_header.copy()
        err_request = normal_request.copy()
        if param.param_type == ParamType.HEADER:
            err_header[param.param_name] = ""
        else:
            err_request[param.param_name] = ""

        case_name = f"{interface.interface_name} - 缺失必填项 {param.param_name}"
        candidate_cases.append(TestCase(
            interface_id=interface_id,
            case_name=case_name,
            request_header=json.dumps(err_header, ensure_ascii=False),
            request_param=json.dumps(err_request, ensure_ascii=False),
            expected_result="",
            assert_rule=f"响应包含缺失{param.param_name}的错误",
            creator_id=creator_id,
            create_time=datetime.datetime.now()
        ))

    # 3.3 异常用例：数值型参数边界值
    numeric_params = InterfaceParam.query.filter(
        and_(
            InterfaceParam.interface_id == interface_id,
            InterfaceParam.data_type == 'number',
            InterfaceParam.param_type.in_([ParamType.PATH, ParamType.QUERY, ParamType.BODY, ParamType.HEADER])
        )
    ).order_by(InterfaceParam.param_id).all()

    for param in numeric_params:
        constraints = {}
        if param.constraint:
            for item in param.constraint.split(';'):
                if '=' in item:
                    k, v = item.split('=')
                    try:
                        constraints[k] = int(v)
                    except ValueError:
                        continue

        min_val = constraints.get('min', 0)
        max_val = constraints.get('max', 100)

        # 最小值用例
        min_header = normal_header.copy()
        min_request = normal_request.copy()
        if param.param_type == ParamType.HEADER:
            min_header[param.param_name] = min_val
        else:
            min_request[param.param_name] = min_val

        case_name = f"{interface.interface_name} - {param.param_name} 最小值用例"
        candidate_cases.append(TestCase(
            interface_id=interface_id,
            case_name=case_name,
            request_header=json.dumps(min_header, ensure_ascii=False),
            request_param=json.dumps(min_request, ensure_ascii=False),
            expected_result="",
            assert_rule=f"响应状态码为200或包含参数错误（{param.param_name}最小值）",
            creator_id=creator_id,
            create_time=datetime.datetime.now()
        ))

        # 最大值用例
        max_header = normal_header.copy()
        max_request = normal_request.copy()
        if param.param_type == ParamType.HEADER:
            max_header[param.param_name] = max_val
        else:
            max_request[param.param_name] = max_val

        case_name = f"{interface.interface_name} - {param.param_name} 最大值用例"
        candidate_cases.append(TestCase(
            interface_id=interface_id,
            case_name=case_name,
            request_header=json.dumps(max_header, ensure_ascii=False),
            request_param=json.dumps(max_request, ensure_ascii=False),
            expected_result="",
            assert_rule=f"响应状态码为200或包含参数错误（{param.param_name}最大值）",
            creator_id=creator_id,
            create_time=datetime.datetime.now()
        ))

        # 超出范围用例
        out_header = normal_header.copy()
        out_request = normal_request.copy()
        if param.param_type == ParamType.HEADER:
            out_header[param.param_name] = max_val + 1
        else:
            out_request[param.param_name] = max_val + 1

        case_name = f"{interface.interface_name} - {param.param_name} 超出范围用例"
        candidate_cases.append(TestCase(
            interface_id=interface_id,
            case_name=case_name,
            request_header=json.dumps(out_header, ensure_ascii=False),
            request_param=json.dumps(out_request, ensure_ascii=False),
            expected_result="",
            assert_rule=f"响应包含参数超出范围错误（{param.param_name}）",
            creator_id=creator_id,
            create_time=datetime.datetime.now()
        ))

    # 4. 过滤已存在的用例（核心逻辑）
    new_cases = []
    existing_count = 0

    # 批量查询已存在的用例（减少数据库交互）
    case_names = [case.case_name for case in candidate_cases]
    existing_case_names = db.session.query(TestCase.case_name).filter(
        and_(
            TestCase.interface_id == interface_id,
            TestCase.case_name.in_(case_names)
        )
    ).all()
    # 转换为集合便于快速判断
    existing_names = {name for (name,) in existing_case_names}

    # 筛选出不存在的用例
    for case in candidate_cases:
        if case.case_name in existing_names:
            existing_count += 1
        else:
            new_cases.append(case)

    # 5. 仅插入新用例
    if new_cases:
        try:
            db.session.add_all(new_cases)
            db.session.commit()
        except IntegrityError as e:
            db.session.rollback()
            raise ValueError(f"数据库约束冲突：{str(e)}")
        except Exception as e:
            db.session.rollback()
            raise ValueError(f"插入用例失败：{str(e)}")

    return len(new_cases), existing_count
