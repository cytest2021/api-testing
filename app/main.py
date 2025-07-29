# app/main.py
from flask import Flask, request, jsonify
from . import create_app, db
from .services.excel_parser import parse_excel
from .services.case_generator import generate_cases

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)