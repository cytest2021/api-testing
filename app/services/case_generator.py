from app.models import InterfaceParam, TestCase, db
from datetime import datetime


def generate_cases(interface_id, creator_id):
    """基于接口参数自动生成测试用例（正常+异常场景）"""
    params = InterfaceParam.query.filter_by(interface_id=interface_id).all()
    if not params:
        return "未找到接口参数，无法生成用例"

    cases = []
    # 1. 正常场景：所有参数正确传递
    normal_params = {p.param_name: get_default_value(p) for p in params}
    cases.append(TestCase(
        interface_id=interface_id,
        case_name="正常请求（全参数）",
        param_values=str(normal_params),
        expected_result='{"status": "success"}',
        assert_rule="status_code=200",
        creator_id=creator_id
    ))

    # 2. 异常场景：必填参数缺失
    for p in params:
        if p.is_required:
            abnormal_params = normal_params.copy()
            del abnormal_params[p.param_name]
            cases.append(TestCase(
                interface_id=interface_id,
                case_name=f"异常请求（缺失必填参数：{p.param_name}）",
                param_values=str(abnormal_params),
                expected_result='{"status": "error", "msg": "参数缺失"}',
                assert_rule="status_code=400",
                creator_id=creator_id
            ))

    # 3. 异常场景：参数类型错误
    for p in params:
        wrong_params = normal_params.copy()
        wrong_params[p.param_name] = get_wrong_type_value(p)  # 生成错误类型的值
        cases.append(TestCase(
            interface_id=interface_id,
            case_name=f"异常请求（参数类型错误：{p.param_name}）",
            param_values=str(wrong_params),
            expected_result='{"status": "error", "msg": "参数类型错误"}',
            assert_rule="status_code=400",
            creator_id=creator_id
        ))

    db.session.add_all(cases)
    db.session.commit()
    return f"成功生成{len(cases)}条用例"


def get_default_value(param):
    """生成符合类型的默认值"""
    if param.data_type == 'int':
        return 0
    elif param.data_type == 'string':
        return "test_value"
    elif param.data_type == 'bool':
        return True
    elif param.data_type == 'float':
        return 0.0
    return None


def get_wrong_type_value(param):
    """生成错误类型的值（用于异常测试）"""
    if param.data_type == 'int':
        return "not_a_number"  # 字符串代替数字
    elif param.data_type == 'string':
        return 12345  # 数字代替字符串
    return None