const { test } = require('node:test');
const assert = require('node:assert/strict');

const invoke = async (options = {}) => {
  const continueWatch = require('../.github/scripts/continue-watch.cjs');
  const calls = [];
  const logs = [];
  const context = {
    repo: { owner: 'owner', repo: 'repo' }, ref: options.ref || 'refs/heads/main',
    runId: 42,
    payload: { repository: { default_branch: 'main', private: options.private || false } },
  };
  const github = { rest: { actions: {
    listWorkflowRuns: async () => ({ data: { total_count: 1, workflow_runs: options.runs || [] } }),
    getWorkflow: async () => ({ data: { state: options.disabled ? 'disabled_manually' : 'active' } }),
    getActionsCacheList: async (args) => {
      calls.push(['cache', args]);
      if (options.cacheError) throw new Error('cache lookup failed');
      return { data: { total_count: 1, actions_caches: options.missing ? [] : [
        { key: options.key || 'help-me-tibooo-state-42-1', ref: options.cacheRef || 'refs/heads/main', id: 10 },
      ] } };
    },
    createWorkflowDispatch: async (args) => { calls.push(['dispatch', args]); },
  } } };
  await continueWatch({ github, context, core: { info: (s) => logs.push(s) },
    cacheKey: 'help-me-tibooo-state-42-1' });
  return { calls, logs };
};

test('dispatches one default-branch loop only after verifying the saved cache', async () => {
  const { calls } = await invoke();
  assert.deepEqual(calls, [
    ['cache', { owner: 'owner', repo: 'repo', key: 'help-me-tibooo-state-42-1', ref: 'refs/heads/main' }],
    ['dispatch', { owner: 'owner', repo: 'repo', workflow_id: 'watch.yml', ref: 'main', inputs: { mode: 'watch-loop' } }],
  ]);
});

for (const [label, options] of [
  ['missing cache', { missing: true }],
  ['previous key', { key: 'help-me-tibooo-state-41-1' }],
  ['different cache branch', { cacheRef: 'refs/heads/feature' }],
  ['API failure', { cacheError: true }],
]) {
  test(`does not dispatch with ${label}`, async () => {
    await assert.rejects(invoke(options), options.cacheError ? /cache lookup failed/ : /상태 캐시 저장/);
  });
}

for (const [label, options] of [
  ['feature branch', { ref: 'refs/heads/feature' }],
  ['disabled workflow', { disabled: true }],
  ['private repository', { private: true }],
]) {
  test(`does not start a chain for ${label}`, async () => {
    const { calls } = await invoke(options);
    assert.equal(calls.filter(([kind]) => kind === 'dispatch').length, 0);
  });
}

for (const status of ['queued', 'pending', 'waiting', 'requested']) {
  test(`keeps the existing ${status} default-branch loop instead of adding a chain`, async () => {
    const { calls } = await invoke({ runs: [{ id: 43, display_title: 'Tibo watcher (watch-loop)', head_branch: 'main', status }] });
    assert.equal(calls.filter(([kind]) => kind === 'dispatch').length, 0);
  });
}

test('completed loops, feature loops, and diagnostics do not prevent the next production loop', async () => {
  const { calls } = await invoke({ runs: [
    { id: 39, display_title: 'Tibo watcher (watch-loop)', head_branch: 'main', status: 'completed' },
    { id: 40, display_title: 'Tibo watcher (watch-loop)', head_branch: 'feature', status: 'queued' },
    { id: 41, display_title: 'Tibo watcher (smoke)', head_branch: 'main', status: 'queued' },
    { id: 42, display_title: 'Tibo watcher (watch-loop)', head_branch: 'main', status: 'in_progress' },
  ] });
  assert.equal(calls.filter(([kind]) => kind === 'dispatch').length, 1);
});
