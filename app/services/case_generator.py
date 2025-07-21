# app/services/case_generator.py
from app.models import InterfaceParam, TestCase


def generate_cases(interface_id, creator_id):
    """基于接口参数自动生成测试用例"""
    params = InterfaceParam.query.filter_by(interface_id=interface_id).all()
    cases = []

    # 1. 生成正常场景用例（所有参数正确）
    normal_params = {p.param_name: get_default_value(p) for p in params}
    cases.append(TestCase(
        interface_id=interface_id,
        case_name="正常请求",
        param_values=str(normal_params),
        expected_result='{"status": "success"}',
        assert_rule="status_code=200",
        creator_id=creator_id
    ))

    # 2. 生成异常场景用例（缺失必填参数）
    for p in params:
        if p.is_required:
            abnormal_params = normal_params.copy()
            del abnormal_params[p.param_name]
            cases.append(TestCase(
                interface_id=interface_id,
                case_name=f"缺失必填参数：{p.param_name}",
                param_values=str(abnormal_params),
                expected_result='{"status": "error"}',
                assert_rule="status_code=400",
                creator_id=creator_id
            ))

    db.session.add_all(cases)
    db.session.commit()
    return f"生成用例数：{len(cases)}"


def get_default_value(param):
    """根据参数类型生成默认值（如int默认0，string默认"test"）"""
    if param.data_type == 'int':
        return 0
    elif param.data_type == 'string':
        return "test"
    return None