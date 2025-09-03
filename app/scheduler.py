from apscheduler.schedulers.background import BackgroundScheduler
from app.models import TestPlan
from app.services.test_executor import run_test_case_batch
from datetime import datetime

scheduler = BackgroundScheduler()

def init_scheduler(app):
    """初始化定时任务调度器"""
    with app.app_context():
        # 启动时加载所有定时计划
        load_timing_plans()
        scheduler.start()

def load_timing_plans():
    """加载所有定时执行的测试计划"""
    plans = TestPlan.query.filter_by(execute_type='timing', status='draft').all()
    for plan in plans:
        if plan.cron_expression:
            add_timing_job(plan.plan_id, plan.cron_expression)

def add_timing_job(plan_id, cron_expr):
    """添加定时任务"""
    scheduler.add_job(
        execute_timing_plan,
        'cron',
        args=[plan_id],
        cron表达式=cron_expr,
        id=f"plan_{plan_id}"
    )

def execute_timing_plan(plan_id):
    """执行定时计划"""
    from flask import current_app
    with current_app.app_context():
        plan = TestPlan.query.get(plan_id)
        if plan:
            # 调用执行逻辑（同手动执行）
            from app.routes.plan_routes import execute_plan
            execute_plan(plan_id)