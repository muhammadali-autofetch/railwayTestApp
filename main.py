from flask import Flask, render_template
import os
import json

# create the jsonFiles Dir if not exists
if not os.path.exists('jsonFiles'):
    os.makedirs('jsonFiles')

app = Flask(__name__)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/json-data', methods=['GET'])
def make_simple_json():
    data = {
        'name': 'John Doe',
        'age': 29,
        'city': 'New York'}
    with open('jsonFiles/data.json', 'w') as outfile:
        json.dump(data, outfile)
    return 'JSON created!'


@app.route('/read-json', methods=['GET'])
def read_json():
    with open('jsonFiles/data.json') as json_file:
        data = json.load(json_file)
    return data


if __name__ == '__main__':
    app.run(port=5000)
