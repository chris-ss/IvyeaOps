/**
 * i18n Configuration
 *
 * Configures i18next for internationalization support.
 * Features:
 * - zh-CN + en bundled eagerly (the defaults); other languages lazy-loaded on
 *   demand via dynamic import, so they stay out of the main Agents chunk
 * - Language detection from localStorage
 * - Fallback to English for missing translations
 */

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

// Eager resources: only the two languages virtually every session uses.
import enCommon from './locales/en/common.json';
import enSettings from './locales/en/settings.json';
import enAuth from './locales/en/auth.json';
import enSidebar from './locales/en/sidebar.json';
import enChat from './locales/en/chat.json';
import enCodeEditor from './locales/en/codeEditor.json';
// eslint-disable-next-line import-x/order
import enTasks from './locales/en/tasks.json';

import zhCommon from './locales/zh-CN/common.json';
import zhSettings from './locales/zh-CN/settings.json';
import zhAuth from './locales/zh-CN/auth.json';
import zhSidebar from './locales/zh-CN/sidebar.json';
import zhChat from './locales/zh-CN/chat.json';
// eslint-disable-next-line import-x/order
import zhCodeEditor from './locales/zh-CN/codeEditor.json';
import zhTasks from './locales/zh-CN/tasks.json';

// Import supported languages configuration
import { languages } from './languages.js';

// Lazy locales: ko/ja/ru/de/tr/it load on first switch instead of shipping in the
// main bundle (~440KB of JSON source). Vite turns each file into its own chunk.
const LAZY_LOCALE_MODULES = import.meta.glob('./locales/{ko,ja,ru,de,tr,it}/*.json');

async function loadLocale(lng) {
  const prefix = `./locales/${lng}/`;
  const entries = Object.entries(LAZY_LOCALE_MODULES).filter(([p]) => p.startsWith(prefix));
  if (!entries.length) {
    return false;
  }
  await Promise.all(entries.map(async ([path, loader]) => {
    const ns = path.slice(prefix.length).replace(/\.json$/, '');
    const mod = await loader();
    i18n.addResourceBundle(lng, ns, mod.default || mod, true, true);
  }));
  return true;
}

// Get saved language preference from localStorage
// Use 'ivyea_ops_lang' key to avoid reading stale 'userLanguage: en' from old installs
const LANG_KEY = 'ivyea_ops_lang';
const getSavedLanguage = () => {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved && languages.some(lang => lang.value === saved)) {
      return saved;
    }
    return 'zh-CN';
  } catch {
    return 'zh-CN';
  }
};

// Initialize i18next
i18n
  .use(initReactI18next)
  .init({
    // Eager resources (lazy languages are added via addResourceBundle on demand)
    resources: {
      en: {
        common: enCommon,
        settings: enSettings,
        auth: enAuth,
        sidebar: enSidebar,
        chat: enChat,
        codeEditor: enCodeEditor,
        tasks: enTasks,
      },
      'zh-CN': {
        common: zhCommon,
        settings: zhSettings,
        auth: zhAuth,
        sidebar: zhSidebar,
        chat: zhChat,
        codeEditor: zhCodeEditor,
        tasks: zhTasks,
      },
    },

    // Default language — zh-CN for IvyeaOps integration
    lng: getSavedLanguage(),

    // Fallback language when a translation is missing
    fallbackLng: 'en',

    // Enable debug mode in development (logs missing keys to console)
    debug: false,

    // Namespaces - load only what's needed
    ns: ['common', 'settings', 'auth', 'sidebar', 'chat', 'codeEditor', 'tasks'],
    defaultNS: 'common',

    // Key separator for nested keys (default: '.')
    keySeparator: '.',

    // Namespace separator (default: ':')
    nsSeparator: ':',

    // Save missing translations (disabled - requires manual review)
    saveMissing: false,

    // Interpolation settings
    interpolation: {
      escapeValue: false, // React already escapes values
    },

    // React-specific settings
    react: {
      useSuspense: false, // Use Suspense for lazy-loading
      bindI18n: 'languageChanged', // Re-render on language change
      bindI18nStore: false, // Don't re-render on resource changes
    },

  });

// Ensure a lazy language's bundles are loaded, then re-announce the change so
// react-i18next re-renders with the real strings (English fallback shows for the
// brief load window). Guarded by hasResourceBundle, so no reload loop.
function ensureLocale(lng) {
  if (!lng || i18n.hasResourceBundle(lng, 'common')) {
    return;
  }
  loadLocale(lng)
    .then((loaded) => {
      if (loaded && i18n.language === lng) {
        return i18n.changeLanguage(lng);
      }
      return undefined;
    })
    .catch((error) => {
      console.error(`Failed to load locale ${lng}:`, error);
    });
}

// Save language preference when it changes; lazy-load its bundles if needed.
i18n.on('languageChanged', (lng) => {
  try {
    localStorage.setItem(LANG_KEY, lng);
  } catch (error) {
    console.error('Failed to save language preference:', error);
  }
  ensureLocale(lng);
});

// The saved language might be a lazy one (e.g. ja) — load it right away.
ensureLocale(getSavedLanguage());

export default i18n;
