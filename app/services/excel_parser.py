from datetime import datetime

import openpyxl
import json
from app.models import Interface, InterfaceParam, TestCase, db  # 新增导入 TestCase
import logging

# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def parse_excel(file, project_id):
    """
    解析Excel接口文档并存储到数据库（适配动态表头，修复 response_result 流向）
    :param file: 上传的文件对象
    :param project_id: 项目ID
    :return: 解析结果字符串
    """
    try:
        # 加载Excel文件
        wb = openpyxl.load_workbook(file, data_only=True)
        sheet = wb.active
        logger.debug(f"加载Excel成功，工作表名称: {sheet.title}，总行数: {sheet.max_row}")

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

        # 校验必要字段
        required_fields = ['interface_name', 'url', 'method']
        missing_fields = [f for f in required_fields if f not in header_mapping]
        if missing_fields:
            error_msg = f"Excel缺少必要表头：{', '.join(missing_fields)}"
            logger.error(error_msg)
            return error_msg

        # 2. 解析数据行
        interface_count = 0
        param_count = 0
        case_count = 0  # 新增：统计 TestCase 数量

        for row_num, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            row_data = list(row)
            # 提取基础接口信息
            interface_name = row_data[header_mapping['interface_name']]
            url = row_data[header_mapping['url']]
            method = row_data[header_mapping['method']]

            if not all([interface_name, url, method]):
                logger.warning(f"第{row_num}行数据不完整，跳过解析")
                continue

            # 创建接口记录（移除 response_result 参数）
            interface = Interface(
                project_id=project_id,
                interface_name=interface_name,
                url=url,
                method=method,
                request_header=row_data[header_mapping.get('request_header')] or ''
            )
            db.session.add(interface)
            db.session.flush()  # 获取临时ID
            interface_count += 1

            # 解析请求体参数
            request_body_str = row_data[header_mapping.get('request_body')]
            if request_body_str:
                try:
                    request_body = json.loads(request_body_str)
                    # 支持嵌套JSON解析
                    def parse_params(params, parent_key='', param_type='body'):
                        nonlocal param_count
                        if isinstance(params, dict):
                            for k, v in params.items():
                                current_key = f"{parent_key}.{k}" if parent_key else k
                                if isinstance(v, (dict, list)):
                                    parse_params(v, current_key, param_type)
                                else:
                                    param = InterfaceParam(
                                        interface_id=interface.interface_id,
                                        param_name=current_key,
                                        param_type=param_type,
                                        data_type=type(v).__name__,
                                        is_required=True,
                                        example_value=str(v)
                                    )
                                    db.session.add(param)
                                    param_count += 1
                    parse_params(request_body)
                except json.JSONDecodeError as e:
                    logger.error(f"第{row_num}行请求体JSON解析错误: {e}")

            # 解析响应结果到 TestCase
            response_result_str = row_data[header_mapping.get('response_result')] or ''
            if response_result_str:
                try:
                    # 创建 TestCase 记录，关联当前 Interface
                    test_case = TestCase(
                        interface_id=interface.interface_id,
                        case_name=interface_name,  # 用接口名称作为用例名称
                        expected_result=response_result_str,  # 存入响应结果
                        # 其他必要字段按实际需求补充，如 param_values 可从 request_body 提取
                        param_values=request_body_str if request_body_str else '{}',
                        assert_rule="",  # 可后续完善断言规则生成逻辑
                        creator_id=1,  # 假设固定用户ID，需按实际业务调整
                        create_time=datetime.now()  # 按实际模型字段调整
                    )
                    db.session.add(test_case)
                    case_count += 1
                except Exception as e:
                    logger.error(f"第{row_num}行响应结果存入 TestCase 失败: {e}")

        db.session.commit()
        return f"解析成功！新增接口 {interface_count} 个，参数 {param_count} 个，用例 {case_count} 个"

    except Exception as e:
        db.session.rollback()
        error_msg = f"解析失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return error_msg