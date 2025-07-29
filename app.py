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

# Đường dẫn thư mục lưu blockchain và uploads
BLOCKCHAIN_DIR = "blockchain_data"
UPLOADS_DIR = "uploads"
for directory in [BLOCKCHAIN_DIR, UPLOADS_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)
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
    progress = round((completed_tasks / total_tasks) * 100, 2)
    status = 'Done' if progress == 100 else 'Pending' if progress == 0 else 'Running'
    conn.execute('UPDATE projects SET progress = ?, status = ? WHERE id = ?', (progress, status, project_id))
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
    projects = conn.execute('SELECT * FROM projects').fetchall()
    projects = [dict(project) for project in projects]

    # Tính tổng nhiệm vụ
    total_tasks = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]

    # Tính số dự án hoàn thành (progress = 100)
    completed_projects = conn.execute('SELECT COUNT(*) FROM projects WHERE progress = 100').fetchone()[0]

    # Chuyển đổi datetime và tính time_progress
    now = datetime.now()
    for project in projects:
        if isinstance(project['start_datetime'], str):
            project['start_datetime'] = datetime.strptime(project['start_datetime'], '%Y-%m-%d %H:%M:%S')
        if isinstance(project['end_datetime'], str):
            project['end_datetime'] = datetime.strptime(project['end_datetime'], '%Y-%m-%d %H:%M:%S')
        if 'deadline' not in project:
            project['deadline'] = project['end_datetime'].strftime('%Y-%m-%d %H:%M')
        
        # Tính time_progress
        total_duration = (project['end_datetime'] - project['start_datetime']).total_seconds()
        elapsed_duration = (now - project['start_datetime']).total_seconds()
        time_progress = (elapsed_duration / total_duration * 100) if total_duration > 0 else 0
        time_progress = round(min(max(time_progress, 0), 100), 2)
        project['time_progress'] = time_progress

    # Tính running và progress
    running = sum(1 for project in projects if 0 < project.get('progress', 0) < 100)
    progress = sum(project.get('progress', 0) for project in projects) / max(len(projects), 1) if projects else 0

    conn.close()
    return render_template('admin_dashboard.html', projects=projects, tasks=[], running=running, progress=progress, total_tasks=total_tasks, completed_projects=completed_projects)

@app.route('/admin/view_task/<int:project_id>')
def view_task(project_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    if not project:
        flash('Project not found.')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    project = dict(project)
    if isinstance(project['start_datetime'], str):
        project['start_datetime'] = datetime.strptime(project['start_datetime'], '%Y-%m-%d %H:%M:%S')
    if isinstance(project['end_datetime'], str):
        project['end_datetime'] = datetime.strptime(project['end_datetime'], '%Y-%m-%d %H:%M:%S')

    phases_raw = conn.execute('SELECT id, name, start_datetime, end_datetime FROM phases WHERE project_id = ?', (project_id,)).fetchall()
    phases = []
    for phase in phases_raw:
        phase_dict = dict(phase)
        if isinstance(phase_dict['start_datetime'], str):
            phase_dict['start_datetime'] = datetime.strptime(phase_dict['start_datetime'], '%Y-%m-%d %H:%M:%S')
        if isinstance(phase_dict['end_datetime'], str):
            phase_dict['end_datetime'] = datetime.strptime(phase_dict['end_datetime'], '%Y-%m-%d %H:%M:%S')
        phases.append(phase_dict)

    tasks_raw = conn.execute('''
        SELECT t.*, GROUP_CONCAT(u.username) as assigned_users 
        FROM tasks t 
        LEFT JOIN task_assignments ta ON t.id = ta.task_id 
        LEFT JOIN users u ON ta.user_id = u.id 
        WHERE t.project_id = ? 
        GROUP BY t.id
    ''', (project_id,)).fetchall()
    tasks = []
    for task in tasks_raw:
        task_dict = dict(task)
        if isinstance(task_dict['start_datetime'], str):
            task_dict['start_datetime'] = datetime.strptime(task_dict['start_datetime'], '%Y-%m-%d %H:%M:%S')
        if isinstance(task_dict['end_datetime'], str):
            task_dict['end_datetime'] = datetime.strptime(task_dict['end_datetime'], '%Y-%m-%d %H:%M:%S')
        tasks.append(task_dict)

    conn.close()
    return render_template('view_tasks.html', project=project, phases=phases, tasks=tasks)

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
            logger.info(f"Deleted blockchain file {blockchain_file} for project {project_id}")
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
        start_datetime = request.form['start_datetime']
        end_datetime = request.form['end_datetime']
        try:
            start_datetime_dt = datetime.fromisoformat(start_datetime.replace('T', ' '))
            end_datetime_dt = datetime.fromisoformat(end_datetime.replace('T', ' '))
            if start_datetime_dt > end_datetime_dt:
                flash('Start date cannot be later than end date.')
                return render_template('create_project.html')
            conn = get_db()
            conn.execute('INSERT INTO projects (name, description, start_datetime, end_datetime, progress) VALUES (?, ?, ?, ?, 0)', 
                        (name, description, start_datetime_dt, end_datetime_dt))
            project_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            blockchain = get_or_create_blockchain(project_id)
            blockchain.save_to_file(os.path.join(BLOCKCHAIN_DIR, f"blockchain_{project_id}.json"))
            logger.info(f"Initialized blockchain for new project {project_id}")
            phase_names = request.form.getlist('phase_names[]')
            phase_descriptions = request.form.getlist('phase_descriptions[]')
            phase_start_datetimes = request.form.getlist('phase_start_datetimes[]')
            phase_end_datetimes = request.form.getlist('phase_end_datetimes[]')
            
            phases = []
            for name, desc, start_dt, end_dt in zip(phase_names, phase_descriptions, phase_start_datetimes, phase_end_datetimes):
                if name and start_dt and end_dt:
                    phase_start_dt = datetime.fromisoformat(start_dt.replace('T', ' '))
                    phase_end_dt = datetime.fromisoformat(end_dt.replace('T', ' '))
                    if phase_start_dt > phase_end_dt or phase_end_dt > end_datetime_dt:
                        flash('Phase start date cannot be later than end date or exceed project end date.')
                        conn.close()
                        return render_template('create_project.html')
                    phases.append({'name': name, 'description': desc or None, 'start_datetime': phase_start_dt, 'end_datetime': phase_end_dt})
            
            phases.sort(key=lambda x: x['start_datetime'])
            for i in range(1, len(phases)):
                if phases[i]['start_datetime'] <= phases[i-1]['end_datetime']:
                    flash('Each phase must start after the previous phase ends.')
                    conn.close()
                    return render_template('create_project.html')
            
            for phase in phases:
                conn.execute('INSERT INTO phases (project_id, name, description, start_datetime, end_datetime) VALUES (?, ?, ?, ?, ?)',
                            (project_id, phase['name'], phase['description'], phase['start_datetime'], phase['end_datetime']))
            
            conn.commit()
            conn.close()
            flash('Project and phases created successfully')
            return redirect(url_for('admin_dashboard'))
        except ValueError:
            flash('Invalid date format. Use YYYY-MM-DD HH:MM.')
            return render_template('create_project.html')
    return render_template('create_project.html')

@app.route('/admin/view_phases/<int:project_id>')
def view_phases(project_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    phases = conn.execute('SELECT * FROM phases WHERE project_id = ? ORDER BY end_datetime', (project_id,)).fetchall()
    conn.close()
    return render_template('view_phases.html', project_id=project_id, project=project, phases=phases)

@app.route('/admin/create_task/<int:project_id>', methods=['GET', 'POST'])
def create_task(project_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    users = conn.execute('SELECT * FROM users WHERE role = "user"').fetchall()
    phases_raw = conn.execute('SELECT id, name, start_datetime, end_datetime FROM phases WHERE project_id = ?', (project_id,)).fetchall()
    now_str = datetime.now().strftime('%Y-%m-%dT%H:%M')
    if not project:
        flash('Project not found.')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    project = dict(project)
    if isinstance(project['start_datetime'], str):
        project['start_datetime'] = datetime.strptime(project['start_datetime'], '%Y-%m-%d %H:%M:%S')
    if isinstance(project['end_datetime'], str):
        project['end_datetime'] = datetime.strptime(project['end_datetime'], '%Y-%m-%d %H:%M:%S')

    phases = []
    for phase in phases_raw:
        phase_dict = dict(phase)
        if isinstance(phase_dict['start_datetime'], str):
            phase_dict['start_datetime'] = datetime.strptime(phase_dict['start_datetime'], '%Y-%m-%d %H:%M:%S')
        if isinstance(phase_dict['end_datetime'], str):
            phase_dict['end_datetime'] = datetime.strptime(phase_dict['end_datetime'], '%Y-%m-%d %H:%M:%S')
        phases.append(phase_dict)

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        start_datetime = request.form['start_datetime']
        end_datetime = request.form['end_datetime']
        user_ids = request.form.getlist('user_ids')
        phase_id = request.form.get('phase_id')

        try:
            task_start_dt = datetime.fromisoformat(start_datetime.replace('T', ' '))
            task_end_dt = datetime.fromisoformat(end_datetime.replace('T', ' '))
            if task_start_dt > task_end_dt or task_end_dt > project['end_datetime']:
                flash('Task start date cannot be later than end date or exceed project end date.')
                conn.close()
                return render_template('create_task.html', project_id=project_id, users=users, project=project, phases=phases, now_str=now_str)
            
            if phase_id:
                phase = conn.execute('SELECT start_datetime, end_datetime FROM phases WHERE id = ?', (phase_id,)).fetchone()
                if phase:
                    phase_start = datetime.strptime(phase['start_datetime'], '%Y-%m-%d %H:%M:%S') if isinstance(phase['start_datetime'], str) else phase['start_datetime']
                    phase_end = datetime.strptime(phase['end_datetime'], '%Y-%m-%d %H:%M:%S') if isinstance(phase['end_datetime'], str) else phase['end_datetime']
                    if task_start_dt < phase_start or task_end_dt > phase_end:
                        flash('Task dates must be within the selected phase dates.')
                        conn.close()
                        return render_template('create_task.html', project_id=project_id, users=users, project=project, phases=phases, now_str=now_str)

            conn.execute('''
                INSERT INTO tasks (project_id, phase_id, title, description, start_datetime, end_datetime, progress, progress_text) 
                VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
            ''', (project_id, phase_id, title, description, task_start_dt, task_end_dt))

            task_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

            for user_id in user_ids:
                conn.execute('INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)', 
                            (task_id, user_id))

            conn.commit()
            conn.close()
            flash('Task created and assigned successfully')
            return redirect(url_for('admin_dashboard'))
        except ValueError:
            flash('Invalid date format. Use YYYY-MM-DD HH:MM.')
            conn.close()
            return render_template('create_task.html', project_id=project_id, users=users, project=project, phases=phases, now_str=now_str)

    conn.close()
    return render_template('create_task.html', project_id=project_id, users=users, project=project, phases=phases, now_str=now_str)

@app.route('/admin/assign_task/<int:task_id>', methods=['GET', 'POST'])
def assign_task(task_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    task = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not task:
        flash('Task not found.')
        conn.close()
        return redirect(url_for('admin_dashboard'))

    task = dict(task)
    if isinstance(task['start_datetime'], str):
        task['start_datetime'] = datetime.strptime(task['start_datetime'], '%Y-%m-%d %H:%M:%S')
    if isinstance(task['end_datetime'], str):
        task['end_datetime'] = datetime.strptime(task['end_datetime'], '%Y-%m-%d %H:%M:%S')

    users = conn.execute('SELECT * FROM users WHERE role = "user"').fetchall()
    current_assignments = conn.execute('SELECT user_id FROM task_assignments WHERE task_id = ?', (task_id,)).fetchall()
    current_user_ids = [row['user_id'] for row in current_assignments]

    if request.method == 'POST':
        user_ids = request.form.getlist('user_ids')
        try:
            conn.execute('DELETE FROM task_assignments WHERE task_id = ?', (task_id,))
            for user_id in user_ids:
                conn.execute('INSERT INTO task_assignments (task_id, user_id) VALUES (?, ?)', (task_id, user_id))
            conn.commit()
            flash('Task assigned successfully.')
            conn.close()
            return redirect(url_for('view_task', project_id=task['project_id']))
        except Exception as e:
            conn.rollback()
            flash(f'Error assigning task: {str(e)}')
            conn.close()
            return render_template('assign_task.html', task=task, users=users, project_id=task['project_id'], current_user_ids=current_user_ids)

    conn.close()
    return render_template('assign_task.html', task=task, users=users, project_id=task['project_id'], current_user_ids=current_user_ids)

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
                        blockchain.chain = [block for i, block in enumerate(blockchain.chain) if i != block_index]
                        blockchain.mine_pending_transactions()
                        blockchain_file = os.path.join(BLOCKCHAIN_DIR, f"blockchain_{project_id}.json")
                        blockchain.save_to_file(blockchain_file)
                        return redirect(url_for('view_project_chain', project_id=project_id))

    conn.close()
    if not relevant_chain:
        flash('No blockchain data available for this project.')
    
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
        SELECT DISTINCT p.id, p.name, p.start_datetime, p.end_datetime, p.progress
        FROM projects p
        JOIN tasks t ON p.id = t.project_id
        JOIN task_assignments ta ON t.id = ta.task_id
        WHERE ta.user_id = ?
    ''', (session['user_id'],))
    projects = cursor.fetchall()
    
    user_tasks = {}
    for project in projects:
        tasks = conn.execute('''
            SELECT t.*, p.end_datetime AS project_end_datetime
            FROM tasks t
            JOIN task_assignments ta ON t.id = ta.task_id
            JOIN projects p ON t.project_id = p.id
            WHERE ta.user_id = ? AND t.project_id = ?
        ''', (session['user_id'], project['id'])).fetchall()
        user_tasks[project['id']] = tasks
    
    conn.close()
    return render_template('user_dashboard.html', projects=projects, user_tasks=user_tasks)

@app.route('/user/update_progress/<int:task_id>', methods=['GET', 'POST'])
def update_progress(task_id):
    if 'user_id' not in session or session['role'] != 'user':
        return redirect(url_for('login'))
    
    conn = get_db()
    task = dict(conn.execute('''
        SELECT t.*, p.end_datetime AS project_end_datetime, p.id AS project_id, 
               GROUP_CONCAT(u.username) AS assigned_users
        FROM tasks t 
        JOIN projects p ON t.project_id = p.id 
        LEFT JOIN task_assignments ta ON t.id = ta.task_id
        LEFT JOIN users u ON ta.user_id = u.id
        WHERE t.id = ?
        GROUP BY t.id
    ''', (task_id,)).fetchone())
    
    if not task:
        flash('Task not found.')
        conn.close()
        return redirect(url_for('user_dashboard'))
    
    if isinstance(task['start_datetime'], str):
        task['start_datetime'] = datetime.strptime(task['start_datetime'], '%Y-%m-%d %H:%M:%S')
    if isinstance(task['end_datetime'], str):
        task['end_datetime'] = datetime.strptime(task['end_datetime'], '%Y-%m-%d %H:%M:%S')
    if isinstance(task['project_end_datetime'], str):
        task['project_end_datetime'] = datetime.strptime(task['project_end_datetime'], '%Y-%m-%d %H:%M:%S')
    
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
        completed = request.form.get('completed') == 'on'
        progress_text = request.form['progress_text'] or ''
        progress = 100 if completed else 0

        # Handle file uploads
        files = request.files.getlist('files')
        uploaded_files = []
        for file in files:
            if file and file.filename:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"task_{task_id}_user_{session['user_id']}_{timestamp}_{file.filename}"
                file_path = os.path.join(UPLOADS_DIR, filename)
                file.save(file_path)
                uploaded_files.append(file_path)
                conn.execute('''
                    INSERT INTO files (task_id, user_id, file_path, upload_timestamp)
                    VALUES (?, ?, ?, ?)
                ''', (task_id, session['user_id'], file_path, datetime.now()))
                logger.info(f"Uploaded file {filename} for task {task_id} by user {session['user_id']}")

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
                flash('Thông tin tiến độ đã được lưu lại.')
            else:
                flash('Cannot save block: Blockchain file not found.')
        else:
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
                        flash('Thông tin tiến độ đã được lưu lại.')
                    else:
                        flash('Cannot save block: Blockchain file not found.')
                else:
                    conn.rollback()
                    flash('Failed to mine block')
            else:
                flash('Invalid transaction signature!')

        conn.close()
        return redirect(url_for('user_dashboard'))

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

    project = dict(project)
    if isinstance(project['start_datetime'], str):
        project['start_datetime'] = datetime.strptime(project['start_datetime'], '%Y-%m-%d %H:%M:%S')
    if isinstance(project['end_datetime'], str):
        project['end_datetime'] = datetime.strptime(project['end_datetime'], '%Y-%m-%d %H:%M:%S')

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        start_datetime = request.form['start_datetime']
        end_datetime = request.form['end_datetime']

        try:
            phase_start_dt = datetime.fromisoformat(start_datetime.replace('T', ' '))
            phase_end_dt = datetime.fromisoformat(end_datetime.replace('T', ' '))
            if phase_start_dt < project['start_datetime'] or phase_end_dt > project['end_datetime']:
                flash('Phase dates must be within project start and end dates.')
                conn.close()
                return render_template('create_phase.html', project_id=project_id, project=project, phases=[])
            if phase_start_dt >= phase_end_dt:
                flash('Phase start date cannot be later than or equal to end date.')
                conn.close()
                return render_template('create_phase.html', project_id=project_id, project=project, phases=[])

            conn.execute('''
                INSERT INTO phases (project_id, name, description, start_datetime, end_datetime)
                VALUES (?, ?, ?, ?, ?)
            ''', (project_id, name, description, phase_start_dt, phase_end_dt))
            conn.commit()
            conn.close()
            flash('Phase created successfully')
            return redirect(url_for('view_task', project_id=project_id))
        except ValueError:
            flash('Invalid date format. Use YYYY-MM-DD HH:MM.')
            conn.close()
            return render_template('create_phase.html', project_id=project_id, project=project, phases=[])

    conn.close()
    return render_template('create_phase.html', project_id=project_id, project=project, phases=[])

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Load blockchains when app starts
load_blockchains()

if __name__ == '__main__':
    app.run(debug=True)