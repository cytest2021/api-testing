from app.models import Interface, InterfaceParam, TestCase, db, ParamType
import json


def generate_test_cases(interface_id, creator_id):
    """根据接口ID生成测试用例并落库"""
    interface = Interface.query.get(interface_id)
    if not interface:
        return "接口不存在"

    test_cases = []

    # 获取各类参数（使用枚举类型过滤）
    header_params = InterfaceParam.query.filter(
        InterfaceParam.interface_id == interface_id,
        InterfaceParam.param_type == ParamType.HEADER
    ).all()

    path_params = InterfaceParam.query.filter(
        InterfaceParam.interface_id == interface_id,
        InterfaceParam.param_type == ParamType.PATH
    ).all()

    query_params = InterfaceParam.query.filter(
        InterfaceParam.interface_id == interface_id,
        InterfaceParam.param_type == ParamType.QUERY
    ).all()

    body_params = InterfaceParam.query.filter(
        InterfaceParam.interface_id == interface_id,
        InterfaceParam.param_type == ParamType.BODY
    ).all()

    response_params = InterfaceParam.query.filter(
        InterfaceParam.interface_id == interface_id,
        InterfaceParam.param_type == ParamType.RESPONSE
    ).all()

    # 正常用例
    normal_header = {p.param_name: p.example_value for p in header_params if p.example_value}
    normal_request = {p.param_name: p.example_value for p in path_params + query_params + body_params if
                      p.example_value}
    normal_response = {p.param_name: p.example_value for p in response_params if p.example_value}

    normal_case = TestCase(
        interface_id=interface_id,
        case_name=f"{interface.interface_name}正常用例",
        method=interface.method.name,
        url=interface.url,
        request_header=json.dumps(normal_header, ensure_ascii=False),
        request_param=json.dumps(normal_request, ensure_ascii=False),
        expected_result=json.dumps(normal_response, ensure_ascii=False),
        assert_rule="响应状态码为200",
        creator_id=creator_id
    )
    test_cases.append(normal_case)

    # 异常用例：缺失必填项
    required_params = InterfaceParam.query.filter(
        InterfaceParam.interface_id == interface_id,
        InterfaceParam.is_required == True,
        InterfaceParam.param_type.in_([ParamType.PATH, ParamType.QUERY, ParamType.BODY, ParamType.HEADER])
    ).all()

    for param in required_params:
        # 复制正常参数
        err_header = normal_header.copy()
        err_request = normal_request.copy()

        # 清空当前必填参数值
        if param.param_type == ParamType.HEADER:
            if param.param_name in err_header:
                err_header[param.param_name] = ""
        else:
            if param.param_name in err_request:
                err_request[param.param_name] = ""

        case = TestCase(
            interface_id=interface_id,
            case_name=f"{interface.interface_name}缺失必填项{param.param_name}",
            method=interface.method.name,
            url=interface.url,
            request_header=json.dumps(err_header, ensure_ascii=False),
            request_param=json.dumps(err_request, ensure_ascii=False),
            expected_result="",  # 不填预期结果
            assert_rule=f"响应中包含缺失{param.param_name}的错误信息",
            creator_id=creator_id
        )
        test_cases.append(case)

    # 异常用例：数值型参数边界值
    numeric_params = InterfaceParam.query.filter(
        InterfaceParam.interface_id == interface_id,
        InterfaceParam.data_type == 'number',
        InterfaceParam.param_type.in_([ParamType.PATH, ParamType.QUERY, ParamType.BODY, ParamType.HEADER])
    ).all()

    for param in numeric_params:
        # 最小值用例
        min_header = normal_header.copy()
        min_request = normal_request.copy()

        # 设置最小值
        if param.param_type == ParamType.HEADER:
            min_header[param.param_name] = "最小值"  # 实际应用中应从param.constraint解析
        else:
            min_request[param.param_name] = "最小值"  # 实际应用中应从param.constraint解析

        min_case = TestCase(
            interface_id=interface_id,
            case_name=f"{interface.interface_name}{param.param_name}最小值用例",
            method=interface.method.name,
            url=interface.url,
            request_header=json.dumps(min_header, ensure_ascii=False),
            request_param=json.dumps(min_request, ensure_ascii=False),
            expected_result="",
            assert_rule="响应状态码为200或包含参数错误信息",
            creator_id=creator_id
        )
        test_cases.append(min_case)

        # 最大值用例
        max_header = normal_header.copy()
        max_request = normal_request.copy()

        if param.param_type == ParamType.HEADER:
            max_header[param.param_name] = "最大值"  # 实际应用中应从param.constraint解析
        else:
            max_request[param.param_name] = "最大值"  # 实际应用中应从param.constraint解析

        max_case = TestCase(
            interface_id=interface_id,
            case_name=f"{interface.interface_name}{param.param_name}最大值用例",
            method=interface.method.name,
            url=interface.url,
            request_header=json.dumps(max_header, ensure_ascii=False),
            request_param=json.dumps(max_request, ensure_ascii=False),
            expected_result="",
            assert_rule="响应状态码为200或包含参数错误信息",
            creator_id=creator_id
        )
        test_cases.append(max_case)

        # 超出范围用例
        out_header = normal_header.copy()
        out_request = normal_request.copy()

        if param.param_type == ParamType.HEADER:
            out_header[param.param_name] = "超出范围值"  # 实际应用中应从param.constraint解析
        else:
            out_request[param.param_name] = "超出范围值"  # 实际应用中应从param.constraint解析

        out_case = TestCase(
            interface_id=interface_id,
            case_name=f"{interface.interface_name}{param.param_name}超出范围用例",
            method=interface.method.name,
            url=interface.url,
            request_header=json.dumps(out_header, ensure_ascii=False),
            request_param=json.dumps(out_request, ensure_ascii=False),
            expected_result="",
            assert_rule="响应包含参数超出范围的错误信息",
            creator_id=creator_id
        )
        test_cases.append(out_case)

    # 保存到数据库
    db.session.add_all(test_cases)
    db.session.commit()
    return f"成功生成{len(test_cases)}条用例"