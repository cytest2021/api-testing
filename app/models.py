from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
from enum import Enum, auto
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import validates
from sqlalchemy import and_


# 初始化 SQLAlchemy
db = SQLAlchemy()

# 自定义枚举类：HTTP方法（支持大小写不敏感）
class HttpMethod(Enum):
    GET = auto()
    POST = auto()
    PUT = auto()
    DELETE = auto()
    PATCH = auto()

    @classmethod
    def _missing_(cls, value):
        upper_value = value.upper()
        for member in cls:
            if member.name == upper_value:
                return member
        return super()._missing_(value)

# 自定义枚举类：参数类型（覆盖 path/query/body/header/response）
class ParamType(Enum):
    PATH = "path"
    QUERY = "query"
    BODY = "body"
    HEADER = "header"
    RESPONSE = "response"

# 1. 用户表（系统用户，区分角色）
class User(db.Model, UserMixin):
    __tablename__ = 'user'
    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.Enum('admin', 'regular', 'viewer'), default='regular', nullable=False)
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)
    update_time = db.Column(db.DateTime, onupdate=datetime.now)  # 记录信息更新时间

    # 关系：用户创建的项目（反向关联 Project.owner）
    owned_projects = db.relationship('Project', backref='owner', lazy='dynamic')
    # 关系：用户创建的测试用例（反向关联 TestCase.creator）
    created_cases = db.relationship('TestCase', backref='creator', lazy='dynamic')

    @property
    def is_active(self):
        return True  # 简化逻辑，实际可结合业务状态控制

    def get_id(self):
        return str(self.user_id)

# 2. 项目表（组织接口、用例的层级容器）
class Project(db.Model):
    __tablename__ = 'project'
    project_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_name = db.Column(db.String(100), nullable=False, unique=True)  # 项目名称唯一
    description = db.Column(db.Text, nullable=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)  # 关联创建者
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)
    status = db.Column(
        db.Enum('active', 'inactive', 'deleted'),
        default='active',
        nullable=False
    )

    # 关系：项目包含的接口（反向关联 Interface.project）
    interfaces = db.relationship('Interface', backref='project', lazy='dynamic', cascade='all, delete-orphan')

    # 联合约束：项目名称 + 状态 唯一性（避免同名项目重复创建）
    __table_args__ = (
        UniqueConstraint('project_name', 'status', name='unique_project_name_status'),
    )

# 3. 接口表（存储接口基础信息，关联项目）
class Interface(db.Model):
    __tablename__ = 'interface'
    interface_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.project_id'), nullable=False)  # 关联项目
    interface_name = db.Column(db.String(100), nullable=False)  # 接口名称（项目内唯一）
    url = db.Column(db.String(255), nullable=False)
    method = db.Column(db.Enum(HttpMethod), nullable=False)  # 关联 HTTP 方法枚举
    request_header = db.Column(db.Text, nullable=True)  # 存储 JSON 格式请求头
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # 关系：接口关联的参数（反向关联 InterfaceParam.interface）
    params = db.relationship('InterfaceParam', backref='interface', lazy='dynamic', cascade='all, delete-orphan')
    # 关系：接口关联的测试用例（反向关联 TestCase.interface）
    test_cases = db.relationship('TestCase', backref='interface', lazy='dynamic', cascade='all, delete-orphan')

    # 项目内接口名称唯一约束
    __table_args__ = (
        UniqueConstraint('project_id', 'interface_name', name='unique_interface_in_project'),
    )


# 4. 接口参数表（细化入参规则，支持嵌套）
class InterfaceParam(db.Model):
    __tablename__ = 'interface_param'
    param_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    interface_id = db.Column(db.Integer, db.ForeignKey('interface.interface_id'), nullable=False)  # 关联接口
    param_name = db.Column(db.String(100), nullable=False)  # 支持嵌套命名（如 data.user.name）
    param_type = db.Column(db.Enum(ParamType), nullable=False)  # 关联参数类型枚举
    data_type = db.Column(db.String(20), nullable=False)  # 数据类型（string/number/boolean 等）
    is_required = db.Column(db.Boolean, default=False)
    parent_key = db.Column(db.String(200), nullable=True)  # 嵌套层级（如 "data.user"）
    example_value = db.Column(db.Text, nullable=True)  # 示例值
    constraint = db.Column(db.String(500), nullable=True)  # 参数约束（长度、范围等）

    # 约束：确保参数类型有效
    # __table_args__ = (
    #     CheckConstraint(
    #         "param_type IN ('path', 'query', 'body', 'header', 'response')",
    #         name="valid_param_type"
    #     ),
    # )

    # 校验 data_type 合理性（示例）
    @validates('data_type')
    def validate_data_type(self, key, value):
        valid_types = {'string', 'number', 'boolean', 'array', 'object', 'null'}
        if value.lower() not in valid_types:
            raise ValueError(f"不支持的数据类型 {value}，请使用 {valid_types} 之一")
        return value

# 7. 依赖关系表（管理接口/用例的依赖）
class Dependency(db.Model):
    __tablename__ = 'dependency'
    dep_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    source_type = db.Column(db.Enum('interface', 'case'), nullable=False)  # 依赖源类型（接口/用例）
    source_id = db.Column(db.Integer, nullable=False)  # 依赖源 ID
    target_type = db.Column(db.Enum('interface', 'case'), nullable=False)  # 依赖目标类型
    target_id = db.Column(db.Integer, nullable=False)  # 依赖目标 ID
    dep_desc = db.Column(db.String(200), nullable=True)  # 依赖描述

    # 联合唯一约束：避免重复依赖关系
    __table_args__ = (
        db.UniqueConstraint('source_type', 'source_id', 'target_type', 'target_id', name='unique_dependency'),
    )

    # 校验依赖类型合理性（示例）
    @validates('source_type', 'target_type')
    def validate_dependency_type(self, key, value):
        valid_types = {'interface', 'case'}
        if value not in valid_types:
            raise ValueError(f"不支持的依赖类型 {value}，请使用 {valid_types} 之一")
        return value

# 5. 测试用例表（核心用例配置，关联接口和参数）
class TestCase(db.Model):
    __tablename__ = 'test_case'
    case_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    interface_id = db.Column(db.Integer, db.ForeignKey('interface.interface_id'), nullable=False)
    case_name = db.Column(db.String(100), nullable=False)
    param_values = db.Column(db.Text, nullable=True)
    expected_result = db.Column(db.Text, nullable=True)
    assert_rule = db.Column(db.String(200), nullable=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    create_time = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # 1. 作为依赖源的关系（source_type='case' 时）
    outgoing_dependencies = db.relationship(
        'Dependency',
        primaryjoin="TestCase.case_id == Dependency.source_id",  # 简化条件（外键已约束）
        backref='source_case',
        lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys=[Dependency.source_id]  # 显式指定外键
    )

    # 2. 作为依赖目标的关系（target_type='case' 时）
    incoming_dependencies = db.relationship(
        'Dependency',
        primaryjoin="TestCase.case_id == Dependency.target_id",  # 简化条件（外键已约束）
        backref='target_case',
        lazy='dynamic',
        foreign_keys=[Dependency.target_id]  # 显式指定外键
    )

    # 用例执行结果（反向关联 TestResult.test_case）
    results = db.relationship(
        'TestResult',
        backref='test_case',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    # 接口内用例名称唯一约束
    __table_args__ = (
        db.UniqueConstraint('interface_id', 'case_name', name='unique_case_in_interface'),
    )

    def get_param_mapping(self):
        """解析 param_values 为字典（兼容空值）"""
        import json
        try:
            return json.loads(self.param_values) if self.param_values else {}
        except json.JSONDecodeError:
            return {}  # 解析失败时返回空字典，避免抛出异常

# 6. 测试结果表（记录用例执行结果）
class TestResult(db.Model):
    __tablename__ = 'test_result'
    result_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    case_id = db.Column(db.Integer, db.ForeignKey('test_case.case_id'), nullable=False)  # 关联用例
    exec_time = db.Column(db.DateTime, default=datetime.now, nullable=False)
    status = db.Column(db.Enum('pass', 'fail', 'error'), nullable=False)  # 执行状态
    actual_response = db.Column(db.Text, nullable=True)  # 实际响应内容
    duration = db.Column(db.Float, nullable=True)  # 执行耗时（秒）
    error_msg = db.Column(db.Text, nullable=True)  # 错误信息（失败/异常时）

