from flask import Flask, render_template, request, jsonify, session, redirect
from pymongo import MongoClient
from datetime import datetime
import pytz

app = Flask(__name__, template_folder='../templates')
app.secret_key = "ALHADAD_VIP_SECURE_2026"

MONGO_URI = "mongodb+srv://admin:admin1312312313@aws.rhgcybe.mongodb.net/?appName=aws"
client = MongoClient(MONGO_URI)
db = client['store_database']
products_col = db['products']
orders_col = db['orders']
users_col = db['users']

def get_time(date_only=False):
    tz = pytz.timezone('Africa/Cairo')
    now = datetime.now(tz)
    return now.strftime('%Y-%m-%d') if date_only else now.strftime('%Y-%m-%d %I:%M %p')

def safe_float(val):
    if val is None: return 0.0
    try: return float(val)
    except (ValueError, TypeError): return 0.0

if not users_col.find_one({"role": "super_admin"}):
    users_col.insert_one({"username": "admin", "password": "123", "name": "المدير العام", "role": "super_admin", "total_earned": 0})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin-login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = users_col.find_one({"username": request.json.get('username'), "password": request.json.get('password')})
        if user:
            session['user'] = {"username": user['username'], "role": user['role'], "name": user['name']}
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "بيانات الدخول غير صحيحة"}), 401
    return render_template('admin.html')

@app.route('/admin-logout')
def logout():
    session.clear()
    return redirect('/admin-login')

@app.route('/api/data')
def get_data():
    products = list(products_col.find({}, {"_id": 0}))
    if 'user' in session:
        curr_user = session['user']
        all_orders = list(orders_col.find({}, {"_id": 0}))
        today = get_time(True)
        
        if curr_user.get('role') == 'super_admin':
            orders_to_send = all_orders
            admins_list = list(users_col.find({}, {"_id": 0}))
        else:
            orders_to_send = [o for o in all_orders if o.get('status') in ['pending', 'fraud'] or o.get('handled_by') == curr_user.get('name')]
            admins_list = list(users_col.find({"username": curr_user['username']}, {"_id": 0}))
            
        completed = [o for o in all_orders if o.get('status') == 'completed']
        fraud = [o for o in all_orders if o.get('status') == 'fraud']
        my_completed = [o for o in completed if o.get('handled_by') == curr_user.get('name')]
        
        stats = {
            "totalSales": sum([safe_float(o.get('amount', o.get('price', 0))) for o in completed]),
            "todaySales": sum([safe_float(o.get('amount', o.get('price', 0))) for o in completed if str(o.get('handled_at', '')).startswith(today)]),
            "myTotalSales": sum([safe_float(o.get('amount', o.get('price', 0))) for o in my_completed]),
            "myTodaySales": sum([safe_float(o.get('amount', o.get('price', 0))) for o in my_completed if str(o.get('handled_at', '')).startswith(today)]),
            "pendingCount": len([o for o in all_orders if o.get('status') == 'pending']),
            "fraudCount": len(fraud),
            "admins": admins_list
        }
        return jsonify({"products": products, "orders": orders_to_send, "stats": stats, "currentUser": curr_user})
    return jsonify({"products": products})

@app.route('/api/action', methods=['POST'])
def handle_action():
    data = request.json
    action = data.get('action')
    
    if action == 'new_order':
        orders_col.insert_one({**data['order'], "date": get_time(), "status": "pending"})
        return jsonify({"status": "success"})
    
    if 'user' not in session: return jsonify({"status": "unauthorized"}), 403
    curr = session['user']
    
    if action == 'complete_order':
        order = orders_col.find_one({"orderId": data['orderId']})
        if order and order['status'] == 'pending':
            orders_col.update_one({"orderId": data['orderId']}, {"$set": {"status": "completed", "handled_by": curr['name'], "handled_at": get_time()}})
            users_col.update_one({"username": curr['username']}, {"$inc": {"total_earned": safe_float(order.get('amount', order.get('price', 0)))}})
            
    elif action == 'undo_order':
        order = orders_col.find_one({"orderId": data['orderId']})
        if order and order['status'] == 'completed':
            if curr['role'] == 'super_admin' or order.get('handled_by') == curr['name']:
                users_col.update_one({"name": order['handled_by']}, {"$inc": {"total_earned": -safe_float(order.get('amount', order.get('price', 0)))}})
                orders_col.update_one({"orderId": data['orderId']}, {"$set": {"status": "pending"}, "$unset": {"handled_by": "", "handled_at": ""}})

    elif action == 'mark_fraud':
        order = orders_col.find_one({"orderId": data['orderId']})
        if order and order['status'] == 'pending':
            orders_col.update_one({"orderId": data['orderId']}, {"$set": {"status": "fraud", "handled_by": curr['name'], "handled_at": get_time()}})

    elif action == 'restore_fraud':
        orders_col.update_one({"orderId": data['orderId']}, {"$set": {"status": "pending"}, "$unset": {"handled_by": "", "handled_at": ""}})

    elif action == 'manage_product':
        if data['sub'] == 'add': 
            # أي موظف يمكنه إضافة منتج، وسيتم تسجيل اسمه
            products_col.insert_one({**data['product'], "added_by": curr['name']})
        elif data['sub'] == 'delete' and curr['role'] == 'super_admin':
            products_col.delete_one({"id": data['id']})
        
    elif action == 'manage_staff':
        if data['sub'] == 'self_update':
            old_name = curr['name']
            new_name = data['new_name']
            users_col.update_one({"username": curr['username']}, {"$set": {"name": new_name, "password": data['new_pass']}})
            session['user']['name'] = new_name
            # التحديث الذكي: تغيير الاسم القديم في كل العمليات السابقة حتى لا تضيع إحصائياته
            if old_name != new_name:
                orders_col.update_many({"handled_by": old_name}, {"$set": {"handled_by": new_name}})
                products_col.update_many({"added_by": old_name}, {"$set": {"added_by": new_name}})
        
        elif curr['role'] == 'super_admin':
            if data['sub'] == 'add': 
                users_col.insert_one({**data['staff'], "role": "admin", "total_earned": 0})
            elif data['sub'] == 'delete':
                target = users_col.find_one({"username": data['username']})
                if target and target['role'] != 'super_admin':
                    users_col.delete_one({"username": data['username']})
            elif data['sub'] == 'edit':
                # تعديل كامل لبيانات الموظف بواسطة المدير الكبير
                old_username = data['old_username']
                old_name = data['old_name']
                new_name = data['new_name']
                new_username = data['new_username']
                new_pass = data['new_pass']
                
                update_fields = {"name": new_name, "username": new_username}
                if new_pass: update_fields["password"] = new_pass
                
                users_col.update_one({"username": old_username}, {"$set": update_fields})
                
                # التحديث الذكي لمنع تصفير الأرباح!
                if old_name != new_name:
                    orders_col.update_many({"handled_by": old_name}, {"$set": {"handled_by": new_name}})
                    products_col.update_many({"added_by": old_name}, {"$set": {"added_by": new_name}})
                    
    elif action == 'delete_order' and curr['role'] == 'super_admin':
        orders_col.delete_one({"orderId": data['orderId']})
    
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(port=8080)
