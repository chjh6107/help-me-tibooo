const { test } = require('node:test');
const assert = require('node:assert/strict');

const invoke = async (options = {}) => {
  const continueWatch = require('../.github/scripts/continue-watch.cjs');
  const calls = [];
  const logs = [];
  const waits = [];
  let listings = 0;
  let dispatches = 0;
  let workflowReads = 0;
  const context = {
    repo: { owner: 'owner', repo: 'repo' }, ref: options.ref || 'refs/heads/main',
    runId: 42,
    payload: { repository: { default_branch: 'main', private: options.private || false } },
  };
  const github = { rest: { actions: {
    listWorkflowRuns: async (args) => {
      const runs = options.listRuns ? await options.listRuns(++listings, args) : options.runs || [];
      return { data: { workflow_runs: runs } };
    },
    getWorkflow: async () => ({ data: { state:
      options.disabled || (options.disableAfterDispatch && workflowReads++ > 0)
        ? 'disabled_manually' : 'active' } }),
    getActionsCacheList: async (args) => {
      calls.push(['cache', args]);
      if (options.cacheError) throw new Error('cache lookup failed');
      if (options.cacheFailure) await options.cacheFailure();
      return { data: { total_count: 1, actions_caches: options.missing ? [] : [
        { key: options.key || 'help-me-tibooo-state-42-1', ref: options.cacheRef || 'refs/heads/main', id: 10 },
      ] } };
    },
    createWorkflowDispatch: async (args) => {
      calls.push(['dispatch', args]);
      if (options.dispatch) await options.dispatch(++dispatches);
    },
  } } };
  await continueWatch({ github, context, core: { info: (s) => logs.push(s) },
    cacheKey: 'help-me-tibooo-state-42-1', wait: async (ms) => { waits.push(ms); } });
  return { calls, logs, waits };
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

for (const status of ['queued', 'pending', 'waiting', 'requested', 'in_progress']) {
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

const apiError = (status, message = 'Unexpected end of JSON input') =>
  Object.assign(new Error(message), { status });
const loop = (id = 43, status = 'queued') => ({
  id, display_title: 'Tibo watcher (watch-loop)', head_branch: 'main', status,
});
const dispatchCount = ({ calls }) => calls.filter(([kind]) => kind === 'dispatch').length;

for (const status of [500, 502, 503, 504]) {
  test(`recovers from HTTP ${status} only after three empty reconciliation reads`, async () => {
    let reads = 0;
    const result = await invoke({
      listRuns: async () => { reads += 1; return []; },
      dispatch: async (attempt) => {
        if (attempt === 1) throw apiError(status);
        assert.equal(reads, 4);
      },
    });
    assert.equal(dispatchCount(result), 2);
    assert.deepEqual(result.waits, [2000, 5000, 10000]);
  });
}

for (const status of ['queued', 'pending', 'waiting', 'requested', 'in_progress', 'completed']) {
  test(`lost response with a delayed ${status} successor does not dispatch twice`, async () => {
    const result = await invoke({
      dispatch: async () => { throw Object.assign(new Error('socket hang up'), { code: 'ECONNRESET' }); },
      listRuns: async (read) => read < 3 ? [] : [loop(43, status)],
    });
    assert.equal(dispatchCount(result), 1);
    assert.deepEqual(result.waits, [2000, 5000]);
  });
}

test('HTTP 500 may still have created a successor', async () => {
  assert.equal(dispatchCount(await invoke({
    dispatch: async () => { throw apiError(500); },
    listRuns: async (read) => read === 1 ? [] : [loop()],
  })), 1);
});

test('checks for an accepted dispatch even after the final attempt', async () => {
  assert.equal(dispatchCount(await invoke({
    dispatch: async () => { throw apiError(500); },
    listRuns: async (read) => read === 8 ? [loop()] : [],
  })), 3);
});

test('persistent 5xx failures stop after three dispatches and report failure', async () => {
  let attempts = 0;
  let reads = 0;
  await assert.rejects(invoke({
    dispatch: async () => { attempts += 1; throw apiError(500); },
    listRuns: async () => { reads += 1; return []; },
  }), /Unexpected end of JSON input/);
  assert.equal(attempts, 3);
  assert.equal(reads, 10);
});

for (const status of [400, 401, 403, 404, 422, 429]) {
  test(`does not retry HTTP ${status}`, async () => {
    let attempts = 0;
    await assert.rejects(invoke({ dispatch: async () => {
      attempts += 1; throw apiError(status);
    } }), /Unexpected end of JSON input/);
    assert.equal(attempts, 1);
  });
}

test('reconciliation lookup failure prevents a second uncertain dispatch', async () => {
  let attempts = 0;
  let reads = 0;
  await assert.rejects(invoke({
    dispatch: async () => { attempts += 1; throw apiError(500); },
    listRuns: async () => {
      if (++reads > 1) throw apiError(503, 'lookup unavailable');
      return [];
    },
  }), /lookup unavailable/);
  assert.equal(attempts, 1);
  assert.equal(reads, 4);
});

test('transient lookup failure is retried before reconciling the successor', async () => {
  assert.equal(dispatchCount(await invoke({
    dispatch: async () => { throw apiError(500); },
    listRuns: async (read) => {
      if (read === 2) throw apiError(502);
      return read > 2 ? [loop()] : [];
    },
  })), 1);
});

test('cache lookup recovers from 5xx without bypassing exact saved-cache verification', async () => {
  let attempts = 0;
  assert.equal(dispatchCount(await invoke({ cacheFailure: async () => {
    if (++attempts === 1) throw apiError(503);
  } })), 1);
  assert.equal(attempts, 2);
});

test('workflow disabled during recovery stops the chain', async () => {
  assert.equal(dispatchCount(await invoke({
    disableAfterDispatch: true,
    dispatch: async () => { throw apiError(500); },
  })), 1);
});

test('old completed runs and new diagnostics/feature runs do not count as recovery', async () => {
  assert.equal(dispatchCount(await invoke({
    dispatch: async (attempt) => { if (attempt === 1) throw apiError(500); },
    listRuns: async () => [loop(39, 'completed'), loop(42, 'in_progress'),
      { ...loop(43), head_branch: 'feature' },
      { ...loop(44), display_title: 'Tibo watcher (smoke)' }],
  })), 2);
});

test('paginates to find an existing loop beyond the first page', async () => {
  assert.equal(dispatchCount(await invoke({ listRuns: async (_, { page }) =>
    page === 1 ? Array.from({ length: 100 }, (_, i) => loop(100 + i, 'completed')) : [loop()],
  })), 0);
});

test('unclassified programming errors are not retried', async () => {
  let attempts = 0;
  await assert.rejects(invoke({ dispatch: async () => {
    attempts += 1; throw new TypeError('bad argument');
  } }), /bad argument/);
  assert.equal(attempts, 1);
});

for (const error of [
  Object.assign(new Error('request timed out'), { status: 0, code: 'ETIMEDOUT' }),
  new SyntaxError('Unexpected end of JSON input'),
  new TypeError('fetch failed', { cause: { code: 'UND_ERR_SOCKET' } }),
]) {
  test(`recovers from response loss: ${error.message}`, async () => {
    assert.equal(dispatchCount(await invoke({ dispatch: async (attempt) => {
      if (attempt === 1) throw error;
    } })), 2);
  });
}

test('initial lookup exhaustion does not dispatch', async () => {
  let attempts = 0;
  let reads = 0;
  await assert.rejects(invoke({
    dispatch: async () => { attempts += 1; },
    listRuns: async () => { reads += 1; throw apiError(503); },
  }), /Unexpected end of JSON input/);
  assert.equal(attempts, 0);
  assert.equal(reads, 3);
});

test('can recover on the third and final dispatch attempt', async () => {
  assert.equal(dispatchCount(await invoke({ dispatch: async (attempt) => {
    if (attempt < 3) throw apiError(503);
  } })), 3);
});
