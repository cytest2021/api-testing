from flask import Blueprint, request, jsonify, render_template
from flask_login import current_user, login_user, LoginManager
from app.models import db, TestPlan, PlanCase, TestCase, ExecutionRecord, TestResult, User, Project # 假设User模型在app.models中定义
from app.services.test_executor import run_test_case_batch
from datetime import datetime
import json

# 创建LoginManager实例
login_manager = LoginManager()

plan_bp = Blueprint('plan', __name__)


# 初始化login_manager，这里假设在主程序中会调用init_app进行绑定
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# 测试计划管理页面
@plan_bp.route('/test-plan-management')
def test_plan_management():
    # 检查用户登录状态，若未登录则使用固定用户登录
    if not current_user or not hasattr(current_user, 'user_id'):
        fixed_user = User.query.filter_by(user_id=1).first()
        if not fixed_user:
            fixed_user = User(
                user_id=1,
                username="fixed_user",
                role='admin',
                create_time=datetime.now()
            )
            db.session.add(fixed_user)
            db.session.commit()
        login_user(fixed_user)
    return render_template('test_plan_management.html')


# 创建测试计划
@plan_bp.route('/api/plan', methods=['POST'])
def create_plan():
    data = request.json
    try:
        # 检查用户登录状态，若未登录则使用固定用户登录
        if not current_user or not hasattr(current_user, 'user_id'):
            fixed_user = User.query.filter_by(user_id=1).first()
            if not fixed_user:
                fixed_user = User(
                    user_id=1,
                    username="fixed_user",
                    role='admin',
                    create_time=datetime.now()
                )
                db.session.add(fixed_user)
                db.session.commit()
            login_user(fixed_user)
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
# @plan_bp.route('/api/plan/<int:plan_id>/execute', methods=['POST'])
# def execute_plan(plan_id):
#     plan = TestPlan.query.get(plan_id)
#     if not plan:
#         return jsonify({"code": 404, "msg": "计划不存在"})
#     try:
#         # 检查用户登录状态，若未登录则使用固定用户登录
#         if not current_user or not hasattr(current_user, 'user_id'):
#             fixed_user = User.query.filter_by(user_id=1).first()
#             if not fixed_user:
#                 fixed_user = User(
#                     user_id=1,
#                     username="fixed_user",
#                     role='admin',
#                     create_time=datetime.now()
#                 )
#                 db.session.add(fixed_user)
#                 db.session.commit()
#             login_user(fixed_user)
#         # 创建执行记录
#         record = ExecutionRecord(
#             plan_id=plan_id,
#             start_time=datetime.now(),
#             status='running'
#         )
#         db.session.add(record)
#         db.session.commit()
#         # 获取计划内的用例（按执行顺序排序）
#         plan_cases = PlanCase.query.filter_by(plan_id=plan_id) \
#             .order_by(PlanCase.sort_order).all()
#         case_ids = [pc.case_id for pc in plan_cases]
#         # 批量执行用例（调用扩展后的执行器）
#         run_test_case_batch(case_ids, plan.env_url, record.record_id)
#         return jsonify({"code": 200, "msg": "计划执行中", "record_id": record.record_id})
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({"code": 500, "msg": f"执行失败：{str(e)}"})


# 获取执行结果
@plan_bp.route('/api/record/<int:record_id>', methods=['GET'])
def get_record_result(record_id):
    record = ExecutionRecord.query.get(record_id)
    if not record:
        return jsonify({"code": 404, "msg": "记录不存在"})
    # 检查用户登录状态，若未登录则使用固定用户登录
    if not current_user or not hasattr(current_user, 'user_id'):
        fixed_user = User.query.filter_by(user_id=1).first()
        if not fixed_user:
            fixed_user = User(
                user_id=1,
                username="fixed_user",
                role='admin',
                create_time=datetime.now()
            )
            db.session.add(fixed_user)
            db.session.commit()
        login_user(fixed_user)
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

# 新增获取测试计划列表的接口
@plan_bp.route('/api/plans', methods=['GET'])
# @login_required  # 如果需要登录才能获取，取消注释这行
def get_test_plans():
    try:
        test_plans = TestPlan.query.all()
        plans_list = []
        for plan in test_plans:
            project = Project.query.filter_by(project_id=plan.project_id).first()
            project_name = project.project_name if project else "未知项目"
            # 状态英文转中文
            status_mapping = {
                'draft': '草稿',
                'running': '运行中',
                'completed': '已完成'
            }
            chinese_status = status_mapping.get(plan.status, plan.status)
            plans_list.append({
                'plan_id': plan.plan_id,
                'plan_name': plan.plan_name,
                'project_id': plan.project_id,
                'project_name': project_name,
                'env_url': plan.env_url,
                'execute_type': plan.execute_type,
                'cron_expression': plan.cron_expression,
                'creator_id': plan.creator_id,
                'create_time': plan.create_time.strftime('%Y-%m-%d %H:%M:%S'),
                'status': chinese_status  # 返回中文状态
            })
        return jsonify({
            'code': 200,
            'message': '获取测试计划列表成功',
            'data': plans_list
        })
    except Exception as e:
        return jsonify({
            'code': 500,
            'message': f'获取测试计划列表失败：{str(e)}'
        })

@plan_bp.route('/api/plan/<int:plan_id>/cases', methods=['GET'])
def get_plan_cases(plan_id):
    try:
        # 查询计划下所有用例及顺序（按顺序排序）
        plan_cases = PlanCase.query.filter_by(plan_id=plan_id).order_by(PlanCase.sort_order).all()
        cases = []
        for pc in plan_cases:
            case = TestCase.query.get(pc.case_id)
            cases.append({
                "case_id": case.case_id,
                "case_name": case.case_name,
                "sort_order": pc.sort_order
            })
        return jsonify({"code": 200, "data": cases})
    except Exception as e:
        return jsonify({"code": 500, "msg": f"查询失败：{str(e)}"})

@plan_bp.route('/api/plan/<int:plan_id>/cases', methods=['PUT'])
def update_plan_case_order(plan_id):
    data = request.json
    try:
        # 先删除原有计划用例关系（批量更新需先清空再插入）
        PlanCase.query.filter_by(plan_id=plan_id).delete()
        # 插入新的顺序
        for idx, case_info in enumerate(data):
            plan_case = PlanCase(
                plan_id=plan_id,
                case_id=case_info["case_id"],
                sort_order=idx + 1  # 顺序从1开始
            )
            db.session.add(plan_case)
        db.session.commit()
        return jsonify({"code": 200, "msg": "更新成功"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"更新失败：{str(e)}"})

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

        # 关键修改：按 sort_order 排序获取用例
        plan_cases = PlanCase.query.filter_by(plan_id=plan_id) \
            .order_by(PlanCase.sort_order).all()  # 按顺序排序
        case_ids = [pc.case_id for pc in plan_cases]  # 按顺序生成用例ID列表

        # 批量执行用例（调用扩展后的执行器，传入顺序后的case_ids）
        run_test_case_batch(case_ids, plan.env_url, record.record_id)

        return jsonify({"code": 200, "msg": "计划执行中", "record_id": record.record_id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"执行失败：{str(e)}"})


@plan_bp.route('/api/plan/<int:plan_id>', methods=['PUT'])
def edit_test_plan(plan_id):
    try:
        data = request.json
        # 校验数据完整性（根据实际需求调整）
        if not all(key in data for key in ['plan_name', 'project_id', 'env_url', 'execute_type']):
            return jsonify({"code": 400, "msg": "参数不完整"}), 400

        plan = TestPlan.query.get(plan_id)
        if not plan:
            return jsonify({"code": 404, "msg": "测试计划不存在"}), 404

        # 更新测试计划字段
        plan.plan_name = data.get('plan_name', plan.plan_name)
        plan.project_id = data.get('project_id', plan.project_id)
        plan.env_url = data.get('env_url', plan.env_url)
        plan.execute_type = data.get('execute_type', plan.execute_type)
        plan.cron_expression = data.get('cron_expression', plan.cron_expression)

        db.session.commit()
        return jsonify({"code": 200, "msg": "编辑成功", "data": {"plan_id": plan_id}}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"编辑失败: {str(e)}"}), 500


@plan_bp.route('/api/plan/<int:plan_id>', methods=['DELETE'])
def delete_test_plan(plan_id):
    try:
        plan = TestPlan.query.get(plan_id)
        if not plan:
            return jsonify({"code": 404, "msg": "测试计划不存在"}), 404

        db.session.delete(plan)
        db.session.commit()
        return jsonify({"code": 200, "msg": "删除成功"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": 500, "msg": f"删除失败: {str(e)}"}), 500