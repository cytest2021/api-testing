from app.models import Interface, InterfaceParam
from sqlalchemy import func


def generate_test_cases(interface):
    test_cases = []
    case_id = 1

    # 正常用例
    normal_case = {
        "case_id": case_id,
        "case_name": f"{interface.interface_name}正常用例",
        "method": interface.method.name,
        "url": interface.url,
        "param_name": "",
        "param_values": "",
        "expected_result": "",
        "assert_rule": "响应状态码为200",
    }
    path_params = InterfaceParam.query.filter_by(interface_id=interface.interface_id, param_type='PATH').all()
    query_params = InterfaceParam.query.filter_by(interface_id=interface.interface_id, param_type='QUERY').all()
    body_params = InterfaceParam.query.filter_by(interface_id=interface.interface_id, param_type='BODY').all()
    header_params = InterfaceParam.query.filter_by(interface_id=interface.interface_id, param_type='HEADER').all()
    response_params = InterfaceParam.query.filter_by(interface_id=interface.interface_id, param_type='RESPONSE').all()

    normal_case["param_values"] = ', '.join([param.example_value for param in path_params + query_params + body_params + header_params if param.example_value])
    normal_case["expected_result"] = ', '.join([param.example_value for param in response_params if param.example_value])

    test_cases.append(normal_case)
    case_id += 1

    # 缺失必填项用例
    required_params = InterfaceParam.query.filter_by(interface_id=interface.interface_id, is_required=True).all()
    for param in required_params:
        missing_param_case = {
            "case_id": case_id,
            "case_name": f"{interface.interface_name}缺失必填项{param.param_name}用例",
            "method": interface.method.name,
            "url": interface.url,
            "param_name": param.param_name,
            "param_values": ', '.join([p.example_value for p in path_params + query_params + body_params + header_params if p.param_name != param.param_name and p.example_value]),
            "expected_result": "请设置预期响应结果",
            "assert_rule": f"响应中包含缺失{param.param_name}的错误信息"
        }
        test_cases.append(missing_param_case)
        case_id += 1

    # 数值型参数边界值用例
    numeric_params = InterfaceParam.query.filter_by(interface_id=interface.interface_id, data_type='number').all()
    for param in numeric_params:
        min_boundary_case = {
            "case_id": case_id,
            "case_name": f"{interface.interface_name}{param.param_name}最小值边界用例",
            "method": interface.method.name,
            "url": interface.url,
            "param_name": param.param_name,
            "param_values": f"{param.param_name}: 最小值",
            "expected_result": "请设置预期响应结果",
            "assert_rule": "响应状态码为200"
        }
        test_cases.append(min_boundary_case)
        case_id += 1

        max_boundary_case = {
            "case_id": case_id,
            "case_name": f"{interface.interface_name}{param.param_name}最大值边界用例",
            "method": interface.method.name,
            "url": interface.url,
            "param_name": param.param_name,
            "param_values": f"{param.param_name}: 最大值",
            "expected_result": "请设置预期响应结果",
            "assert_rule": "响应状态码为200"
        }
        test_cases.append(max_boundary_case)
        case_id += 1

        out_of_range_case = {
            "case_id": case_id,
            "case_name": f"{interface.interface_name}{param.param_name}超出范围用例",
            "method": interface.method.name,
            "url": interface.url,
            "param_name": param.param_name,
            "param_values": f"{param.param_name}: 超出范围值",
            "expected_result": "请设置预期响应结果",
            "assert_rule": "响应包含参数超出范围的错误信息"
        }
        test_cases.append(out_of_range_case)
        case_id += 1

    return test_cases
