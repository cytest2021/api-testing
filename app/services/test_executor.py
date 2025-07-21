# app/services/test_executor.py
import requests
from datetime import datetime
from app.models import TestCase, TestResult


def run_test_case(case_id, env_url):
    """执行单条测试用例并记录结果"""
    case = TestCase.query.get(case_id)
    result = TestResult(case_id=case_id, exec_time=datetime.now())

    try:
        # 1. 构造请求
        url = env_url + case.interface.url  # 拼接环境前缀
        method = case.interface.method
        params = eval(case.param_values)  # 实际开发建议用json.loads

        # 2. 发送请求
        start_time = datetime.now()
        if method == 'GET':
            response = requests.get(url, params=params, timeout=10)
        else:
            response = requests.post(url, json=params, timeout=10)
        duration = (datetime.now() - start_time).total_seconds()

        # 3. 断言结果
        result.actual_response = response.text
        result.duration = duration
        if eval_assert(response, case.assert_rule):  # 自定义断言函数
            result.status = 'pass'
        else:
            result.status = 'fail'
            result.error_msg = f"断言失败：预期{case.assert_rule}，实际{response.status_code}"

    except Exception as e:
        result.status = 'fail'
        result.error_msg = str(e)

    db.session.add(result)
    db.session.commit()
    return result


def eval_assert(response, rule):
    """解析断言规则（如"status_code=200"）"""
    if 'status_code' in rule:
        expected_code = int(rule.split('=')[1])
        return response.status_code == expected_code
    # 可扩展其他断言（如JSON字段匹配）
    return False