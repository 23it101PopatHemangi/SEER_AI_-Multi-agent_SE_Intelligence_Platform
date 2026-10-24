export const oktaConfig = {
  issuer: import.meta.env.VITE_OKTA_ISSUER || 'https://dev-dummy.oktapreview.com/oauth2/default',
  clientId: import.meta.env.VITE_OKTA_CLIENT_ID || 'dummy_client_id',
  redirectUri: import.meta.env.VITE_OKTA_REDIRECT_URI || window.location.origin + '/login/callback',
  scopes: ['openid', 'profile', 'email'],
  pkce: true,
};
