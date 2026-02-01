import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

// English translations
import enCommon from './locales/en/common.json';
import enNavigation from './locales/en/navigation.json';

// Japanese translations
import jaCommon from './locales/ja/common.json';
import jaNavigation from './locales/ja/navigation.json';

// French translations
import frCommon from './locales/fr/common.json';
import frNavigation from './locales/fr/navigation.json';

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
  },
  ja: {
    common: jaCommon,
    navigation: jaNavigation,
  },
  fr: {
    common: frCommon,
    navigation: frNavigation,
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
