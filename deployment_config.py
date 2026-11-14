"""Migrate and project the operator's BenchForge deployment configuration."""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import shlex
import tempfile
from urllib.parse import quote, urlsplit

from service_access.configuration import isaac_config, validate_providers
from service_access.runtime_config import expand_environment, read_json


SECTIONS = ('web', 'server', 'database', 'client', 'worker')
SERVER_PATHS = ('artifacts', 'harness', 'task_root', 'scene_policy_path')
CLIENT_PATHS = (*SERVER_PATHS, 'models_config', 'service_config')
WORKER_PATHS = ('runs', 'ssh_config', 'asset_cache')
ISAAC_WORKER_KEYS = {
    'mode': 'isaac_mode',
    'grpc': 'isaac_grpc',
    'local': 'isaac_local',
    'capture_timeout_seconds': 'capture_timeout_seconds',
}
CONFIG_VERSION = 4
DEPLOYMENT_DEFAULTS = {
    'web': {'port': 3081, 'default_workspace': None},
    'server': {
        'service_host': '127.0.0.1', 'port': 3841, 'execution_mode': 'production',
        'artifacts': '../.benchforge/backend/artifacts',
        'scene_policy_path': 'generated/scene-library/policy.json',
    },
    'database': {'project': 'benchforge', 'port': 55432, 'user': 'benchforge', 'name': 'benchforge'},
    'client': {},
    'worker': {'worker_id': 'desktop-isaac-main'},
}
SERVER_CONFIG = 'benchforge-server.local.json'
CLIENT_CONFIG = 'benchforge-client.local.json'
MANAGED_MARKER = 'BENCHFORGE_DATABASE_MANAGED'
MANAGED_URL = 'BENCHFORGE_DATABASE_URL'
DATABASE_SETTINGS = ('COMPOSE_PROJECT_NAME', 'POSTGRES_PORT', 'POSTGRES_USER', 'POSTGRES_DB', 'POSTGRES_PASSWORD')
DEFAULT_POLICY = {
    'enabled': True,
    'enforce_realism': True,
    'require_scene_brief': True,
    'excluded_tasks': [],
    'excluded_runs': [],
    'excluded_scene_groups': [],
    'excluded_paths': [],
}
API_NAMES = ('operator', 'worker')


def read_object(path, *, optional=False):
    if optional and not path.exists():
        return {}
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f'{path.name} must contain a JSON object')
    return value


def read_env(path, *, shell=False):
    """Read literal .env assignments without running a shell."""
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        name, separator, value = line.lstrip().removeprefix('export ').partition('=')
        name = name.strip()
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError(f'{path.name} contains an invalid environment assignment')
        if shell:
            # shlex preserves literal single-quoted values and supports double
            # quotes without evaluating commands or substituting environment.
            lexer = shlex.shlex(value, posix=True)
            lexer.whitespace_split = True
            try:
                words = list(lexer)
            except ValueError:
                raise ValueError(f'{path.name} has invalid quoting for {name}') from None
            value = ' '.join(words)
        values[name] = value
    return values


def write_text(path, value):
    """Replace local settings and secret-bearing projections atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(value)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


@contextmanager
def projection_lock(generated):
    """Keep two init/sync processes from selecting different credentials."""
    generated.mkdir(parents=True, exist_ok=True)
    with (generated / '.sync.lock').open('a+b', buffering=0) as marker:
        if os.name == 'nt':
            import msvcrt

            marker.seek(0)
            msvcrt.locking(marker.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                marker.seek(0)
                msvcrt.locking(marker.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(marker, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(marker, fcntl.LOCK_UN)


def port(value, field):
    if isinstance(value, str) and re.fullmatch(r'[0-9]+', value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError(f'{field} must be an integer between 1 and 65535')
    return value


def compose_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', value):
        raise ValueError('database.project must be a valid Docker Compose project name')
    return value


def env_name(value, field):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError(f'{field} must name an environment variable')
    return value


def text_value(value, field):
    if not isinstance(value, str) or not value or any(c in value for c in '\r\n\0'):
        raise ValueError(f'{field} must be a nonempty string without line breaks')
    return value


def _file_path(value, directory, environment):
    expanded = expand_environment(value, environment)
    if os.name != 'nt' and PureWindowsPath(expanded).is_absolute():
        # The Windows worker is often configured from a Linux Web/DB host.
        # A drive/UNC path in its profile belongs to the worker machine.
        return expanded
    path = Path(expanded).expanduser()
    return str((directory / path).resolve())


def _resolve_paths(values, fields, directory, environment):
    for field in fields:
        if values.get(field):
            values[field] = _file_path(values[field], directory, environment)


def local_service_configs(generated):
    return {path.resolve(): path for path in (generated / SERVER_CONFIG, generated / CLIENT_CONFIG)}


def database_is_managed(database):
    return not (database.get('url') or database.get('url_env'))


def previous_database_project(saved):
    return saved.get('COMPOSE_PROJECT_NAME', 'benchforge') if saved else None


def _sections(local):
    result = {}
    for name in SECTIONS:
        value = local.get(name, {})
        if not isinstance(value, dict):
            raise ValueError(f'{name} configuration must be a JSON object')
        result[name] = value
    return result


def _inherit_defaults(values, defaults):
    for key, value in defaults.items():
        if key not in values:
            values[key] = deepcopy(value)
        elif isinstance(values[key], dict) and isinstance(value, dict):
            _inherit_defaults(values[key], value)


def read_configuration(config, *, overrides=None):
    template = read_object(config / 'benchforge.example.json')
    path = config / 'benchforge.local.json'
    local = read_object(path, optional=True)
    if path.is_file() and local.get('config_version') != CONFIG_VERSION:
        raise ValueError(f'Update {path} to config_version {CONFIG_VERSION} using benchforge.example.json')
    known = {'config_version', 'dsh', 'providers', 'collectors', 'cleaning', *SECTIONS}
    if unknown := local.keys() - known:
        raise ValueError(f'Unknown BenchForge configuration sections: {", ".join(sorted(unknown))}')
    environment = {**read_env(config / 'dsh.env', shell=True), **os.environ}
    registry = deepcopy(local)
    settings = _sections(registry)
    for name in SECTIONS:
        _inherit_defaults(settings[name], (overrides or {}).get(name, {}))
        _inherit_defaults(settings[name], DEPLOYMENT_DEFAULTS[name])
        registry[name] = settings[name]
    providers = registry.setdefault('providers', {})
    if isinstance(providers, dict):
        _inherit_defaults(providers, template['providers'])
    if any(key in registry['worker'] for key in ISAAC_WORKER_KEYS.values()):
        raise ValueError('Configure the Isaac endpoint and capture timeout under providers.IssacSim4A100')
    for name in ('web', 'server', 'database'):
        settings[name]['port'] = port(settings[name]['port'], f'{name}.port')
    default_workspace = settings['web']['default_workspace']
    if default_workspace is not None:
        text_value(default_workspace, 'web.default_workspace')
    settings['database']['project'] = compose_name(settings['database']['project'])
    mode = settings['server']['execution_mode']
    if mode not in ('production', 'exploration'):
        raise ValueError('server.execution_mode must be production or exploration')
    registry['config_version'] = CONFIG_VERSION
    registry['dsh'] = template['dsh']
    validate_providers(registry)
    return registry, local, environment


def _secret(credentials, field, size):
    if not credentials.get(field):
        credentials[field] = secrets.token_urlsafe(size)
    return text_value(credentials[field], field)


def _token(config, name, credentials):
    field = name + '_token_env'
    if config.get(field):
        env_name(config[field], 'server.' + field)
        config.pop(name + '_token', None)
    else:
        config.pop(field, None)
        config[name + '_token'] = _secret(credentials, name + '_token', 32)


def _service_url(server):
    if server.get('service_url'):
        return text_value(server['service_url'], 'server.service_url')
    host = text_value(server['service_host'], 'server.service_host').strip('[]')
    if host in ('0.0.0.0', '::'):
        host = '127.0.0.1'
    if ':' in host:
        host = f'[{host}]'
    return f"http://{host}:{server['port']}"


def _database_projection(database, environment, credentials):
    name = database.get('url_env')
    url = database.get('url')
    if url and name:
        raise ValueError('Configure database.url or database.url_env, not both')
    managed = database_is_managed(database)
    resolved = {}
    env = {MANAGED_MARKER: 'true' if managed else 'false',
           'COMPOSE_PROJECT_NAME': database['project'], 'POSTGRES_PORT': str(database['port'])}
    if not managed and name:
        name = env_name(name, 'database.url_env')
        if name in {MANAGED_MARKER, *DATABASE_SETTINGS}:
            raise ValueError('database.url_env conflicts with a managed database setting')
        resolved['database_url_env'] = name
    elif not managed:
        resolved['database_url'] = text_value(url, 'database.url')
    else:
        user = text_value(database['user'], 'database.user')
        db_name = text_value(database['name'], 'database.name')
        password_env = database.get('password_env')
        if password_env is not None:
            password_env = env_name(password_env, 'database.password_env')
            password = environment.get(password_env)
            if not password:
                raise ValueError(f'database.password_env references unset variable {password_env}')
            password = text_value(password, 'database password')
        else:
            password = _secret(credentials, 'database_password', 24)
        resolved['database_url_env'] = MANAGED_URL
        env.update(POSTGRES_USER=user, POSTGRES_DB=db_name, POSTGRES_PASSWORD=password)
        env[MANAGED_URL] = (
            f'postgresql+psycopg://{quote(user, safe="")}:{quote(password, safe="")}@127.0.0.1:'
            f"{database['port']}/{quote(db_name, safe='')}"
        )
    return resolved, env


def _worker_projection(config, server, environment, credentials, config_dir):
    profile = dict(config['worker'])
    isaac = isaac_config(config)
    for key, projected in ISAAC_WORKER_KEYS.items():
        if key in isaac:
            profile.setdefault(projected, isaac[key])
    if profile.get('isaac_mode') == 'local':
        profile['isaac_local'] = dict(profile['isaac_local'])
        _resolve_paths(profile['isaac_local'], ('asset_root',), config_dir, environment)
        # Keep the local interpreter or launcher path exactly as selected, including venv symlinks.
        python = Path(expand_environment(profile['isaac_local']['python'], environment)).expanduser()
        profile['isaac_local']['python'] = os.path.abspath(config_dir / python)
    _resolve_paths(profile, (*WORKER_PATHS, 'service_config'), config_dir, environment)
    reference = profile.get('service_config')
    if not reference:
        profile.setdefault('url', server['service_url'])
        profile.setdefault('ssh_forward', f"{server['port']}:127.0.0.1:{server['port']}")
        if not profile.get('worker_token_env'):
            if server.get('worker_token_env'):
                profile['worker_token_env'] = server['worker_token_env']
            else:
                profile['worker_token'] = server['worker_token']
    if (profile.get('worker_token_env') == 'BENCHFORGE_WORKER_OVERRIDE_TOKEN'
            and credentials.get('worker_override_token')):
        profile.pop('worker_token_env')
        profile['worker_token'] = credentials['worker_override_token']
    for key in ('operator_token', 'operator_token_env', 'database_url', 'database_url_env',
                'database', 'models_config'):
        profile.pop(key, None)
    return profile


def sync_configuration(config, generated, server_path, state, *, overrides=None):
    path = config / 'benchforge.local.json'
    credentials_path = state / 'credentials.local.json'
    with projection_lock(generated):
        value, previous_value, environment = read_configuration(config, overrides=overrides)
        stored_credentials = read_object(credentials_path, optional=True)
        credentials = dict(stored_credentials)
        for scope, fields in (
            ('server', {'operator_token': 'operator_token', 'worker_token': 'worker_token'}),
            ('client', {'operator_token': 'client_operator_token'}),
            ('worker', {'worker_token': 'worker_override_token'}),
        ):
            for field, key in fields.items():
                token = value[scope].pop(field, None)
                if token is not None:
                    credentials[key] = text_value(token, scope + '.' + field)
                    if scope != 'server' and not value[scope].get(field + '_env'):
                        value[scope][field + '_env'] = 'BENCHFORGE_' + key.upper()
        server = dict(value['server'])
        if server.get('scene_policy_path') is None and server['execution_mode'] == 'production':
            raise ValueError('server.scene_policy_path is required in production mode')
        _resolve_paths(server, SERVER_PATHS, config, environment)
        if 'task_root' not in server:
            server['task_root'] = str(Path(server['artifacts']) / 'operator_workspaces')
        server['service_url'] = _service_url(server)
        for name in API_NAMES:
            _token(server, name, credentials)
        server['models_config'] = Path(os.path.relpath(path, server_path.parent)).as_posix()
        db_file = generated / 'database.env'
        database, database_env = _database_projection(value['database'], environment, credentials)
        server.update(database)

        client = dict(value['client'])
        _resolve_paths(client, CLIENT_PATHS, config, environment)
        if not (client.get('service_config') or client.get('service_url')):
            client['service_config'] = Path(os.path.relpath(server_path, generated)).as_posix()
        if (client.get('operator_token_env') == 'BENCHFORGE_CLIENT_OPERATOR_TOKEN'
                and credentials.get('client_operator_token')):
            client.pop('operator_token_env')
            client['operator_token'] = credentials['client_operator_token']

        worker = _worker_projection(value, server, environment, credentials, config)
        policy = server.get('scene_policy_path')
        default_policy = generated / 'scene-library/policy.json'
        if policy and Path(policy) == default_policy.resolve() and not default_policy.exists():
            write(default_policy, DEFAULT_POLICY)
        if credentials and credentials != stored_credentials:
            write(credentials_path, credentials)
        write(server_path, server)
        write(generated / CLIENT_CONFIG, client)
        write(generated / 'worker.local.json', worker)
        write_text(db_file, ''.join(f'{key}={item}\n' for key, item in database_env.items()))
        saved = {
            key: item for key, item in value.items() if key not in SECTIONS
        }
        for name in SECTIONS:
            previous_section = previous_value.get(name, {})
            section = {
                key: item for key, item in value[name].items()
                if key in previous_section
                or key in (overrides or {}).get(name, {})
                or item != DEPLOYMENT_DEFAULTS[name].get(key)
            }
            if section and name == 'server':
                for key in ('operator_token_env', 'worker_token_env'):
                    if section.get(key) is None:
                        section.pop(key, None)
            if section and name == 'database':
                for key in ('url', 'url_env', 'password_env'):
                    if section.get(key) is None:
                        section.pop(key, None)
            if section:
                saved[name] = section
        if saved != previous_value or not path.exists():
            write(path, saved)
    return value
