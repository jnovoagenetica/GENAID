// src/aws-amplify-config.ts
import { Amplify } from 'aws-amplify';

Amplify.configure({
  Auth: {
    region: import.meta.env.VITE_APP_REGION,
    userPoolId: import.meta.env.VITE_APP_USER_POOL_ID,
    userPoolWebClientId: import.meta.env.VITE_APP_USER_POOL_CLIENT_ID,
    oauth: {
      domain: import.meta.env.VITE_APP_COGNITO_DOMAIN?.replace(/^https?:\/\//, ''),
      scope: ['email', 'openid', 'profile'],
      redirectSignIn: import.meta.env.VITE_APP_REDIRECT_SIGNIN_URL,
      redirectSignOut: import.meta.env.VITE_APP_REDIRECT_SIGNOUT_URL,
      responseType: 'code',
    },
  },
  ssr: false,
});
