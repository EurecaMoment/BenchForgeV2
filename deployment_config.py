"""Migrate and project the operator's BenchForgeV2 deployment configuration."""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import shlex
import tempfile
from urllib.parse import quote, unquote, urlsplit

from spatialforge.model_configuration import initialize_model_config
from spatialforge.runtime_config import expand_environment, read_json


SECTIONS = ('web', 'server', 'database', 'client', 'worker')
SERVER_PATHS = ('artifacts', 'harness', 'task_root', 'scene_policy_path')
CLIENT_PATHS = (*SERVER_PATHS, 'models_config', 'service_config')
WORKER_PATHS = ('isaac_asset_root', 'runs', 'ssh_config', 'asset_cache')
ISAAC_WORKER_KEYS = {
    'grpc': 'isaac_grpc',
    'isaac_asset_root': 'isaac_asset_root',
    'runs': 'runs',
    'capture_timeout_seconds': 'capture_timeout_seconds',
}
OLD_WORKER_KEYS = (
    'isaac_mode', 'isaac_root', 'isaac_python', 'isaac_remote', 'isaac_rpc',
    'isaac_resident', 'isaac_idle_seconds',
)
MODEL_FIELDS = ('model_url', 'model_id', 'model_api_key_env')
MANAGED_MARKER = 'BENCHFORGE_DATABASE_MANAGED'
MANAGED_URL = 'SPATIALFORGE_DATABASE_URL'
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


def _rebase_paths(values, fields, source, target):
    for field in fields:
        value = values.get(field)
        if not isinstance(value, str) or not value:
            continue
        path = Path(value)
        if path.is_absolute() or PureWindowsPath(value).is_absolute() or value.startswith('~'):
            continue
        try:
            values[field] = Path(os.path.relpath(source / path, target)).as_posix()
        except ValueError:
            values[field] = str(source / path)


def _resolve_paths(values, fields, directory, environment):
    for field in fields:
        if values.get(field):
            values[field] = _file_path(values[field], directory, environment)


def _managed_parts(url):
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
        if (parts.scheme == 'postgresql+psycopg' and parts.hostname in {'127.0.0.1', 'localhost'}
                and parts.username == 'spatialforge' and parts.path == '/spatialforge'
                and not parts.query and not parts.fragment):
            return parts.port or 5432, unquote(parts.password or '')
    except ValueError:
        pass
    return None


def database_is_managed(database):
    return not (database.get('url') or database.get('url_env'))


def _old_database(server, saved, environment):
    name = server.get('database_url_env')
    url = ((environment.get(name) or saved.get(name)) if name
           else server.get('database_url') or saved.get(MANAGED_URL))
    local = _managed_parts(url)
    values = {}
    password = saved.get('POSTGRES_PASSWORD')
    managed = bool(local and local[1] and (
        password == local[1] or (not password and name is None)
    )) or bool(not url and password and name in (None, MANAGED_URL))
    if name and not managed:
        values['url_env'] = name
    elif url and not managed:
        values['url'] = url
    if managed and local:
        values['port'] = local[0]
        password = password or local[1]
    if saved.get('POSTGRES_PORT'):
        values['port'] = port(saved['POSTGRES_PORT'], 'database.port')
    if saved.get('COMPOSE_PROJECT_NAME'):
        values['project'] = saved['COMPOSE_PROJECT_NAME']
    return values, password


def _legacy_profile(path, fallback):
    candidate = path if path.is_file() else fallback
    return candidate, read_object(candidate, optional=True)


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


def _legacy_settings(config, generated, server_path, environment):
    server_path, server = _legacy_profile(server_path, config / server_path.name)
    db_env = server_path.with_name('database.env')
    if not db_env.is_file():
        db_env = generated / 'database.env'
    saved = read_env(db_env)
    database, password = _old_database(server, saved, environment)

    old_paths = {
        server_path.resolve(),
        (config / 'spatialforge-server.local.json').resolve(),
        (generated / 'spatialforge-server.local.json').resolve(),
    }
    model_source = dict(server)
    if not model_source.get('models_config'):
        models = next((path for path in (generated / 'models.local.json', config / 'models.local.json')
                       if path.is_file()), None)
        if models:
            model_source['models_config'] = str(models)
    for field in ('models_config', 'service_config', 'database_url', 'database_url_env', *MODEL_FIELDS):
        server.pop(field, None)
    credentials = {}
    for name in API_NAMES:
        token = server.pop(f'{name}_token', None)
        if token:
            credentials[f'{name}_token'] = token
    if password:
        credentials['database_password'] = password
    legacy_url_name = database.get('url_env')
    if legacy_url_name and saved.get(legacy_url_name):
        credentials['legacy_database_urls'] = {legacy_url_name: saved[legacy_url_name]}
    _rebase_paths(server, SERVER_PATHS, server_path.parent, config)

    profiles = {}
    worker_isaac = {}
    shared_isaac = read_object(config / 'benchforge.local.json', optional=True).get('isaac') or {}
    legacy_port = port(server.get('port', 3841), 'server.port')
    legacy_loopback = f'http://127.0.0.1:{legacy_port}'
    for name, filename, path_fields in (
        ('client', 'spatialforge.local.json', CLIENT_PATHS),
        ('worker', 'worker.local.json', (*WORKER_PATHS, 'service_config')),
    ):
        path, profile = _legacy_profile(generated / filename, config / filename)
        reference = profile.get('service_config')
        local_reference = reference and _file_path(reference, path.parent, environment) in {str(p) for p in old_paths}
        if local_reference:
            profile.pop('service_config')
        if name == 'worker':
            for field in OLD_WORKER_KEYS:
                profile.pop(field, None)
            if profile.get('ssh_host') == 'user@server':
                profile.pop('ssh_host')
            grpc = profile.pop('isaac_grpc', None)
            if grpc:
                worker_isaac['grpc'] = grpc
            if local_reference:
                if profile.get('url') == legacy_loopback:
                    profile.pop('url')
                if profile.get('ssh_forward') == f'{legacy_port}:127.0.0.1:{legacy_port}':
                    profile.pop('ssh_forward')
            timeout = profile.get('capture_timeout_seconds')
            if timeout == shared_isaac.get('capture_timeout_seconds') or (
                    'capture_timeout_seconds' not in shared_isaac and timeout == 1800):
                profile.pop('capture_timeout_seconds', None)
            token = profile.pop('worker_token', None)
            if token:
                credentials['worker_override_token'] = token
                if not profile.get('worker_token_env'):
                    profile['worker_token_env'] = 'BENCHFORGE_WORKER_OVERRIDE_TOKEN'
        else:
            token = profile.pop('operator_token', None)
            if token:
                credentials['client_operator_token'] = token
                if not profile.get('operator_token_env'):
                    profile['operator_token_env'] = 'BENCHFORGE_CLIENT_OPERATOR_TOKEN'
        _rebase_paths(profile, path_fields, path.parent, config)
        profiles[name] = profile

    web = {}
    ports = read_env(config / 'ports.env', shell=True)
    for section, key in ((web, 'BENCHFORGE_WEB_PORT'), (server, 'SPATIALFORGE_PORT'),
                         (database, 'POSTGRES_PORT')):
        if ports.get(key):
            section['port'] = port(ports[key], key)
    return {'web': web, 'server': server, 'database': database, **profiles}, (
        server_path, model_source, worker_isaac, credentials
    )


def read_configuration(config, generated, server, *, overrides=None):
    template = config / 'benchforge.example.json'
    path = config / 'benchforge.local.json'
    local = read_object(path, optional=True)
    local_sections = _sections(local)
    version = local.get('config_version')
    if version is not None and (type(version) is not int or version != 1):
        raise ValueError('Unsupported BenchForgeV2 config_version')
    environment = {**read_env(config / 'dsh.env', shell=True), **os.environ}
    if version is None:
        settings, (legacy_server, model_source, worker_isaac, credentials) = _legacy_settings(
            config, generated, server, environment
        )
        registry = initialize_model_config(path, template, legacy_server, model_source,
                                           lambda *_: None)
        isaac = registry['isaac']
        if 'grpc' not in local.get('isaac', {}) and 'grpc' in worker_isaac:
            isaac['grpc'] = worker_isaac['grpc']
        for field in ('isaac_asset_root', 'runs'):
            value = local.get('isaac', {}).get(field)
            if value:
                settings['worker'][field] = value
    else:
        settings = {name: {} for name in SECTIONS}
        registry = deepcopy(local)
        credentials = {}

    defaults = read_object(template)
    for name, values in local_sections.items():
        # Runtime paths and credential references belong to the operator once
        # that section has been saved in the canonical file.
        settings[name].update(values)
        _inherit_defaults(settings[name], (overrides or {}).get(name, {}))
        _inherit_defaults(settings[name], defaults[name])
        registry[name] = settings[name]
    for name in ('web', 'server', 'database'):
        settings[name]['port'] = port(settings[name]['port'], f'{name}.port')
    settings['database']['project'] = compose_name(settings['database']['project'])
    mode = settings['server']['execution_mode']
    if mode not in ('production', 'exploration'):
        raise ValueError('server.execution_mode must be production or exploration')
    registry['config_version'] = 1
    return registry, local, credentials, environment


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


def _database_projection(database, environment, previous, credentials):
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
        if name in {MANAGED_MARKER, 'COMPOSE_PROJECT_NAME', 'POSTGRES_PORT', 'POSTGRES_PASSWORD'}:
            raise ValueError('database.url_env conflicts with a managed database setting')
        resolved['database_url_env'] = name
        # An old deployment can store a custom URL in generated/database.env.
        # Never reinterpret the just-generated managed URL as an external URI.
        saved_url = previous.get(name) if previous.get(MANAGED_MARKER) != 'true' else None
        saved_url = saved_url or credentials.get('legacy_database_urls', {}).get(name)
        if saved_url:
            env[name] = text_value(saved_url, 'legacy database URL')
    elif not managed:
        resolved['database_url'] = text_value(url, 'database.url')
    else:
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
        env['POSTGRES_PASSWORD'] = password
        env[MANAGED_URL] = (
            f'postgresql+psycopg://spatialforge:{quote(password, safe="")}@127.0.0.1:'
            f"{database['port']}/spatialforge"
        )
    return resolved, env


def _worker_projection(config, server, environment, credentials, config_dir):
    profile = dict(config['worker'])
    for key, projected in ISAAC_WORKER_KEYS.items():
        if key in config['isaac']:
            profile.setdefault(projected, config['isaac'][key])
    for key in OLD_WORKER_KEYS:
        profile.pop(key, None)
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
        value, previous_value, imported, environment = read_configuration(
            config, generated, server_path, overrides=overrides
        )
        stored_credentials = read_object(credentials_path, optional=True)
        credentials = {**imported, **stored_credentials}
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
        server['service_url'] = _service_url(server)
        for name in API_NAMES:
            _token(server, name, credentials)
        server['models_config'] = Path(os.path.relpath(path, server_path.parent)).as_posix()
        db_file = generated / 'database.env'
        database, database_env = _database_projection(value['database'], environment,
                                                       read_env(db_file), credentials)
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
        write(generated / 'spatialforge.local.json', client)
        write(generated / 'worker.local.json', worker)
        write_text(db_file, ''.join(f'{key}={item}\n' for key, item in database_env.items()))
        if value != previous_value or not path.exists():
            write(path, value)
    return value
