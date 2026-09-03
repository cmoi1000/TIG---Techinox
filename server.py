#!/usr/bin/env python3
"""
TIG — Tech Inox Gestion · Techinox SARL
Serveur partagé avec authentification
Usage : python server.py [port]   (port par défaut : 3210)

Identifiants par défaut : admin / admin  (à changer dès le premier démarrage)

Clé API Claude : définir la variable d'environnement ANTHROPIC_API_KEY
(jamais stockée dans db.json, jamais renvoyée au navigateur — voir /api/extract-facture).
"""
import base64, hashlib, json, os, re, secrets, sys, time
import urllib.request, urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PORT      = int(sys.argv[1]) if len(sys.argv) > 1 else 3210
BASE      = Path(__file__).parent
HTML_FILE = BASE / 'index.html'   # code — jamais dans le volume de données

# Données persistantes : isolées dans data/ pour que ce dossier seul soit monté
# en volume Docker (une mise à jour du code via l'image ne les écrase jamais,
# et un `docker compose up --build` ne masque jamais le code par le volume).
DATA_DIR   = BASE / 'data'
DB_FILE    = DATA_DIR / 'db.json'
PDF_DIR    = DATA_DIR / 'pdfs'
USERS_FILE = DATA_DIR / 'users.json'

DATA_DIR.mkdir(exist_ok=True)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '').strip()
ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages'

PDF_DIR.mkdir(exist_ok=True)

# Sessions en mémoire : token → {username, role, expires}
sessions: dict = {}
SESSION_TTL = 8 * 3600  # 8 heures

# Anti brute-force sur /api/login : échecs récents par identifiant, en mémoire.
login_failures: dict = {}   # username → [timestamps des échecs récents]
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW = 15 * 60      # 15 minutes
LOGIN_LOCKOUT = 15 * 60     # verrouillage 15 minutes après le 5e échec


# ──────────────────────────── helpers auth ────────────────────────────

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000).hex()


def init_users():
    if not USERS_FILE.exists():
        salt = secrets.token_hex(16)
        USERS_FILE.write_text(json.dumps({
            'admin': {'hash': _hash('admin', salt), 'salt': salt, 'role': 'admin'}
        }, indent=2, ensure_ascii=False))
        print('  ⚠  Fichier users.json créé — login : admin / admin')


def load_users() -> dict:
    return json.loads(USERS_FILE.read_text(encoding='utf-8')) if USERS_FILE.exists() else {}


def save_users(users: dict):
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding='utf-8')


def get_session(headers) -> dict | None:
    auth = headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:]
    sess = sessions.get(token)
    if not sess or sess['expires'] < time.time():
        sessions.pop(token, None)
        return None
    return sess


def login_locked(username: str) -> int:
    """Renvoie le nb de secondes restant avant déverrouillage, 0 si non verrouillé."""
    attempts = [t for t in login_failures.get(username, []) if time.time() - t < LOGIN_WINDOW]
    login_failures[username] = attempts
    if len(attempts) < LOGIN_MAX_ATTEMPTS:
        return 0
    remaining = LOGIN_LOCKOUT - (time.time() - attempts[-1])
    return max(0, int(remaining))


def register_login_failure(username: str):
    login_failures.setdefault(username, []).append(time.time())


def clear_login_failures(username: str):
    login_failures.pop(username, None)


def require_auth(fn):
    """Décorateur : injecte sess ou renvoie 401."""
    def wrapper(self, *a, **kw):
        sess = get_session(self.headers)
        if not sess:
            self._json(401, {'error': 'Non authentifié'})
            return
        fn(self, sess, *a, **kw)
    return wrapper


def require_admin(fn):
    def wrapper(self, *a, **kw):
        sess = get_session(self.headers)
        if not sess:
            self._json(401, {'error': 'Non authentifié'})
            return
        if sess['role'] != 'admin':
            self._json(403, {'error': 'Accès réservé à l\'administrateur'})
            return
        fn(self, sess, *a, **kw)
    return wrapper


# ──────────────────────────── handler ────────────────────────────

class Handler(BaseHTTPRequestHandler):

    # ── OPTIONS (CORS preflight) ──────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ── GET ───────────────────────────────────────────────────────

    def do_GET(self):
        path = self.path.split('?')[0]   # ignorer query string

        if path in ('/', '/index.html'):
            data = HTML_FILE.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(data))
            self.send_header('X-Robots-Tag', 'noindex, nofollow')
            self.send_header('Cache-Control', 'no-store')
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        elif path == '/api/db':
            sess = get_session(self.headers)
            if not sess:
                self._json(401, {'error': 'Non authentifié'}); return
            data = DB_FILE.read_bytes() if DB_FILE.exists() else b'{}'
            self._raw(200, data, 'application/json')

        # ── statut clé API Claude (booléen seulement, jamais la clé) ──
        elif path == '/api/claude-status':
            sess = get_session(self.headers)
            if not sess:
                self._json(401, {'error': 'Non authentifié'}); return
            self._json(200, {'configured': bool(ANTHROPIC_API_KEY)})

        elif path == '/api/users':
            sess = get_session(self.headers)
            if not sess or sess['role'] != 'admin':
                self._json(403, {'error': 'Accès refusé'}); return
            users = load_users()
            result = [{'username': u, 'role': v['role']} for u, v in users.items()]
            self._json(200, result)

        elif path.startswith('/pdfs/'):
            sess = get_session(self.headers)
            if not sess:
                self._json(401, {'error': 'Non authentifié'}); return
            filename = path[6:]
            if not filename or '/' in filename or '..' in filename:
                self.send_error(400); return
            pdf_path = PDF_DIR / filename
            if not pdf_path.exists():
                self.send_error(404); return
            data = pdf_path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Length', len(data))
            self.send_header('Content-Disposition', f'inline; filename="{filename}"')
            self.send_header('X-Robots-Tag', 'noindex, nofollow')
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        else:
            self.send_error(404)

    # ── POST ──────────────────────────────────────────────────────

    def do_POST(self):
        length  = int(self.headers.get('Content-Length', 0))
        body    = self.rfile.read(length)
        path    = self.path.split('?')[0]

        # ── login (public) ────────────────────────────────────────
        if path == '/api/login':
            try:
                p = json.loads(body)
                username = p.get('username', '').strip()
                password = p.get('password', '')

                locked_for = login_locked(username)
                if locked_for:
                    self._json(429, {'error': f'Trop de tentatives — réessayez dans {locked_for // 60 + 1} min.'}); return

                users    = load_users()
                u        = users.get(username)
                if not u or _hash(password, u['salt']) != u['hash']:
                    register_login_failure(username)
                    self._json(401, {'error': 'Identifiants incorrects'}); return
                clear_login_failures(username)
                token = secrets.token_hex(32)
                sessions[token] = {
                    'username': username,
                    'role':     u['role'],
                    'expires':  time.time() + SESSION_TTL
                }
                self._json(200, {'token': token, 'username': username, 'role': u['role']})
            except Exception as e:
                self._json(400, {'error': str(e)})

        # ── logout ────────────────────────────────────────────────
        elif path == '/api/logout':
            auth = self.headers.get('Authorization', '')
            if auth.startswith('Bearer '):
                sessions.pop(auth[7:], None)
            self._json(200, {'ok': True})

        # ── db (protégé) ──────────────────────────────────────────
        elif path == '/api/db':
            sess = get_session(self.headers)
            if not sess:
                self._json(401, {'error': 'Non authentifié'}); return
            try:
                json.loads(body)
            except Exception:
                self._json(400, {'error': 'JSON invalide'}); return
            DB_FILE.write_bytes(body)
            self._json(200, {'ok': True})

        # ── pdf upload (protégé) ──────────────────────────────────
        elif path == '/api/pdf':
            sess = get_session(self.headers)
            if not sess:
                self._json(401, {'error': 'Non authentifié'}); return
            try:
                p        = json.loads(body)
                filename = re.sub(r'[^A-Za-z0-9_.\-]', '_', p['filename'])
                if not filename.endswith('.pdf'):
                    filename += '.pdf'
                (PDF_DIR / filename).write_bytes(base64.b64decode(p['data']))
                self._json(200, {'ok': True, 'filename': filename})
            except Exception as e:
                self._json(400, {'error': str(e)})

        # ── extraction facture via Claude (proxy — la clé ne quitte jamais le serveur) ──
        elif path == '/api/extract-facture':
            sess = get_session(self.headers)
            if not sess:
                self._json(401, {'error': 'Non authentifié'}); return
            if not ANTHROPIC_API_KEY:
                self._json(500, {'error': "Clé API Claude non configurée sur le serveur (variable d'environnement ANTHROPIC_API_KEY manquante)."}); return
            try:
                p = json.loads(body)
                pdf_b64 = p['pdf_base64']
                prompt  = p['prompt']
                model   = p.get('model') or 'claude-opus-5'
            except Exception as e:
                self._json(400, {'error': str(e)}); return

            anthro_req_body = json.dumps({
                'model': model,
                'max_tokens': 4096,
                'messages': [{
                    'role': 'user',
                    'content': [
                        {'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': pdf_b64}},
                        {'type': 'text', 'text': prompt}
                    ]
                }]
            }).encode('utf-8')

            req = urllib.request.Request(
                ANTHROPIC_API_URL,
                data=anthro_req_body,
                method='POST',
                headers={
                    'Content-Type': 'application/json',
                    'x-api-key': ANTHROPIC_API_KEY,
                    'anthropic-version': '2023-06-01'
                }
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    self._raw(resp.status, resp.read(), 'application/json')
            except urllib.error.HTTPError as e:
                self._raw(e.code, e.read(), 'application/json')
            except Exception as e:
                self._json(502, {'error': "Erreur d'appel à l'API Claude : " + str(e)})

        # ── créer / modifier user (admin) ─────────────────────────
        elif path == '/api/users':
            sess = get_session(self.headers)
            if not sess or sess['role'] != 'admin':
                self._json(403, {'error': 'Accès refusé'}); return
            try:
                p        = json.loads(body)
                username = p['username'].strip()
                password = p.get('password', '')
                role     = p.get('role', 'user')
                if role not in ('admin', 'user'):
                    role = 'user'
                users = load_users()
                if username in users and not password:
                    users[username]['role'] = role   # changement de rôle seul
                else:
                    if not password:
                        self._json(400, {'error': 'Mot de passe requis'}); return
                    if len(password) < 8:
                        self._json(400, {'error': 'Mot de passe trop court (8 car. min)'}); return
                    salt = secrets.token_hex(16)
                    users[username] = {'hash': _hash(password, salt), 'salt': salt, 'role': role}
                save_users(users)
                self._json(200, {'ok': True})
            except Exception as e:
                self._json(400, {'error': str(e)})

        # ── changer son propre mot de passe ───────────────────────
        elif path == '/api/change-password':
            sess = get_session(self.headers)
            if not sess:
                self._json(401, {'error': 'Non authentifié'}); return
            try:
                p      = json.loads(body)
                old_pw = p.get('old_password', '')
                new_pw = p.get('new_password', '')
                if len(new_pw) < 8:
                    self._json(400, {'error': 'Nouveau mot de passe trop court (8 car. min)'}); return
                users  = load_users()
                u      = users[sess['username']]
                if _hash(old_pw, u['salt']) != u['hash']:
                    self._json(401, {'error': 'Ancien mot de passe incorrect'}); return
                salt   = secrets.token_hex(16)
                u['hash'] = _hash(new_pw, salt)
                u['salt'] = salt
                save_users(users)
                self._json(200, {'ok': True})
            except Exception as e:
                self._json(400, {'error': str(e)})

        else:
            self.send_error(404)

    # ── DELETE ────────────────────────────────────────────────────

    def do_DELETE(self):
        path = self.path.split('?')[0]
        if path.startswith('/api/users/'):
            sess = get_session(self.headers)
            if not sess or sess['role'] != 'admin':
                self._json(403, {'error': 'Accès refusé'}); return
            username = path[11:]
            if not username or username == sess['username']:
                self._json(400, {'error': 'Impossible de supprimer votre propre compte'}); return
            users = load_users()
            # Garder au moins un admin
            remaining_admins = [u for u, v in users.items() if v['role'] == 'admin' and u != username]
            if not remaining_admins:
                self._json(400, {'error': 'Impossible de supprimer le dernier administrateur'}); return
            users.pop(username, None)
            save_users(users)
            self._json(200, {'ok': True})
        else:
            self.send_error(404)

    # ── helpers ───────────────────────────────────────────────────

    def _json(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self._raw(code, body, 'application/json; charset=utf-8')

    def _raw(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(body))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def log_message(self, fmt, *args):
        print(f'[{self.address_string()}] {fmt % args}')


# ──────────────────────────── main ────────────────────────────────────

if __name__ == '__main__':
    init_users()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print('TIG — Tech Inox Gestion · Techinox SARL')
    print(f'  URL locale   : http://localhost:{PORT}')
    print(f'  Réseau local : http://<votre-IP>:{PORT}')
    print(f'  Base données : {DB_FILE}')
    print(f'  Utilisateurs : {USERS_FILE}')
    print(f'  PDFs         : {PDF_DIR}')
    print('  Ctrl+C pour arrêter\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServeur arrêté.')
