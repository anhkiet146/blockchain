from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from blockchain import Wallet, Transaction, Blockchain
import hashlib
import os
import time
import json
import glob
from datetime import datetime, timedelta
import logging

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Đường dẫn thư mục lưu blockchain
BLOCKCHAIN_DIR = "blockchain_data"
if not os.path.exists(BLOCKCHAIN_DIR):
    os.makedirs(BLOCKCHAIN_DIR)
WALLET_DIR = "Wallet"
if not os.path.exists(WALLET_DIR):
    os.makedirs(WALLET_DIR)


# Tắt logger mặc định của Flask/Werkzeug
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Cấu hình logger tùy chỉnh
logger = logging.getLogger('project_management')
logger.setLevel(logging.INFO)

# Handler cho console
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Handler cho file
file_handler = logging.FileHandler('project_management.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Thêm cả hai handler vào logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Database connection
def get_db():
    conn = sqlite3.connect('project_management.db')
    conn.row_factory = sqlite3.Row
    return conn

def load_wallet(username):
    wallet = Wallet()
    wallet_file = os.path.join(WALLET_DIR, f"{username}_wallet.json")
    if wallet.load_from_file(wallet_file):
        logger.info(f"Loaded wallet for {username} from {wallet_file}")
        return wallet
    else:
        flash(f"Failed to load wallet for {username}. Please contact admin.")
        return None

# Dictionary to store blockchains for each project
project_blockchains = {}

# Load all blockchains from files on startup
def load_blockchains():
    global project_blockchains
    for file_path in glob.glob(os.path.join(BLOCKCHAIN_DIR, "blockchain_*.json")):
        file_name = os.path.basename(file_path)
        try:
            project_id = int(file_name.split("_")[1].split(".")[0])
            blockchain_file = os.path.join(BLOCKCHAIN_DIR, f"blockchain_{project_id}.json")
            blockchain = Blockchain(difficulty=2)
            if blockchain.load_from_file(blockchain_file):
                project_blockchains[project_id] = blockchain
                logger.info(f"Loaded blockchain for project {project_id} from {blockchain_file} with {len(blockchain.chain)} blocks")
            else:
                logger.info(f"Failed to load blockchain for project {project_id} from {blockchain_file}, initializing new one")
                project_blockchains[project_id] = Blockchain(difficulty=2)
        except (ValueError, IndexError) as e:
            logger.error(f"Error processing file {file_path}: {e} - Skipping this file")
        except Exception as e:
            logger.error(f"Error loading blockchain for project from {file_path}: {e}")

# Initialize or load blockchain
def get_or_create_blockchain(project_id):
    if project_id not in project_blockchains:
        blockchain_file = os.path.join(BLOCKCHAIN_DIR, f"blockchain_{project_id}.json")
        if os.path.exists(blockchain_file):
            blockchain = Blockchain(difficulty=2)
            if blockchain.load_from_file(blockchain_file):
                project_blockchains[project_id] = blockchain
                logger.info(f"Restored blockchain for project {project_id} with {len(blockchain.chain)} blocks")
            else:
                logger.info(f"Error restoring blockchain for project {project_id}, creating new one")
                project_blockchains[project_id] = Blockchain(difficulty=2)
        else:
            project_blockchains[project_id] = Blockchain(difficulty=2)
            logger.info(f"Created new blockchain for project {project_id}")
    return project_blockchains[project_id]

def update_project_progress(conn, project_id):
    total_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE project_id = ?', (project_id,)).fetchone()[0]
    if total_tasks == 0:
        return 0
    completed_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE project_id = ? AND progress = 100', (project_id,)).fetchone()[0]
    progress = (completed_tasks / total_tasks) * 100
    conn.execute('UPDATE projects SET progress = ? WHERE id = ?', (progress, project_id))
    conn.commit()
    logger.info(f"Updated project {project_id} progress to {progress}% (Total tasks: {total_tasks}, Completed: {completed_tasks})")
    return progress

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not all([username, password]):
            flash('Username and password are required!')
            return render_template('login.html')

        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user:
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            if hashed_password == user['password']:
                # Load wallet trước khi đăng nhập
                wallet = load_wallet(username)
                if wallet:
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    session['role'] = user['role']
                    session['wallet_private_key'] = wallet.get_private_key()
                    session['wallet_public_key'] = wallet.get_public_key()
                    flash('Login successful! Wallet loaded.')
                    return redirect(url_for('admin_dashboard' if user['role'] == 'admin' else 'user_dashboard'))
                else:
                    flash('Failed to load wallet. Please contact admin.')
                    return render_template('login.html')
            else:
                flash('Invalid username or password!')
        else:
            flash('User not found!')

    # Load ví mặc định khi GET (nếu cần kiểm tra trước)
    if 'username' in request.args:
        username = request.args['username']
        wallet = load_wallet(username)
        if wallet:
            flash(f'Wallet for {username} loaded successfully (preview).')
        else:
            flash(f'Failed to load wallet for {username}.')

    return render_template('login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db()
    for project in conn.execute('SELECT id FROM projects').fetchall():
        update_project_progress(conn, project['id'])
    projects = conn.execute('SELECT p.*, (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id) as task_count FROM projects p').fetchall()
    tasks = conn.execute('''
        SELECT t.*, GROUP_CONCAT(u.username) as assigned_users
        FROM tasks t
        LEFT JOIN task_assignments ta ON t.id = ta.task_id
        LEFT JOIN users u ON ta.user_id = u.id
        GROUP BY t.id
    ''').fetchall()
    conn.close()
    running = sum(1 for p in projects if p['progress'] > 0 and p['progress'] < 100)
    total_progress = sum((p['progress'] if p['progress'] else 0) for p in projects)
    progress = total_progress / max(1, len(projects)) if projects else 0
    return render_template('admin_dashboard.html', projects=projects, tasks=[], running=running, progress=progress)

@app.route('/admin/view_tasks/<int:project_id>')
def view_tasks(project_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    tasks = conn.execute('''
        SELECT t.*, GROUP_CONCAT(u.username) as assigned_users
        FROM tasks t
        LEFT JOIN task_assignments ta ON t.id = ta.task_id
        LEFT JOIN users u ON ta.user_id = u.id
        WHERE t.project_id = ?
        GROUP BY t.id
    ''', (project_id,)).fetchall()
    phases = conn.execute('SELECT * FROM phases WHERE project_id = ? ORDER BY deadline', (project_id,)).fetchall()
    conn.close()
    return render_template('view_tasks.html', project=project, tasks=tasks, phases=phases)

@app.route('/admin/delete_project/<int:project_id>', methods=['POST'])
def delete_project(project_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db()
    conn.execute('DELETE FROM task_assignments WHERE task_id IN (SELECT id FROM tasks WHERE project_id = ?)', (project_id,))
    conn.execute('DELETE FROM tasks WHERE project_id = ?', (project_id,))
    conn.execute('DELETE FROM phases WHERE project_id = ?', (project_id,))
    conn.execute('DELETE FROM phase_dependencies WHERE phase_id IN (SELECT id FROM phases WHERE project_id = ?) OR prerequisite_phase_id IN (SELECT id FROM phases WHERE project_id = ?)', (project_id, project_id))
    conn.execute('DELETE FROM projects WHERE id = ?', (project_id,))
    if project_id in project_blockchains:
        del project_blockchains[project_id]
        blockchain_file = os.path.join(BLOCKCHAIN_DIR, f"blockchain_{project_id}.json")
        if os.path.exists(blockchain_file):
            os.remove(blockchain_file)
            print(f"Deleted blockchain file {blockchain_file} for project {project_id}")
    conn.commit()
    conn.close()
    flash('Project and related data deleted successfully')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
def admin_users():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db()
    users = conn.execute('SELECT * FROM users').fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)

@app.route('/admin/create_project', methods=['GET', 'POST'])
def create_project():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        deadline = request.form['deadline']
        try:
            deadline_datetime = datetime.fromisoformat(deadline.replace('T', ' '))
            conn = get_db()
            conn.execute('INSERT INTO projects (name, description, deadline, progress) VALUES (?, ?, ?, 0)', 
                        (name, description, deadline_datetime))
            project_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            # Tạo blockchain mới và lưu file
            blockchain = get_or_create_blockchain(project_id)
            blockchain.save_to_file(os.path.join(BLOCKCHAIN_DIR, f"blockchain_{project_id}.json"))
            print(f"Initialized blockchain for new project {project_id}")
            # Xử lý các giai đoạn từ form
            phase_names = request.form.getlist('phase_names[]')
            phase_descriptions = request.form.getlist('phase_descriptions[]')
            phase_deadlines = request.form.getlist('phase_deadlines[]')
            
            # Kiểm tra và sắp xếp giai đoạn
            phases = []
            for name, desc, dl in zip(phase_names, phase_descriptions, phase_deadlines):
                if name and dl:
                    phase_deadline = datetime.fromisoformat(dl.replace('T', ' '))
                    if phase_deadline > deadline_datetime:
                        flash('Phase deadline cannot exceed project deadline.')
                        conn.close()
                        return render_template('create_project.html')
                    phases.append({'name': name, 'description': desc or None, 'deadline': phase_deadline})
            
            # Sắp xếp theo deadline tăng dần
            phases.sort(key=lambda x: x['deadline'])
            
            # Kiểm tra ngày bắt đầu (dựa trên deadline của phase trước)
            for i in range(1, len(phases)):
                if phases[i]['deadline'] <= phases[i-1]['deadline']:
                    flash('Each phase must have a deadline after the previous phase.')
                    conn.close()
                    return render_template('create_project.html')
            
            # Thêm các giai đoạn vào cơ sở dữ liệu
            for phase in phases:
                conn.execute('INSERT INTO phases (project_id, name, description, deadline) VALUES (?, ?, ?, ?)',
                            (project_id, phase['name'], phase['description'], phase['deadline']))
            
            conn.commit()
            conn.close()
            flash('Project and phases created successfully')
            return redirect(url_for('admin_dashboard'))
        except ValueError:
            flash('Invalid deadline format. Use YYYY-MM-DD HH:MM.')
            return render_template('create_project.html')
    return render_template('create_project.html')

@app.route('/admin/view_phases/<int:project_id>')
def view_phases(project_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    phases = conn.execute('SELECT * FROM phases WHERE project_id = ? ORDER BY deadline', (project_id,)).fetchall()
    conn.close()
    return render_template('view_phases.html', project_id=project_id, project=project, phases=phases)

@app.route('/admin/create_task/<int:project_id>', methods=['GET', 'POST'])
def create_task(project_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    users = conn.execute('SELECT * FROM users WHERE role = "user"').fetchall()
    # Truy vấn phases và định dạng deadline
    phases_raw = conn.execute('SELECT id, name, deadline FROM phases WHERE project_id = ?', (project_id,)).fetchall()
    phases = []
    for phase in phases_raw:
        phase_dict = dict(phase)
        if isinstance(phase_dict['deadline'], str):
            # Chuyển đổi deadline từ chuỗi sang datetime và định dạng lại
            phase_dict['deadline'] = datetime.strptime(phase_dict['deadline'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M')
        else:
            phase_dict['deadline'] = phase_dict['deadline'].strftime('%Y-%m-%dT%H:%M')
        phases.append(phase_dict)
    now_str = datetime.now().strftime('%Y-%m-%dT%H:%M')
    if not project:
        flash('Project not found.')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    try:
        project = dict(project)
        project['deadline'] = datetime.strptime(project['deadline'], '%Y-%m-%d %H:%M:%S')
    except Exception:
        flash('Invalid project deadline format.')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        deadline = request.form['deadline']
        user_ids = request.form.getlist('user_ids')
        phase_id = request.form.get('phase_id')

        try:
            task_deadline = datetime.fromisoformat(deadline.replace('T', ' '))
            if task_deadline > project['deadline']:
                flash('Task deadline cannot be later than project deadline.')
                conn.close()
                return render_template('create_task.html', project_id=project_id, users=users, project=project, phases=phases, now_str=now_str)
            
            # Kiểm tra deadline của task so với deadline của phase
            if phase_id:
                phase = conn.execute('SELECT deadline FROM phases WHERE id = ?', (phase_id,)).fetchone()
                if phase:
                    phase_deadline = datetime.strptime(phase['deadline'], '%Y-%m-%d %H:%M:%S')
                    if task_deadline > phase_deadline:
                        flash('Task deadline cannot exceed the deadline of the selected phase.')
                        conn.close()
                        return render_template('create_task.html', project_id=project_id, users=users, project=project, phases=phases, now_str=now_str)

            conn.execute('''
                INSERT INTO tasks (project_id, phase_id, title, description, progress, deadline, progress_text) 
                VALUES (?, ?, ?, ?, 0, ?, NULL)
            ''', (project_id, phase_id, title, description, task_deadline))

            task_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

            for user_id in user_ids:
                conn.execute('INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)', 
                            (task_id, user_id))

            conn.commit()
            conn.close()
            flash('Task created and assigned successfully')
            return redirect(url_for('admin_dashboard'))
        except ValueError:
            flash('Invalid deadline format. Use YYYY-MM-DD HH:MM.')
            conn.close()
            return render_template('create_task.html', project_id=project_id, users=users, project=project, phases=phases, now_str=now_str)

    conn.close()
    return render_template('create_task.html', project_id=project_id, users=users, project=project, phases=phases, now_str=now_str)

@app.route('/admin/assign_task/<int:task_id>', methods=['GET', 'POST'])
def assign_task(task_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db()
    users = conn.execute('SELECT * FROM users WHERE role = "user"').fetchall()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (task['project_id'],)).fetchone()
    if request.method == 'POST':
        user_ids = request.form.getlist('user_ids')
        deadline = request.form['deadline']
        try:
            task_deadline = datetime.fromisoformat(deadline.replace('T', ' '))
            project_deadline = datetime.strptime(str(project['deadline']), '%Y-%m-%d %H:%M:%S')
            if task_deadline > project_deadline:
                flash('Task deadline cannot be later than project deadline.')
                conn.close()
                return render_template('assign_task.html', task_id=task_id, users=users, task=task, project=project)
            # Kiểm tra deadline so với phase nếu có
            if task['phase_id']:
                phase = conn.execute('SELECT deadline FROM phases WHERE id = ?', (task['phase_id'],)).fetchone()
                if phase and task_deadline > datetime.strptime(phase['deadline'], '%Y-%m-%d %H:%M:%S'):
                    flash('Task deadline cannot exceed the deadline of the selected phase.')
                    conn.close()
                    return render_template('assign_task.html', task_id=task_id, users=users, task=task, project=project)
        except ValueError:
            flash('Invalid deadline format. Use YYYY-MM-DD HH:MM.')
            conn.close()
            return render_template('assign_task.html', task_id=task_id, users=users, task=task, project=project)
        conn.execute('UPDATE tasks SET deadline = ? WHERE id = ?', (task_deadline, task_id))
        conn.execute('DELETE FROM task_assignments WHERE task_id = ?', (task_id,))
        for user_id in user_ids:
            conn.execute('INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)', 
                        (task_id, user_id))
        conn.commit()
        conn.close()
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/view_chain')
def view_chain():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db()
    projects = conn.execute('SELECT * FROM projects').fetchall()
    conn.close()
    return render_template('view_chain.html', projects=projects)

@app.route('/admin/view_project_chain/<int:project_id>', methods=['GET', 'POST'])
def view_project_chain(project_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Load wallet khi xem blockchain
    username = session['username']
    wallet = load_wallet(username)
    if not wallet:
        flash('Failed to load wallet. Please login again.')
        return redirect(url_for('login'))

    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    blockchain = get_or_create_blockchain(project_id)
    relevant_chain = blockchain.chain

    if request.method == 'POST':
        block_index = int(request.form['block_index'])
        if 0 <= block_index < len(relevant_chain):
            for tx in relevant_chain[block_index].transactions:
                if tx.task_id and "Edit: Old=" in tx.progress_text:
                    parts = tx.progress_text.split(", ")
                    old_content = next((p.split("=")[1] for p in parts if p.startswith("Old=")), None)
                    if old_content:
                        conn.execute('UPDATE tasks SET progress_text = ? WHERE id = ?', (old_content, tx.task_id))
                        conn.commit()
                        flash(f'Reset block {block_index} to old content for task {tx.task_id}')
                        # Xóa block cũ và tái tạo blockchain
                        blockchain.chain = [block for i, block in enumerate(blockchain.chain) if i != block_index]
                        blockchain.mine_pending_transactions()
                        blockchain_file = os.path.join(BLOCKCHAIN_DIR, f"blockchain_{project_id}.json")
                        blockchain.save_to_file(blockchain_file)
                        return redirect(url_for('view_project_chain', project_id=project_id))

    conn.close()
    if not relevant_chain:
        flash('No blockchain data available for this project.')
    
    # Kiểm tra có chỉnh sửa không cho từng block
    has_edits = any(block.is_edited for block in relevant_chain)
    annotated_chain = [
        {
            'block': block,
            'is_edited': block.is_edited
        } for block in relevant_chain
    ]

    return render_template('project_chain.html', project=project, chain=annotated_chain, has_edits=has_edits)

@app.route('/user/dashboard')
def user_dashboard():
    if 'user_id' not in session or session['role'] != 'user':
        return redirect(url_for('login'))
    conn = get_db()
    cursor = conn.execute('''
        SELECT DISTINCT p.id, p.name, p.deadline, p.progress
        FROM projects p
        JOIN tasks t ON p.id = t.project_id
        JOIN task_assignments ta ON t.id = ta.task_id
        WHERE ta.user_id = ?
    ''', (session['user_id'],))
    projects = cursor.fetchall()
    
    user_tasks = {}
    for project in projects:
        tasks = conn.execute('''
            SELECT t.*, p.deadline as project_deadline
            FROM tasks t
            JOIN task_assignments ta ON t.id = ta.task_id
            JOIN projects p ON t.project_id = p.id
            WHERE ta.user_id = ? AND t.project_id = ?
        ''', (session['user_id'], project['id'])).fetchall()
        user_tasks[project['id']] = tasks
    
    print(f"User ID: {session['user_id']}, Projects: {projects}, Tasks: {user_tasks}")
    conn.close()
    return render_template('user_dashboard.html', projects=projects, user_tasks=user_tasks)

@app.route('/user/update_progress/<int:task_id>', methods=['GET', 'POST'])
def update_progress(task_id):
    if 'user_id' not in session or session['role'] != 'user':
        return redirect(url_for('login'))
    
    conn = get_db()
    task = dict(conn.execute('''
        SELECT t.*, p.deadline AS project_deadline, p.id AS project_id 
        FROM tasks t 
        JOIN projects p ON t.project_id = p.id 
        WHERE t.id = ?
    ''', (task_id,)).fetchone())
    
    if isinstance(task['deadline'], str):
        task['deadline'] = datetime.strptime(task['deadline'], '%Y-%m-%d %H:%M:%S')
    if isinstance(task['project_deadline'], str):
        task['project_deadline'] = datetime.strptime(task['project_deadline'], '%Y-%m-%d %H:%M:%S')
    
    phase = conn.execute('SELECT * FROM phases WHERE id = ? AND progress < 100', (task.get('phase_id'),)).fetchone()
    if phase:
        prerequisites = conn.execute('SELECT prerequisite_phase_id FROM phase_dependencies WHERE phase_id = ?', (phase['id'],)).fetchall()
        for prereq in prerequisites:
            prereq_phase = conn.execute('SELECT progress FROM phases WHERE id = ?', (prereq['prerequisite_phase_id'],)).fetchone()
            if prereq_phase and prereq_phase['progress'] < 100:
                flash('Cannot update progress: Prerequisite phase not completed.')
                conn.close()
                return render_template('update_progress.html', task=task)

    if request.method == 'POST':
        progress_text = request.form['progress_text']
        old_progress_text = task.get('progress_text', '')

        progress = 100 if any(keyword in progress_text.lower() for keyword in ["hoàn thành", "completed", "done"]) else 0

        # Tạo giao dịch và ký
        private_key = session['wallet_private_key']
        transaction = Transaction(
            session['wallet_public_key'],
            session['username'],
            task_id,
            progress_text,
            "",
            task['project_id'],
            task.get('phase_id', 0),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        transaction.sign_transaction(private_key)

        blockchain = get_or_create_blockchain(task['project_id'])
        # Thử cập nhật giao dịch hiện có
        if blockchain.update_transaction_in_chain(task['project_id'], task_id, progress_text, private_key):
            blockchain_file = os.path.join(BLOCKCHAIN_DIR, f"blockchain_{task['project_id']}.json")
            if os.path.exists(blockchain_file):
                blockchain.save_to_file(blockchain_file)
                conn.execute('UPDATE tasks SET progress = ?, progress_text = ? WHERE id = ?', (progress, progress_text, task_id))
                if task.get('phase_id'):
                    phase_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE phase_id = ? AND progress < 100', (task['phase_id'],)).fetchone()[0]
                    if phase_tasks == 0:
                        conn.execute('UPDATE phases SET progress = 100 WHERE id = ?', (task['phase_id'],))
                update_project_progress(conn, task['project_id'])
                conn.commit()
                flash('Thông tin người dùng đã được lưu lại.')
            else:
                flash('Cannot save block: Blockchain file not found.')
        else:
            # Nếu không tìm thấy, thêm giao dịch mới và mine block
            if blockchain.add_transaction(transaction):
                success = blockchain.mine_pending_transactions()
                if success:
                    blockchain_file = os.path.join(BLOCKCHAIN_DIR, f"blockchain_{task['project_id']}.json")
                    if os.path.exists(blockchain_file):
                        blockchain.save_to_file(blockchain_file)
                        conn.execute('UPDATE tasks SET progress = ?, progress_text = ? WHERE id = ?', (progress, progress_text, task_id))
                        if task.get('phase_id'):
                            phase_tasks = conn.execute('SELECT COUNT(*) FROM tasks WHERE phase_id = ? AND progress < 100', (task['phase_id'],)).fetchone()[0]
                            if phase_tasks == 0:
                                conn.execute('UPDATE phases SET progress = 100 WHERE id = ?', (task['phase_id'],))
                        update_project_progress(conn, task['project_id'])
                        conn.commit()
                        flash('Thông tin người dùng đã được lưu lại.')
                    else:
                        flash('Cannot save block: Blockchain file not found.')
                else:
                    conn.rollback()
                    flash('Failed to mine block')
            else:
                flash('Invalid transaction signature!')

    conn.close()
    return render_template('update_progress.html', task=task)

@app.route('/admin/notifications')
def admin_notifications():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    projects = conn.execute('SELECT id, name FROM projects').fetchall()
    notifications = []
    
    for project in projects:
        blockchain_file = os.path.join(BLOCKCHAIN_DIR, f"blockchain_{project['id']}.json")
        if os.path.exists(blockchain_file):
            blockchain = Blockchain(difficulty=2)
            blockchain.load_from_file(blockchain_file)
            for block in blockchain.chain:
                for tx in block.transactions:
                    notifications.append({
                        'project_name': project['name'],
                        'username': tx.username,
                        'task_id': tx.task_id,
                        'progress_text': tx.progress_text,
                        'timestamp': tx.timestamp,
                        'is_edited': block.is_edited
                    })
    
    conn.close()
    return render_template('admin_notifications.html', notifications=notifications)

@app.route('/admin/create_phase/<int:project_id>', methods=['GET', 'POST'])
def create_phase(project_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))

    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    if not project:
        flash('Project not found.')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    try:
        project = dict(project)
        project['deadline'] = datetime.strptime(project['deadline'], '%Y-%m-%d %H:%M:%S')
    except Exception:
        flash('Invalid project deadline format.')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        deadline = request.form['deadline']

        try:
            phase_deadline = datetime.fromisoformat(deadline.replace('T', ' '))
            if phase_deadline > project['deadline']:
                flash('Phase deadline cannot be later than project deadline.')
                phases = conn.execute('SELECT * FROM phases WHERE project_id = ?', (project_id,)).fetchall()
                phases = [dict(phase) for phase in phases]
                for phase in phases:
                    if isinstance(phase['deadline'], str):
                        phase['deadline'] = datetime.strptime(phase['deadline'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M')
                conn.close()
                return render_template('create_phase.html', project_id=project_id, project=project, phases=phases, now_str=datetime.now().strftime('%Y-%m-%dT%H:%M'))

            conn.execute('''
                INSERT INTO phases (project_id, name, description, deadline)
                VALUES (?, ?, ?, ?)
            ''', (project_id, name, description, phase_deadline))
            conn.commit()
            flash('Phase created successfully')
            conn.close()
            return redirect(url_for('admin_dashboard'))
        except ValueError:
            flash('Invalid deadline format. Use YYYY-MM-DD HH:MM.')
            phases = conn.execute('SELECT * FROM phases WHERE project_id = ?', (project_id,)).fetchall()
            phases = [dict(phase) for phase in phases]
            for phase in phases:
                if isinstance(phase['deadline'], str):
                    phase['deadline'] = datetime.strptime(phase['deadline'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M')
            conn.close()
            return render_template('create_phase.html', project_id=project_id, project=project, phases=phases, now_str=datetime.now().strftime('%Y-%m-%dT%H:%M'))

    phases = conn.execute('SELECT * FROM phases WHERE project_id = ?', (project_id,)).fetchall()
    phases = [dict(phase) for phase in phases]
    for phase in phases:
        if isinstance(phase['deadline'], str):
            phase['deadline'] = datetime.strptime(phase['deadline'], '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%dT%H:%M')
    conn.close()
    return render_template('create_phase.html', project_id=project_id, project=project, phases=phases, now_str=datetime.now().strftime('%Y-%m-%dT%H:%M'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Load blockchains when app starts
load_blockchains()

if __name__ == '__main__':
    app.run(debug=True)