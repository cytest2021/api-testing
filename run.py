from app.main import app

if __name__ == '__main__':
    app.run(debug=True)  # 可以根据需要调整 host 和 port，比如 app.run(host='0.0.0.0', port=5000, debug=True)