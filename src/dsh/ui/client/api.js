export async function requestWorkbench(params, {body, signal} = {}) {
  const response = await fetch('api/benchforge/workbench?' + new URLSearchParams(params), {
    cache: 'no-store', credentials: 'same-origin', signal,
    ...(body === undefined ? {} : {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    }),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'HTTP ' + response.status);
  return value;
}

export function createApiHooks({React}) {
  function useRecord(params, revision, interval = 0, active = true) {
    const key = params ? new URLSearchParams(params).toString() : '';
    const [record, setRecord] = React.useState({key: '', value: null, error: null, loading: false});
    React.useEffect(() => {
      if (!key) return;
      let stopped = false, timer, controller, inFlight = false;
      const load = async () => {
        if (stopped || inFlight) return;
        inFlight = true;
        controller = new AbortController();
        const deadline = setTimeout(() => controller.abort(), 16000);
        setRecord((old) => old.key === key ? {...old, loading: !old.value, refreshing: true} :
          {key, value: null, error: null, loading: true, refreshing: true});
        try {
          const value = await requestWorkbench(key, {signal: controller.signal});
          if (!stopped) setRecord((old) => {
            if (value.scenes && old.key === key && old.value?.scenes) {
              const prior = old.value.scenes.runs || [];
              if (value.scenes.status === 'unavailable') value.scenes.runs = prior;
              else value.scenes.runs = (value.scenes.runs || []).map((row) => row.error
                ? {...(prior.find((previous) => previous.run_id === row.run_id) || row), error: row.error} : row);
            }
            return {key, value, error: null, loading: false, refreshing: false, updatedAt: new Date().toISOString()};
          });
        } catch (error) {
          if (!stopped) setRecord((old) => ({...old, key, error: error.message, loading: false, refreshing: false}));
        } finally {
          clearTimeout(deadline); inFlight = false;
          if (!stopped && interval && active && document.visibilityState !== 'hidden') timer = setTimeout(load, interval);
        }
      };
      const resume = () => {
        clearTimeout(timer);
        if (active && document.visibilityState !== 'hidden') load();
      };
      load();
      if (interval) document.addEventListener('visibilitychange', resume);
      return () => {stopped = true; clearTimeout(timer); controller?.abort(); document.removeEventListener('visibilitychange', resume);};
    }, [key, revision, interval, active]);
    return record.key === key ? record : {value: null, error: null, loading: Boolean(key)};
  }

  function usePanelVisible(ref) {
    const [visible, setVisible] = React.useState(false);
    React.useEffect(() => {
      const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
      observer.observe(ref.current);
      return () => observer.disconnect();
    }, []);
    return visible;
  }
  return {useRecord, usePanelVisible};
}
