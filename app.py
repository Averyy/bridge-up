#app.py
from flask import Flask

app = Flask(__name__)

# @app.route('/')
# def home():
#     return "Scheduler is running!", 200

if __name__ == '__main__':
    app.run()