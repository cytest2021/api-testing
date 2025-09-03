from flask import Blueprint, request, jsonify,render_template
from flask_login import current_user
from app.models import db, TestPlan, PlanCase, TestCase, ExecutionRecord, TestResult
from app.services.test_executor import run_test_case_batch
from datetime import datetime
import json

plan_bp = Blueprint('plan', __name__)


# 测试计划管理页面
@plan_bp.route('/test-plan-management')
def test_plan_management():
    return render_template('test_plan_management.html')


# 创建测试计划
@plan_bp.route('/api/plan', methods=['POST'])
def create_plan():
    data = request.json
    try:
        plan = TestPlan(
            plan_name=data['plan_name'],
            project_id=data['project_id'],
            env_url=data['env_url'],
            execute_type=data['execute_type'],
            cron_expression=data.get('cron_expression'),
            creator_id=current_user.user_id
        )
        db.session.add(plan)
        db.session.commit()

        # 添加计划用例及执行顺序
        for idx, case_id in enumerate(data['case_ids']):
            plan_case = PlanCase(
                plan_id=plan.plan_id,
                case_id=case_id,
                sort_order=idx + 1
            )
            db.session.add(plan_case)
        db.session.commit()
        return jsonify({"code": 200, "msg": "计划创建成功", "plan_id": plan.plan_id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"创建失败：{str(e)}"})


# 执行测试计划
@plan_bp.route('/api/plan/<int:plan_id>/execute', methods=['POST'])
def execute_plan(plan_id):
    plan = TestPlan.query.get(plan_id)
    if not plan:
        return jsonify({"code": 404, "msg": "计划不存在"})

    try:
        # 创建执行记录
        record = ExecutionRecord(
            plan_id=plan_id,
            start_time=datetime.now(),
            status='running'
        )
        db.session.add(record)
        db.session.commit()

        # 获取计划内的用例（按执行顺序排序）
        plan_cases = PlanCase.query.filter_by(plan_id=plan_id) \
            .order_by(PlanCase.sort_order).all()
        case_ids = [pc.case_id for pc in plan_cases]

        # 批量执行用例（调用扩展后的执行器）
        run_test_case_batch(case_ids, plan.env_url, record.record_id)

        return jsonify({"code": 200, "msg": "计划执行中", "record_id": record.record_id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"执行失败：{str(e)}"})


# 获取执行结果
@plan_bp.route('/api/record/<int:record_id>', methods=['GET'])
def get_record_result(record_id):
    record = ExecutionRecord.query.get(record_id)
    if not record:
        return jsonify({"code": 404, "msg": "记录不存在"})

    # 获取该记录下的所有用例结果
    results = TestResult.query.filter_by(record_id=record_id).all()
    result_list = [{
        "case_id": r.case_id,
        "case_name": TestCase.query.get(r.case_id).case_name,
        "status": r.status,
        "duration": r.duration,
        "error_msg": r.error_msg,
        "actual_response": r.actual_response
    } for r in results]

    return jsonify({
        "code": 200,
        "data": {
            "record": {
                "start_time": record.start_time,
                "end_time": record.end_time,
                "total": record.total_cases,
                "pass": record.pass_cases,
                "fail": record.fail_cases,
                "status": record.status
            },
            "results": result_list
        }
    })