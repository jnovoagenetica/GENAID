import React, { ReactNode, cloneElement, ReactElement } from 'react';
import { BaseProps } from '../@types/common';
import { Authenticator } from '@aws-amplify/ui-react';
import { SocialProvider } from '@aws-amplify/ui';
import { useAuthenticator } from '@aws-amplify/ui-react';

type Props = BaseProps & {
  socialProviders: SocialProvider[];
  children: ReactNode;
};

const AuthAmplify: React.FC<Props> = ({ socialProviders, children }) => {
  const { signOut } = useAuthenticator();

  return (
    <Authenticator
      socialProviders={socialProviders}
      hideSignUp
      components={{
        Header: () => (
          <div className="mb-5 mt-10 flex justify-center">
            <img
              src="/Gentica_Humana.png" // ✅ Imagen en carpeta `public/`
              alt="Logo Genética Humana"
              className="h-50 w-auto object-contain"
            />
          </div>
        ),
      }}
    >
      <>{cloneElement(children as ReactElement, { signOut })}</>
    </Authenticator>
  );
};

export default AuthAmplify;
