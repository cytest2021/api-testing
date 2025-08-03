from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
from enum import Enum, auto
from sqlalchemy import CheckConstraint

# 初始化 SQLAlchemy
db = SQLAlchemy()

# 自定义枚举类，支持忽略大小写解析HTTP方法
class HttpMethod(Enum):
    GET = auto()
    POST = auto()
    PUT = auto()
    DELETE = auto()
    PATCH = auto()

    @classmethod
    def _missing_(cls, value):
        """重写_missing_方法，实现忽略大小写匹配"""
        upper_value = value.upper()
        for member in cls:
            if member.name == upper_value:
                return member
        return super()._missing_(value)

# 1. 用户表（管理系统用户，区分角色）
class User(db.Model, UserMixin):
    __tablename__ = 'user'
    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.Enum('admin', 'regular', 'viewer'), default='regular', nullable=False)
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)
    update_time = db.Column(db.DateTime, onupdate=datetime.now, nullable=True)  # 信息更新时间

    # 关系：用户创建的测试用例
    test_cases = db.relationship('TestCase', backref='creator', lazy=True)
    # 关系：用户创建的项目
    projects = db.relationship('Project', backref='owner', lazy=True)

    @property
    def is_active(self):
        return True  # 默认用户激活状态

    def get_id(self):
        return str(self.user_id)  # 返回用户唯一标识

# 2. 项目表（组织接口、用例的层级）
class Project(db.Model):
    __tablename__ = 'project'
    project_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)  # 项目负责人
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)
    status = db.Column(
        db.Enum('active', 'inactive', 'deleted'),
        default='active',
        nullable=False
    )

    # 关系：项目包含的接口
    interfaces = db.relationship('Interface', backref='project', lazy=True)

# 3. 接口表（存储接口基础信息）
class Interface(db.Model):
    __tablename__ = 'interface'
    interface_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.project_id'), nullable=False)
    interface_name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(255), nullable=False)
    method = db.Column(db.Enum(HttpMethod), nullable=False)  # 支持大小写不敏感的HTTP方法
    request_header = db.Column(db.Text)  # 存储JSON格式的请求头
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # 关系：接口关联的参数
    params = db.relationship('InterfaceParam', backref='interface', lazy=True)
    # 关系：接口关联的测试用例
    test_cases = db.relationship('TestCase', backref='interface', lazy=True)

# 4. 接口参数表（细化接口入参规则，支持嵌套参数）
class InterfaceParam(db.Model):
    __tablename__ = 'interface_param'
    param_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    interface_id = db.Column(db.Integer, db.ForeignKey('interface.interface_id'), nullable=False)
    param_name = db.Column(db.String(100), nullable=False)  # 支持嵌套参数名（如data.user.name）
    param_type = db.Column(
        db.Enum('path', 'query', 'body', 'header', 'response'),  # 新增response类型
        nullable=False
    )
    data_type = db.Column(db.String(20), nullable=False)  # 支持string/number/boolean等
    is_required = db.Column(db.Boolean, default=False)
    parent_key = db.Column(db.String(200))  # 记录嵌套层级（如"data.user"）
    example_value = db.Column(db.Text)  # 存储示例值

    # 约束：确保参数类型有效
    __table_args__ = (
        CheckConstraint(
            "param_type IN ('path', 'query', 'body', 'header', 'response')",
            name="valid_param_type"
        ),
    )

# 5. 测试用例表（核心用例配置，关联接口参数）
class TestCase(db.Model):
    __tablename__ = 'test_case'
    case_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    interface_id = db.Column(db.Integer, db.ForeignKey('interface.interface_id'), nullable=False)
    case_name = db.Column(db.String(100), nullable=False)
    param_values = db.Column(db.Text)  # 存储{param_name: value}的JSON格式，与InterfaceParam对应
    expected_result = db.Column(db.Text)  # 预期响应结果（JSON字符串）
    assert_rule = db.Column(db.String(200))  # 断言规则（如"status == 'success'"）
    creator_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # 关联测试结果
    results = db.relationship('TestResult', backref='test_case', lazy=True)
    # 关联依赖关系
    dependencies = db.relationship('Dependency',
                                  primaryjoin="(TestCase.case_id == Dependency.source_id) & (Dependency.source_type == 'case')",
                                  backref='source_case', lazy=True)
    dependent_on = db.relationship('Dependency',
                                  primaryjoin="(TestCase.case_id == Dependency.target_id) & (Dependency.target_type == 'case')",
                                  backref='target_case', lazy=True)

    def get_param_mapping(self):
        """解析param_values为字典，关联InterfaceParam的param_name"""
        import json
        return json.loads(self.param_values) if self.param_values else {}

# 6. 测试结果表（记录用例执行结果）
class TestResult(db.Model):
    __tablename__ = 'test_result'
    result_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    case_id = db.Column(db.Integer, db.ForeignKey('test_case.case_id'), nullable=False)
    exec_time = db.Column(db.DateTime, default=datetime.now, nullable=False)
    status = db.Column(db.Enum('pass', 'fail', 'error'), nullable=False)
    actual_response = db.Column(db.Text)  # 实际响应结果
    duration = db.Column(db.Float)  # 执行耗时（秒）
    error_msg = db.Column(db.Text)  # 错误信息（失败/异常时）

# 7. 依赖关系表（管理接口/用例的依赖）
class Dependency(db.Model):
    __tablename__ = 'dependency'
    dep_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    source_type = db.Column(db.Enum('interface', 'case'), nullable=False)  # 依赖源类型
    source_id = db.Column(db.Integer, nullable=False)  # 依赖源ID
    target_type = db.Column(db.Enum('interface', 'case'), nullable=False)  # 依赖目标类型
    target_id = db.Column(db.Integer, nullable=False)  # 依赖目标ID
    dep_desc = db.Column(db.String(200))  # 依赖描述（如"需先获取token"）

    # 联合唯一约束：避免重复依赖
    __table_args__ = (
        db.UniqueConstraint('source_type', 'source_id', 'target_type', 'target_id', name='unique_dependency'),
    )
