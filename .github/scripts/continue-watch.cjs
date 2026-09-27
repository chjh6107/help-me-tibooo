module.exports = async ({ github, context, core, cacheKey }) => {
  const defaultBranch = context.payload.repository.default_branch;
  if (context.ref !== `refs/heads/${defaultBranch}` || context.payload.repository.private) {
    core.info('기본 브랜치의 공개 저장소에서만 감시를 연결합니다.');
    return;
  }
  const workflow = await github.rest.actions.getWorkflow({
    ...context.repo, workflow_id: 'watch.yml',
  });
  if (workflow.data.state !== 'active') {
    core.info('감시 workflow가 비활성화되어 연결을 중지합니다.');
    return;
  }
  const caches = await github.rest.actions.getActionsCacheList({
    ...context.repo, key: cacheKey, ref: context.ref,
  });
  if (!caches.data.actions_caches.some((cache) => cache.key === cacheKey && cache.ref === context.ref)) {
    throw new Error('이번 실행의 상태 캐시 저장을 확인하지 못했습니다.');
  }
  await github.rest.actions.createWorkflowDispatch({
    ...context.repo, workflow_id: 'watch.yml', ref: defaultBranch,
    inputs: { mode: 'watch-loop' },
  });
  core.info('상태 캐시 저장 확인 완료 · 다음 반복 감시 실행 요청 완료');
};
