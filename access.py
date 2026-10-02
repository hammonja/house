"""Single-house access control. Passwords and setup codes never enter Git."""
from collections import deque
from datetime import timedelta
from pathlib import Path
import hmac
import json
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

from flask import abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


def private_write(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        file.write(value)
    os.replace(temp, path)
    path.chmod(0o600)


def protect(app, root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    auth_file, code_file = root / 'auth.json', root / 'setup-code.txt'
    if auth_file.exists():
        auth = json.loads(auth_file.read_text(encoding='utf-8'))
    else:
        auth = {'secret': secrets.token_urlsafe(48), 'password_hash': None}
        private_write(auth_file, json.dumps(auth))
    if not auth['password_hash'] and not code_file.exists():
        private_write(code_file, secrets.token_urlsafe(32))
    app.secret_key = auth['secret']
    app.config.update(SESSION_COOKIE_NAME='house_session', SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=timedelta(hours=12))
    lock = threading.RLock()
    attempts = deque(maxlen=20)

    def csrf():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return session['csrf']

    app.jinja_env.globals['csrf_token'] = csrf

    @app.before_request
    def guard():
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            supplied = request.form.get('csrf', '') or request.headers.get('X-CSRF-Token', '')
            expected = session.get('csrf', '')
            if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
                abort(400, 'Please reload the page and try again.')
            origin = request.headers.get('Origin')
            if origin and (urlsplit(origin).netloc != request.host
                           or urlsplit(origin).scheme != request.scheme):
                abort(403)
        if request.endpoint in {'login', 'setup', 'health', 'static'}:
            return None
        if not session.get('signed_in'):
            if request.path.startswith(('/api/', '/models/', '/reference/')):
                return jsonify(error='Sign in to view this private project.'), 401
            return redirect(url_for('login'))

    @app.after_request
    def private_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    def attempt_allowed():
        now = time.monotonic()
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 10:
            return False
        attempts.append(now)
        return True

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if not auth['password_hash']:
            return redirect(url_for('setup'))
        error, status = None, 200
        if request.method == 'POST':
            with lock:
                if not attempt_allowed():
                    error, status = 'Too many attempts. Please wait one minute.', 429
                elif check_password_hash(auth['password_hash'], request.form.get('password', '')):
                    session.clear()
                    session['signed_in'] = True
                    session.permanent = True
                    return redirect(url_for('index'))
                else:
                    error, status = 'That password was not accepted.', 401
        return render_template('access.html', setup=False, error=error), status

    @app.route('/setup', methods=['GET', 'POST'])
    def setup():
        error, status = None, 200
        with lock:
            if auth['password_hash']:
                return redirect(url_for('login'))
            if request.method == 'POST':
                supplied = request.form.get('setup_code', '').strip()
                password = request.form.get('password', '')
                if not attempt_allowed():
                    error, status = 'Too many attempts. Please wait one minute.', 429
                elif not hmac.compare_digest(supplied.encode(), code_file.read_bytes().strip()):
                    error, status = 'The setup code was not accepted.', 401
                elif not 12 <= len(password) <= 256:
                    error, status = 'Use a password between 12 and 256 characters.', 400
                elif password != request.form.get('confirmation'):
                    error, status = 'The passwords do not match.', 400
                else:
                    auth['password_hash'] = generate_password_hash(password)
                    private_write(auth_file, json.dumps(auth))
                    code_file.unlink(missing_ok=True)
                    session.clear()
                    session['signed_in'] = True
                    session.permanent = True
                    return redirect(url_for('index'))
        return render_template('access.html', setup=True, error=error), status

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))
