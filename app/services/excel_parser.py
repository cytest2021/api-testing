from datetime import datetime
import openpyxl
import json
from app.models import Interface, InterfaceParam, TestCase, db  # 确保导入正确的模型路径
import logging
from sqlalchemy.exc import IntegrityError

# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def parse_excel(file, project_id, creator_id):
    """
    解析 Excel 接口文档，关联接口参数与测试用例，支持区分参数类型（query/body/header 等）
    :param file: 上传的文件对象
    :param project_id: 项目 ID（关联 Project 表）
    :param creator_id: 测试用例创建者 ID（关联 User 表）
    :return: 解析结果字符串
    """
    try:
        # 加载 Excel 文件
        wb = openpyxl.load_workbook(file, data_only=True)
        sheet = wb.active
        logger.debug(f"加载 Excel 成功，工作表名称: {sheet.title}，总行数: {sheet.max_row}")

        # 1. 读取表头并建立映射关系
        header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
        header_mapping = {}
        for idx, header in enumerate(header_row):
            if not header:
                continue
            # 支持多种表头名称（不区分大小写）
            header_lower = header.lower()
            if '接口名称' in header_lower or 'api名称' in header_lower:
                header_mapping['interface_name'] = idx
            elif 'url' in header_lower or '地址' in header_lower:
                header_mapping['url'] = idx
            elif '方法' in header_lower or '请求方式' in header_lower:
                header_mapping['method'] = idx
            elif '请求头' in header_lower or 'headers' in header_lower:
                header_mapping['request_header'] = idx
            elif '请求体' in header_lower or 'body' in header_lower:
                header_mapping['request_body'] = idx
            elif '响应' in header_lower or 'response' in header_lower:
                header_mapping['response_result'] = idx  # 标记响应结果表头
            # 新增对“参数类型”表头的支持
            elif '参数类型' in header_lower or 'param type' in header_lower:
                header_mapping['param_type'] = idx

        # 校验必要字段
        required_fields = ['interface_name', 'url', 'method']
        missing_fields = [f for f in required_fields if f not in header_mapping]
        if missing_fields:
            error_msg = f"Excel 缺少必要表头：{', '.join(missing_fields)}"
            logger.error(error_msg)
            return error_msg

        # 2. 解析数据行
        interface_count = 0
        param_count = 0
        case_count = 0  # 统计 TestCase 数量

        for row_num, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            row_data = list(row)
            # 提取基础接口信息
            interface_name = row_data[header_mapping['interface_name']]
            url = row_data[header_mapping['url']]
            method = row_data[header_mapping['method']]

            if not all([interface_name, url, method]):
                logger.warning(f"第{row_num}行数据不完整，跳过解析")
                continue

            # 3. 创建/关联接口（先查后创建）
            interface = Interface.query.filter_by(
                project_id=project_id,
                url=url,
                method=method
            ).first()

            if not interface:
                # 处理请求头（转为 JSON 字符串）
                request_header = row_data[header_mapping.get('request_header')] or '{}'
                try:
                    # 尝试解析为 JSON（若用户填了非 JSON 格式则保留原始值）
                    json.loads(request_header)
                except json.JSONDecodeError:
                    logger.warning(f"第{row_num}行请求头非 JSON 格式，已保留原始值")

                interface = Interface(
                    project_id=project_id,
                    interface_name=interface_name,
                    url=url,
                    method=method,
                    request_header=request_header
                )
                db.session.add(interface)
                db.session.commit()  # 提交获取 interface_id
                interface_count += 1

                # 4. 解析参数并关联到接口（支持嵌套，区分参数类型）
                request_body_str = row_data[header_mapping.get('request_body')] or '{}'
                try:
                    request_body = json.loads(request_body_str)
                    # 获取当前行的参数类型，若未配置则默认 'body'
                    row_param_type = row_data[header_mapping.get('param_type')] if 'param_type' in header_mapping else 'body'
                    parse_nested_params(
                        interface_id=interface.interface_id,
                        data=request_body,
                        param_type=row_param_type
                    )
                    param_count += count_nested_params(request_body)  # 统计参数数量
                except json.JSONDecodeError as e:
                    logger.error(f"第{row_num}行请求体解析失败: {e}")

            # 5. 创建测试用例（关联接口）
            response_result_str = row_data[header_mapping.get('response_result')] or '{}'
            create_test_case(
                interface=interface,
                request_body_str=request_body_str,
                response_result_str=response_result_str,
                creator_id=creator_id
            )
            case_count += 1

        db.session.commit()
        return f"解析成功！新增接口 {interface_count} 个，参数 {param_count} 个，用例 {case_count} 个"

    except IntegrityError as e:
        db.session.rollback()
        error_msg = f"数据库唯一约束冲突: {str(e)}"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        db.session.rollback()
        error_msg = f"解析失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg


def parse_nested_params(interface_id, data, param_type, parent_key=''):
    """
    递归解析嵌套参数，支持 JSON 层级，使用 Excel 中定义的 param_type
    :param interface_id: 接口 ID
    :param data: JSON 数据（dict）
    :param param_type: 参数类型（path/query/body/header 等，来自 Excel 配置）
    :param parent_key: 嵌套层级（如 "data.user"）
    """
    if not isinstance(data, dict):
        return  # 非字典不解析（如数组）

    for key, value in data.items():
        full_key = f"{parent_key}.{key}" if parent_key else key
        # 推断数据类型
        data_type = type(value).__name__ if not isinstance(value, (dict, list)) else 'object'

        # 创建参数记录，使用传入的 param_type
        param = InterfaceParam(
            interface_id=interface_id,
            param_name=full_key,
            param_type=param_type,
            data_type=data_type,
            is_required=True,
            parent_key=parent_key,
            example_value=str(value)
        )
        db.session.add(param)

        # 递归处理子字典
        if isinstance(value, dict):
            parse_nested_params(interface_id, value, param_type, full_key)


def count_nested_params(data):
    """统计嵌套参数总数（用于 param_count）"""
    if not isinstance(data, dict):
        return 0
    count = len(data)
    for value in data.values():
        if isinstance(value, dict):
            count += count_nested_params(value)
    return count


def create_test_case(interface, request_body_str, response_result_str, creator_id):
    """
    创建测试用例，关联接口参数
    :param interface: Interface 实例
    :param request_body_str: 请求体 JSON 字符串
    :param response_result_str: 响应结果 JSON 字符串
    :param creator_id: 用例创建者 ID
    """
    try:
        request_body = json.loads(request_body_str) if request_body_str else {}
        response_result = json.loads(response_result_str) if response_result_str else {}

        # 提取参数映射（param_name: value）
        param_mapping = {}
        for param in interface.params:
            # 支持嵌套参数名（如 data.user.name）
            if param.param_name in request_body:
                param_mapping[param.param_name] = request_body[param.param_name]

        test_case = TestCase(
            interface_id=interface.interface_id,
            case_name=f"用例_{interface.interface_name}",
            param_values=json.dumps(param_mapping),  # 存储参数值映射
            expected_result=json.dumps(response_result),  # 存储预期响应
            assert_rule=generate_assert_rule(response_result),  # 自动生成断言
            creator_id=creator_id,
            create_time=datetime.now()
        )
        db.session.add(test_case)
    except json.JSONDecodeError as e:
        logger.error(f"创建测试用例失败: {e}")


def generate_assert_rule(response_result):
    """自动生成简单断言规则（示例：检查 status == 'success'）"""
    if 'status' in response_result:
        return f"response['status'] == '{response_result['status']}'"
    return "response.get('status') == 'success'"  # 默认规则