import json
from datetime import datetime
from app.models import db, Project, Interface, InterfaceParam, HttpMethod, ParamType, TestCase
from flask_login import current_user

class PostmanParser:
    def __init__(self, postman_file, project_name, project_desc):
        self.postman_file = postman_file
        self.project_name = project_name
        self.project_desc = project_desc
        self.project = None

    def _load_json(self):
        """加载并校验 Postman JSON 文件"""
        try:
            return json.load(self.postman_file)
        except json.JSONDecodeError as e:
            raise ValueError(f"Postman JSON 格式错误: {str(e)}")

    def _create_project(self):
        """创建或复用项目"""
        existing_project = Project.query.filter_by(project_name=self.project_name).first()
        if existing_project:
            self.project = existing_project
            return

        # 兼容未登录场景（若 current_user 无 id，设为 1）
        creator_id = current_user.id if current_user and hasattr(current_user, 'id') else 1

        self.project = Project(
            project_name=self.project_name,
            description=self.project_desc or "从 Postman 导入",
            creator_id=creator_id,
            create_time=datetime.now()
        )
        db.session.add(self.project)
        db.session.flush()  # 提前获取 project_id

    def _parse_params(self, interface_id, params, param_type):
        """解析并创建接口参数"""
        for param in params:
            param_name = param.get("key")
            if not param_name:
                continue

            # 处理嵌套参数（如 user.name → parent_key=user, param_name=name）
            parent_key = None
            if "." in param_name:
                parts = param_name.split(".")
                param_name = parts[-1]
                parent_key = ".".join(parts[:-1])

            example_value = param.get("value")
            data_type = self._infer_data_type(example_value)

            interface_param = InterfaceParam(
                interface_id=interface_id,
                param_name=param_name,
                param_type=param_type,
                data_type=data_type,
                is_required=param.get("required", False),
                parent_key=parent_key,
                example_value=str(example_value) if example_value is not None else None
            )
            db.session.add(interface_param)

    def _infer_data_type(self, value):
        """推断参数数据类型"""
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, (list, tuple)):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "string"

    def _create_test_case(self, interface):
        """创建测试用例"""
        case_name = f"默认用例_{interface.interface_name}"
        if TestCase.query.filter_by(interface_id=interface.id, case_name=case_name).first():
            return

        params = InterfaceParam.query.filter_by(interface_id=interface.id).all()
        param_values = {p.param_name: p.example_value for p in params if p.example_value}


        test_case = TestCase(
            interface_id=interface.id,
            case_name=case_name,
            param_values=json.dumps(param_values) if param_values else None,
            expected_result="状态码: 200",
            assert_rule="response.status_code == 200",
            creator_id=current_user.id if current_user and hasattr(current_user, 'id') else 1
        )
        db.session.add(test_case)

    def _parse_item(self, item, parent_path=""):
        """递归解析 Postman 目录/请求"""
        item_name = item.get("name", "未命名")
        current_path = f"{parent_path}/{item_name}" if parent_path else item_name

        # 若为目录，继续递归子项
        if "item" in item and isinstance(item["item"], list):
            for sub_item in item["item"]:
                self._parse_item(sub_item, current_path)
            return

        request = item.get("request")
        if not request:
            return

        # 解析 URL
        url = request.get("url", {})
        raw_url = url.get("raw", "") if isinstance(url, dict) else str(url)

        # 解析请求方法
        method = request.get("method", "GET")
        try:
            http_method = HttpMethod(method)
        except ValueError:
            http_method = HttpMethod.GET

        # 关联或创建接口
        interface = Interface.query.filter_by(
            project_id=self.project.id,
            interface_name=current_path
        ).first()

        if not interface:
            interface = Interface(
                project_id=self.project.id,
                interface_name=current_path,
                url=raw_url,
                method=http_method,
                request_header=json.dumps(request.get("header", []))
            )
            db.session.add(interface)
            db.session.flush()

        # 解析不同类型的参数（路径、查询、请求头、请求体）
        params = {
            ParamType.PATH: self._parse_url_params(url),
            ParamType.QUERY: request.get("query", []),
            ParamType.HEADER: request.get("header", []),
            ParamType.BODY: self._parse_body_params(request.get("body", {}))
        }

        for param_type, param_list in params.items():
            self._parse_params(interface.id, param_list, param_type)

        # 创建测试用例
        self._create_test_case(interface)

    def _parse_url_params(self, url):
        """解析路径参数（如 /user/:id → id 参数）"""
        path_params = []
        if isinstance(url, dict) and "path" in url:
            for segment in url["path"]:
                if isinstance(segment, str) and segment.startswith(":"):
                    param_name = segment[1:]
                    path_params.append({
                        "key": param_name,
                        "value": f"{{{param_name}}}",
                        "required": True
                    })
        return path_params

    def _parse_body_params(self, body):
        """解析请求体参数（formdata/urlencoded）"""
        mode = body.get("mode")
        if mode in ["formdata", "urlencoded"] and isinstance(body.get(mode), list):
            return body[mode]
        return []

    def parse(self):
        """主解析逻辑，返回统一格式的结果"""
        try:
            postman_data = self._load_json()
            self._create_project()
            for item in postman_data.get("item", []):
                self._parse_item(item)
            db.session.commit()
            return {
                "success": True,
                "parse_success": True,
                "project_id": self.project.id,
                "message": "Postman JSON 解析成功"
            }
        except Exception as e:
            db.session.rollback()
            return {
                "success": False,
                "parse_success": False,
                "error": f"Postman 解析失败: {str(e)}"
            }