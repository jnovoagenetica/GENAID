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
          <div className="mb-5 mt-20 flex flex-col items-center justify-center gap-2">
            <div className="flex justify-center space-x-1 items-center">
              <img
                src="/Gentica_Humana.png"
                alt="Logo Genética Humana"
                className="h-56 max-h-56 w-auto object-contain shrink-0"
              />
              <img
                src="/GeneticaLogoAid.png"
                alt="Logo GHeneAid"
                className="h-56 max-h-50 w-auto object-contain shrink-0"
              />
            </div>
            <p className="text-3xl font-bold text-slate-800 mt-2">
              GHeneAid - Genética Humana
            </p>
          </div>
        ),
      }}
    >
      <>{cloneElement(children as ReactElement, { signOut })}</>
    </Authenticator>
  );
};;

export default AuthAmplify;
