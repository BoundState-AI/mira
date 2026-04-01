/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_COGNITO_USER_POOL_ID?: string;
  readonly VITE_COGNITO_CLIENT_ID?: string;
  readonly VITE_COGNITO_HOSTED_UI_DOMAIN?: string;
  readonly VITE_COGNITO_REDIRECT_URI?: string;
  readonly VITE_COGNITO_LOGOUT_URI?: string;
  readonly VITE_COGNITO_OAUTH_SCOPES?: string;
  readonly VITE_COGNITO_IDENTITY_PROVIDER?: string;
  readonly VITE_COGNITO_FEDERATED_BUTTON_LABEL?: string;
  readonly VITE_COGNITO_PASSWORD_LOGIN_DISABLED?: string;
  readonly VITE_MIRA_ALLOWED_GROUPS?: string;
  readonly VITE_MIRA_ALLOWED_USERNAMES?: string;
  readonly VITE_MIRA_ALLOWED_EMAILS?: string;
  readonly VITE_API_AUTH_HOSTS?: string;
  readonly VITE_AUTH_BYPASS_LOCAL?: string;
  readonly REACT_APP_COGNITO_USER_POOL_ID?: string;
  readonly REACT_APP_COGNITO_CLIENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
