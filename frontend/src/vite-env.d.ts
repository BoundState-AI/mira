/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUTH_BYPASS?: string;
  readonly VITE_AUTH_BYPASS_LOCAL?: string;
  readonly VITE_COGNITO_USER_POOL_ID?: string;
  readonly VITE_COGNITO_CLIENT_ID?: string;
  readonly VITE_API_AUTH_HOSTS?: string;
  readonly REACT_APP_COGNITO_USER_POOL_ID?: string;
  readonly REACT_APP_COGNITO_CLIENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
