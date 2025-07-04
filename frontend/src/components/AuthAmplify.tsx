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
          <div className="mb-5 mt-20 flex flex-col items-center justify-center gap-4 px-4">
      <div className="flex flex-col sm:flex-row items-center justify-center gap-4 w-full max-w-screen-md">
        <img
          src="/Gentica_Humana.png"
          alt="Logo Genética Humana"
          className="h-32 sm:h-40 md:h-48 w-auto object-contain"
        />
        <img
          src="/GeneticaLogoAid.png"
          alt="Logo GHeneAid"
          className="h-32 sm:h-40 md:h-48 w-auto object-contain"
        />
      </div>
    </div>
        ),
      }}
    >
      <>{cloneElement(children as ReactElement, { signOut })}</>
    </Authenticator>
  );
};;

export default AuthAmplify;
