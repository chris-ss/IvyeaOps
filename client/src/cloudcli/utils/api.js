import { IS_PLATFORM } from "../constants/config";

// 后端从 Node(:3002)全量重写为 ops 原生 FastAPI(/api/ccui/*),逐阶段 dogfood 切换。
// 已迁移并验证的路径前缀走原生后端(/api/ccui,同源 + opshub_session cookie 鉴权);
// 其余仍经 nginx /ccui-api 反代到 Node :3002,保持线上可用。每完成一个阶段就把对应前缀
// 加进 _MIGRATED;全部迁完后即彻底脱离 :3002。
// 已迁移到原生后端的路径前缀(P0)。
const _MIGRATED_PREFIXES = [
  '/api/auth',               // P0
  '/api/user',               // P0(onboarding / git-config)
  '/api/git',                // P4(status/diff/branches/commits/commit/checkout/push/pull/... )
  '/api/taskmaster',         // P7(tasks/prd/templates/init/add-task/parse-prd/update-task)
  '/api/settings',           // P8(credentials/notification-preferences/push 占位/api-keys)
  '/api/commands',           // P8(slash 命令 list/execute)
  '/api/mcp-utils',          // P8(taskmaster-server 探测)
  '/api/system',             // P8(system/update 占位)
];
// 单项目下已迁移的子路径(P1 会话管理 + P3 文件操作)。taskmaster→P7、clone-progress 未移植,仍走 Node。
const _MIGRATED_PROJECT_SUBS = new Set([
  'sessions', 'rename', 'toggle-star', 'restore',   // P1
  'file', 'files', 'upload-images',                 // P3
  'taskmaster',                                     // P7(GET /projects/{id}/taskmaster)
]);
const _isMigrated = (rawPath) => {
  const p = rawPath.split('?')[0];
  if (_MIGRATED_PREFIXES.some((pre) => p === pre || p.startsWith(pre + '/'))) return true;
  // P1 会话 + P6 provider(auth/models/skills/mcp) + 对话搜索 全部原生。
  if (p.startsWith('/api/providers/')) return true;
  if (p === '/api/projects' || p === '/api/projects/archived'
      || p === '/api/projects/create-project' || p === '/api/projects/migrate-legacy-stars') return true;
  if (p === '/api/browse-filesystem' || p === '/api/create-folder') return true;  // P3
  if (p === '/api/projects/clone-progress') return false;
  const m = p.match(/^\/api\/projects\/[^/]+\/(.+)$/);
  if (m) {
    const sub = m[1];
    if (_MIGRATED_PROJECT_SUBS.has(sub) || sub.startsWith('files/')) return true;  // P3: files/content|create|rename|upload
    if (/^sessions\/[^/]+\/token-usage$/.test(sub)) return true;  // P8: token-usage
    return false;  // clone-progress 等仍走 Node
  }
  if (/^\/api\/projects\/[^/]+$/.test(p)) return true;  // bare id (DELETE/archive)
  return false;
};
const _apiUrl = (path) =>
  _isMigrated(path)
    ? path.replace(/^\/api/, '/api/ccui')
    : path.replace(/^\/api/, '/ccui-api');

// Utility function for authenticated API calls
export const authenticatedFetch = (url, options = {}) => {
  url = _apiUrl(url);
  const token = localStorage.getItem('auth-token');

  const defaultHeaders = {};

  // Only set Content-Type for non-FormData requests
  if (!(options.body instanceof FormData)) {
    defaultHeaders['Content-Type'] = 'application/json';
  }

  if (!IS_PLATFORM && token) {
    defaultHeaders['Authorization'] = `Bearer ${token}`;
  }

  return fetch(url, {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  }).then((response) => {
    const refreshedToken = response.headers.get('X-Refreshed-Token');
    if (refreshedToken) {
      localStorage.setItem('auth-token', refreshedToken);
    }
    return response;
  });
};

// API endpoints
export const api = {
  // Auth endpoints (no token required)
  auth: {
    status: () => fetch(_apiUrl('/api/auth/status')),
    login: (username, password) => fetch(_apiUrl('/api/auth/login'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
    register: (username, password) => fetch(_apiUrl('/api/auth/register'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
    user: () => authenticatedFetch('/api/auth/user'),
    logout: () => authenticatedFetch('/api/auth/logout', { method: 'POST' }),
  },

  // Protected endpoints
  // config endpoint removed - no longer needed (frontend uses window.location)
  // After the projectName → projectId migration the path/query identifier is
  // the DB-assigned `projectId`; parameter names reflect that for clarity.
  projects: () => authenticatedFetch('/api/projects'),
  archivedProjects: () => authenticatedFetch('/api/projects/archived'),
  projectSessions: (projectId, { limit = 20, offset = 0 } = {}) => {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    return authenticatedFetch(`/api/projects/${encodeURIComponent(projectId)}/sessions?${params.toString()}`);
  },
  projectTaskmaster: (projectId) =>
    authenticatedFetch(`/api/projects/${encodeURIComponent(projectId)}/taskmaster`),
  // Unified endpoint for persisted session messages.
  // Provider/project metadata are resolved by the backend from sessionId.
  unifiedSessionMessages: (sessionId, _provider = 'claude', { limit = null, offset = 0 } = {}) => {
    const params = new URLSearchParams();
    if (limit !== null) {
      params.append('limit', String(limit));
      params.append('offset', String(offset));
    }
    const queryString = params.toString();
    return authenticatedFetch(`/api/providers/sessions/${encodeURIComponent(sessionId)}/messages${queryString ? `?${queryString}` : ''}`);
  },
  renameProject: (projectId, displayName) =>
    authenticatedFetch(`/api/projects/${projectId}/rename`, {
      method: 'PUT',
      body: JSON.stringify({ displayName }),
    }),
  restoreProject: (projectId) =>
    authenticatedFetch(`/api/projects/${encodeURIComponent(projectId)}/restore`, {
      method: 'POST',
    }),
  // Session deletion now mirrors project deletion:
  // - default: archive only (`isArchived = 1`)
  // - hardDelete: remove the row and, by default, its persisted transcript file
  deleteSession: (sessionId, hardDelete = false) => {
    const params = new URLSearchParams();
    if (hardDelete) {
      params.set('force', 'true');
    }
    const qs = params.toString();
    return authenticatedFetch(`/api/providers/sessions/${sessionId}${qs ? `?${qs}` : ''}`, {
      method: 'DELETE',
    });
  },
  getArchivedSessions: () =>
    authenticatedFetch('/api/providers/sessions/archived'),
  restoreSession: (sessionId) =>
    authenticatedFetch(`/api/providers/sessions/${sessionId}/restore`, {
      method: 'POST',
    }),
  renameSession: (sessionId, summary) =>
    authenticatedFetch(`/api/providers/sessions/${sessionId}`, {
      method: 'PUT',
      body: JSON.stringify({ summary }),
    }),
  // `hardDelete` => server `?force=true` (remove DB row + Claude *.jsonl + sessions rows for path).
  deleteProject: (projectId, hardDelete = false) => {
    const params = new URLSearchParams();
    if (hardDelete) params.set('force', 'true');
    const qs = params.toString();
    return authenticatedFetch(`/api/projects/${projectId}${qs ? `?${qs}` : ''}`, {
      method: 'DELETE',
    });
  },
  searchConversationsUrl: (query, limit = 50) => {
    // 原生后端:SSE 走同源 /api/ccui/providers/search/sessions(cookie 鉴权,无需 token)。
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    return _apiUrl(`/api/providers/search/sessions?${params.toString()}`);
  },
  createProject: (projectData) =>
    authenticatedFetch('/api/projects/create-project', {
      method: 'POST',
      body: JSON.stringify(projectData),
    }),
  migrateLegacyProjectStars: (projectIds) =>
    authenticatedFetch('/api/projects/migrate-legacy-stars', {
      method: 'POST',
      body: JSON.stringify({ projectIds }),
    }),
  toggleProjectStar: (projectId) =>
    authenticatedFetch(`/api/projects/${encodeURIComponent(projectId)}/toggle-star`, {
      method: 'POST',
    }),
  readFile: (projectId, filePath) =>
    authenticatedFetch(`/api/projects/${projectId}/file?filePath=${encodeURIComponent(filePath)}`),
  readFileBlob: (projectId, filePath) =>
    authenticatedFetch(`/api/projects/${projectId}/files/content?path=${encodeURIComponent(filePath)}`),
  saveFile: (projectId, filePath, content) =>
    authenticatedFetch(`/api/projects/${projectId}/file`, {
      method: 'PUT',
      body: JSON.stringify({ filePath, content }),
    }),
  getFiles: (projectId, options = {}) =>
    authenticatedFetch(`/api/projects/${projectId}/files`, options),

  // File operations
  createFile: (projectId, { path, type, name }) =>
    authenticatedFetch(`/api/projects/${projectId}/files/create`, {
      method: 'POST',
      body: JSON.stringify({ path, type, name }),
    }),

  renameFile: (projectId, { oldPath, newName }) =>
    authenticatedFetch(`/api/projects/${projectId}/files/rename`, {
      method: 'PUT',
      body: JSON.stringify({ oldPath, newName }),
    }),

  deleteFile: (projectId, { path, type }) =>
    authenticatedFetch(`/api/projects/${projectId}/files`, {
      method: 'DELETE',
      body: JSON.stringify({ path, type }),
    }),

  uploadFiles: (projectId, formData) =>
    authenticatedFetch(`/api/projects/${projectId}/files/upload`, {
      method: 'POST',
      body: formData,
      headers: {}, // Let browser set Content-Type for FormData
    }),

  // TaskMaster endpoints — all addressed by DB projectId post-migration.
  taskmaster: {
    // Initialize TaskMaster in a project
    init: (projectId) =>
      authenticatedFetch(`/api/taskmaster/init/${projectId}`, {
        method: 'POST',
      }),

    // Add a new task
    addTask: (projectId, { prompt, title, description, priority, dependencies }) =>
      authenticatedFetch(`/api/taskmaster/add-task/${projectId}`, {
        method: 'POST',
        body: JSON.stringify({ prompt, title, description, priority, dependencies }),
      }),

    // Parse PRD to generate tasks
    parsePRD: (projectId, { fileName, numTasks, append }) =>
      authenticatedFetch(`/api/taskmaster/parse-prd/${projectId}`, {
        method: 'POST',
        body: JSON.stringify({ fileName, numTasks, append }),
      }),

    // Get available PRD templates
    getTemplates: () =>
      authenticatedFetch('/api/taskmaster/prd-templates'),

    // Apply a PRD template
    applyTemplate: (projectId, { templateId, fileName, customizations }) =>
      authenticatedFetch(`/api/taskmaster/apply-template/${projectId}`, {
        method: 'POST',
        body: JSON.stringify({ templateId, fileName, customizations }),
      }),

    // Update a task
    updateTask: (projectId, taskId, updates) =>
      authenticatedFetch(`/api/taskmaster/update-task/${projectId}/${taskId}`, {
        method: 'PUT',
        body: JSON.stringify(updates),
      }),
  },

  // Browse filesystem for project suggestions
  browseFilesystem: (dirPath = null) => {
    const params = new URLSearchParams();
    if (dirPath) params.append('path', dirPath);

    return authenticatedFetch(`/api/browse-filesystem?${params}`);
  },

  createFolder: (folderPath) =>
    authenticatedFetch('/api/create-folder', {
      method: 'POST',
      body: JSON.stringify({ path: folderPath }),
    }),

  // User endpoints
  user: {
    gitConfig: () => authenticatedFetch('/api/user/git-config'),
    updateGitConfig: (gitName, gitEmail) =>
      authenticatedFetch('/api/user/git-config', {
        method: 'POST',
        body: JSON.stringify({ gitName, gitEmail }),
      }),
    onboardingStatus: () => authenticatedFetch('/api/user/onboarding-status'),
    completeOnboarding: () =>
      authenticatedFetch('/api/user/complete-onboarding', {
        method: 'POST',
      }),
  },

  // Generic GET method for any endpoint
  get: (endpoint) => authenticatedFetch(`/api${endpoint}`),

  // Generic POST method for any endpoint
  post: (endpoint, body) => authenticatedFetch(`/api${endpoint}`, {
    method: 'POST',
    ...(body instanceof FormData ? { body } : { body: JSON.stringify(body) }),
  }),

  // Generic PUT method for any endpoint
  put: (endpoint, body) => authenticatedFetch(`/api${endpoint}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  }),

  // Generic DELETE method for any endpoint
  delete: (endpoint, options = {}) => authenticatedFetch(`/api${endpoint}`, {
    method: 'DELETE',
    ...options,
  }),
};
