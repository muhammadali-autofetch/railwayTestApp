from flask import Flask, jsonify, render_template
import os

app = Flask(__name__)

# create a directory called jsonFiles if it doesn't exist

if not os.path.exists('jsonFiles'):
    os.makedirs('jsonFiles')






@app.route('/')
def index():
    return jsonify({"Choo Choo": "Welcome to your Flask app 🚅"})


@app.route('/about')
def about():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, port=os.getenv("PORT", default=5000))
