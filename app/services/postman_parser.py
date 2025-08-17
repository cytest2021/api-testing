import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from app.models import db, Project, Interface, InterfaceParam, HttpMethod, ParamType, TestCase
from flask_login import current_user
import logging

# 配置日志用于调试
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Path 参数映射规则：键为原始路径段，值为参数名
PATH_PARAM_MAPPING = {
    "1": "user_id"
    # 可根据需要添加更多映射，如 "2": "other_param"
}


class PostmanParser:
    def __init__(self, postman_file, project_name, project_desc):
        self.postman_file = postman_file
        self.project_name = project_name
        self.project_desc = project_desc
        self.project = None
        # 提前验证current_user类型
        self._validate_current_user()

    def _validate_current_user(self):
        """验证current_user类型并记录日志"""
        logger.debug(f"current_user类型: {type(current_user)}")
        logger.debug(f"current_user属性: {dir(current_user)}")

        # 检查是否为匿名用户或无效类型
        if not hasattr(current_user, 'user_id'):
            logger.warning("current_user缺少user_id属性，将使用默认值1")

    def _load_json(self):
        try:
            return json.load(self.postman_file)
        except json.JSONDecodeError as e:
            raise ValueError(f"Postman JSON 格式错误: {str(e)}")

    def _create_project(self):
        existing_project = Project.query.filter_by(project_name=self.project_name).first()
        if existing_project:
            self.project = existing_project
            logger.debug(f"使用现有项目: {self.project.project_id}")
            return

        # 安全获取用户ID，增加类型检查
        if isinstance(current_user, dict):
            raise TypeError("current_user是字典类型，预期为User对象")

        creator_id = current_user.user_id if (current_user and hasattr(current_user, 'user_id')) else 1
        logger.debug(f"创建项目的用户ID: {creator_id}")

        self.project = Project(
            project_name=self.project_name,
            description=self.project_desc or "从 Postman 导入",
            creator_id=creator_id,
            create_time=datetime.now()
        )

        # 验证项目对象类型
        if not isinstance(self.project, Project):
            raise TypeError("创建的项目不是Project模型实例")

        db.session.add(self.project)
        try:
            db.session.flush()
            logger.debug(f"新创建项目ID: {self.project.project_id}")
        except Exception as e:
            db.session.rollback()
            raise RuntimeError(f"项目创建数据库操作失败: {str(e)}")

    def _parse_params(self, interface_id, params, param_type):
        # 验证接口ID类型
        if not isinstance(interface_id, int):
            raise TypeError(f"接口ID应为整数，实际为{type(interface_id)}")

        for param in params:
            if not isinstance(param, dict):
                logger.warning(f"跳过非字典类型的参数: {param}")
                continue

            param_name = param.get("key")
            if not param_name:
                continue

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

            # 验证参数对象类型
            if not isinstance(interface_param, InterfaceParam):
                raise TypeError("创建的参数不是InterfaceParam模型实例")

            db.session.add(interface_param)

    def _infer_data_type(self, value):
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

    def _create_test_case(self, interface, response_data=None):
        # 验证接口对象类型
        if not isinstance(interface, Interface):
            raise TypeError(f"预期Interface对象，实际为{type(interface)}")

        case_name = f"默认用例_{interface.interface_name}"
        existing_case = TestCase.query.filter_by(interface_id=interface.interface_id, case_name=case_name).first()
        if existing_case:
            return existing_case

        params = InterfaceParam.query.filter_by(interface_id=interface.interface_id).all()
        param_values = {p.param_name: p.example_value for p in params if p.example_value}

        # 处理响应数据，设置预期结果
        expected_result = "状态码: 200"
        assert_rule = "response.status_code == 200"
        if response_data:
            status = response_data.get("status")
            code = response_data.get("code")
            body = response_data.get("body")
            if status and code:
                expected_result = f"状态: {status}, 状态码: {code}"
                assert_rule = f"response.status == '{status}' and response.code == {code}"
            if body:
                # 直接拼接中文，不进行转义
                expected_result += f", 响应体包含关键数据: {body}"

        # 安全获取用户ID
        creator_id = current_user.user_id if (current_user and hasattr(current_user, 'user_id')) else 1

        test_case = TestCase(
            interface_id=interface.interface_id,
            case_name=case_name,
            param_values=json.dumps(param_values, ensure_ascii=False) if param_values else None,
            expected_result=expected_result,
            assert_rule=assert_rule,
            creator_id=creator_id
        )

        # 验证测试用例对象类型
        if not isinstance(test_case, TestCase):
            raise TypeError("创建的测试用例不是TestCase模型实例")

        db.session.add(test_case)
        return test_case

    def _parse_request_body(self, body):
        body_params = []
        if not isinstance(body, dict):
            return body_params
        mode = body.get("mode")
        if mode == "raw":
            raw_data = body.get("raw")
            if raw_data:
                try:
                    json_data = json.loads(raw_data)
                    if isinstance(json_data, dict):
                        for key, value in json_data.items():
                            body_params.append({
                                "key": key,
                                "value": value,
                                "required": True
                            })
                except json.JSONDecodeError:
                    logger.warning(f"请求体Raw数据不是有效的JSON: {raw_data}")
        elif mode in ["formdata", "urlencoded"] and isinstance(body.get(mode), list):
            body_params = body[mode]
        return body_params

    def _parse_response(self, response, interface):
        response_params = []
        if not isinstance(response, dict):
            return response_params

        # 提取响应主要信息：status、code、body
        status = response.get("status")
        code = response.get("code")
        body = response.get("body")

        # 处理状态参数
        if status is not None:
            response_params.append({
                "key": "status",
                "value": status,
                "required": True
            })

        # 处理状态码参数
        if code is not None:
            response_params.append({
                "key": "code",
                "value": code,
                "required": True
            })

        # 处理响应体参数（保留完整JSON）
        if body is not None:
            try:
                # 尝试解析为JSON对象保留原始结构
                json_body = json.loads(body) if isinstance(body, str) else body
                response_params.append({
                    "key": "body",
                    "value": json_body,  # 存储完整JSON对象（含中文）
                    "required": True
                })
            except json.JSONDecodeError:
                # 非JSON格式直接存储原始字符串
                response_params.append({
                    "key": "body",
                    "value": body,  # 非JSON格式直接存储字符串（含中文）
                    "required": True
                })
                logger.warning(f"响应体不是有效的JSON，已存储原始字符串: {body}")

        # 保存响应参数到数据库
        for param in response_params:
            interface_param = InterfaceParam(
                interface_id=interface.interface_id,
                param_name=param["key"],
                param_type=ParamType.RESPONSE,
                data_type=self._infer_data_type(param["value"]),
                is_required=param.get("required", False),
                example_value=json.dumps(param["value"], ensure_ascii=False) if isinstance(param["value"], (dict, list)) else str(
                    param["value"])
            )
            db.session.add(interface_param)

        # 返回提取的主要响应数据
        return {
            "status": status,
            "code": code,
            "body": body
        }

    def _parse_item(self, item, parent_path=""):
        # 验证item是字典类型
        if not isinstance(item, dict):
            logger.warning(f"跳过非字典类型的item: {item}")
            return

        item_name = item.get("name", "未命名")
        current_path = f"{parent_path}/{item_name}" if parent_path else item_name

        if "item" in item and isinstance(item["item"], list):
            for sub_item in item["item"]:
                self._parse_item(sub_item, current_path)
            return

        request = item.get("request")
        response = item.get("response")
        if not request:
            return

        # 从originalRequest中提取更完整的请求信息（含Query参数）
        original_request = request.get("originalRequest", request)
        url = original_request.get("url", {})
        raw_url = url.get("raw", "") if isinstance(url, dict) else str(url)

        # 提取并处理Path参数，生成参数化的path_url
        parsed_url = urlparse(raw_url)
        original_path = parsed_url.path
        path_segments = original_path.split("/")
        processed_segments = []
        for segment in path_segments:
            if segment in PATH_PARAM_MAPPING:
                processed_segments.append(f"{{{PATH_PARAM_MAPPING[segment]}}}")
            else:
                processed_segments.append(segment)
        path_url = "/".join(processed_segments)  # 参数化后的路径，如/api/users/{user_id}/orders

        method = original_request.get("method", "GET")
        try:
            http_method = HttpMethod(method)
        except ValueError:
            http_method = HttpMethod.GET

        # 确保项目已创建
        if not self.project:
            raise RuntimeError("解析接口前未创建项目")

        interface = Interface.query.filter_by(
            project_id=self.project.project_id,
            interface_name=current_path
        ).first()

        if not interface:
            interface = Interface(
                project_id=self.project.project_id,
                interface_name=current_path,
                url=path_url,  # 存储参数化后的路径
                method=http_method,
                # 处理请求头，只保留key和value，且保留中文
                request_header=json.dumps([{"key": h.get("key"), "value": h.get("value")}
                                           for h in original_request.get("header", []) if isinstance(h, dict)], ensure_ascii=False)
            )
            db.session.add(interface)
            try:
                db.session.flush()
                logger.debug(f"新创建接口ID: {interface.interface_id}")
            except Exception as e:
                db.session.rollback()
                raise RuntimeError(f"接口创建数据库操作失败: {str(e)}")

        # 解析Query参数（从URL查询字符串中提取）
        query_string = parsed_url.query
        query_params = []
        if query_string:
            # 使用parse_qs解析查询字符串，如 min_price=1000&max_price=3000 → {min_price: ['1000'], max_price: ['3000']}
            parsed_query = parse_qs(query_string)
            for key, values in parsed_query.items():
                # 取第一个值作为示例值（若有多个值，可根据需求调整）
                query_params.append({"key": key, "value": values[0], "required": True})

        # 解析请求参数
        params = {
            ParamType.PATH: self._parse_url_params(url),
            ParamType.QUERY: query_params,  # 从URL查询字符串提取的Query参数
            # 处理请求头参数，只保留key和value
            ParamType.HEADER: [{"key": h.get("key"), "value": h.get("value"), "required": h.get("required", False)}
                               for h in original_request.get("header", []) if isinstance(h, dict)],
            ParamType.BODY: self._parse_request_body(original_request.get("body", {}))
        }

        for param_type, param_list in params.items():
            self._parse_params(interface.interface_id, param_list, param_type)

        # 解析响应参数
        response_data = None
        if response:
            # 处理响应列表情况，取第一个有效响应
            if isinstance(response, list) and len(response) > 0:
                response_data = self._parse_response(response[0], interface)
            else:
                response_data = self._parse_response(response, interface)

        # # 创建测试用例
        # self._create_test_case(interface, response_data)

    def _parse_url_params(self, url):
        path_params = []
        if isinstance(url, dict) and "path" in url:
            for segment in url["path"]:
                if isinstance(segment, str):
                    # 规则1：识别以:开头的路径段（Postman常见Path参数标记）
                    if segment.startswith(":"):
                        param_name = segment[1:]
                        path_params.append({
                            "key": param_name,
                            "value": f"{{{param_name}}}",
                            "required": True
                        })
                    # 规则2：通过PATH_PARAM_MAPPING映射数字等路径段为参数
                    elif segment in PATH_PARAM_MAPPING:
                        param_name = PATH_PARAM_MAPPING[segment]
                        path_params.append({
                            "key": param_name,
                            "value": f"{{{param_name}}}",
                            "required": True
                        })
        return path_params

    def parse(self):
        try:
            postman_data = self._load_json()
            self._create_project()
            for item in postman_data.get("item", []):
                self._parse_item(item)
            db.session.commit()
            return {
                "success": True,
                "parse_success": True,
                "project_id": self.project.project_id,
                "message": "Postman JSON 解析成功"
            }
        except json.JSONDecodeError as e:
            db.session.rollback()
            return {
                "success": False,
                "parse_success": False,
                "error": f"JSON 解析错误: {str(e)}"
            }
        except TypeError as e:
            db.session.rollback()
            return {
                "success": False,
                "parse_success": False,
                "error": f"类型错误: {str(e)}"  # 明确提示类型错误
            }
        except RuntimeError as e:
            db.session.rollback()
            return {
                "success": False,
                "parse_success": False,
                "error": str(e)
            }
        except Exception as e:
            db.session.rollback()
            return {
                "success": False,
                "parse_success": False,
                "error": f"Postman 解析过程中发生未知错误: {str(e)}"
            }