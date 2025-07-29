CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
    private_key TEXT NOT NULL,
    public_key TEXT NOT NULL
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    deadline DATETIME NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Running', 'Pending', 'Done')),
    progress INTEGER DEFAULT 0
);

CREATE TABLE phases (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    deadline DATETIME NOT NULL,
    progress INTEGER DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE phase_dependencies (
    id INTEGER PRIMARY KEY,
    phase_id INTEGER NOT NULL,
    prerequisite_phase_id INTEGER NOT NULL,
    FOREIGN KEY (phase_id) REFERENCES phases(id),
    FOREIGN KEY (prerequisite_phase_id) REFERENCES phases(id),
    CHECK (phase_id != prerequisite_phase_id)
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    phase_id INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    progress INTEGER DEFAULT 0,
    deadline DATETIME NOT NULL,
    progress_text TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (phase_id) REFERENCES phases(id)
);

CREATE TABLE task_assignments (
    id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE task_progress (
    task_id INTEGER,
    user_id INTEGER,
    progress INTEGER DEFAULT 0,
    timestamp TEXT,
    PRIMARY KEY (task_id, user_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);