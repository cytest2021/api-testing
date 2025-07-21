# app/main.py
from flask import Flask, request, jsonify
from . import create_app, db
from .services.excel_parser import parse_excel
from .services.case_generator import generate_cases

app = create_app()

# 接口文档导入接口
@app.route('/api/import-excel', methods=['POST'])
def import_excel():
    file = request.files['file']
    project_id = request.form['project_id']
    result = parse_excel(file.stream, project_id)
    return jsonify({"msg": result})

# 用例生成接口
@app.route('/api/generate-cases', methods=['POST'])
def generate():
    data = request.json
    result = generate_cases(data['interface_id'], data['creator_id'])
    return jsonify({"msg": result})

# 测试执行接口
@app.route('/api/run-case', methods=['POST'])
def run_case():
    data = request.json
    result = run_test_case(data['case_id'], data['env_url'])
    return jsonify({
        "status": result.status,
        "duration": result.duration,
        "error_msg": result.error_msg
    })

if __name__ == '__main__':
    app.run(debug=True)