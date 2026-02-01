import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

// English translations
import enCommon from './locales/en/common.json';
import enNavigation from './locales/en/navigation.json';
import enKnowledgeTwins from './locales/en/pages/knowledgeTwins.json';
import enGasCompatibility from './locales/en/pages/gasCompatibility.json';
import enQuery from './locales/en/pages/query.json';

// Japanese translations
import jaCommon from './locales/ja/common.json';
import jaNavigation from './locales/ja/navigation.json';
import jaKnowledgeTwins from './locales/ja/pages/knowledgeTwins.json';
import jaGasCompatibility from './locales/ja/pages/gasCompatibility.json';
import jaQuery from './locales/ja/pages/query.json';

// French translations
import frCommon from './locales/fr/common.json';
import frNavigation from './locales/fr/navigation.json';
import frKnowledgeTwins from './locales/fr/pages/knowledgeTwins.json';
import frGasCompatibility from './locales/fr/pages/gasCompatibility.json';
import frQuery from './locales/fr/pages/query.json';

export const supportedLanguages = [
  { code: 'en', name: 'English', nativeName: 'English' },
  { code: 'ja', name: 'Japanese', nativeName: '日本語' },
  { code: 'fr', name: 'French', nativeName: 'Français' },
] as const;

export type LanguageCode = typeof supportedLanguages[number]['code'];

const resources = {
  en: {
    common: enCommon,
    navigation: enNavigation,
    knowledgeTwins: enKnowledgeTwins,
    gasCompatibility: enGasCompatibility,
    query: enQuery,
  },
  ja: {
    common: jaCommon,
    navigation: jaNavigation,
    knowledgeTwins: jaKnowledgeTwins,
    gasCompatibility: jaGasCompatibility,
    query: jaQuery,
  },
  fr: {
    common: frCommon,
    navigation: frNavigation,
    knowledgeTwins: frKnowledgeTwins,
    gasCompatibility: frGasCompatibility,
    query: frQuery,
  },
};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'en',
    defaultNS: 'common',
    ns: ['common', 'navigation'],

    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'mira-language',
    },

    interpolation: {
      escapeValue: false, // React already escapes
    },
  });

export default i18n;
