import json
from concurrent.futures import ThreadPoolExecutor
import requests
from datetime import datetime
from app.models import TestCase, TestResult, ExecutionRecord, db


def eval_assert(response, assert_rule_str):
    """
    解析断言规则并验证响应
    :param response: requests 库的响应对象
    :param assert_rule_str: 断言规则的 JSON 字符串（如 {"status": true, "code": 200}）
    :return: bool，断言是否通过
    """
    try:
        # 将断言规则字符串解析为字典
        assert_rule = json.loads(assert_rule_str)

        # 1. 校验响应状态码（规则含 "status": true 时，校验状态码为 200）
        if assert_rule.get("status"):
            if response.status_code != 200:
                return False

        # 2. 校验业务码（规则含 "code" 时，校验响应体 code 字段匹配）
        if "code" in assert_rule:
            expected_code = assert_rule["code"]
            try:
                resp_json = response.json()
                if resp_json.get("code") != expected_code:
                    return False
            except json.JSONDecodeError:
                return False

        # 可根据需要扩展更多断言逻辑（如 body 字段、header 等校验）
        return True
    except Exception as e:
        print(f"断言解析/验证失败: {str(e)}")
        return False


# 批量执行用例
def run_test_case_batch(case_ids, env_url, record_id):
    """并发执行测试用例批次"""
    record = ExecutionRecord.query.get(record_id)
    if not record:
        raise ValueError(f"执行记录不存在（ID: {record_id}）")
    record.total_cases = len(case_ids)
    db.session.commit()

    # 使用线程池并发执行
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(
            run_test_case, case_id, env_url, record_id
        ) for case_id in case_ids]

        # 等待所有任务完成（若需忽略异常，可捕获 Future 异常）
        for future in futures:
            future.result()  # 若任务抛异常，此处会抛出

    # 更新执行记录统计
    update_execution_record(record_id)


def run_test_case(case_id, env_url, record_id=None):
    """执行单条测试用例（支持关联执行记录）"""
    case = TestCase.query.get(case_id)
    if not case:
        raise ValueError(f"测试用例不存在（ID: {case_id}）")

    result = TestResult(
        case_id=case_id,
        exec_time=datetime.now(),
        record_id=record_id  # 关联执行记录
    )

    try:
        # 1. 构造请求
        url = env_url + case.interface.url
        method = case.interface.method
        # 安全解析请求参数（替换原 eval）
        try:
            params = json.loads(case.request_param)
        except json.JSONDecodeError:
            raise ValueError(f"用例参数解析失败（ID: {case_id}，参数：{case.request_param}）")

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
        if eval_assert(response, case.assert_rule):
            result.status = 'pass'
        else:
            result.status = 'fail'
            result.error_msg = f"断言失败：预期{case.assert_rule}，实际响应：{response.text[:100]}..."  # 截断长响应

        db.session.add(result)
        db.session.commit()  # 单次提交
    except Exception as e:
        # 异常时回滚事务，避免脏数据
        db.session.rollback()
        result.status = 'fail'
        result.error_msg = str(e)
        db.session.add(result)
        db.session.commit()  # 提交异常结果

    return result


def update_execution_record(record_id):
    """更新执行记录统计信息"""
    record = ExecutionRecord.query.get(record_id)
    if not record:
        return  # 记录不存在时直接返回

    results = TestResult.query.filter_by(record_id=record_id).all()
    if not results:
        return

    record.pass_cases = sum(1 for r in results if r.status == 'pass')
    record.fail_cases = sum(1 for r in results if r.status == 'fail')
    record.end_time = datetime.now()
    record.status = 'completed'

    db.session.commit()  # 提交统计结果