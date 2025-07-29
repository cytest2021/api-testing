from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
# 初始化 SQLAlchemy
db = SQLAlchemy()

# 1. 用户表（管理系统用户，区分角色）
class User(db.Model, UserMixin):  # 新增：继承 UserMixin
    __tablename__ = 'user'
    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.Enum('admin', 'regular', 'viewer'), default='regular', nullable=False)
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # 新增：实现 is_active 属性，Flask - Login 会调用它判断用户是否激活
    @property
    def is_active(self):
        # 简单返回 True，代表用户默认激活；实际可根据业务逻辑（如数据库字段）控制
        return True
    # 新增：实现 get_id 方法，返回用户唯一标识
    def get_id(self):
        return str(self.user_id)  # 返回 user_id 作为用户唯一标识，需转字符串

# 2. 项目表（组织接口、用例的层级）
class Project(db.Model):
    __tablename__ = 'project'
    project_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)

# 3. 接口表（存储接口基础信息）
class Interface(db.Model):
    __tablename__ = 'interface'
    interface_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.project_id'), nullable=False)
    interface_name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(255), nullable=False)
    method = db.Column(db.Enum('GET', 'POST', 'PUT', 'DELETE', 'PATCH'), nullable=False)
    request_header = db.Column(db.Text)
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)
    # 关联参数（一对多）
    params = db.relationship('InterfaceParam', backref='interface', lazy='dynamic')
    # 关联测试用例（一对多）
    cases = db.relationship('TestCase', backref='interface', lazy='dynamic')

# 4. 接口参数表（细化接口入参规则）
class InterfaceParam(db.Model):
    __tablename__ = 'interface_param'
    param_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    interface_id = db.Column(db.Integer, db.ForeignKey('interface.interface_id'), nullable=False)
    param_name = db.Column(db.String(50), nullable=False)
    param_type = db.Column(db.Enum('path', 'query', 'body', 'header'), nullable=False)
    data_type = db.Column(db.String(20), nullable=False)
    is_required = db.Column(db.Boolean, default=False)
    constraint = db.Column(db.String(200))
    example_value = db.Column(db.String(200))

# 5. 测试用例表（核心用例配置）
class TestCase(db.Model):
    __tablename__ = 'test_case'
    case_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    interface_id = db.Column(db.Integer, db.ForeignKey('interface.interface_id'), nullable=False)
    case_name = db.Column(db.String(100), nullable=False)
    param_values = db.Column(db.Text)
    expected_result = db.Column(db.Text)
    assert_rule = db.Column(db.String(200))
    creator_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)

# 6. 测试结果表（记录用例执行结果）
class TestResult(db.Model):
    __tablename__ = 'test_result'
    result_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    case_id = db.Column(db.Integer, db.ForeignKey('test_case.case_id'), nullable=False)
    exec_time = db.Column(db.DateTime, default=datetime.now, nullable=False)
    status = db.Column(db.Enum('pass', 'fail', 'error'), nullable=False)
    actual_response = db.Column(db.Text)
    duration = db.Column(db.Float)
    error_msg = db.Column(db.Text)

# 7. 依赖关系表（管理接口/用例的依赖）
class Dependency(db.Model):
    __tablename__ = 'dependency'
    dep_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    source_type = db.Column(db.Enum('interface', 'case'), nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    target_type = db.Column(db.Enum('interface', 'case'), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    dep_desc = db.Column(db.String(200))