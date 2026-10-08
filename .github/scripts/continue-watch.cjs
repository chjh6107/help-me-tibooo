const { setTimeout: sleep } = require('node:timers/promises');

const retryable = (error) => {
  const status = Number(error.status);
  return (status >= 500 && status <= 599) ||
    ((!error.status || status === 0) && (
      ['ECONNRESET', 'ETIMEDOUT', 'ECONNABORTED', 'EPIPE', 'ENOTFOUND', 'EAI_AGAIN',
        'UND_ERR_SOCKET', 'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_HEADERS_TIMEOUT']
        .includes(error.code || error.cause?.code) ||
      ['AbortError', 'TimeoutError', 'SyntaxError'].includes(error.name) ||
      /fetch failed|socket hang up|Unexpected end of JSON input/i.test(error.message)
    ));
};

module.exports = async ({ github, context, core, cacheKey, wait = sleep }) => {
  const defaultBranch = context.payload.repository.default_branch;
  if (context.ref !== `refs/heads/${defaultBranch}` || context.payload.repository.private) {
    core.info('기본 브랜치의 공개 저장소에서만 감시를 연결합니다.');
    return;
  }
  // Reads are safe to retry. Dispatches need reconciliation before another POST.
  const read = async (request) => {
    for (let attempt = 0; ; attempt += 1) {
      try { return await request(); } catch (error) {
        if (!retryable(error) || attempt === 2) throw error;
        core.info(`GitHub API 조회 재시도 ${attempt + 1}/2`);
        await wait([2000, 5000][attempt]);
      }
    }
  };
  const active = async () => {
    const workflow = await read(() => github.rest.actions.getWorkflow({
      ...context.repo, workflow_id: 'watch.yml',
    }));
    if (workflow.data.state === 'active') return true;
    core.info('감시 workflow가 비활성화되어 연결을 중지합니다.');
    return false;
  };
  if (!await active()) return;
  const caches = await read(() => github.rest.actions.getActionsCacheList({
    ...context.repo, key: cacheKey, ref: context.ref,
  }));
  if (!caches.data.actions_caches.some((cache) => cache.key === cacheKey && cache.ref === context.ref)) {
    throw new Error('이번 실행의 상태 캐시 저장을 확인하지 못했습니다.');
  }
  const listRuns = async () => {
    const runs = [];
    for (let page = 1; ; page += 1) {
      const result = await read(() => github.rest.actions.listWorkflowRuns({
        ...context.repo, workflow_id: 'watch.yml', branch: defaultBranch, per_page: 100, page,
      }));
      runs.push(...result.data.workflow_runs);
      if (result.data.workflow_runs.length < 100) return runs;
    }
  };
  const isLoop = (run) =>
    run.id !== context.runId && run.head_branch === defaultBranch &&
    run.display_title === 'Tibo watcher (watch-loop)';
  const isLive = (run) =>
    ['queued', 'pending', 'waiting', 'requested', 'in_progress'].includes(run.status);
  const initialRuns = await listRuns();
  if (initialRuns.some((run) => isLoop(run) && isLive(run))) {
    core.info('이미 대기 중인 반복 감시가 다음 세션을 이어갑니다.');
    return;
  }
  const initialIds = new Set(initialRuns.map((run) => run.id));
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    if (attempt > 1 && !await active()) return;
    try {
      await github.rest.actions.createWorkflowDispatch({
        ...context.repo, workflow_id: 'watch.yml', ref: defaultBranch,
        inputs: { mode: 'watch-loop' },
      });
      core.info('상태 캐시 저장 확인 완료 · 다음 반복 감시 실행 요청 완료');
      return;
    } catch (error) {
      if (!retryable(error)) throw error;
      core.info(`다음 실행 요청 결과 불확실 (${attempt}/3) · 기존 실행 재조회`);
      // Allow eventual visibility, including a run that already started/finished.
      // A failed lookup throws: never blindly repeat an uncertain dispatch.
      for (const delay of [2000, 5000, 10000]) {
        await wait(delay);
        const runs = await listRuns();
        if (runs.some((run) => isLoop(run) && (isLive(run) || !initialIds.has(run.id)))) {
          core.info('기존 반복 감시 실행 확인 · 추가 요청을 생략합니다.');
          return;
        }
      }
      if (attempt === 3) throw error;
      core.info('기존 실행 없음 · 다음 반복 감시 요청을 재시도합니다.');
    }
  }
};
