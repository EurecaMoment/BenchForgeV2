export function createGalleryComponents({React, helpers}) {
  const h = React.createElement;
  const {status, button, card, empty, json, sceneName, questionText, planValue, planMarkdown,
  planMarkdownView, planEditInstruction, table, select, initialState, initialDemand, sceneConstraint,
  productionRequest, displayRef, filteredPage, useRecord, usePanelVisible, lifecycle,
  productionProductsRevision, sceneStage, pipelineForStage, sceneForStage, progressSceneForStage,
  registeredCollectionProgress, currentGeneration, sceneCollectionProgress, annotationProducts,
  stageState, recordedStageState,
  STAGES, PLAN_SECTIONS, PLAN_FIELDS, styles, dictionaries} = helpers;
  function PublicObservation({src, type = 'image/*', label, compact = false, t}) {
    const [record, setRecord] = React.useState({loading: type === 'application/json', data: null, error: ''});
    const [attempt, setAttempt] = React.useState(0);
    React.useEffect(() => {
      setRecord({loading: type === 'application/json', data: null, error: ''});
      if (type !== 'application/json') return;
      const controller = new AbortController();
      fetch(src, {signal: controller.signal}).then(async (response) => {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      }).then((data) => {if (!controller.signal.aborted) setRecord({loading: false, data, error: ''});})
        .catch((error) => {if (!controller.signal.aborted) setRecord({loading: false, data: null, error: error.message});});
      return () => controller.abort();
    }, [src, type, attempt]);
    return h('figure', {className: 'bfw-public-observation', 'data-observation-type': type, 'data-compact': compact},
      !compact && h('figcaption', null, label, type.startsWith('image/') && h('a',{href:src,target:'_blank',rel:'noopener noreferrer',className:'bfw-original-image'},'打开原图')),
      record.error ? h('div', {className: 'bfw-error', role: 'alert'}, t('observationReadFailed'), ' ' + record.error,
        button(t('retry'), () => setAttempt((value) => value + 1))) : type === 'application/json' ?
        record.loading ? empty(t('loading')) : json(record.data) : type.startsWith('image/') ?
          h('img', {className: 'bfw-observation', key: attempt, src, alt: label, loading: compact ? 'lazy' : undefined,
            onError: () => setRecord({loading: false, data: null, error: t('readFailed')})}) :
          h('p', {className: 'bfw-muted'}, t('unsupportedObservation')));
  }
  function firstImage(item) {
    const index = item.media_types ? item.media_types.findIndex((type) => type.startsWith('image/')) : 0;
    return item.media?.[index];
  }
  function QuestionDialog({item,close,t}) {
    const ref=React.useRef(null);
    const presentation=item.question_presentation;
    React.useEffect(()=>{
      const trigger=document.activeElement,dialog=ref.current;
      dialog.showModal();
      return ()=>{dialog.close();trigger?.focus();};
    },[]);
    const title='题目 '+(item.row_index+1);
    return h('dialog',{ref,className:'bfw-preview-dialog bfw-question-dialog','data-question-dialog':true,'aria-label':title,
      onCancel:event=>{event.preventDefault();close();},onClick:event=>{if(event.target===ref.current)close();}},
      h('div',{className:'bfw-preview-header'},h('h2',null,title),button(t('previewClose'),close)),
      h('p',{className:'bfw-question','data-question-stem':true},presentation?.stem || questionText(item.question)),
      presentation && [['context','已知条件'],['conditions','作答规则'],['options','选项']].map(([key,label])=>
        presentation[key]?.length > 0 && h('section',{key,className:'bfw-question-section','data-question-section':key},
          h('h3',null,label),h('ul',null,presentation[key].map((value,index)=>h('li',{key:index},value))))),
      presentation && h('p',{className:'bfw-question-response'},'作答方式：'+presentation.response),
      item.media?.length ? item.media.map((src,index)=>{
        const label=presentation?.media_labels?.[index] || t('media')+' '+(index+1);
        const observation=h(PublicObservation,{key:src,src,type:item.media_types?.[index],label,t});
        return item.media_types?.[index]==='application/json' ? h('details',{key:src},h('summary',null,label),observation) : observation;
      }) : empty(t('noMedia')),
      item.assets?.length > 0 && h('details',{'data-public-assets':true},
        h('summary',null,t('publicAssets')+' ('+item.assets.length+')'),
        h('ul',null,item.assets.map((src,index)=>h('li',{key:src},
          h('a',{href:src,target:'_blank',rel:'noreferrer'},item.asset_names?.[index] || t('publicAssets')+' '+(index+1)))))),
      h('details',null,h('summary',null,t('details')),json({...item,media:undefined,media_types:undefined})));
  }
  function sceneProjects(items) {
    const groups = new Map();
    for (const item of items.filter((row) => ['image', 'video'].includes(row.kind))) {
      const id = item.task_id || item.scene_id || 'scene';
      if (!groups.has(id)) groups.set(id, {id, title: item.scene_name || id, frames: [], video: null, kind: 'scene'});
      const project = groups.get(id);
      project.title=sceneName(project.title,groups.size-1);
      if (item.kind === 'video' && (!project.video || item.purpose === 'scene_tour')) project.video = item;
      else project.frames.push(item);
    }
    for (const project of groups.values()) project.frames.sort((a, b) => (a.file || a.title || '').localeCompare(b.file || b.title || '', undefined, {numeric: true}));
    return [...groups.values()];
  }
  function SceneGallery({items, preview, t}) {
    const projects = sceneProjects(items);
    if (!projects.length) return empty(t('artifactPending'));
    return h('div', {className: 'bfw-scene-projects'}, projects.map((project, index) => h('article', {
      className: 'bfw-preview-card bfw-scene-project', key: project.id, 'data-scene-project': project.id},
      h('button', {type: 'button', className: 'bfw-preview-open', onClick: () => preview(project),
        'aria-label': t('preview') + ' ' + t('sceneProject') + ' ' + (index + 1)},
        h('span', {className: 'bfw-scene-poster'}, project.video ? h('video', {src: project.video.url,
          poster: project.frames[0]?.url, preload: 'auto', muted: true, playsInline: true, 'aria-label': project.title}) :
          h('img', {src: project.frames[0].url, alt: project.title}),
          h('span', {className: 'bfw-scene-play', 'aria-hidden': true}, project.video ? '▶' : '↔')),
        h('strong', null, t('sceneProject') + ' ' + (index + 1)),
        h('span', {className: 'bfw-muted'}, t(project.video ? 'sceneTour' : 'sceneViews') + ' · ' + t('recordedViews') + ': ' + project.frames.length)),
      h('p', {className: 'bfw-code'}, displayRef(project.title)))));
  }
  function SceneVideo({project, t}) {
    const [view, setView] = React.useState(0);
    const [error, setError] = React.useState('');
    const [attempt, setAttempt] = React.useState(0);
    const videoUrl=project.video?.url || '';
    React.useEffect(() => {setError('');setView(0);}, [project.id, videoUrl]);
    const hasVideo=!!project.video && !error;
    const frameViews=project.frames.length ? h(React.Fragment, null,
      h('img', {src: project.frames[view]?.url, alt: project.title}),
      h('div', {className: 'bfw-pagination'}, button(t('previous'), () => setView((index) => index - 1), {disabled: view === 0}),
        h('span', null, t('sceneViews') + ' ' + (view + 1) + ' / ' + project.frames.length),
        button(t('nextPage'), () => setView((index) => index + 1), {disabled: view >= project.frames.length - 1}))) : null;
    return h('div', {className: 'bfw-scene-video'},
      error && h('div', {className: 'bfw-error', role: 'alert'},
        t('sceneVideoFailed'), ' ' + error, button(t('retry'), () => {setError(''); setAttempt((value) => value + 1);}),
        project.frames.length > 0 && h('span', {className: 'bfw-muted'}, ' · 已切换到实拍视角')),
      hasVideo ? h('video', {key: videoUrl + ':' + attempt, src: videoUrl, poster: project.frames[0]?.url, preload: 'auto',
        controls: true, autoPlay: true, loop: true, muted: true, playsInline: true,
        'aria-label': t('sceneTour'), onLoadedData: () => setError(''), onError: () => setError(t('artifactReadFailed'))}) : frameViews,
      h('p', {className: 'bfw-muted'}, t(project.video ? 'sceneTour' : 'sceneViews') + ' · ' + t('recordedViews') + ': ' + project.frames.length));
  }
  function SceneLibrary({record, selection, saving, error, choose, query, search, origin, filter, page, refresh, preview, t}) {
    const data = record.value;
    if (!data) return h('div', null, record.error ? h('p', {className: 'bfw-error', role: 'alert'}, record.error) : empty(t('loading')),
      button(t('retry'), refresh));
    const selected = selection?.selected || [];
    const busy = saving || record.loading;
    const changePage = (checked) => {
      const ids = new Set(data.items.map((row) => row.id));
      const kept = selected.filter((row) => !ids.has(row.id));
      choose(checked ? [...kept, ...data.items.filter((row) => row.available && row.production_eligible!==false).map((row) => ({id: row.id, revision: row.revision}))] : kept,
        selection.allow_new_scenes);
    };
    return h('section', {'data-scene-library': true},
      h('div', {className: 'bfw-toolbar'}, h('h3', null, t('sceneLibrary')),
        h('span', {className: 'bfw-pill'}, t('sceneSelected') + ': ' + selected.length + ' / ' + data.all),
        h('span', {className: 'bfw-muted', role: 'status', 'aria-live': 'polite'}, t(saving ? 'sceneSaving' : record.loading ? 'sceneLibraryLoading' : 'sceneSaved'))),

      h('div', {className: 'bfw-toolbar bfw-library-controls'},
        h('input', {className: 'bfw-input', type: 'search', 'aria-label': t('sceneSearch'), placeholder: t('sceneSearch'), value: query,
          onChange: (event) => search(event.target.value)}),
        select(t('sceneOrigin'), origin, filter, [['all', t('all')], ['current', t('currentScenes')], ['history', t('historyScenes')]]),
        button(t('selectScenePage'), () => changePage(true), {disabled: busy || !data.items.some((row) => row.available)}),
        button(t('clearScenePage'), () => changePage(false), {disabled: busy || !selected.length})),
      h('label', {className: 'bfw-consent bfw-library-policy'}, h('input', {type: 'checkbox', checked: !!selection?.allow_new_scenes,
        disabled: busy, onChange: (event) => choose(selected, event.target.checked)}), t('allowNewScenes')),
      h('small', {className: 'bfw-hint'}, t('sceneSelectionHelp')),
      selection?.notice && h('small', {className: 'bfw-hint', role: 'status'}, selection.notice),
      error && h('p', {className: 'bfw-error', role: 'alert'}, error),
      h('div', {className: 'bfw-scene-projects'}, data.items.map((row) => {
        const checked = selected.some((reference) => reference.id === row.id && reference.revision === row.revision);
        const name=sceneName(row.name,data.items.indexOf(row));
        const project = {...row, title: name, kind: 'scene', library: true};
        return h('article', {className: 'bfw-preview-card bfw-scene-project' + (checked ? ' bfw-scene-selected' : ''), key: row.id,
          'data-scene-project': row.id, 'data-scene-selected': String(checked)},
          h('label', {className: 'bfw-scene-select'}, h('input', {type: 'checkbox', checked, disabled: busy || !row.available || row.production_eligible===false,
            'aria-label': t('useScene') + ' ' + name, onChange: (event) => choose(event.target.checked
              ? [...selected.filter((reference) => reference.id !== row.id), {id: row.id, revision: row.revision}]
              : selected.filter((reference) => reference.id !== row.id), selection.allow_new_scenes)}), row.production_eligible===false ? '待物理与生活合理性验收' : t('useScene')),
          row.scene_style==='simplified_geometry' ? h('p', {className: 'bfw-muted'}, '简化几何实验 · ' + (row.geometry_purpose || '按计划测量')) : null,
          h('button', {type: 'button', className: 'bfw-preview-open', disabled: !row.available, onClick: () => preview(project),
            'aria-label': t('preview') + ' ' + name},
            h('span', {className: 'bfw-scene-poster'}, row.video ? h('video', {src: row.video.url, poster: row.frames[0]?.url,
              preload: 'metadata', muted: true, playsInline: true}) : row.frames.length ? h('img', {src: row.frames[0].url, alt: row.name, loading: 'lazy'}) :
                h('span', {className: 'bfw-muted'}, t('sceneUnavailable')),
              row.available && h('span', {className: 'bfw-scene-play', 'aria-hidden': true}, row.video ? '▶' : '↔')),
            h('strong', null, name), h('span', {className: 'bfw-muted'}, t(row.origin_session === selection?.session_id ? 'currentScenes' : 'historyScenes') +
              ' · ' + t('recordedViews') + ': ' + row.frame_count)),
          row.description ? h('details',null,h('summary',null,'场景摘要'),h('p',null,row.description)) : null,
          h('details',null,h('summary',null,'技术详情'),h('p', {className: 'bfw-code'}, row.id+' · 采集版本 '+row.revision)));
      })),
      !data.items.length && empty(t('noMatchingRuns')),
      h('div', {className: 'bfw-pagination'}, button(t('previous'), () => page(data.page - 1), {disabled: data.page <= 1}),
        h('span', null, t('page') + ' ' + data.page + ' / ' + data.pages + ' · ' + t('matches') + ': ' + data.total),
        button(t('nextPage'), () => page(data.page + 1), {disabled: data.page >= data.pages})),
      h('details', {className: 'bfw-library-location'}, h('summary', null, t('sceneStorage')),
        h('p', {className: 'bfw-code'}, data.catalog_path), h('p', {className: 'bfw-code'}, selection?.selection_path)));
  }
  function PreviewDialog({item, close, t}) {
    const ref = React.useRef(null);
    const [content, setContent] = React.useState(null);
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      const dialog = ref.current;
      const trigger = document.activeElement;
      dialog.showModal();
      return () => {dialog.close(); trigger?.focus();};
    }, []);
    React.useEffect(() => {
      if (item.data || !item.url || ['image', 'video'].includes(item.kind)) return;
      const controller = new AbortController();
      fetch(item.url, {signal: controller.signal}).then(async (response) => {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return item.kind === 'json' ? response.json() : response.text();
      }).then(setContent).catch((reason) => {if (reason.name !== 'AbortError') setError(reason.message);});
      return () => controller.abort();
    }, [item]);
    const data = item.data || content;
    return h('dialog', {ref, className: 'bfw-preview-dialog', 'aria-label': t('preview') + ' · ' + item.title,
      onCancel: (event) => {event.preventDefault(); close();}, onClick: (event) => {if (event.target === ref.current) close();}},
      h('div', {className: 'bfw-preview-header'}, h('h2', null, item.title), button(t('previewClose'), close)),
      item.kind === 'scene' ? h(SceneVideo, {project: item, t}) : item.kind === 'image' ? h('img', {src: item.url, alt: item.title}) : item.kind === 'video' ?
        h('video', {src: item.url, controls: true, preload: 'metadata'}) : error ? h('p', {role: 'alert'}, t('artifactReadFailed') + ' ' + error) :
        data ? h(React.Fragment, null,
          item.image_url && h('div', {className: 'bfw-annotation-image'}, h('img', {src: item.image_url, alt: item.title}),
            data.image_size?.width > 0 && h('svg', {viewBox: '0 0 ' + data.image_size.width + ' ' + data.image_size.height,
              role: 'img', 'aria-label': t('annotationGallery')}, (data.visible_objects || []).filter((row) => row.bbox_2d?.xyxy?.length === 4).map((row, index) => {
                const [x1, y1, x2, y2] = row.bbox_2d.xyxy;
                return h('g', {key: row.object_id || index}, h('rect', {x: x1, y: y1, width: x2 - x1, height: y2 - y1, fill: 'none', stroke: '#4ade80', strokeWidth: 2}),
                  h('text', {x: x1 + 4, y: Math.max(18, y1 - 5), fill: '#4ade80', stroke: '#102020', strokeWidth: .5,
                    fontSize: Math.max(14, data.image_size.width / 65)}, row.label || row.object_id));
              }))),
          typeof data === 'string' ? h('pre', {className: 'bfw-json'}, data) : h(React.Fragment,null,
            data.visible_objects?.length>0 && h('div',null,h('p',null,'可见物体：'+data.visible_objects.length+' · 图像标注与当前场景配对'),
              table(['物体','图像位置（像素）'],data.visible_objects.map((row,index)=>[row.label || '物体 '+(index+1),row.bbox_2d?.xyxy?.join(', ') || '—']))),
            h('details',null,h('summary',null,t('details')),json(data)))) : empty(t('loading')));
  }
  function ArtifactGallery({items, preview, t}) {
    if (!items.length) return empty(t('artifactPending'));
    return h('div', {className: 'bfw-gallery'}, items.map((saved,index) => {
      const view=(saved.file || saved.title || '').match(/view[_-](\d+)/);
      const kind=saved.image_url ? '标注' : saved.kind==='image' ? '场景图' : saved.kind==='video' ? '场景巡览' : '产物';
      const item={...saved,title:(view ? '视角 '+(Number(view[1])+1)+' · '+kind : saved.title || kind+' '+(index+1))};
      return h('article', {className: 'bfw-preview-card', key: item.url || item.title,
      'data-preview-kind': item.kind},
      h('button', {type: 'button', className: 'bfw-preview-open', onClick: () => preview(item), 'aria-label': t('preview') + ' ' + item.title},
        item.kind === 'image' || item.image_url ? h('img', {src: item.image_url || item.url, loading: 'lazy', alt: item.title}) : item.kind === 'video' ?
          h('video', {src: item.url, preload: 'metadata', muted: true, 'aria-label': item.title}) :
          h('div', {className: 'bfw-document-thumb'}, h('span', null, item.kind === 'json' ? '{ }' : '≡'), h('span', null, item.title)),
        h('strong', null, item.title), h('span', {className: 'bfw-muted'}, t('preview'))),
      item.task_id && h('details',null,h('summary',null,'技术详情'),h('div', {className: 'bfw-code bfw-muted'}, item.task_id + (item.revision === undefined ? '' : ' · r' + item.revision))));}));
  }
  return {PublicObservation, QuestionDialog, firstImage, sceneProjects, SceneGallery, SceneVideo, SceneLibrary, PreviewDialog, ArtifactGallery};
}
