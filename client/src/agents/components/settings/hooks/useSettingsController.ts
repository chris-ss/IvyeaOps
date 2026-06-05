import { useCallback, useEffect, useRef, useState } from 'react';
import { authenticatedFetch } from '../../../utils/api';
import { useProviderAuthStatus } from '../../provider-auth/hooks/useProviderAuthStatus';
import { DEFAULT_CURSOR_PERMISSIONS } from '../constants/constants';
import type {
  AgentProvider,
  ClaudePermissionsState,
  CodexPermissionMode,
  CursorPermissionsState,
  GeminiPermissionMode,
  SettingsMainTab,
} from '../types/types';

type UseSettingsControllerArgs = {
  isOpen: boolean;
  initialTab: string;
};

type ClaudeSettingsStorage = {
  allowedTools?: string[];
  disallowedTools?: string[];
  skipPermissions?: boolean;
};

type CursorSettingsStorage = {
  allowedCommands?: string[];
  disallowedCommands?: string[];
  skipPermissions?: boolean;
};

type CodexSettingsStorage = {
  permissionMode?: CodexPermissionMode;
};

type ActiveLoginProvider = AgentProvider | '';

const KNOWN_MAIN_TABS: SettingsMainTab[] = ['agents', 'plugins'];

const normalizeMainTab = (tab: string): SettingsMainTab => {
  if (tab === 'tools') return 'agents';
  return KNOWN_MAIN_TABS.includes(tab as SettingsMainTab) ? (tab as SettingsMainTab) : 'agents';
};

const parseJson = <T>(value: string | null, fallback: T): T => {
  if (!value) return fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
};

const toCodexPermissionMode = (value: unknown): CodexPermissionMode => {
  if (value === 'acceptEdits' || value === 'bypassPermissions') return value;
  return 'default';
};

const createEmptyClaudePermissions = (): ClaudePermissionsState => ({
  allowedTools: [],
  disallowedTools: [],
  skipPermissions: false,
});

const createEmptyCursorPermissions = (): CursorPermissionsState => ({
  ...DEFAULT_CURSOR_PERMISSIONS,
});

export function useSettingsController({ isOpen, initialTab }: UseSettingsControllerArgs) {
  const closeTimerRef = useRef<number | null>(null);

  const [activeTab, setActiveTab] = useState<SettingsMainTab>(() => normalizeMainTab(initialTab));
  const [saveStatus, setSaveStatus] = useState<'success' | 'error' | null>(null);
  const [claudePermissions, setClaudePermissions] = useState<ClaudePermissionsState>(() => createEmptyClaudePermissions());
  const [cursorPermissions, setCursorPermissions] = useState<CursorPermissionsState>(() => createEmptyCursorPermissions());
  const [codexPermissionMode, setCodexPermissionMode] = useState<CodexPermissionMode>('default');
  const [geminiPermissionMode, setGeminiPermissionMode] = useState<GeminiPermissionMode>('default');
  const [showLoginModal, setShowLoginModal] = useState(false);
  const [loginProvider, setLoginProvider] = useState<ActiveLoginProvider>('');

  const {
    providerAuthStatus,
    checkProviderAuthStatus,
    refreshProviderAuthStatuses,
  } = useProviderAuthStatus();

  const loadSettings = useCallback(async () => {
    try {
      const savedClaudeSettings = parseJson<ClaudeSettingsStorage>(localStorage.getItem('claude-settings'), {});
      setClaudePermissions({
        allowedTools: savedClaudeSettings.allowedTools || [],
        disallowedTools: savedClaudeSettings.disallowedTools || [],
        skipPermissions: Boolean(savedClaudeSettings.skipPermissions),
      });

      const savedCursorSettings = parseJson<CursorSettingsStorage>(localStorage.getItem('cursor-tools-settings'), {});
      setCursorPermissions({
        allowedCommands: savedCursorSettings.allowedCommands || [],
        disallowedCommands: savedCursorSettings.disallowedCommands || [],
        skipPermissions: Boolean(savedCursorSettings.skipPermissions),
      });

      const savedCodexSettings = parseJson<CodexSettingsStorage>(localStorage.getItem('codex-settings'), {});
      setCodexPermissionMode(toCodexPermissionMode(savedCodexSettings.permissionMode));

      const savedGeminiSettings = parseJson<{ permissionMode?: GeminiPermissionMode }>(localStorage.getItem('gemini-settings'), {});
      setGeminiPermissionMode(savedGeminiSettings.permissionMode || 'default');
    } catch (error) {
      console.error('Error loading settings:', error);
      setClaudePermissions(createEmptyClaudePermissions());
      setCursorPermissions(createEmptyCursorPermissions());
      setCodexPermissionMode('default');
    }
  }, []);

  const openLoginForProvider = useCallback((provider: AgentProvider) => {
    setLoginProvider(provider);
    setShowLoginModal(true);
  }, []);

  const handleLoginComplete = useCallback((exitCode: number) => {
    if (!loginProvider) return;
    void (async () => {
      const authStatus = await checkProviderAuthStatus(loginProvider);
      if (exitCode !== 0) console.warn(`Login process exited with code ${exitCode}`);
      setSaveStatus(authStatus.authenticated ? 'success' : 'error');
    })();
  }, [checkProviderAuthStatus, loginProvider]);

  const saveSettings = useCallback(async () => {
    setSaveStatus(null);
    try {
      const now = new Date().toISOString();
      localStorage.setItem('claude-settings', JSON.stringify({
        allowedTools: claudePermissions.allowedTools,
        disallowedTools: claudePermissions.disallowedTools,
        skipPermissions: claudePermissions.skipPermissions,
        lastUpdated: now,
      }));
      localStorage.setItem('cursor-tools-settings', JSON.stringify({
        allowedCommands: cursorPermissions.allowedCommands,
        disallowedCommands: cursorPermissions.disallowedCommands,
        skipPermissions: cursorPermissions.skipPermissions,
        lastUpdated: now,
      }));
      localStorage.setItem('codex-settings', JSON.stringify({ permissionMode: codexPermissionMode, lastUpdated: now }));
      localStorage.setItem('gemini-settings', JSON.stringify({ permissionMode: geminiPermissionMode, lastUpdated: now }));

      // Keep notification preferences endpoint alive (server expects it)
      await authenticatedFetch('/api/settings/notification-preferences', {
        method: 'PUT',
        body: JSON.stringify({ channels: { inApp: true, webPush: false }, events: { actionRequired: true, stop: true, error: true } }),
      });

      setSaveStatus('success');
    } catch (error) {
      console.error('Error saving settings:', error);
      setSaveStatus('error');
    }
  }, [
    claudePermissions.allowedTools,
    claudePermissions.disallowedTools,
    claudePermissions.skipPermissions,
    codexPermissionMode,
    cursorPermissions.allowedCommands,
    cursorPermissions.disallowedCommands,
    cursorPermissions.skipPermissions,
    geminiPermissionMode,
  ]);

  useEffect(() => {
    if (!isOpen) return;
    setActiveTab(normalizeMainTab(initialTab));
    void loadSettings();
    void refreshProviderAuthStatuses();
  }, [initialTab, isOpen, loadSettings, refreshProviderAuthStatuses]);

  const autoSaveTimerRef = useRef<number | null>(null);
  const isInitialLoadRef = useRef(true);

  useEffect(() => {
    if (isInitialLoadRef.current) {
      isInitialLoadRef.current = false;
      return;
    }
    if (autoSaveTimerRef.current !== null) window.clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = window.setTimeout(() => { saveSettings(); }, 500);
    return () => { if (autoSaveTimerRef.current !== null) window.clearTimeout(autoSaveTimerRef.current); };
  }, [saveSettings]);

  useEffect(() => {
    if (saveStatus === null) return;
    const timer = window.setTimeout(() => setSaveStatus(null), 2000);
    return () => window.clearTimeout(timer);
  }, [saveStatus]);

  useEffect(() => {
    if (isOpen) isInitialLoadRef.current = true;
  }, [isOpen]);

  useEffect(() => () => {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
    if (autoSaveTimerRef.current !== null) window.clearTimeout(autoSaveTimerRef.current);
  }, []);

  return {
    activeTab,
    setActiveTab,
    saveStatus,
    claudePermissions,
    setClaudePermissions,
    cursorPermissions,
    setCursorPermissions,
    codexPermissionMode,
    setCodexPermissionMode,
    providerAuthStatus,
    geminiPermissionMode,
    setGeminiPermissionMode,
    openLoginForProvider,
    showLoginModal,
    setShowLoginModal,
    loginProvider,
    handleLoginComplete,
  };
}
