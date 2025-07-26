# app/services/excel_parser.py
import openpyxl
from app.models import Interface, InterfaceParam, db


def parse_excel(file_path, project_id):
    """解析Excel接口文档并存储到数据库"""
    wb = openpyxl.load_workbook(file_path)
    sheet = wb.active

    # 假设Excel表头：接口名称、URL、方法、参数名、参数类型、是否必填...
    for row in sheet.iter_rows(min_row=2, values_only=True):  # 跳过表头
        interface_name, url, method, param_name, param_type, is_required = row[0:6]

        # 1. 存储接口信息
        interface = Interface(
            project_id=project_id,
            interface_name=interface_name,
            url=url,
            method=method
        )
        db.session.add(interface)
        db.session.flush()  # 暂存以获取interface_id

        # 2. 存储参数信息
        param = InterfaceParam(
            interface_id=interface.interface_id,
            param_name=param_name,
            param_type=param_type,
            data_type=row[6],  # 假设第7列是数据类型
            is_required=is_required == '是'
        )
        db.session.add(param)

    db.session.commit()
    return "解析完成，新增接口数：{}".format(sheet.max_row - 1)