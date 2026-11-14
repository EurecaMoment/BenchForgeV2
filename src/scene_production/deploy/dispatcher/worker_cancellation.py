"""Acknowledge a canceled capture only after its remote executor has stopped."""


def finish_canceled_capture(job, job_id, client, api):
    remote = client.call('/jobs/'+job_id)
    if remote.get('status') not in ('succeeded','failed','canceled'):
        raise RuntimeError('Canceled capture executor has not finished')
    health = client.call('/health')
    if not isinstance(health.get('state'),dict) or 'active_job' not in health['state']:
        raise RuntimeError('Remote executor ownership could not be verified')
    if health['state']['active_job'] == job_id:
        raise RuntimeError('Canceled capture still owns the remote executor')
    identity = {key:job[key] for key in ('task_id','revision','token')}
    identity['transport_retry'] = job.get('transport_retry',0)
    return api('/worker/finish',{'job':identity,'outcome':'canceled','processes_stopped':True,
        'error':'Capture canceled after remote executor finished; local artifacts preserved'})
