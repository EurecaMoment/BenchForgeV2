"""Bind resumable local capture files to the frozen job without hashing media."""
import json
from capabilities.capture.capture_transfer import capture_identity
from capabilities.capture.capture_transfer import required_capture_files
from capabilities.capture.capture_transfer import validate_manifest


def require_frozen_request(job, request):
    if not isinstance(request, dict) or any(request.get(key) != job[key] for key in ('task_id','revision','token')):
        raise ValueError('local capture belongs to another frozen job')
    for key in ('program', 'capture_options', 'capture'):
        if request.get(key, {}) != job.get(key, {}):
            raise ValueError('local capture does not match the frozen '+key)


def require_capture_receipt(receipt, job):
    if not isinstance(receipt, dict) or receipt.get('job') != capture_identity(job):
        raise ValueError('capture recovery receipt belongs to another frozen job')
    for key in ('program', 'capture_options', 'capture'):
        expected = job.get(key, {}) if key != 'program' else job['program']
        if receipt.get(key) != expected:
            raise ValueError('capture recovery receipt does not match the frozen '+key)
    report = receipt.get('report', {})
    evidence = receipt.get('evidence', {})
    if (report.get('status') != 'captured' or report.get('token') != job['token'] or
            evidence.get('token') != job['token'] or evidence.get('origin') != 'isaac_native'):
        raise ValueError('capture recovery needs matching native report and evidence')
    files = validate_manifest(receipt.get('files'))
    names = {row['name'] for row in files if row['size'] > 0}
    if not set(required_capture_files(job['program'], report, job.get('capture_options'))).issubset(names):
        raise ValueError('capture recovery receipt has incomplete native files')
    return receipt


def local_capture_receipt(job, directory):
    """Return None for unfinished execution; only read required metadata and stat files."""
    report_path = directory/'capture'/'report.json'
    if not report_path.is_file():return None
    report = json.loads(report_path.read_text(encoding='utf8'))
    if report.get('status') != 'captured':return None
    request_path = directory/'request.json'
    if not request_path.is_file():
        raise ValueError('complete native capture is missing its frozen request')
    request = json.loads(request_path.read_text(encoding='utf8'))
    require_frozen_request(job, request)
    evidence_path = directory/'capture'/'evidence.json'
    if not evidence_path.is_file():return None
    evidence = json.loads(evidence_path.read_text(encoding='utf8'))
    files = []
    for name in required_capture_files(job['program'], report, job.get('capture_options')):
        path = directory/'capture'/name
        if not path.is_file() or not path.stat().st_size:return None
        stat = path.stat()
        files.append({'name':name, 'size':stat.st_size, 'mtime_ns':stat.st_mtime_ns})
    receipt = {'job':capture_identity(job), 'program':job['program'],
        'capture_options':job.get('capture_options', {}), 'capture':job.get('capture', {}),
        'report':{key:report[key] for key in ('status','token','scene_format','scene_resources','interaction') if key in report},
        'evidence':{key:evidence.get(key) for key in ('origin','token')}, 'files':files}
    require_capture_receipt(receipt, job)
    previous = job.get('capture_resume_receipt')
    if previous is not None and receipt != previous:
        raise ValueError('local capture changed after its frozen recovery receipt')
    return receipt
