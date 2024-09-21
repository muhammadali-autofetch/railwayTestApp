from flask import Flask, request, redirect, url_for, render_template, session, flash, jsonify
import csv
import requests
import json
import io
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from datetime import datetime
import time

app = Flask(__name__)
app.secret_key = 'ali'

STORE_CONFIG_PATH = './JsonFiles/stores_config.json'
ORDER_STATS_FILE = './JsonFiles/order_stats.json'

print("Running the Flask app...")


# if it doesn't exist, create the jsonFiles directory
if not os.path.exists('./JsonFiles'):
    os.makedirs('./JsonFiles')

# create order_stats.json if it doesn't exist with initial data {}
if not os.path.isfile(ORDER_STATS_FILE):
    with open(ORDER_STATS_FILE, 'w') as f:
        json.dump({}, f)
        f.close()


# create stores_config.json if it doesn't exist with initial data {}
if not os.path.isfile(STORE_CONFIG_PATH):
    with open(STORE_CONFIG_PATH, 'w') as f:
        json.dump({}, f)
        f.close()



with open(STORE_CONFIG_PATH) as f:  # NOQA
    STORE_CONFIG = json.load(f)

store_threads = {}


def get_product_and_variant_ids(store_url, api_key, password):
    products_url = f'https://{api_key}:{password}@{store_url}/admin/api/2023-10/products.json'
    response = requests.get(products_url)
    if response.status_code == 200:
        products = response.json().get('products', [])
        product_variant_map = {}
        for product in products:
            product_id = product['id']
            product_variant_map[product_id] = [variant['id'] for variant in product['variants']]
        return product_variant_map
    else:
        print("Failed to retrieve products.")
        return {}


def read_csv_data(file):
    orders = []
    stream = io.TextIOWrapper(file.stream, encoding='utf-8', newline='')
    reader = csv.DictReader(stream)
    for row in reader:
        orders.append({
            'quantity': int(row['QUANTITY']),
            'product_id': int(row['SKU']),
            'first_name': row['FIRST NAME'],
            'last_name': row['LAST NAME'],
            'phone': row['PHONE'],
            'address1': row['ADDRESS 1'],
            'address2': row['ADDRESS 2'],
            'city': row['CITY'],
            'state': row['STATE'],
            'pincode': row['PINCODE'],
            'payment_status': row['PAYMENT STATUS']
        })
    return orders


def create_order(store_url, api_key, password, variant_id, customer_data, store_name):
    orders_url = f'https://{api_key}:{password}@{store_url}/admin/api/2023-10/orders.json'
    order_data = {
        "order": {
            "line_items": [
                {
                    "variant_id": variant_id,
                    "quantity": customer_data['quantity']
                }
            ],
            "customer": {
                "first_name": customer_data['first_name'],
                "last_name": customer_data['last_name'],
                "phone": customer_data['phone']
            },
            "billing_address": {
                "first_name": customer_data['first_name'],
                "last_name": customer_data['last_name'],
                "address1": customer_data['address1'],
                "address2": customer_data['address2'],
                "city": customer_data['city'],
                "province": customer_data['state'],
                "zip": customer_data['pincode'],
                "phone": customer_data['phone']
            },
            "shipping_address": {
                "first_name": customer_data['first_name'],
                "last_name": customer_data['last_name'],
                "address1": customer_data['address1'],
                "address2": customer_data['address2'],
                "city": customer_data['city'],
                "province": customer_data['state'],
                "zip": customer_data['pincode'],
                "phone": customer_data['phone']
            },
            "financial_status": customer_data["payment_status"],
            "send_receipt": True,
            "send_fulfillment_receipt": True
        }
    }

    response = requests.post(orders_url, headers={'Content-Type': 'application/json'}, data=json.dumps(order_data))
    if response.status_code == 201:
        order_response = response.json()
        order_id = order_response.get('order', {}).get('id')
        print(f"Order {order_id} created successfully for {store_name}.")
    else:
        print(f"Failed to create order: {response.json()}")


def update_order_stats(store_name, total_orders, pending_orders, last_order_time):
    order_stats = {}

    if os.path.exists(ORDER_STATS_FILE):
        try:
            with open(ORDER_STATS_FILE, 'r') as f:
                order_stats = json.load(f)
                if not isinstance(order_stats, dict):
                    order_stats = {}
        except (json.JSONDecodeError, ValueError):
            order_stats = {}

    order_stats[store_name] = {
        "total_orders": total_orders,
        "pending_orders": pending_orders,
        "last_order_time": last_order_time,
    }

    with open(ORDER_STATS_FILE, 'w') as f:
        json.dump(order_stats, f, indent=4)


def process_orders_in_batches(product_variant_map, orders, batch_size=1, delay=15, store_url=None, api_key=None,
                              password=None, store_name=None):
    stop_event = store_threads.get(store_name)
    total_orders = len(orders)
    for i in range(0, total_orders, batch_size):
        if stop_event and stop_event.is_set():
            print(f"Stopping order processing for {store_name}.")
            return

        batch = orders[i:i + batch_size]
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = []
            for order in batch:
                product_id = order['product_id']
                if product_id in product_variant_map:
                    variant_ids = product_variant_map[product_id]
                    for variant_id in variant_ids:
                        future = executor.submit(create_order, store_url, api_key, password, variant_id, order,
                                                 store_name)
                        futures.append(future)

            for future in as_completed(futures):
                future.result()

        pending_orders = total_orders - (i + batch_size)
        last_order_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_order_stats(store_name, total_orders, pending_orders, last_order_time)

        if i + batch_size < total_orders:
            time.sleep(delay)


@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('add_store'))

    if request.method == 'POST':
        token = request.form.get('token')
        if token == '12345':
            session['user'] = 'authenticated'
            return redirect(url_for('add_store'))
        else:
            flash("Invalid token", "error")
            return redirect(url_for('login'))
    return render_template('Login.html')


@app.route('/create')
def index():
    """
    Route for the main page
    """
    if 'user' not in session:
        return redirect(url_for('login'))

    # Always read the latest store config from the file
    with open(STORE_CONFIG_PATH) as f:
        store_config = json.load(f)

    store_names = list(store_config.keys())  # Get store names from the config
    return render_template('UploadFile.html', store_names=store_names)


@app.route('/add-store', methods=['GET', 'POST'])
def add_store():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        store_name = request.form.get('store_name')
        api_key = request.form.get('api_key')
        api_password = request.form.get('api_password')
        store_url = request.form.get('store_url')

        if not all([store_name, api_key, api_password, store_url]):
            flash("All fields are required!", "error")
            return redirect(url_for('add_store'))

        # Check if store name matches the first part of the store URL
        if not store_url.startswith(f"{store_name}.myshopify.com"):
            flash("Store URL must be Correct", "error")
            return redirect(url_for('add_store'))

        # Load existing store config
        store_config = {}
        if os.path.exists(STORE_CONFIG_PATH):
            with open(STORE_CONFIG_PATH, 'r') as f:
                store_config = json.load(f)

        # Check for uniqueness
        for store in store_config.values():
            if store['api_key'] == api_key or store['password'] == api_password or store['store_url'] == store_url:
                flash("A store with the same API key, password, or URL already exists!", "error")
                return redirect(url_for('add_store'))

        if store_name in store_config:
            flash("Store with this name already exists!", "error")
            return redirect(url_for('add_store'))

        # Save new store
        store_config[store_name] = {
            'api_key': api_key,
            'api_password': api_password,
            'store_url': store_url
        }

        with open(STORE_CONFIG_PATH, 'w') as f:
            json.dump(store_config, f, indent=4)

        flash(f"Store '{store_name}' added successfully", "success")
        return redirect(url_for('upload_file'))

    return render_template('AddConfig.html')


@app.route('/api/store_names')
def api_store_names():
    with open(STORE_CONFIG_PATH) as f:
        store_config = json.load(f)
    store_names = list(store_config.keys())
    return jsonify({'store_names': store_names})


@app.route('/save_store', methods=['POST'])
def save_store():
    data = request.json
    store_name = data.get('store_name')
    api_key = data.get('api_key')
    password = data.get('password')
    store_url = data.get('store_url')

    if not all([store_name, api_key, password, store_url]):
        return jsonify({'message': 'All fields are required!'}), 400

    store_config = {}
    if os.path.exists(STORE_CONFIG_PATH):
        with open(STORE_CONFIG_PATH, 'r') as f:
            store_config = json.load(f)

    # Check for uniqueness
    for existing_store_name, store in store_config.items():
        if (existing_store_name != store_name and
                (store['api_key'] == api_key or store['password'] == password or store['store_url'] == store_url)):
            return jsonify({'message': 'A store with the same API key, password, or URL already exists!'}), 400

    if store_name in store_config:
        return jsonify({'message': 'Store with this name already exists!'}), 400

    # Save new store
    store_config[store_name] = {
        'api_key': api_key,
        'password': password,
        'store_url': store_url
    }

    with open(STORE_CONFIG_PATH, 'w') as f:
        json.dump(store_config, f, indent=4)

    return jsonify({'message': 'Store saved successfully!'})


@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if 'user' not in session:
        return redirect(url_for('login'))



    if request.method == 'POST':
        print("POST request received")
        store_name = request.form.get('store')
        csv_file = request.files.get('csvFile')

        if not store_name or not csv_file:
            print("Store name and CSV file are required!")
            flash("Store name and CSV file are required!", "error")
            return redirect(url_for('upload_file'))

        store_config = STORE_CONFIG.get(store_name)
        if not store_config:
            print(f"Store '{store_name}' not found!")
            flash("Invalid store name!", "error")
            return redirect(url_for('upload_file'))

        api_key = store_config.get('api_key')
        if not api_key:
            print(f"API key for store '{store_name}' not found!")
            flash(f"API key for store '{store_name}' not found!", "error")
            return redirect(url_for('upload_file'))

        password = store_config.get('password')
        store_url = store_config.get('store_url')

        product_variant_map = get_product_and_variant_ids(store_url, api_key, password)
        if product_variant_map:
            orders = read_csv_data(csv_file)

            stop_event = threading.Event()
            store_threads[store_name] = stop_event

            threading.Thread(target=process_orders_in_batches, args=(
                product_variant_map, orders, 1, 15, store_url, api_key, password, store_name)).start()

            flash(f"Started processing orders for store '{store_name}'", "success")
            return redirect(url_for('order_management'))
        else:
            print("No product variant mappings found.")
            flash("No product variant mappings found.", "error")

    return render_template('UploadFile.html')


@app.route('/existing-stores')
def existing_stores():
    with open(STORE_CONFIG_PATH) as f:
        store_config = json.load(f)
    store_names = list(store_config.keys())
    return jsonify({'store_names': store_names})


@app.route('/order')
def order_management():
    if 'user' not in session:
        return redirect(url_for('login'))

    if not os.path.exists(ORDER_STATS_FILE):
        order_stats = {}
    else:
        with open(ORDER_STATS_FILE, 'r') as f:
            order_stats = json.load(f)

    return render_template('Orders.html', stats=order_stats)


@app.route('/delete_store/<store_name>', methods=['POST'])
def delete_store(store_name):
    """
    Route to delete a store
    :param store_name:
    :return:
    """

    stop_event = store_threads.pop(store_name, None)
    if stop_event:
        stop_event.set()

    # Proceed with store deletion
    if os.path.exists(STORE_CONFIG_PATH):
        with open(STORE_CONFIG_PATH, 'r') as f:
            store_config = json.load(f)

        if store_name in store_config:
            del store_config[store_name]

            with open(STORE_CONFIG_PATH, 'w') as f:
                json.dump(store_config, f, indent=4)

            if os.path.exists(ORDER_STATS_FILE):
                with open(ORDER_STATS_FILE, 'r') as f:
                    order_stats = json.load(f)

                if store_name in order_stats:
                    del order_stats[store_name]

                    with open(ORDER_STATS_FILE, 'w') as f:
                        json.dump(order_stats, f, indent=4)

            return '', 204
        else:
            return 'Store not found', 404
    else:
        return 'Store configuration file not found', 500


@app.route('/logout', methods=['GET'])
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


# see all JsonFiles/order_stats.json
@app.route('/api/order_stats')
def api_order_stats():
    with open(ORDER_STATS_FILE) as f:
        order_stats = json.load(f)
    return jsonify(order_stats)

# see all stores in JsonFiles/store_config.json
@app.route('/api/store_config')
def api_store_config():
    with open(STORE_CONFIG_PATH) as f:
        store_config = json.load(f)
    return jsonify(store_config)



if __name__ == '__main__':
    app.run(port=5000)

